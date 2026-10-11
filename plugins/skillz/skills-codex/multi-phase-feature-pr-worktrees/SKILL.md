---
name: multi-phase-feature-pr-worktrees
description: |
  Ship a multi-phase feature as a stack of small reviewable PRs while
  preserving incremental commit history and parallel review. Use when:
  (1) an issue or design doc lays out N discrete phases (PoC →
  incremental → metadata → polish), (2) you want each phase reviewable
  on its own without losing the big-picture diff, (3) merging the whole
  feature in one PR would be too large to review well, (4) you want to
  develop later phases in parallel with review of earlier ones.
  Pattern: one umbrella `feature/<name>` branch off main, one
  `phase-N-<topic>` branch per phase, each phase PR targets the
  umbrella branch (NOT main), final PR merges umbrella → main once
  all phases are in. Each phase lives in its own git worktree under
  `<repo>.worktrees/<branch-name>/`. After each phase merge, rebase
  the next phase's worktree onto the updated umbrella branch.
author: Claude Code
version: 1.1.0
date: 2026-05-08
---

# Multi-Phase Feature PRs with Worktrees

## Problem

A feature breaks naturally into N phases (e.g., issue #15 listed
4 implementation phases plus a blog post). Two common failure modes
when shipping it:

1. **One mega-PR**: 1500-line diff, reviewers skim, bugs ship.
2. **N independent PRs against main**: each phase has to wait for
   the previous to merge before review can begin; reviewers lose
   the connecting thread; later phases need rebasing on earlier
   ones every time main moves.

The umbrella-feature-branch pattern fixes both: small per-phase
PRs that are reviewable in isolation, but stacked on a stable
base that lives long enough for the whole feature to land
together.

## Context / Trigger Conditions

- An issue body or RFC explicitly lists "Phase 1 / Phase 2 /
  Phase 3" or similar staged delivery.
- The user says "do these as separate PRs but keep history" or
  "incremental commits, one per phase".
- The work is too big for one PR but each phase is too small to
  justify its own merge to main.
- You want phase 2 to start coding while phase 1 is in review.

## Solution

### 1. Umbrella branch

From a clean main:

```bash
cd <repo>
git fetch origin
git checkout -b feature/<name> origin/main
git push -u origin feature/<name>
git checkout main  # main repo stays on main; phases live in worktrees
```

The umbrella branch starts identical to main. Every phase PR
targets it.

### 2. Worktree per phase

Convention used in this user's environment: main checkout stays
on main/master in `<repo>/`; branches live in
`<repo>.worktrees/<branch-name>/` siblings. So:

```bash
git worktree add ../<repo>.worktrees/phase-1-<slug> \
    -b phase-1-<slug> feature/<name>
```

Now `<repo>.worktrees/phase-1-<slug>/` is a fully checked-out
working copy on `phase-1-<slug>`, branched from
`feature/<name>`.

### 3. Implement phase 1, push, open PR

```bash
cd <repo>.worktrees/phase-1-<slug>
# ... edits ...
git add -A
git commit -m "Phase 1: ..."
git push -u origin phase-1-<slug>
gh pr create \
    --base feature/<name> \
    --head phase-1-<slug> \
    --title "Phase 1: ..." \
    --body "..."
```

Critical: `--base feature/<name>`, not main.

### 4. Phase 2 starts in parallel (optional)

If phase 2 is independent of phase 1, branch it ALSO off
`feature/<name>` (not phase 1):

```bash
git worktree add ../<repo>.worktrees/phase-2-<slug> \
    -b phase-2-<slug> feature/<name>
```

Phase 2 PR also targets `feature/<name>`. The two PRs review in
parallel.

If phase 2 depends on phase 1, branch off phase 1 instead, but
note the PR will show phase 1's diff plus its own — that's
unavoidable until phase 1 merges into the umbrella.

### 5. Merge phases as they're approved

Each phase PR merges into `feature/<name>` (squash or merge,
your call — squash gives one clean commit per phase on the
umbrella branch, which is usually what you want for the final
diff). For dependent phases, rebase on the updated umbrella:

```bash
cd <repo>.worktrees/phase-2-<slug>
git fetch origin
git rebase origin/feature/<name>
git push --force-with-lease
```

### 5.5. Decimal-numbered unblocker sub-PRs (the "discovered-mid-test" pattern)

Manual testing of phase N routinely uncovers latent bugs that are NOT
in scope for phase N. Two ways to handle them, both common in
practice:

**Wrong, but tempting**: silently slip the fix into the phase-N branch
and amend the commit. Couples two unrelated changes into one PR, makes
review harder, makes the umbrella PR's per-phase diff lie about what
phase N actually did.

**Right**: file the fix as its own sub-PR using a decimal number
between phases. Branch off the umbrella `feature/<name>`, fix, push,
PR, squash-merge into the umbrella, rebase phase N+1 on the updated
umbrella. Phase N can then resume its own scope.

