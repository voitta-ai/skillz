---
name: gh-pr-merge-delete-branch-closes-dependent-pr
description: |
  Fix the surprising auto-close of stacked / dependent PRs when their
  base branch gets deleted on GitHub. Use when: (1) you ran
  `gh pr merge --delete-branch` (or any branch-deleting merge action) on
  PR A, and PR B which was based on PR A is now CLOSED with no warning —
  not retargeted to the repo's default branch as you might expect,
  (2) a stacked-PR workflow where each PR in the chain has its base set
  to the previous PR's head, and you'd like to land them in sequence
  without losing the dependent PRs' review history, (3) you want to
  reopen a PR closed by the base-branch-delete cascade. Root cause:
  GitHub auto-closes (does not retarget) dependent PRs when their base
  ref vanishes. `gh pr reopen` then fails with
  "GraphQL: Could not open the pull request" because the base ref no
  longer exists. Fix: recreate the deleted ref via
  `gh api repos/OWNER/REPO/git/refs -f ref='refs/heads/<deleted>' -f sha='<some-sha>'`,
  reopen the PR, retarget its base to your real target (usually main),
  optionally delete the recreated ref again. Hit twice in one session
  on a 3-PR stack (#82 → #71 → #84) because the gh-merge of each PR's
  predecessor cascaded the close to the next.
author: Claude Code
version: 1.3.0
date: 2026-08-26
---

# `gh pr merge --delete-branch` closes (not retargets) dependent PRs

## Problem

You have a stacked PR chain on GitHub:

```
main ←— PR A (base=main,        head=feature/A)
        PR B (base=feature/A,   head=feature/B)
        PR C (base=feature/B,   head=feature/C)
```

You squash-merge PR A with `gh pr merge --delete-branch`. Two things
happen at the GitHub API level:

1. A squash commit lands on `main`.
2. The `feature/A` branch ref is **deleted** on the remote.

You'd expect GitHub to auto-retarget PR B's base to the repo's default
branch (`main`). It does not. Instead:

- **PR B is auto-CLOSED** (state goes to `CLOSED`, not `OPEN`).
- The review history, comments, approvals, and check results stay
  attached to PR B, but it's closed.
- `gh pr reopen B` fails with `GraphQL: Could not open the pull
  request. (reopenPullRequest)` because GitHub can't reopen a PR whose
  `baseRefName` points at a ref that no longer exists on the remote.

The cascade can chain: if you then merge PR B (after reopening), the
same thing happens to PR C, etc.

## Symptoms

- After `gh pr merge --delete-branch N`, querying a downstream PR M
  whose base was that branch shows:
  ```
  gh pr view M --json state,baseRefName,closed,closedAt
  → {"baseRefName":"feature/A","closed":true,"closedAt":"...","state":"CLOSED"}
  ```
- `gh pr reopen M` returns:
  ```
  GraphQL: Could not open the pull request. (reopenPullRequest)
  ```
- `gh pr edit M --base main` on the closed PR returns:
  ```
  GraphQL: Cannot change the base branch of a closed pull request. (updatePullRequest)
  ```

## Fix

Recreate the deleted base ref temporarily so the PR can be reopened
and retargeted:

```bash
# 1. Get a sensible SHA to point the resurrected branch at. main's tip
#    is fine — the PR's base ref just needs to *exist* for reopen to
#    succeed.
SHA=$(gh api repos/OWNER/REPO/branches/main --jq '.commit.sha')

# 2. Recreate the deleted branch ref at that SHA.
gh api repos/OWNER/REPO/git/refs \
  -f ref="refs/heads/<deleted-branch>" \
  -f sha="$SHA"

# 3. Reopen the dependent PR + retarget to your real base.
gh pr reopen M --repo OWNER/REPO
gh pr edit   M --repo OWNER/REPO --base main

# 4. Verify the PR is back open and pointed at main.
gh pr view M --repo OWNER/REPO --json state,baseRefName,mergeStateStatus,mergeable
# → state=OPEN, baseRefName=main

# 5. (Optional) clean up the resurrected branch — once PR M's base is
#    no longer pointed at it, it can be deleted again safely.
gh api -X DELETE repos/OWNER/REPO/git/refs/heads/<deleted-branch>
```

## Verification

After step 4:

- `state` is `OPEN`.
- `baseRefName` is `main` (or whichever real base you set).
- `mergeStateStatus` is `CLEAN` / `MERGEABLE` if the commits don't
  conflict against the new base. (If the rebased commits from the
  upstream PR are now duplicated in main via the squash, GitHub
  usually recognizes the diff is empty for those and the merge stays
  clean.)
- The PR's review history, comments, and approvals are unchanged from
  before the close.

## Alternative recovery: rebase and reopen as a new PR

The ref-recreation recovery above preserves the PR number, its review
history, comments and approvals. That is the right choice when any of
those exist.

When the closed PR has **no** review state worth keeping — nobody had
reviewed or commented yet — it is simpler to rebase onto the real base
and open a fresh PR:

```bash
cd <worktree-on-the-dependent-branch>
git fetch origin
git rebase origin/main        # parent's commits are recognised as
                              # already applied and skipped, because the
                              # parent was squash-merged into main
git diff origin/main --stat   # verify only YOUR change remains
git push --force-with-lease
gh pr create --base main --head <branch> --title ... --body ...
```

The rebase prints `warning: skipped previously applied commit <sha>` for
the parent's commits. That is expected and correct — squash-merging the
parent put an equivalent change in `main`, and git recognises it.

**Verify the diff before opening the PR.** If the rebase did *not* skip
the parent's commits, the new PR will re-propose changes already in
`main`.

Trade-off: you lose the original PR number, so any Jira ticket, commit
message or comment referencing it now points at a closed PR. Update those
references, or use the ref-recreation path instead.

## Prevention

Pre-emptively retarget downstream PRs **before** merging the upstream
PR with `--delete-branch`:

```bash
# Before merging PR A:
gh pr edit B --repo OWNER/REPO --base main
gh pr edit C --repo OWNER/REPO --base main  # if C exists too

# Then safe to:
gh pr merge A --repo OWNER/REPO --squash --delete-branch
```

This way the dependent PRs are already pointed at `main` when their
old base disappears, GitHub has nothing to close them over, and the
review state continues seamlessly.

For long chains, retarget the *whole* downstream chain to `main` up
front, then squash-merge the top of the stack normally. Downstream
PRs may need to be rebased onto the new base before they're clean,
which is usually expected on a stacked workflow anyway.

## Why this is non-obvious

- The `gh` CLI gives no warning that the merge will cascade-close
  downstream PRs.
- GitHub's web UI shows a small banner on the closed PR pointing at
  the original base branch, but it doesn't link to a recovery path.
- Many people expect "auto-retarget to default branch" because that's
  the behavior some other forges (GitLab, Bitbucket) implement.
- The error from `gh pr reopen` (`Could not open the pull request`)
  doesn't explain the root cause — you have to know to check whether
  the base ref still exists on the remote.

## Notes

- The exact same cascade applies to manual branch deletion via
  `gh api -X DELETE repos/OWNER/REPO/git/refs/heads/X` or
  `git push origin --delete X` — anything that removes the ref.
- It also applies to PRs from forks if the upstream fork branch is
  deleted, though those rarely sit in a stacked configuration.
- The resurrected ref doesn't have to point at the original SHA; any
  reachable commit works for `gh pr reopen` to succeed. We use
  `main`'s tip because it's stable and won't break anything.
- If you don't care about the dependent PR's review history (no
  approvals, no inline comments worth preserving), it's cleaner to
  let it stay closed and open a fresh PR from the same head branch
  against the correct base. The recovery procedure above is for when
  you *do* want the history.

## Related

- `multi-phase-feature-pr-worktrees` — stacked-PR worktree
  conventions where this trap is most likely to appear.

## Related

- `multi-phase-feature-pr-worktrees` — the stack this failure happens to: each
  phase is a PR based on the previous one's branch, which is what makes a
  `--delete-branch` merge cascade.
- `git-simulate-sequential-merges` — deciding the merge order of a queue before
  merging any of it, which is how you find out a stack exists in the first
  place.
- `git-pr-merge-unblock` — the other half of "the PR will not merge": states
  with no error message, as opposed to this skill's state where the merge
  succeeded and closed something else.
