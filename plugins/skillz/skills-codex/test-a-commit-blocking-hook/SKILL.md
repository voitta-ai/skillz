---
name: test-a-commit-blocking-hook
description: |
  Verify a pre-commit hook that is supposed to REFUSE commits, without
  destroying the hook while testing it. Use when: (1) you just wrote a
  pre-commit hook and need to prove it blocks and allows the right things,
  (2) a hook you wrote reports "nothing changed" during a commit even though
  files are obviously staged, (3) you ran `git reset --hard HEAD~1` to undo a
  test commit and lost real work that was in the same commit, (4) you need to
  recover a commit you just hard-reset away. Covers the staged-vs-committed
  diff trap, safe test sequencing, and reflog recovery.
author: Claude Code
version: 1.0.0
date: 2026-09-22
source: skillz-private version-bump guard, 2026-09
source_file: skills/test-a-commit-blocking-hook/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/test-a-commit-blocking-hook/SKILL.md`). Updates go through the
> repo's worktree + PR workflow.

# Testing a commit-blocking hook

## Problem

A pre-commit hook whose whole job is to **refuse** a commit can only be tested
by attempting a commit. That creates two traps that bite in sequence, and the
second one destroys work.

## Trigger conditions

- You wrote a `pre-commit` hook and want to prove it blocks the bad case and
  allows the good one.
- Your hook runs a script that reports "no files changed" while files are
  plainly staged.
- You ran `git reset --hard HEAD~1` to clean up a test commit and the hook, the
  script, or the CI workflow vanished with it.

## Trap 1: a commit-range diff is empty in pre-commit

The natural way to ask "what changed?" is a commit range:

```sh
git diff --name-only "$BASE...HEAD"
```

In a `pre-commit` hook that returns **nothing**. The change is in the index; it
has not been committed, so it is not in any range ending at `HEAD`. The hook
runs, the script reports no changes, the check passes, and the commit you meant
to block goes through. The hook appears installed and does nothing.

Read the index instead:

```sh
git diff --cached --name-only          # which paths are staged
git show ":path/to/file"               # the staged blob's content
```

Give the script an explicit mode rather than guessing:

```sh
# in .githooks/pre-commit
python3 "$(git rev-parse --show-toplevel)/scripts/check.py" --staged
```

`--staged` compares the index against `HEAD`. The same script keeps its normal
range mode for CI, where the change genuinely is committed.

## Trap 2: cleaning up the test destroys the tooling

Sequence that loses work, and it looks completely reasonable at each step:

1. Write the hook, the script and the CI workflow. They are untracked.
2. Make a throwaway edit to trip the hook.
3. `git add -A` — this stages the throwaway edit **and all the new tooling**.
4. Commit. The hook lets it through (trap 1) or you bypass it to test something
   else.
5. `git reset --hard HEAD~1` to undo the test commit.
6. The tooling is gone. It only ever existed in that commit.

`git add -A` during a test is the actual error. The reset is just where the
cost lands.

## Solution: commit the tooling first, then test with throwaway files only

**Commit the guard before testing it.** A version-bump guard, a secret
scanner, a lint gate: the tooling commit itself usually does not trip its own
rule, so it lands cleanly.

```sh
git add scripts/check.py .githooks/pre-commit .github/workflows/checks.yml
git commit -m "ci: add the guard"      # safe: touches nothing the guard checks
```

Now the tooling is in history. Anything you do next is recoverable by
`git reset` without loss.

**Then test with a file you do not care about**, staged by explicit path:

```sh
printf '\n<!-- probe -->\n' >> path/the/guard/watches
git add path/the/guard/watches          # NEVER `git add -A` while testing
git commit -m "probe: must be refused"  # expect refusal
```

**Test both directions.** A hook that refuses everything passes the first test
and is still broken:

```sh
# make the change the guard actually wants, then:
git add -A && git commit -m "probe: must pass"   # expect success
```

**Clean up without `reset --hard`** where possible:

```sh
git restore --staged path && git checkout -- path   # un-stage and revert
```

If a probe commit did land, `git reset --hard HEAD~1` is fine **only because**
the tooling is already in an earlier commit.

## Alternative: test in a scratch worktree

Zero risk to the real tree, at the cost of a little setup:

```sh
git worktree add ../probe -b probe-hook
cd ../probe
git config core.hooksPath .githooks
# ... trip the hook here ...
cd - && git worktree remove --force ../probe && git branch -D probe-hook
```

Worth it when the guard is expensive to re-create or the repo is shared.

## Recovery: the reflog still has it

If you have already hard-reset away a commit containing real work, it is not
gone. `reset` moves a branch pointer; the commit object survives until gc.

```sh
git reflog -5
# c2305bc HEAD@{1}: commit: probe: bumped, must pass
# 22646c0 HEAD@{0}: reset: moving to HEAD~1
```

Take back **only** what you want, not the whole commit — the probe's other
changes usually should stay dead:

```sh
git checkout c2305bc -- scripts/check.py .githooks/pre-commit
chmod +x scripts/check.py .githooks/pre-commit    # mode is not always restored
```

Then verify you did not drag along the probe's side effects:

```sh
git status --short
grep -n "probe" path/the/guard/watches || echo "probe residue gone"
```

## Verification

The hook is correctly wired when all four hold:

1. Staging a bad change and committing is **refused**, with the reason printed.
2. Staging the corresponding good change and committing **succeeds**.
3. The guard's own tooling commit is not blocked by the guard.
4. `git log` shows no probe commits and the watched files contain no probe text.

## Notes

- `core.hooksPath` is per-clone config, not tracked. A hook in `.githooks/` is
  inert until someone runs the install step. Ship a one-line
  `scripts/install-hooks.sh` and say so in the README, or people will assume
  the guard is active when it is not.
- Hooks are bypassable with `--no-verify` by design. A pre-commit hook is a
  guard against mistakes, not against intent; put the authoritative version of
  the check in CI, where it cannot be skipped.
- Make the failure output say **why** the rule exists, not just that it was
  broken. Whoever trips it at 2am is deciding whether to `--no-verify`, and a
  sentence of reason is what makes them fix it instead.

## References

- `git help reflog` — recovering commits after a reset.
- `git help githooks` — hook contract and `core.hooksPath`.
- Related skill: `prevent-committing-secrets`, which installs a gitleaks
  pre-commit hook and has the same install-step-not-tracked caveat.
