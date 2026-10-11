#!/usr/bin/env python3
"""suggest-terms.py - suggest names to add to the private sensitive-terms wordlist.

Scans what a session produced (agent transcripts, a git commit range, and any
plain-text files such as saved PR or issue bodies) for proper nouns and
hostnames that look private, drops the ones already on the wordlist and the
ones that are ordinary words or well-known public names, and prints a ranked
local report.

It never writes the wordlist and never prints the wordlist's contents.

Usage:
  suggest-terms.py [--transcript JSONL]... [--git-range A..B [--repo DIR]]...
                   [--top N] [FILE ...]

The wordlist is read from $SKILLZ_SENSITIVE_TERMS_FILE, else
${XDG_CONFIG_HOME:-~/.config}/skillz/sensitive-terms.txt - the same path the
check-sensitive-terms.sh gate uses.
"""

import argparse
import collections
import json
import os
import re
import subprocess
import sys

DICT_PATHS = ["/usr/share/dict/words", "/usr/dict/words"]

# Well-known public entities that show up in agent sessions and are not
# private. Lowercase. Extend in place when a public name keeps resurfacing.
PUBLIC_NAMES = {
    "anthropic", "claude", "codex", "openai", "chatgpt", "gpt", "gemini",
    "github", "gitlab", "bitbucket", "slack", "google", "gmail", "youtube",
    "microsoft", "windows", "linux", "ubuntu", "debian", "macos", "ios",
    "android", "apple", "safari", "chrome", "chromium", "firefox", "mozilla",
    "aws", "amazon", "azure", "gcp", "cloudflare", "vercel", "netlify",
    "heroku", "docker", "kubernetes", "terraform", "grafana", "prometheus",
    "pagerduty", "datadog", "sentry", "jira", "confluence", "atlassian",
    "notion", "figma", "linkedin", "twitter", "reddit", "wordpress", "npm",
    "pypi", "python", "javascript", "typescript", "nodejs", "java", "kotlin",
    "golang", "rust", "bash", "zsh", "json", "jsonl", "yaml", "toml", "html",
    "markdown", "readme", "sqlite", "postgres", "postgresql", "mysql",
    "mongodb", "redis", "playwright", "pytest", "homebrew", "launchd",
    "systemd", "cmux", "tmux", "vscode", "jetbrains", "intellij", "mcp",
    "oauth", "api", "cli", "url", "http", "https", "ssh", "tls", "ssl",
}

PUBLIC_DOMAINS = {
    "github.com", "githubusercontent.com", "github.io", "anthropic.com",
    "claude.ai", "claude.com", "clau.de", "openai.com", "chatgpt.com",
    "google.com", "googleapis.com", "gstatic.com", "youtube.com",
    "amazonaws.com", "aws.amazon.com", "amazon.com", "cloudfront.net",
    "microsoft.com", "azure.com", "slack.com", "atlassian.net",
    "atlassian.com", "wordpress.com", "npmjs.com", "npmjs.org", "pypi.org",
    "python.org", "mozilla.org", "wikipedia.org", "stackoverflow.com",
    "apple.com", "linkedin.com", "twitter.com", "x.com", "reddit.com",
    "vercel.app", "vercel.com", "cloudflare.com", "docker.com", "docker.io",
    "grafana.com", "grafana-workspace.us-east-1.amazonaws.com",
    "example.com", "example.org", "example.net", "localhost.localdomain",
    "shields.io", "jsdelivr.net", "unpkg.com", "cdnjs.cloudflare.com",
}

# TLDs that make a dotted token a hostname rather than a filename like
# SKILL.md or plugin.json.
TLDS = {
    "com", "net", "org", "io", "ai", "dev", "app", "co", "cloud", "tech",
    "us", "uk", "de", "fr", "ca", "au", "in", "me", "xyz", "info", "biz",
    "internal", "corp", "intranet", "local", "lan", "site", "online",
}

# JSON keys whose values are identifiers, timestamps or opaque blobs, never
# prose a name could leak through.
SKIP_KEYS = {
    "uuid", "parentUuid", "sessionId", "requestId", "id", "tool_use_id",
    "leafUuid", "timestamp", "cwd", "signature", "encrypted_content",
    "data", "media_type", "msg_id", "version", "gitBranch", "model",
}

PROPER = re.compile(r"\b[A-Z][a-z0-9]{2,}(?:[A-Z][a-z0-9]+)*\b")
HOST = re.compile(r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}\b")
HUMP = re.compile(r"[A-Z][a-z0-9]*")


def terms_path():
    env = os.environ.get("SKILLZ_SENSITIVE_TERMS_FILE")
    if env:
        return env
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "skillz", "sensitive-terms.txt")


def load_terms(path):
    """Compiled whole-word, case-insensitive patterns; None if no list."""
    if not os.path.isfile(path):
        return None
    pats = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            try:
                pats.append(re.compile(r"(?<![A-Za-z0-9_])(?:%s)(?![A-Za-z0-9_])" % t, re.I))
            except re.error:
                pats.append(re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(t), re.I))
    return pats


def load_dictionary():
    for p in DICT_PATHS:
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                return {w.strip().lower() for w in f if w.strip()}
    return None


def walk_strings(obj, key=None):
    if key in SKIP_KEYS:
        return
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)


