---
name: pr-amend-force-push-lost-to-racing-merge
description: |
  A review-fix amend + force-push that lands after the reviewer's squash-merge
  succeeds silently and never reaches the default branch: the merge snapshots
  the head GitHub had when the merge ran, the later force-push still updates
  the branch ref without any warning, and the default branch keeps the
  pre-review version. Use when: (1) you force-pushed to a PR branch while the
  PR was under active review or had auto-merge armed, (2) a merged PR's
  requested change is mysteriously absent from the default branch though your
  branch has it, (3) a stacked follow-up branch starts failing validation
  after a rebase on something the amendment fixed (e.g. terraform's `Error:
  Reference to undeclared resource`), (4) `git show origin/<default>:<file>`
  shows the pre-amendment shape of a file you know you fixed. Covers the
  post-push detection check, the tree-diff test that works despite
  squash-merge ancestry breakage, and the carry-the-fix-forward recovery.
author: Claude Code
version: 1.0.0
date: 2026-08-27
source: https://github.com/voitta-ai/skillz
source_file: skills/pr-amend-force-push-lost-to-racing-merge/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/pr-amend-force-push-lost-to-racing-merge/SKILL.md`). Updates go
> through the repo's worktree + PR workflow - open an issue, branch, PR.

# Amend + force-push racing an in-flight merge loses silently

## Problem

Review feedback arrives; you amend the commit and force-push. The reviewer
squash-merges in the same window. Two facts make the outcome invisible:

- The merge snapshots whatever head GitHub had **when the merge API call
  ran**, not whatever the branch points at later.
- A force-push to the branch of an already-merged PR **succeeds** — the
  branch ref updates normally (the branch still exists until someone deletes
  it), the PR stays `MERGED`, and nothing anywhere warns that the two events
  crossed.

Net result: your branch and your local checkout contain the fix; the default
branch carries the pre-review version; the PR page reads as if the review
round concluded normally. Nobody finds out until something downstream trips
over the missing change.

## How it actually surfaced

The miss was discovered late, through a stacked follow-up branch: after
retargeting it to the default branch and rebasing, `terraform validate`
failed with

```
Error: Reference to undeclared resource
```

because the follow-up assumed a resource the amendment had introduced — and
the default branch still had the pre-amendment shape. Confirmed with:

```bash
git show origin/main:<file>        # pre-review content, amendment absent
```

Any validator, compiler, or test in a dependent branch can be the tripwire;
until one fires, the loss is invisible.

## Detection — do this after any force-push to a PR under review

Cheap and immediate:

```bash
gh pr view <N> --repo OWNER/REPO --json state,mergeCommit,headRefOid
```

If `state` is `MERGED` and the merge happened around your push, check whether
your amendment made it in. Squash merges break ancestry, so
`git merge-base --is-ancestor` proves nothing — **diff the trees**:

```bash
git fetch origin
git diff <mergeCommit-sha> <your-branch-head> -- <files you amended>
```

Non-empty output on the files you amended means the amendment missed the
merge window. (An empty diff means the merge caught your push — you are
fine.)

## Recovery

Do not rewrite the default branch, and a revert is overkill — the merged
content is not wrong, it is merely incomplete:

1. **Carry the lost fix forward as its own commit** in the stacked follow-up
   PR (or a small new PR if none exists), with a commit body that says it
   carries over the review fix from the merged PR, which missed its merge
   window. Keeping it a separate commit preserves the review trail.
2. **Comment on the merged PR** stating that the requested change raced the
   merge and naming the PR that now carries it — otherwise the reviewer
   reasonably believes their feedback landed.

## Prevention

- Before amending a PR that is approved or under live review, check
  `gh pr view --json state` — and check it **again right after pushing**.
  The whole detection is two cheap commands.
- Saying "pushing a fix now, hold the merge" in the PR thread before the
  amend removes the race entirely.
- Armed auto-merge (`gh pr merge --auto`) widens the window: the merge fires
  the instant checks go green, which can be mid-amend. If you are about to
  force-push, disarm first (`gh pr merge --disable-auto`).

## Notes

- This is the sibling of the stacked-PR deletion race covered by
  `gh-pr-merge-delete-branch-closes-dependent-pr`: that one loses the
  dependent PR when the base branch is deleted; this one loses the amendment
  when the merge wins the race. Both come from treating a PR branch as
  exclusively yours while a reviewer holds the merge button.
- The same race exists with regular (non-force) pushes of new commits; the
  squash simply omits them. Force-push is called out because an amend is the
  usual review-fix shape and rewritten history makes the loss harder to see
  in `git log`.
