---
name: git-simulate-sequential-merges
description: |
  Find out which merges in a queue of N branches will actually conflict, before
  merging any of them, without touching refs, worktrees, the index or the
  working tree. Use when: (1) several open PRs all append to the same file
  (a plugin registry, an `__init__.py`, a barrel export, a CHANGELOG, a lockfile)
  and you need the real conflict set rather than a guess, (2) you are picking a
  merge ORDER and want to know which order minimizes hand-resolution, (3) someone
  handed you a claim like "expect a conflict on the second and third merge" and
  you want to verify rather than adopt it, (4) you want to preview the exact
  merged content of a file after a whole queue lands, (5) you must not create
  branches or dirty a worktree because other agents or sessions are working in
  the repo. Covers why `git merge-tree A B` alone answers the wrong question for
  a queue, the `--write-tree` + `commit-tree` chaining trick that answers the
  right one, reading the stage-1/2/3 conflict output, and the ORDER_FILE cleanup.
author: Claude Code
version: 1.0.0
date: 2026-08-24
source: https://github.com/voitta-ai/skillz
source_file: skills/git-simulate-sequential-merges/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/git-simulate-sequential-merges/SKILL.md`). Updates go through the
> repo's worktree + PR workflow.

# Simulate a queue of merges without touching the repo

## Problem

You have N branches queued to merge into one base. Several of them append to the
same file. You want three answers *before* merging anything:

1. **Which merges conflict?** Not "will there be conflicts" — which specific ones.
2. **Does merge order change that?**
3. **What does the file look like when the whole queue has landed?**

The usual ways to find out are all destructive or expensive:

- Actually merging and hitting the conflict. Now you have a dirty index mid-queue.
- `git merge --no-commit --no-ff` then `git merge --abort`. Touches the index and
  working tree; unusable if another session or agent is working in that checkout.
- Spinning up a scratch clone or worktree per permutation. Slow, and litters
  branches you then have to clean up.
- Guessing from the diffs. **This is where the errors come from** — see below.

**The guess is wrong more often than it feels.** Two branches that both edit a
file do not necessarily conflict; git merges non-overlapping hunks silently. The
common failure is over-predicting: assuming every branch touching a shared
registry file collides with every other one, and budgeting N-1 hand-resolutions
when the real answer is one.

## The wrong tool for this job

`git merge-tree <branch1> <branch2>` is the obvious reach and it answers a
different question: it merges those two against **their** merge base. For a
queue you do not want `base+A` and `base+B` compared — you want `base+A` merged
with `C`, which requires the intermediate result to exist as a commit.

That is the whole trick: **you need commits, not trees, to chain — but you do not
need refs.**

## The technique

`git merge-tree --write-tree` writes the merged tree into the object database and
prints its OID. `git commit-tree` wraps any tree in a commit object, also without
a ref. Chain them: each simulated merge becomes the base for the next.

Nothing is written outside `.git/objects`. No branch is created, no ref moves, the
index and working tree are untouched. Unreferenced objects are garbage-collected
on their own schedule.

```bash
#!/usr/bin/env bash
# Which merges in this queue actually conflict?
set -e
cd /path/to/repo

BASE=master
QUEUE=(feature-a feature-b feature-c)   # merge order under test

prev=$(git rev-parse "$BASE")
echo "base=$prev"

for b in "${QUEUE[@]}"; do
  if out=$(git merge-tree --write-tree "$prev" "$b" 2>&1); then
    tree=$(echo "$out" | head -1)
    echo "MERGE $b : clean -> tree $tree"
    prev=$(git commit-tree "$tree" -p "$prev" -p "$(git rev-parse "$b")" \
             -m "sim merge $b")
  else
    echo "MERGE $b : CONFLICT"
    echo "$out" | head -20
    break
  fi
