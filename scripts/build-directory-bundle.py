#!/usr/bin/env python3
"""Materialize the skillz bundle plugin as a standalone folder for the Claude
plugin directory.

The directory's portal validates a plugin folder and rejects what the repo
layout relies on: plugins/skillz/ is a tree of symlinks back to skills/<name>/
(blocked), it has no README of its own (blocked), and it sits in a subfolder,
which tightens the rules on scripts the plugin runs. This script copies the
Claude half of the bundle with every symlink dereferenced into OUTDIR, at the
folder root, adds a generated README and the repo LICENSE, and checks the
directory's size limits so a bad build fails here instead of in review.

The .github/workflows/directory-branch.yml job commits the result to the
`directory` branch, which is what the directory submission tracks.

Usage: build-directory-bundle.py OUTDIR
"""

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, "plugins", "skillz")

# Limits from the directory pre-submission checklist. Exceeding them holds the
# version for a reviewer rather than blocking it, but a hold on every release
# defeats auto-publish, so treat them as hard limits here.
MAX_FILES = 512
MAX_TEXT_BYTES = 256 * 1024
IGNORED_NAMES = {"__pycache__", ".DS_Store", "Thumbs.db", "desktop.ini", "__MACOSX"}


def copy_tree(src, dst):
    shutil.copytree(
        src,
        dst,
        symlinks=False,
        ignore=shutil.ignore_patterns(*IGNORED_NAMES, "*.pyc"),
    )


def render_readme(catalog, manifest):
    bundle = next(p for p in catalog["plugins"] if p["name"] == "skillz")
    summaries = {s["name"]: s.get("summary", "") for s in catalog["skills"]}
    lines = [
        "# skillz",
        "",
        "A catalog of agent skills for Claude: reusable, field-tested procedures for",
        "debugging, operations, and agent workflows, each written as a plain",
        "`SKILL.md` that Claude loads when the task matches its description.",
        "",
        "This plugin bundles every skill in the catalog except those whose own",
        "plugin ships hooks. It contains only Markdown instructions and helper",
        "scripts that a skill tells Claude to run; it installs no hooks, starts no",
        "MCP servers, and sends nothing anywhere on its own. Skills that talk to an",
        "external service say so in their own `SKILL.md` and use the credentials",
        "you give them for that task.",
        "",
        "Source, issues, and the per-skill plugins:",
        manifest["repository"],
        "",
        "This folder is generated from the source repository by",
        "`scripts/build-directory-bundle.py`; send changes there, not here.",
        "",
        "## Skills",
        "",
    ]
    for name in bundle["skills"]:
        lines.append(f"- **{name}**: {summaries.get(name, '')}".rstrip())
    lines.append("")
    retval = "\n".join(lines)
    return retval


def check_limits(outdir):
    problems = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(outdir):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                problems.append(f"symlink left in output: {path}")
        for name in filenames:
            count += 1
            path = os.path.join(dirpath, name)
            size = os.path.getsize(path)
            if size > MAX_TEXT_BYTES:
                problems.append(f"{path} is {size} bytes (limit {MAX_TEXT_BYTES})")
    if count > MAX_FILES:
        problems.append(f"{count} files (limit {MAX_FILES})")
    retval = (count, problems)
    return retval


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        sys.exit(2)
    outdir = os.path.abspath(sys.argv[1])
    if os.path.exists(outdir):
        print(f"error: {outdir} already exists", file=sys.stderr)
        sys.exit(2)

    with open(os.path.join(ROOT, "catalog.json")) as f:
        catalog = json.load(f)
    with open(os.path.join(BUNDLE, ".claude-plugin", "plugin.json")) as f:
        manifest = json.load(f)

    os.makedirs(outdir)
    copy_tree(os.path.join(BUNDLE, ".claude-plugin"), os.path.join(outdir, ".claude-plugin"))
    skills_dir = (manifest.get("skills") or "./skills/").strip("./")
    copy_tree(os.path.join(BUNDLE, skills_dir), os.path.join(outdir, skills_dir))
    copy_tree(os.path.join(BUNDLE, "bin"), os.path.join(outdir, "bin"))
    shutil.copyfile(os.path.join(ROOT, "LICENSE"), os.path.join(outdir, "LICENSE"))
    with open(os.path.join(outdir, "README.md"), "w") as f:
        f.write(render_readme(catalog, manifest))

    count, problems = check_limits(outdir)
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    if problems:
        sys.exit(1)
    print(f"built {outdir}: skillz {manifest['version']}, {count} files")


if __name__ == "__main__":
    main()