def record_kind(rec):
    """A short label for where in a transcript line the text came from."""
    kind = rec.get("type") or "record"
    msg = rec.get("message") or rec.get("payload") or {}
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                kind = "tool_use %s" % c.get("name", "?")
                break
            if isinstance(c, dict) and c.get("type") == "tool_result":
                kind = "tool_result"
                break
    if isinstance(msg, dict) and msg.get("type") == "function_call":
        kind = "function_call %s" % msg.get("name", "?")
    return kind


def transcript_chunks(path):
    name = os.path.basename(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            where = "%s:%d (%s)" % (name, n, record_kind(rec))
            for s in walk_strings(rec):
                yield where, s


def git_chunks(repo, rng):
    log = subprocess.run(
        ["git", "-C", repo, "--no-pager", "log", "--format=%h%x00%B%x1e", rng],
        capture_output=True, text=True, check=True).stdout
    for entry in log.split("\x1e"):
        if "\x00" not in entry:
            continue
        sha, body = entry.strip("\n").split("\x00", 1)
        yield "commit %s message" % sha, body
        diff = subprocess.run(
            ["git", "-C", repo, "--no-pager", "show", "--format=", "--unified=0", sha],
            capture_output=True, text=True, check=True).stdout
        fname = "?"
        for line in diff.splitlines():
            if line.startswith("+++ "):
                fname = line[6:] if line.startswith("+++ b/") else line[4:]
            elif line.startswith("+"):
                yield "commit %s %s" % (sha, fname), line[1:]


def file_chunks(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            yield "%s:%d" % (path, n), line


# The system dictionary lists base forms only, so "Covers" or "Verified"
# would otherwise read as unknown names.
SUFFIXES = ("ies", "ied", "es", "s", "ed", "d", "ing", "ly", "er", "ers", "ment", "ments")


def is_word(w, words):
    if w in words:
        return True
    for suf in SUFFIXES:
        stem = w[:-len(suf)]
        if w.endswith(suf) and len(stem) >= 3 and (stem in words or stem + "e" in words or stem + "y" in words):
            return True
    return False


def is_ordinary(token, words):
    """True if every camel hump of the token is a dictionary word."""
    if words is None:
        return False
    humps = HUMP.findall(token) or [token]
    retval = all(is_word(h.lower(), words) for h in humps)
    return retval


def registrable(host):
    labels = host.lower().split(".")
    retval = ".".join(labels[-2:])
    return retval


def candidates_in(text, words):
    for m in HOST.finditer(text):
        host = m.group(0)
        tld = host.rsplit(".", 1)[-1].lower()
        if tld not in TLDS:
            continue
        low = host.lower()
        if low in PUBLIC_DOMAINS or registrable(low) in PUBLIC_DOMAINS:
            continue
        yield registrable(low), host
    for m in PROPER.finditer(text):
        tok = m.group(0)
        low = tok.lower()
        if low in PUBLIC_NAMES or is_ordinary(tok, words):
            continue
        yield low, tok


def on_list(term, examples, pats):
    retval = any(p.search(s) for p in pats for s in [term] + list(examples))
    return retval


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--transcript", action="append", default=[], help="agent session JSONL")
    ap.add_argument("--git-range", action="append", default=[], help="commit range, e.g. origin/master..HEAD")
    ap.add_argument("--repo", default=".", help="repo for --git-range (default: .)")
    ap.add_argument("--top", type=int, default=25, help="max candidates to show (default 25)")
    ap.add_argument("files", nargs="*", help="plain-text files: PR/issue bodies, release notes")
    a = ap.parse_args()
    if not (a.transcript or a.git_range or a.files):
        ap.error("nothing to scan: pass --transcript, --git-range or files")

    path = terms_path()
    pats = load_terms(path)
    if pats is None:
        print("warning: no wordlist found at %s - every candidate is new to you." % path, file=sys.stderr)
        pats = []
    words = load_dictionary()
    if words is None:
        print("warning: no system dictionary; ordinary words are not filtered.", file=sys.stderr)

    counts = collections.Counter()
    where = collections.defaultdict(list)
    shown = collections.defaultdict(set)

    def scan(chunks):
        for loc, text in chunks:
            for term, form in candidates_in(text, words):
                counts[term] += 1
                shown[term].add(form)
                if loc not in where[term]:
                    where[term].append(loc)

    for t in a.transcript:
        scan(transcript_chunks(t))
    for r in a.git_range:
        scan(git_chunks(a.repo, r))
    for f in a.files:
        scan(file_chunks(f))

    fresh = [t for t, _ in counts.most_common() if not on_list(t, shown[t], pats)][:a.top]
    if not fresh:
        print("no new candidates")
        return 0

    print("Candidates for %s (review; add only what is private):\n" % path)
    for t in fresh:
        locs = where[t]
        more = " (+%d more)" % (len(locs) - 3) if len(locs) > 3 else ""
        forms = ", ".join(sorted(shown[t])[:3])
        print("%5d  %-30s  as: %s" % (counts[t], t, forms))
        print("       at: %s%s" % ("; ".join(locs[:3]), more))
    quoted = " ".join("'%s'" % t.replace("'", "'\\''") for t in fresh)
    print("\nAppend the ones you accept (delete the rest from the command first):")
    print("  printf '%%s\\n' %s >> \"%s\"" % (quoted, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