done
```

`$prev` now names a real (if unreferenced) commit representing the whole queue
landed. Inspect any file at that state:

```bash
git show "$prev:path/to/registry.py"
```

That is the answer to question 3, and it is often the thing you actually wanted:
the resolved file content, ready to paste onto the last branch so the final merge
lands clean.

### Reading the output

**Clean:** exit 0, first line is the tree OID.

**Conflict:** exit 1 (specifically, exit status 1 means conflicts; other nonzero
values mean the merge could not be attempted at all). Output looks like:

```
<conflicted-tree-oid>
100644 <base-blob> 1	src/registry.py
100644 <ours-blob>  2	src/registry.py
100644 <their-blob> 3	src/registry.py

Auto-merging src/registry.py
CONFLICT (content): Merge conflict in src/registry.py
```

The trailing digit is the **merge stage**: `1` = merge base, `2` = "ours"
(the accumulated queue so far), `3` = "theirs" (the branch being merged). Those
blob OIDs are readable directly — `git cat-file -p <oid>` — which is how you see
all three sides without ever materializing a conflicted working tree.

The first line is still a tree OID, but it is the *conflicted* tree with conflict
markers embedded. Do not chain from it.

### Testing whether order matters

Wrap the loop in a function and run it per permutation. Ordering effects are real
when one branch restructures a region others insert into: merge the restructuring
branch **first** and the rest often merge clean against the new shape; merge it
last and everything collides with it.

```bash
for order in "a b c" "b c a" "c a b"; do
  echo "=== order: $order ==="
  simulate $order
done
```

## Gotchas

1. **`--write-tree` is the modern mode and needs Git 2.38+.** Older git has only
   the deprecated `--trivial-merge` mode with completely different output. Check
   `git --version` before trusting a script that assumes the new form.

2. **The conflicted tree is not chainable.** On conflict, stop — or resolve by
   hand and `git hash-object -w` / `git mktree` a corrected tree if you really
   want to continue past it. Silently chaining from a conflicted tree gives you
   a simulation containing literal `<<<<<<<` markers, and everything downstream
   is meaningless.

3. **`commit-tree` needs identity.** In an environment with no configured
   `user.email` it fails. Pass it inline if needed:
   `git -c user.email=sim@local -c user.name=sim commit-tree ...`

4. **Simulate the same base git will.** `git merge-tree` uses the merge base of
   the two commits you name. If your host squash-merges or rebases on merge, the
   real integration is not a merge commit and this simulation predicts the wrong
   thing. It models a true merge; check what your forge is configured to do.

5. **`--name-only` shrinks the output** to just conflicted paths when you want a
   list rather than the full stage table. Useful for the "which files" question
   when the queue is large.

6. **`ORDER_FILE` and other merge-strategy config still apply.** A repo with
   `.gitattributes` merge drivers will have those honored, which is usually what
   you want — but it means the simulation is only as reproducible as the config.

7. **The objects are real.** They are unreferenced and will be gc'd eventually,
   but if you simulate a very large queue repeatedly you are writing trees into
   the object database each time. Harmless; not free.

## Why this matters beyond convenience

The output is **evidence rather than prediction**, and it is cheap enough that
there is no excuse for guessing. In a multi-agent or multi-session workflow the
conflict forecast tends to get written into a handoff document, repeated by a
second agent, and then acted on by a third — with nobody having run it. A
three-line loop settles it, and settles it in a form the next reader can re-run.

Corollary worth internalizing: **when a teammate hands you a conflict forecast,
re-run it.** It costs seconds and the failure mode of adopting it is that you
budget hand-resolution for merges that were always going to be clean, or worse,
reorder the queue to avoid a conflict that does not exist.

## Related

- `multi-phase-feature-pr-worktrees` — the workflow that produces these queues in
  the first place.
- `git-worktree-convention` — where the branches under test usually live.
- `gh-pr-merge-delete-branch-closes-dependent-pr` — a different, nastier failure
  mode of merging a queue of dependent PRs.