```bash
# Hit a bug while testing phase 2. Don't pollute phase 2.
git worktree add ../<repo>.worktrees/phase-2.5-<short-slug> \
    -b phase-2.5-<short-slug> origin/feature/<name>
# fix, commit, PR with --base feature/<name>, merge, return to phase 2 test
```

Real-world example: voitta-rag PR #41 closed issue #15 with phases
1, 2, **2.5**, **2.7**, **2.8**, **2.9**, 3, **3.1**, 4. The bolded
decimals were all unblocker sub-PRs discovered during manual testing
— DB init bugs, lock contention, qdrant timeout, orphan-cleanup race
— none of which were "Phase 2" or "Phase 3" work in the original
issue body. Each one is a tiny, reviewable PR pinned to the symptom
it fixed.

Rules of thumb:

- Major numbers map 1:1 to the issue body's phases.
- Decimal numbers are for fixes that are EITHER unrelated to any
  phase OR that unblock a phase but don't belong inside it.
- A decimal sub-PR is allowed to depend on prior phases (e.g.
  phase-2.5 might depend on phase-2 having landed) — that's fine
  because the umbrella branch is the base.
- Don't try to renumber if you skip — `phase-2.7` next to
  `phase-2.5` is fine. The number is a sort key, not an ordinal.

### 6. Final merge

When all phases are in, open ONE PR `feature/<name>` → `main`.
Review surface here is "did everything come together cleanly?",
not line-by-line — that's already happened on the per-phase
PRs.

```bash
gh pr create --base main --head feature/<name> \
    --title "Feature <name>" --body "Closes #<issue>"
```

After merge, clean up:

```bash
cd <repo>
git worktree remove ../<repo>.worktrees/phase-1-<slug>
git worktree remove ../<repo>.worktrees/phase-2-<slug>
git branch -d phase-1-<slug> phase-2-<slug> feature/<name>
git push origin --delete phase-1-<slug> phase-2-<slug> feature/<name>
```

## Verification

After step 1, `git log --oneline feature/<name>` should match
main. After step 3, the GitHub PR page for the phase-1 PR should
show "wants to merge into `feature/<name>` from `phase-1-...`".
After step 6, `git log --oneline main` should show all phase
commits (squashed or merged) in order, no orphans.

## Example

Issue #15 in voitta-rag (May 2026): 4-phase llm-tldr integration.

```
master
  └── feature/llm-tldr-integration   ← umbrella, lives ~weeks
        ├── phase-1-poc              ← PR #31 → feature branch
        ├── phase-2-incremental      ← PR #?? → feature branch
        ├── phase-3-metadata         ← PR #?? → feature branch
        └── phase-4-hook             ← PR #?? → feature branch
```

Per-phase PRs reviewable independently; final PR
`feature/llm-tldr-integration` → `master` is the integration
gate.

## Notes

- **Squash vs merge for phase PRs**: prefer squash. Per-phase
  history during development is noisy (WIP commits, fixup
  commits). One squashed commit per phase on the umbrella branch
  gives a clean four-commit final PR — exactly what reviewers
  want at the integration step.
- **Stale phase branches**: if a phase merges and you continue
  working in its worktree, you'll be on a dead branch. Either
  remove the worktree right after merge, or `git checkout
  feature/<name>` inside it to keep the worktree alive for
  follow-ups.
- **CI on the umbrella branch**: most CI configs run on PRs
  AND on push to long-lived branches. Your umbrella branch will
  rebuild on every phase merge — that's fine and gives you an
  integration smoke test for free.
- **Conflict avoidance**: phases that touch the same files
  cause rebase conflicts when merged in sequence. Plan phase
  boundaries to follow file/module boundaries when possible.
- **Don't make the umbrella branch long-lived in `master`'s
  history.** It's a staging area, not a release branch. Squash
  the umbrella PR into main if your repo's policy allows; it
  flattens to N (one per phase) commits on main, which is
  exactly the history you want.

## References

- Git worktrees:
  https://git-scm.com/docs/git-worktree
- GitHub stacked PR patterns (this is a low-tech version of
  what tools like Graphite / Sapling automate):
  https://graphite.dev/guides/stacked-prs

## Related

- `git-worktree-convention` — the sibling-worktree layout each phase's tree
  follows, and the absolute-path rule that keeps a phase worktree from nesting
  inside the repo.
- `gh-pr-merge-delete-branch-closes-dependent-pr` — the trap that bites this
  shape specifically: merging phase N with branch deletion closes phase N+1
  rather than retargeting it.
- `git-simulate-sequential-merges` — deciding which phases actually conflict
  before merging any of them.
- `work-on-pr` — the per-phase loop, once a phase has a PR.
