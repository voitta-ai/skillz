#!/usr/bin/env python3
"""Fail a PR that changes a plugin's shipped content without bumping that
plugin's version.

The release gate in .github/workflows/release.yml only watches the bundle
plugin's version, which is the repo's release anchor. But every single-skill
plugin carries its OWN version, and that version is the cache key for
~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/ (and the Codex
equivalent). Edit skills/foo/SKILL.md, bump only the bundle, and anyone who
installed the standalone `foo` plugin keeps running the old copy forever
while `claude plugin update` reports "up to date". Nothing errors. That has
already happened here at least once.

So: work out which plugins a diff touches, and require each of them to have
advanced. Also require a plugin's Claude and Codex manifests to carry the
same version, since the two runtimes pin independently and drifting them
freezes one host silently.

On the long-lived `next` integration branch the bundle is exempted with
`--exempt skillz`: it is a monotonic counter shared by every skill PR, so on a
branch that batches many of them it acts as a lock rather than a safeguard (see
issue #188). Per-skill plugins are never exempt - their versions are
independent cache keys, not a shared counter.

Usage: check-plugin-version-bumps.py [--exempt <plugin>]... [<base-ref>]
       (base-ref default: FETCH_HEAD; one of FETCH_HEAD, origin/master,
       origin/next, master, next)
"""

import json
import pathlib
import re
import subprocess
import sys

# Every git argv below is a literal list at its own call site; refs and paths
# that vary travel on stdin. A permission gate that judges a subprocess call by
# its argv (voitta-ai/voitta-yolt#162, fixed in #167) can then see that this
# script only reads, instead of refusing the repo's own release check. So the
# base ref is one of the documented ones, each with its own literal call.


def _stdout(proc):
    retval = proc.stdout if proc.returncode == 0 else None
    return retval


def diff_names(base):
    """`git diff --name-only <base>`, for the documented bases only."""
    if base == "FETCH_HEAD":
        proc = subprocess.run(["git", "diff", "--name-only", "FETCH_HEAD"], capture_output=True, text=True)
    elif base == "origin/master":
        proc = subprocess.run(["git", "diff", "--name-only", "origin/master"], capture_output=True, text=True)
    elif base == "origin/next":
        proc = subprocess.run(["git", "diff", "--name-only", "origin/next"], capture_output=True, text=True)
    elif base == "master":
        proc = subprocess.run(["git", "diff", "--name-only", "master"], capture_output=True, text=True)
    elif base == "next":
        proc = subprocess.run(["git", "diff", "--name-only", "next"], capture_output=True, text=True)
    else:
        retval = None
        return retval
    retval = _stdout(proc)
    return retval


SUPPORTED_BASES = ("FETCH_HEAD", "origin/master", "origin/next", "master", "next")

_OBJECT_HEADER = re.compile(rb"^[0-9a-f]{40}(?:[0-9a-f]{24})? [a-z]+ [0-9]+$")


def show(spec):
    """Contents of `<rev>:<path>` like `git show` prints a blob, or None if git
    has no such object. The spec goes to `cat-file --batch` on stdin, which is
    newline-framed, so a path containing a newline fails closed rather than
    reading as a missing (brand-new) manifest."""
    if "\n" in spec:
        raise SystemExit(f"::error::cannot read {spec!r}: path contains a newline")
    out = _stdout(subprocess.run(
        ["git", "cat-file", "--batch"], input=(spec + "\n").encode(), capture_output=True,
    ))
    if out is None:
        retval = None
        return retval
    header, _, rest = out.partition(b"\n")
    # "<spec> missing" / "ambiguous", or a tree: only a blob can be a manifest.
    if not _OBJECT_HEADER.match(header) or header.split(b" ")[1] != b"blob":
        retval = None
        return retval
    size = int(header.rsplit(b" ", 1)[1])
    retval = rest[:size].decode(errors="replace")
    return retval


def parse_version(raw):
    """'1.2.10' -> (1, 2, 10). Non-numeric parts sort as -1 so they compare
    low rather than raising; validate-catalog.sh owns format policy."""
    parts = []
    for piece in str(raw).split("."):
        parts.append(int(piece) if piece.isdigit() else -1)
    retval = tuple(parts)
    return retval


