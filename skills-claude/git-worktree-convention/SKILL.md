---
name: git-worktree-convention
description: |
  Keep every git repo on its default branch and do all branch work in a
  sibling `<repo>.worktrees/` directory. Use when: (1) starting branch work
  in any repo under a managed tree and you need to know where the worktree
  goes, (2) cloning a new repo and setting up its layout, (3) you notice a
  repo sitting on a non-default branch, or worktrees scattered outside
  `<repo>.worktrees/` (e.g. `repo-wt-87`, a nested `repo/repo.worktrees/...`)
  and want to know whether and how to reorganize, (4) `git worktree add`
  put a worktree INSIDE the repo instead of the sibling dir, (5) a branch is
  already checked out in the repo dir and `git worktree add` refuses with
  "is already used by worktree at". Covers the layout, the drift check to run
  before starting work, the ask-before-reorganizing rule, and the recovery
  procedures for each drift shape.
author: Claude Code
version: 1.1.0
date: 2026-08-07
source: Consolidation of the local git-worktree-convention note with skills/git-worktree-add-relative-path-nests-inside-repo (absorbed here).
source_file: skills/git-worktree-convention/SKILL.md
---

# Git worktree convention: repo on default, branches in `<repo>.worktrees/`

Canonical source: this file in `voitta-ai/skillz`.

## The pattern

```
<parent-dir>/
  <repo>/              # ALWAYS on the default branch (main or master)
  <repo>.worktrees/    # sibling dir holding every branch worktree
    <branch-name>/     # one dir per active branch; path mirrors branch name
```

Rules:

1. The repo directory itself **never leaves the default branch**. It is the
   place you read "what is shipped" and the place you branch from.
2. All branch work happens in `<repo>.worktrees/<branch-name>/`.
3. On a fresh clone, create the `.worktrees` sibling immediately.
4. A branch name with a slash nests (`feature/x` -> `.worktrees/feature/x/`).
   That is correct — the path mirrors the branch name.

Why: a repo pinned to the default branch means `git log`, `gh pr create
--base`, and any tooling that reads the repo dir always sees a stable base,
and N branches can be worked (or reviewed, or built) at once without
stashing.

## Before starting branch work: check for drift

Run this in the repo whose branch you are about to touch. It is read-only.

```bash
REPO=/path/to/repo
git -C "$REPO" rev-parse --abbrev-ref HEAD          # expect main or master
git -C "$REPO" worktree list                        # expect only <repo> + <repo>.worktrees/*
ls -d "${REPO}"* 2>/dev/null                        # expect only <repo> and <repo>.worktrees
```

Three drift shapes, each with its own fix below:

| Symptom | Shape |
| ------- | ----- |
| `rev-parse` prints something other than main/master | repo dir is on a branch |
| `worktree list` shows a path outside `<repo>.worktrees/` (e.g. `repo-wt-87`, `repo.wt/x`) | ad-hoc worktree location |
| `worktree list` shows the repo name twice (`repo/repo.worktrees/x`) | worktree nested inside the repo |

## When you find drift: ASK, do not silently reorganize

Reorganizing moves someone's working directory. An editor, a terminal, a
running dev server, or a background agent may be sitting in the path you are
about to move, and a worktree with uncommitted changes is not yours to
relocate on a hunch.

So: **report what you found and ask before restructuring.** Say which repos
drifted, which shape each one is, and what the fix would do. Offer to do the
whole set, a subset, or nothing. Then act on the answer.

Two things to check before proposing a move, because they change the answer:

```bash
git -C "$WORKTREE" status --short          # uncommitted work?
git -C "$WORKTREE" rev-parse --abbrev-ref HEAD   # detached HEAD?
```

- **Uncommitted changes** — offer to commit or stash first; do not move over them.
- **Detached HEAD** — there is no branch to name the worktree after. Ask what
  it was for; often the answer is that it is stale and should be removed
  (`git worktree remove`), not relocated.
- **Nothing to salvage** — a worktree that is on the default branch, clean,
  and duplicated by the repo dir itself is just clutter; removing it is the
  fix, not moving it.

## Fix order when a repo has several drift shapes at once

Do **removals first, then the repo-dir checkout, then the moves.** Fix 1
tells you to put the repo back on its default branch — but if a stale
worktree is itself sitting on that default branch, the checkout fails:

```
$ git -C skillz checkout master
fatal: 'master' is already used by worktree at '.../skillz-wt-87'
```

Same constraint as Fix 1, from the other direction: a branch can be
checked out in exactly one place. Clear the stale worktrees holding it
before you try to take it.

## Fix 1: repo dir is on a non-default branch

Switch the repo back to default **first**, then add the worktree for the
now-free branch.

If the branch has commits the remote does not, push it before the
checkout — the branch is about to stop being the thing you have open, and
an unpushed commit is easy to forget once it is.

Do NOT try `git worktree add <path> <current-branch>` while still on that
branch — git refuses with `fatal: '<current-branch>' is already used by
worktree at '<repo>'`. A branch checked out in the repo dir cannot also be
checked out in a worktree, so you must leave it before you can re-add it.

```bash
git -C /path/to/repo status                     # inspect the working tree
mkdir -p /path/to/repo.worktrees

# Ambient uncommitted/untracked changes will abort the checkout below with
# "Your local changes to the following files would be overwritten".
# Stash them (including untracked) so the switch is clean:
git -C /path/to/repo stash push -u -m "ambient-pre-worktree-restructure"

git -C /path/to/repo checkout main              # or master
git -C /path/to/repo pull --ff-only

# <branch> is free now:
git -C /path/to/repo worktree add /path/to/repo.worktrees/<branch> <branch>

git -C /path/to/repo stash pop                  # restore ambient files
```

The branch's commits are untouched (no force-push), so any open PR for that
branch needs no update. If `stash pop` conflicts, resolve it in the repo
(default) checkout — the worktree is already created and unaffected.

## Fix 2: worktree in an ad-hoc location

Use `git worktree move`. Never `mv` a worktree by hand — that breaks the
gitdir linkage in both directions.

```bash
git -C /path/to/repo worktree move /path/to/repo-wt-87 /path/to/repo.worktrees/<branch>
git -C /path/to/repo worktree list        # verify
```

If the ad-hoc worktree is detached or stale, remove it instead:

```bash
git -C /path/to/repo worktree remove /path/to/repo-wt-pr84
git -C /path/to/repo worktree prune       # clears records of deleted dirs
```

## Fix 3: worktree nested inside the repo

Absorbed from the former `git-worktree-add-relative-path-nests-inside-repo`
skill.

**Root cause:** `git worktree add` resolves a **relative** path against the
**current working directory**, not against the repo's parent. Run from inside
the repo, a relative path lands under the repo root:

```bash
cd /path/to/myrepo
git worktree add myrepo.worktrees/feature/x feature/x
# -> /path/to/myrepo/myrepo.worktrees/feature/x   NESTED, wrong
# wanted /path/to/myrepo.worktrees/feature/x      SIBLING
```

The tell is the repo name appearing **twice** in `git worktree list`. A
nested worktree pollutes `git status` and can get accidentally committed.

Fix:

```bash
git worktree move myrepo.worktrees/feature/x /path/to/myrepo.worktrees/feature/x
rmdir myrepo.worktrees/feature myrepo.worktrees 2>/dev/null
git worktree list   # repo name should appear once
```

**Prevention: always pass an absolute path** to `git worktree add` and
`git worktree move`, then confirm with `git worktree list`.

## Command reference

```bash
# New clone
git clone <url> /path/to/repo
mkdir -p /path/to/repo.worktrees

# New branch (absolute path, always)
git -C /path/to/repo worktree add /path/to/repo.worktrees/<branch> -b <branch> origin/main

# Existing remote branch
git -C /path/to/repo fetch origin
git -C /path/to/repo worktree add /path/to/repo.worktrees/<branch> <branch>

# List / clean up
git -C /path/to/repo worktree list
git -C /path/to/repo worktree remove /path/to/repo.worktrees/<branch>
git -C /path/to/repo worktree prune
```

## Related

- `multi-phase-feature-pr-worktrees` — stacking one worktree per phase under
  an umbrella feature branch when a feature ships as several PRs.
- `git-graft-worktree-onto-remote` — wiring an existing on-disk directory up
  as a clone of a remote without losing local files.
- `work-on-pr` and `review-pr-loop` — the two PR loops that create worktrees
  per round. Both follow this layout; if you find either describing a
  `<repo>-wt-<N>` path, it predates this skill and the layout here wins.
