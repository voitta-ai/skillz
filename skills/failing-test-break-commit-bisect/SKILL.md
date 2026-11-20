---
name: failing-test-break-commit-bisect
description: |
  Trace every test that fails today to the commit that broke it: when the test
  was written, whether it passed then, and the first commit where it fails.
  Use when: (1) a test suite that nothing ran has old failures and you must
  tell an out-of-date test from a regression, (2) you need proof that one fix
  broke the check that held another, (3) the history has merges, so a walk
  along one line of it would blame the wrong commit, (4) the tests run in a
  container and a bind mount of a tree that was just switched shows stale
  files. Covers `git bisect --no-checkout`, feeding each commit to the
  container with `git archive`, one whole-file run cached per commit, tests
  that first pass one commit after they were added, and why a commit where the
  test cannot run is skipped and never counted.
author: Claude Code
version: 1.0.0
date: 2026-11-19
source: https://github.com/voitta-ai/skillz
source_file: skills/failing-test-break-commit-bisect/SKILL.md
---

# Failing test to breaking commit, by bisect

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/failing-test-break-commit-bisect/SKILL.md`). Updates go through the
> repo's worktree + PR workflow.

## Problem

A repository has tests that nobody runs, and some fail. "N tests fail" says
nothing about what happened. For each one you need three facts: when it was
written, whether it passed then, and which commit made it fail. With those,
a failing test is either out of date (the rule it holds was changed on
purpose) or a regression, and you can show the change that did it.

Doing this by hand for a dozen tests over thousands of commits is not
practical, and three things make the obvious script give wrong answers.

## Context / Trigger Conditions

- A suite fails on the main branch and no CI ever ran it.
- You want a before/after that anyone can rerun: the test passes at commit A
  and fails at its child B.
- `git rev-list --first-parent --count` is far below `git rev-list --count`:
  the history has merges.
- Tests run through `docker run -v "$PWD":/w ...` and a run right after a
  `git checkout` reports no tests, or results that belong to another commit.

## Solution

1. **Use `git bisect`, not your own binary search.** A search along the
   first-parent chain treats a merge as one step and blames the merge. Let git
   pick the commits:

   ```bash
   git bisect start --no-checkout <bad> <good>
   sha=$(git rev-parse BISECT_HEAD)     # the commit to test; nothing is checked out
   git bisect good | bad | skip         # then read BISECT_HEAD again
   ```

   Stop when the output contains `<sha> is the first bad commit`, or when it
   says only skipped commits are left. Run this in a spare worktree: the bisect
   state belongs to the worktree, and `--no-checkout` leaves its files alone.

2. **Give the container the commit through `git archive`, not a bind mount.**

   ```bash
   git archive "$sha" | docker run --rm -i -v test-cache:/cache <image> \
     sh -c 'mkdir -p /w && tar -x -C /w && cd /w && <test command> "$1"' sh "$test_file"
   ```

   On macOS with a VM-backed Docker (Rancher Desktop was where this was seen),
   a bind mount of a tree that was just switched can show stale files. The
   first run after each jump reported zero tests; a later run of the same
   commit was fine. Piping the tree in has no such window, needs no checkout,
   and cannot touch the working tree. Keep the dependency cache in a named
   volume so each run does not download again.

3. **Run the whole test file once per commit and cache every test's status.**
   Parse the runner's per-test lines into `{name: ok | FAILED}` and cache by
   `(commit, file)`. Several failing tests in one file then share runs, and
   later searches reuse the early steps.

4. **Three statuses, not two.** `ok`, `FAILED`, and `absent`: the file is not
   in that commit, does not load, or does not contain the test. Mark `absent`
   as `git bisect skip`. Never count it as a pass or a failure. In a history
   with merges, bisect visits side branches that predate the test file, so
   `absent` is common and is not an error.

5. **Find the good end properly.** The commit that added the test is
   `git log --reverse --format=%H -S"<test name>" <tip> -- <file> | head -1`.
   An agent that writes test first and code second commits them a minute
   apart, so the test can fail at its own commit and pass at the next. Look
   for the first `ok` among that commit and its next few descendants
   (`git rev-list --ancestry-path --reverse <intro>..<tip>`), and use that as
   `good`. Reporting "failed when written" from the first commit alone is
   wrong.

6. **Check the answer.** For the commit bisect names, run the file at each
   parent and at the commit itself: parent `ok`, commit `FAILED`. Record
   `git show --stat` of that commit. Its diff, and any dated comment in it,
   says what the change was for.

7. **Then classify.** Compare the failing assertion with the newest dated
   rule in the code it tests. If the rule was changed on purpose, the test is
   out of date. If the newest rule still wants the old behaviour, it is a
   regression. If two dated rules disagree, it is a question for the owner.

## Verification

- No run reports zero tests for a commit where the file exists.
- Every row has parent `ok` and commit `FAILED`.
- Someone who was not there can rerun two commands, one at the parent and one
  at the commit, and get the two results.

## Example

One run of this: 11 failing tests in 5 files, 8,816 commits with merges (1,919
on the first-parent chain). 144 container runs, a few seconds each. All 11
were isolated to 9 commits. All 11 had passed when written; two of them only
at the commit after the one that added them. A first version that used a bind
mount and `git checkout` reported zero tests on 67 of 102 runs and isolated
one test.

## Notes

- Turn type checking off for the search if the runner type-checks by default
  (`deno test --no-check`). An old commit that fails to type-check would be
  `absent`, and the question is whether the assertion held.
- Bisect assumes one change from good to bad. A test that went back and forth
  still yields a real pair: the parent passes and the commit fails.
- A test file can already have other failures at the "good" commit. Read the
  line of the named test, not the summary.
- Match a test by exact name or by a prefix; names get edited.

## References

- [git-bisect documentation](https://git-scm.com/docs/git-bisect), `--no-checkout` and `skip`.
- [git-archive documentation](https://git-scm.com/docs/git-archive).
