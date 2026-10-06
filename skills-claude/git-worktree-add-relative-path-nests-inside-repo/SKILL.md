---
name: git-worktree-add-relative-path-nests-inside-repo
description: |
  Fix a git worktree that landed INSIDE the repo instead of the sibling worktrees
  directory. Use when: (1) you ran `git worktree add <relative/path> <branch>` from
  within the repo and the worktree appeared at `<repo>/<relative/path>` instead of a
  sibling like `<repo>.worktrees/<name>`, (2) your convention keeps worktrees in a
  sibling dir (e.g. `project.worktrees/feature/x`) but a new one nested under the repo
  root, (3) a nested worktree is now polluting `git status` / risks being tracked.
  Root cause: `git worktree add` resolves a RELATIVE path against the current working
  directory (the repo root when run from inside), not against the repo's parent. Fix
  with an absolute path, or relocate a mistaken one with `git worktree move`.
author: Claude Code
version: 1.0.0
date: 2026-07-18
source: DoubleDoor IDX/RESO feed work — created a feature worktree that nested inside the repo.
source_file: skills/git-worktree-add-relative-path-nests-inside-repo/SKILL.md
---

# git worktree add resolves relative paths against CWD (nests inside the repo)

Canonical source: this file in `voitta-ai/skillz`.

## Problem

Repos with a sibling-worktree convention (e.g. `myrepo/` + `myrepo.worktrees/<prefix>/<name>`)
break when you run `git worktree add` with a **relative** path from **inside** the repo:

```bash
cd /path/to/myrepo
git worktree add myrepo.worktrees/feature/x feature/x
# -> creates /path/to/myrepo/myrepo.worktrees/feature/x   (NESTED, wrong)
# wanted /path/to/myrepo.worktrees/feature/x              (SIBLING)
```

The relative path is resolved against the current working directory (the repo root),
not the repo's parent. The worktree ends up nested inside the working tree, where it
pollutes `git status` and can get accidentally added.

## Context / Trigger Conditions

- Project convention stores worktrees in a **sibling** dir (`<repo>.worktrees/...`).
- You ran `git worktree add` with a relative path while `cwd` was the repo root.
- `git worktree list` shows a path like `<repo>/<repo>.worktrees/...` (repo name twice).

## Solution

Use an **absolute path** for the target:

```bash
git worktree add /path/to/myrepo.worktrees/feature/x feature/x
```

To relocate one already created in the wrong place, use `git worktree move` (do NOT
`mv` a worktree by hand — it breaks the gitdir linkage):

```bash
git worktree move myrepo.worktrees/feature/x /path/to/myrepo.worktrees/feature/x
# then clean up the now-empty nested dirs
rmdir myrepo.worktrees/feature myrepo.worktrees 2>/dev/null
git worktree list   # verify the path is the sibling, and repo name appears once
```

## Prevention

- Always pass an absolute path to `git worktree add` (and `move`).
- After adding, run `git worktree list` and confirm the new path is the sibling
  location — a doubled repo name in the path (`myrepo/myrepo.worktrees`) is the tell.