def version_in(blob):
    """Version string out of a manifest's text, or None if unreadable."""
    if blob is None:
        return None
    try:
        retval = json.loads(blob).get("version")
    except json.JSONDecodeError:
        retval = None
    return retval


def version_at(ref, path):
    """Version in `path` as of `ref`, or None if the file did not exist."""
    retval = version_in(show(f"{ref}:{path}"))
    return retval


def version_now(path):
    """Version in the working tree - which is what `git diff <base>` compares
    against, so the two must read the same side. In CI the working tree and
    HEAD are identical; locally this makes the script usable on uncommitted
    changes."""
    p = pathlib.Path(path)
    retval = version_in(p.read_text()) if p.exists() else None
    return retval


def parse_argv(argv):
    """Pull repeatable --exempt <plugin> flags out, leaving the base ref.
    Hand-rolled rather than argparse so the script keeps working when invoked
    with no arguments at all, which is how it is used locally."""
    exempt = set()
    rest = []
    i = 0
    while i < len(argv):
        if argv[i] == "--exempt" and i + 1 < len(argv):
            exempt.add(argv[i + 1])
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    base = rest[0] if rest else "FETCH_HEAD"
    retval = (base, exempt)
    return retval


def main():
    base, exempt = parse_argv(sys.argv[1:])

    if base not in SUPPORTED_BASES:
        print(
            f"::error::unsupported base {base!r}; use one of: {', '.join(SUPPORTED_BASES)}",
            file=sys.stderr,
        )
        return 1
    diff = diff_names(base)
    if diff is None:
        print(f"::error::cannot diff against {base}", file=sys.stderr)
        return 1
    changed = [line for line in diff.splitlines() if line]

    catalog = json.loads(pathlib.Path("catalog.json").read_text())
    plugins = catalog["plugins"]

    # Which skills and which plugin dirs did this diff touch?
    touched_skills = set()
    touched_plugins = set()
    for path in changed:
        parts = path.split("/")
        if len(parts) > 2 and parts[0] == "skills":
            touched_skills.add(parts[1])
        elif len(parts) > 2 and parts[0] == "plugins":
            touched_plugins.add(parts[1])

    # A plugin is implicated if its own dir changed, or if it ships a skill
    # that changed. The bundle ships every skill, so it is implicated by any
    # skill edit - which is exactly the intent.
    implicated = set(touched_plugins)
    for plugin in plugins:
        if set(plugin.get("skills", [])) & touched_skills:
            implicated.add(plugin["name"])

    if exempt:
        skipped = sorted(implicated & exempt)
        implicated -= exempt
        if skipped:
            print(f"exempt from the bump check: {', '.join(skipped)}")

    if not implicated:
        print("no plugin content touched; nothing to check")
        return 0

    errors = []
    checked = 0
    for plugin in sorted(plugins, key=lambda p: p["name"]):
        name = plugin["name"]
        if name not in implicated:
            continue

        manifests = [
            plugin[key]
            for key in ("claude_manifest", "codex_manifest")
            if plugin.get(key)
        ]

        seen = {}
        for manifest in manifests:
            new = version_now(manifest)
            old = version_at(base, manifest)
            seen[manifest] = new

            if new is None:
                errors.append(f"{manifest}: cannot read a version")
                continue
            if old is None:
                # Brand-new plugin: nothing to advance past.
                continue
            if parse_version(new) <= parse_version(old):
                errors.append(
                    f"{manifest}: still {old} - bump it, "
                    f"'{name}' content changed in this PR"
                )

        distinct = {v for v in seen.values() if v is not None}
        if len(distinct) > 1:
            pairs = ", ".join(f"{m}={v}" for m, v in seen.items())
            errors.append(
                f"{name}: Claude and Codex manifests disagree ({pairs}). "
                "Both runtimes pin on their own version string; bump both."
            )
        checked += 1

    for err in errors:
        print(f"::error::{err}")
    if errors:
        return 1

    print(f"OK: {checked} implicated plugin(s) bumped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
