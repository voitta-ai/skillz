#!/usr/bin/env python3
"""Materialize the Codex marketplace with every symlink dereferenced.

Codex plugin installs drop symlinked skill directories (#176): the repo's
bundle and single-skill plugins are trees of symlinks back to skills/<name>/,
so a Codex install reports success and lands zero skills. This script copies
the Codex marketplace manifest and every plugin it lists into OUTDIR as real
files, at the same relative paths, so the result works as a Codex marketplace
on its own.

The .github/workflows/codex-branch.yml job commits the result to the `codex`
branch. Users add it with: codex plugin marketplace add voitta-ai/skillz@codex

Usage: build-codex-branch.py OUTDIR
"""

import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKETPLACE = os.path.join(".codex-plugin", "marketplace.json")
# Codex does not read .codex-plugin/marketplace.json at a marketplace root; its
# native location is .agents/plugins/marketplace.json (it also accepts
# .claude-plugin/ and .cursor-plugin/ as legacy). Verified on codex-cli 0.160.1.
CODEX_MARKETPLACE = os.path.join(".agents", "plugins", "marketplace.json")
# The Claude half of the bundle is not read by Codex; leaving it out halves the size.
IGNORED = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "skills-claude")


def skill_count(plugin_dir):
    with open(os.path.join(plugin_dir, ".codex-plugin", "plugin.json")) as f:
        manifest = json.load(f)
    skills_dir = os.path.join(plugin_dir, (manifest.get("skills") or "./skills/").lstrip("./"))
    retval = 0
    for dirpath, _, filenames in os.walk(skills_dir):
        retval += filenames.count("SKILL.md")
    return retval


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        sys.exit(2)
    outdir = os.path.abspath(sys.argv[1])
    if os.path.exists(outdir):
        print(f"error: {outdir} already exists", file=sys.stderr)
        sys.exit(2)

    with open(os.path.join(ROOT, MARKETPLACE)) as f:
        marketplace = json.load(f)
    os.makedirs(os.path.dirname(os.path.join(outdir, CODEX_MARKETPLACE)))
    shutil.copyfile(os.path.join(ROOT, MARKETPLACE), os.path.join(outdir, CODEX_MARKETPLACE))
    shutil.copyfile(os.path.join(ROOT, "LICENSE"), os.path.join(outdir, "LICENSE"))
    with open(os.path.join(outdir, "README.md"), "w") as f:
        f.write("# skillz (Codex marketplace build)\n\n"
                "Generated from https://github.com/voitta-ai/skillz by "
                "`scripts/build-codex-branch.py`; send changes there, not here.\n\n"
                "    codex plugin marketplace add voitta-ai/skillz@codex\n")

    problems = []
    for plugin in marketplace["plugins"]:
        rel = plugin["source"].lstrip("./").rstrip("/")
        src = os.path.join(ROOT, rel)
        dst = os.path.join(outdir, rel)
        shutil.copytree(src, dst, symlinks=False, ignore=IGNORED)
        if skill_count(dst) == 0 and not os.path.isdir(os.path.join(dst, "hooks")):
            problems.append(f"{plugin['name']}: no SKILL.md after materializing")

    for dirpath, dirnames, filenames in os.walk(outdir):
        for name in dirnames + filenames:
            if os.path.islink(os.path.join(dirpath, name)):
                problems.append(f"symlink left in output: {os.path.join(dirpath, name)}")
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    if problems:
        sys.exit(1)
    bundle = os.path.join(outdir, "plugins", "skillz")
    print(f"built {outdir}: {len(marketplace['plugins'])} plugins, "
          f"skillz bundle has {skill_count(bundle)} skills")


if __name__ == "__main__":
    main()
