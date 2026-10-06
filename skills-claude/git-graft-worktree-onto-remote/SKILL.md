---
name: git-graft-worktree-onto-remote
description: |
  Wire up an existing on-disk working tree as a clone of a remote repo without
  losing local files. Use when: (1) a project's source files already exist on
  disk in directory X but X is not a git repo and the canonical repo lives at
  a remote URL, (2) the parent of X is a misconfigured git repo (only a stub
  README committed, with X and other unrelated dirs showing as untracked),
  (3) you cloned files manually or unpacked a tarball and now want to start
  tracking against the upstream remote, (4) you must preserve the local files
  exactly as they are (do not overwrite, do not stash) while still inheriting
  the remote's commit history. Covers the `git reset --mixed` vs `--soft`
  distinction that trips up this workflow.
author: Claude Code
version: 1.0.0
date: 2026-05-02
---

# Graft an existing working tree onto a remote git history

## Problem

You have a directory full of project files on disk. The canonical git
repository for that project lives somewhere else (typically a GitHub remote).
You want to make the on-disk directory a working clone of that remote
**without touching the on-disk files**, so you can commit your existing local
changes as the next commit on top of the remote's history.

The naive approaches fail:
- `git clone <remote> <dir>` refuses if `<dir>` is non-empty.
- `git clone <remote> tmp && mv tmp/.git <dir>/` leaves the index empty, so
  every existing file shows as untracked. Worse, if a file like `README.md`
  exists both on the remote and locally with different content, you lose the
  signal that it is a *modification* (not an addition) and risk committing a
  wholesale replacement instead of a normal diff.
- `git init && git remote add && git pull` triggers a merge with no common
  ancestor, often refusing or producing conflicts on every overlapping file.
- `git reset --soft origin/<branch>` after `init`+`fetch` looks right but
  stages a *deletion* of every file in the remote tree, because `--soft`
  preserves the (still-empty) index. You end up with `D README.md` plus
  `?? README.md` — the local file shows as both deleted and untracked.

The correct trick is `git reset --mixed origin/<branch>`, which sets `HEAD`
to the remote commit *and* repopulates the index from that commit, so the
existing on-disk files are diffed against the remote's tree as normal
modifications/additions.

## Context / Trigger Conditions

Apply this skill when ALL of the following hold:

1. A directory `X` on disk contains the project files you want to track.
2. `X` is not currently a git repo (`X/.git` does not exist) — OR `X` is a
   subdirectory of an unrelated/misconfigured git repo whose `.git` you have
   first moved aside.
3. There is a remote URL `R` whose default branch (e.g. `master`/`main`)
   contains earlier commits for this same project (often just a stub
   README).
4. You want the existing files in `X` to land as the *next* commit on top of
   the remote's history, with the diff displayed as a normal modification of
   any pre-existing files (not as wholesale replacement).

Common precursor symptom: at some parent of `X`, `git status` shows `X/` and
several other unrelated sibling directories as untracked. That parent is the
misconfigured repo and its `.git` should be moved aside before you start.

## Solution

```bash
# 0. (If applicable) Move aside a misconfigured parent .git so X stops
#    being inside an unrelated working tree. Back up — do not delete.
TS=$(date +%Y%m%d-%H%M%S)
mv /path/to/parent/.git /tmp/parent-git-backup-$TS

# 1. Initialize a fresh repo at X with the correct default branch name.
cd /path/to/X
git init -b <default-branch>      # e.g. master or main

# 2. Wire up the remote.
git remote add origin <remote-url>

# 3. Fetch so refs/remotes/origin/<default-branch> exists locally.
git fetch origin

# 4. The critical step: reset --mixed (NOT --soft, NOT --hard).
#    --mixed sets HEAD to origin/<branch> and repopulates the index from
#    that tree, leaving the working tree untouched. Existing on-disk files
#    that match the upstream tree go quiet; ones that differ show as
#    modifications; new files show as untracked.
git reset --mixed origin/<default-branch>

# 5. Wire up branch tracking so future push/pull DTRT.
git branch --set-upstream-to=origin/<default-branch> <default-branch>

# 6. Verify and commit as normal.
git status --short --branch
git add .
git commit -m "..."
git push    # only when you're ready
```

## Verification

After step 4, `git status --short --branch` should show:

- `## <branch>...origin/<branch>` (no `[ahead/behind]` indicator).
- `M <file>` for every locally-existing file whose contents differ from the
  remote's version.
- `??` entries for every locally-existing file that the remote does not have.
- **No** `D <file>` entries (no spurious deletions).

If you see `D <file>` lines, you used `--soft` instead of `--mixed`. Re-run
`git reset --mixed origin/<branch>` to fix.

If `git diff <file>` for a `M` entry shows a sensible per-line diff against
the upstream version (rather than the entire file as added/removed), the
graft worked.

## Example

Concrete case: a directory `voitta-omemepo/` with a fuller README, a
`pyproject.toml`, a `src/` tree, and several other files. Its parent dir
was set up as the `voitta-ai/omemepo` git repo by mistake, with only a
one-line stub README committed. Goal: make `voitta-omemepo/` itself the
clone of `git@github.com:voitta-ai/omemepo.git`, preserving every file.

```bash
TS=$(date +%Y%m%d-%H%M%S)
mv /Users/me/g/git.voitta/.git /tmp/git.voitta-toplevel-git-backup-$TS

cd /Users/me/g/git.voitta/voitta-omemepo
git init -b master
git remote add origin git@github.com:voitta-ai/omemepo.git
git fetch origin
git reset --mixed origin/master
git branch --set-upstream-to=origin/master master

# Result of `git status --short`:
#  M README.md          <-- stub README differs from full local README
# ?? .claude-plugin/
# ?? .gitignore
# ?? docs/
# ?? plugins/
# ?? pyproject.toml
# ?? src/

git add .
git commit -m "WIP: project skeleton"
# git push  -- when ready
```

`git diff README.md` correctly shows the stub `# omemepo` becoming the
full multi-paragraph README — a normal one-file modification, not a
delete-plus-add.

## Notes

- **`--mixed` is the default for `git reset`**, but spell it explicitly here
  so the intent is obvious to a future reader.
- **`--hard` would destroy the local files** — never use it for this workflow.
- **`--soft` looks tempting** because you're "starting fresh," but it leaves
  the index empty, which makes the upstream tree look like a pending
  deletion. The lived experience is "why does git think I want to delete
  every file in the repo?" The fix is to swap `--soft` for `--mixed`.
- **If the local README and the remote README share zero similarity**, the
  resulting diff may still be large, but it'll be a *single-file* diff. That
  is fine — it's the truthful representation of the change.
- **If history doesn't matter**, you can skip steps 3–5 and just
  `git init && git add . && git commit && git remote add && git push --force`,
  but you'll discard the upstream's commits. Only do that if both you and the
  remote agree the upstream history is throwaway.
- **The `.git` backup at `/tmp/parent-git-backup-*` can be deleted** once you
  have verified the new repo at X is good and pushed. Keep it for at least
  one session in case you need to recover anything (e.g. a hooks dir or
  config you forgot about).
- This is distinct from `git worktree add`, which creates an additional
  working tree off an existing repo. Here we're creating a *new* repo whose
  working tree happens to already be populated.

## References

- `git reset` modes: <https://git-scm.com/docs/git-reset#_reset_modes>
- Why `--mixed` is the default: it's the safest middle ground (touches the
  index but not the working tree), which is exactly what this workflow
  needs.
