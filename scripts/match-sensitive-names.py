#!/usr/bin/env python3
"""match-sensitive-names.py - the name pass of check-sensitive-terms.sh.

Usage: match-sensitive-names.py TERMS_FILE PATH [PATH ...]

Matches each wordlist term against the given files (directories are walked
like `grep -rI`: symlinks met during the walk are skipped, binaries are
skipped) and prints `file:line:text` for every hit. Exit 0 = no hits,
1 = hits, 2 = usage error.

Why this is not grep: a name must match as a whole word, and a camelCase hump
must also count as a word boundary. grep can do one or the other. `-w` misses
`AcmeCorpThing`; without `-w` a short term matches inside `rubella` or
`labelLarge`. Telling those apart needs a case-SENSITIVE boundary check around
a case-INSENSITIVE match, which a single grep cannot express. So each term is
found case-insensitively, then its boundaries are checked on the original
text:

- Start: beginning of text, a non-alphanumeric character before it, or the
  match starts on an uppercase letter right after a lowercase letter or digit
  (`myAcmeCorp`).
- End: end of text, a non-alphanumeric character after it, or the next
  character is uppercase while the match ended on a lowercase letter or digit
  (`AcmeCorpThing`).

A plain multi-word term ("seeds of fog", or "seeds-of-fog") is also matched as
an identifier: words joined with nothing, `_` or `-`. The spaced form matches
only when the term itself is written with spaces. Terms are extended regexes, as before;
one that does not compile is matched literally.
"""

import os
import re
import sys


def load_patterns(path):
    patterns = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            term = line.strip()
            if not term or term.startswith("#"):
                continue
            variants = {term}
            if re.fullmatch(r"[A-Za-z0-9 _\-]+", term):
                words = re.split(r"[\s_\-]+", term)
                if len(words) > 1:
                    # Identifier spellings only. A term listed as an identifier
                    # (foo-bar) is not widened to the prose phrase "foo bar",
                    # which can be an ordinary public product name.
                    variants |= {"".join(words), "_".join(words), "-".join(words)}
            for variant in sorted(variants):
                try:
                    patterns.append(re.compile(variant, re.IGNORECASE))
                except re.error:
                    patterns.append(re.compile(re.escape(variant), re.IGNORECASE))
    return patterns


def boundary_ok(text, start, end):
    before = text[start - 1] if start > 0 else ""
    first = text[start]
    after = text[end] if end < len(text) else ""
    last = text[end - 1]
    start_ok = (
        not before
        or not before.isalnum()
        or (first.isupper() and (before.islower() or before.isdigit()))
    )
    end_ok = (
        not after
        or not after.isalnum()
        or (after.isupper() and (last.islower() or last.isdigit()))
    )
    retval = start_ok and end_ok
    return retval


def iter_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
                for name in sorted(files):
                    full = os.path.join(root, name)
                    if not os.path.islink(full):
                        yield full
        elif os.path.isfile(p):
            yield p


def read_text(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    retval = data.decode("utf-8", errors="replace")
    return retval


def hits_in(text, patterns):
    lines = set()
    for pattern in patterns:
        for m in pattern.finditer(text):
            if m.end() > m.start() and boundary_ok(text, m.start(), m.end()):
                lines.add(text.count("\n", 0, m.start()) + 1)
    retval = sorted(lines)
    return retval


def main(argv):
    if len(argv) < 3:
        print("usage: %s TERMS_FILE PATH [PATH ...]" % argv[0], file=sys.stderr)
        return 2
    patterns = load_patterns(argv[1])
    found = False
    for path in iter_files(argv[2:]):
        text = read_text(path)
        if text is None:
            continue
        numbers = hits_in(text, patterns)
        if numbers:
            found = True
            all_lines = text.split("\n")
            for n in numbers:
                print("%s:%d:%s" % (path, n, all_lines[n - 1]))
    retval = 1 if found else 0
    return retval


if __name__ == "__main__":
    sys.exit(main(sys.argv))
