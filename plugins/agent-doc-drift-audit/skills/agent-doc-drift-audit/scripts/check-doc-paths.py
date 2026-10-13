#!/usr/bin/env python3
"""Flag references in agent docs to repo paths that do not exist.

Agent docs (CLAUDE.md, AGENTS.md, .claude/*.md, REPO_MAP.md, README) are
loaded every session and acted on, so a path that a refactor removed sends
the next agent to the wrong place. This checks, against the repo's files:

  * backticked paths: `dir/`, `a/b.tf`, `File.java:12` (suffix match, so
    `module/x/main.tf` passes when terraform/module/x/main.tf exists)
  * relative markdown links: [t](../docs/x.md) (exact, from the doc's dir)
  * two markers that should never be committed: a plugin-generated
    `<claude-mem-context>` stub and machine-local `~/.claude/skills` paths

What it deliberately does not check:
  * fenced code blocks, and the text of links to http(s) URLs
  * tokens that do not look like paths: a token counts only if it has a file
    extension, ends with `/` after a real directory name, or starts with a
    top-level entry of the repo (so `origin/main`, `role/x` and
    `kubernetes.io/arch` are ignored)
  * lines that name another repo of the same owner (`<owner>/<other-repo>`):
    their paths belong to that repo. The owner comes from the git remote, or
    from --owner for a plain directory
  * paths that .gitignore covers (generated files), in a git checkout

Usage:
  check-doc-paths.py [--repo DIR] [--owner NAME] [--ignore REGEX]... [DOC...]
  check-doc-paths.py --self-test

DIR may be a git checkout (tracked files) or a plain directory such as a
`git archive` snapshot (all files). With no DOC, checks the agent docs it
finds. Exit 1 on findings.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

EXT = re.compile(
    r"\.(md|tf|tfvars|hcl|java|kt|kts|groovy|gradle|py|sh|ya?ml|json|toml"
    r"|sql|proto|xml|properties|txt|cfg|ini|j2|tpl)$"
)
TICK = re.compile(r"`([^`\s]+)`")
LINK = re.compile(r"\]\(([^)\s]+)\)")
HTTP_LINK = re.compile(r"\[[^\]]*\]\(https?:[^)]*\)")
URL = re.compile(r"https?://\S+")
LINEREF = re.compile(r":\d[\d,\-]*$")
SKIP_CHARS = set("<>*{}$=|@~?%[]…")
MARKERS = (
    ("<claude-mem-context>", "plugin-generated stub"),
    ("~/.claude/skills/", "machine-local skill path"),
    ("$HOME/.claude/skills", "machine-local skill path"),
)
DOC_NAMES = {"CLAUDE.md", "AGENTS.md", "REPO_MAP.md"}


def git_ok(repo):
    probe = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True,
    )
    retval = probe.returncode == 0 and probe.stdout.strip() == "true"
    return retval


def list_files(repo, in_git):
    if in_git:
        out = subprocess.run(
            ["git", "-C", repo, "ls-files", "-z"],
            capture_output=True, text=True, check=True,
        ).stdout
        files = {f for f in out.split("\0") if f}
    else:
        files = set()
        for root, dirnames, names in os.walk(repo):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            rel = os.path.relpath(root, repo)
            for n in names:
                files.add(n if rel == "." else os.path.join(rel, n).replace(os.sep, "/"))
    dirs = set()
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    retval = (files, dirs)
    return retval


def remote_owner_repo(repo):
    out = subprocess.run(
        ["git", "-C", repo, "remote", "get-url", "origin"],
        capture_output=True, text=True,
    ).stdout.strip()
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", out)
    retval = (m.group(1), m.group(2)) if m else (None, None)
    return retval


def default_docs(files):
    retval = sorted(
        f for f in files
        if os.path.basename(f) in DOC_NAMES
        or (f.startswith(".claude/") and f.endswith(".md"))
        or ("/" not in f and f.lower().startswith("readme") and f.lower().endswith(".md"))
    )
    return retval


def path_token(token, top, dirnames):
    t = LINEREF.sub("", token.rstrip(".,;)"))
    plausible = (
        t
        and not t.startswith(("/", "-"))
        and "://" not in t
        and not (set(t) & SKIP_CHARS)
    )
    first = t.split("/")[0] if t else ""
    looks_like_path = (
        EXT.search(t)
        or (t.endswith("/") and (first in dirnames or first in top or first in (".", "..")))
        or ("/" in t and first in top)
    ) if plausible else False
    retval = t if looks_like_path else None
    return retval


def exists(rel, files, dirs):
    retval = rel in files or rel in dirs
    return retval


def suffix_exists(token, files, dirs):
    t = token.rstrip("/")
    tail = "/" + t
    retval = (
        exists(t, files, dirs)
        or any(p.endswith(tail) for p in files)
        or any(d.endswith(tail) for d in dirs)
    )
    return retval


def resolve(doc, target):
    joined = target.lstrip("/") if target.startswith("/") else os.path.join(os.path.dirname(doc), target)
    retval = os.path.normpath(joined).replace(os.sep, "/")
    return retval


def git_ignored(repo, rel):
    retval = subprocess.run(["git", "-C", repo, "check-ignore", "-q", rel]).returncode == 0
    return retval


def foreign_line(line, owner, repo_name):
    retval = False
    if owner:
        for m in re.finditer(rf"(?<![\w.-]){re.escape(owner)}/([A-Za-z0-9_.-]+)", URL.sub("", line)):
            if m.group(1).removesuffix(".git") != repo_name:
                retval = True
    return retval


def check_doc(ctx, doc):
    repo, files, dirs, top, dirnames, ignore, owner, repo_name, in_git = ctx
    findings = []
    fenced = False
    with open(os.path.join(repo, doc), encoding="utf-8", errors="replace") as fh:
        lines = fh.read().splitlines()
    for n, line in enumerate(lines, 1):
        for marker, why in MARKERS:
            if marker in line:
                findings.append(f"{doc}:{n}: {why}: {marker}")
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or foreign_line(line, owner, repo_name):
            continue
        for token in TICK.findall(HTTP_LINK.sub("", line)):
            t = path_token(token, top, dirnames)
            if t is None or any(rx.search(t) for rx in ignore):
                continue
            relative = t.startswith(("./", "../"))
            ok = exists(resolve(doc, t).rstrip("/"), files, dirs) if relative else suffix_exists(t, files, dirs)
            if not ok and in_git and git_ignored(repo, resolve(doc, t) if relative else t):
                ok = True
            if not ok:
                findings.append(f"{doc}:{n}: missing path: {t}")
        for target in LINK.findall(line):
            rel = target.split("#", 1)[0].split("?", 1)[0]
            placeholder = "/" not in rel and "." not in rel
            if target.startswith(("http:", "https:", "mailto:", "#")) or not rel or placeholder:
                continue
            if any(rx.search(rel) for rx in ignore):
                continue
            if not exists(resolve(doc, rel).rstrip("/"), files, dirs):
                findings.append(f"{doc}:{n}: broken link: {target}")
    retval = findings
    return retval


def run(repo, docs, ignore, owner=None):
    in_git = git_ok(repo)
    files, dirs = list_files(repo, in_git)
    remote_owner, repo_name = remote_owner_repo(repo) if in_git else (None, None)
    owner = owner or remote_owner
    repo_name = repo_name or os.path.basename(os.path.abspath(repo))
    top = {f.split("/")[0] for f in files}
    dirnames = {d.split("/")[-1] for d in dirs}
    ctx = (repo, files, dirs, top, dirnames, ignore, owner, repo_name, in_git)
    findings = []
    for doc in docs or default_docs(files):
        findings.extend(check_doc(ctx, doc))
    retval = findings
    return retval


def self_test():
    doc = "\n".join([
        "# AGENTS.md",
        "Compute lives in `module/svc/main.tf` and `module/svc-eks/`.",
        "Dashboards: `terraform/module/dashboard` (gone).",
        "CI role `role/github-actions`, branch `origin/main`, S3 prefix `models/raw/`.",
        "See `App.java:12` and `Gone.java`, env `terraform/env/<env>.tfvars`, secrets `env/secrets.env`.",
        "[runbook](docs/RUNBOOK.md) [old](docs/OLD.md#x) [web](https://example.com/a.md) [PR](url)",
        "Alerts live in `acme/grafana` -> `terraform/alerts.tf`.",
        "Spec: [`docs/CONTRACT.md`](https://example.com/acme/other/blob/main/docs/CONTRACT.md).",
        "```",
        "`not/checked.md`",
        "```",
        "<claude-mem-context>",
    ])
    with tempfile.TemporaryDirectory() as tmp:
        for rel, body in (
            ("terraform/module/svc/main.tf", ""),
            ("docs/RUNBOOK.md", "# r"),
            ("src/App.java", "class App {}"),
            (".gitignore", "env/secrets.env\n"),
            ("AGENTS.md", doc),
        ):
            path = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
        subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
        subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
        got = set(run(tmp, ["AGENTS.md"], [], owner="acme"))
    want = {
        "AGENTS.md:2: missing path: module/svc-eks/",
        "AGENTS.md:3: missing path: terraform/module/dashboard",
        "AGENTS.md:5: missing path: Gone.java",
        "AGENTS.md:6: broken link: docs/OLD.md#x",
        "AGENTS.md:12: plugin-generated stub: <claude-mem-context>",
    }
    assert got == want, f"self-test mismatch:\n got  {sorted(got)}\n want {sorted(want)}"
    print("self-test OK")


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("docs", nargs="*", help="docs to check, relative to --repo")
    ap.add_argument("--repo", default=".", help="repo root or snapshot dir (default .)")
    ap.add_argument("--owner", help="org/owner whose other repos' paths to skip (default: from git remote)")
    ap.add_argument("--ignore", action="append", default=[], help="regex of tokens to skip; repeatable")
    ap.add_argument("--self-test", action="store_true", help="run the built-in checks and exit")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return 0
    findings = run(args.repo, args.docs, [re.compile(p) for p in args.ignore], args.owner)
    for f in findings:
        print(f)
    retval = 1 if findings else 0
    return retval


if __name__ == "__main__":
    sys.exit(main())
