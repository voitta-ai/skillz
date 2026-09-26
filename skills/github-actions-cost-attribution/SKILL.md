---
name: github-actions-cost-attribution
description: |
  Reconstruct GitHub Actions spend per repo / workflow / event / branch /
  triggering actor / job / step from run and job timestamps, when you cannot
  see org billing, then rank concrete CI savings with numbers. Use when:
  (1) someone reports "Actions usage skyrocketed" or a spending budget was
  raised or hit and you need to say where the minutes went, (2) the billing
  endpoints return 404 "needs the admin:org scope" because you are a member,
  not an admin, (3) `GET /repos/{o}/{r}/actions/runs/{id}/timing` returns
  `billable.total_ms: 0` (deprecated field - it answers 0 when it means "I
  cannot"), (4) jobs fail in ~4s with no steps and the annotation "The job
  was not started because an Actions budget is preventing further use",
  (5) you are evaluating CI savings proposals (drop branch-push triggers,
  skip the re-run on the default branch, gate docker builds, path/diff
  gating, consolidate small jobs) and want measured savings, not guesses.
author: Claude Code
version: 1.0.0
date: 2026-09-25
---

# GitHub Actions cost attribution without billing access

## Problem

Someone with billing access says "Actions spend doubled, look at repos X, Y,
Z". You are an org member: the org billing API 404s, and the per-run
`/timing` endpoint's `billable` block is deprecated and returns zeros. The
numbers still exist - every job carries `started_at`, `completed_at`,
`labels` and `runner_name` - and GitHub's billing rule is simple enough to
recompute: each job rounds UP to a whole minute, priced by runner SKU.
Recomputed this way, per-repo totals matched the admin's billing figures
within ~10% on two repos and ~30% on a third (list price vs net / window
edges) - close enough to rank causes and size fixes.

## Procedure

`scripts/gha_cost.py` implements steps 1-4 (uses the `gh` CLI for auth;
run it from a scratch directory, it writes JSON caches to the cwd).

1. **List runs per UTC day** (`gha_cost.py runs OWNER/REPO START END`).
   Filtered run listings are search-backed and cap at 1000 results; one
   `created=YYYY-MM-DD` query per day keeps each under the cap. Check
   fetched == `total_count` and `total_count < 1000` per day (the script
   flags violations). Do not use `branch=` / `event=` filters for
   completeness: a `branch=main&event=push` listing returned a newest run
   11 days old while the per-day listing held at least 82 such runs from
   the last 3 days.
2. **Fetch jobs with `filter=all`** (`gha_cost.py jobs ...`) - re-run
   attempts are billed too. Budget: one call per run; sample (`0.25`) for
   big months and scale by the actual sampled fraction.
3. **Billed minutes per job = ceil((completed_at - started_at) / 60).**
   Exclude:
   - zero-duration jobs (skipped by `if:` / `needs:`);
   - `runner_name == ""` with duration > 0: never got a runner. Includes
     budget refusals - signature: `conclusion: failure`, `steps: []`,
     ~4 s, annotation (via `GET /repos/{o}/{r}/check-runs/{job_id}/annotations`)
     "The job was not started because an Actions budget is preventing
     further use." Grouping these by hour also dates exactly when the cap
     tripped;
   - self-hosted runners (`runner_group_name` other than "GitHub Actions").
4. **Price by label** (arm64 vs x64 2-core; larger runners have their own
   SKUs) at list rates, then aggregate (`gha_cost.py report ...`): by day,
   workflow x event x (default branch | other), triggering actor, job, and a
   sub-minute-jobs table (billed vs actual). `gha_cost.py steps ... "Job"`
   gives per-step median/p90 from the step timestamps - that is how you find
   the one step that is the job.
5. **Cross-check** your window's total against the billing-admin's number
   before presenting anything else.

## Patterns worth checking (each was worth 10-45% of a repo)

- **Sub-minute jobs.** A paths-filter "changes" job, a lint job, a PR-title
  check each bill a full minute for 5-30 s of work. One repo billed 1,346
  min for 399 min of actual work in three days (~15% of its spend).
  Consolidating tiny jobs that share a trigger recovers most of it.
- **PR-title checks on `synchronize`** (e.g. `action-semantic-pull-request`
  with `types: [opened, edited, synchronize]`): the title cannot change on a
  push. Drop `synchronize` unless the check is required - check with
  `gh pr checks N --required` (per-check `isRequired` is readable without
  admin, unlike classic branch protection, which 404s for members).
- **Diff-gated jobs that diff `github.event.before..github.sha`** fail open
  on a new branch (`before` is all zeros) and over-trigger when a push
  merges or rebases the default branch (upstream edits to the workflow file
  itself count as "changed", which usually means "run everything"). For
  non-default branches diff `origin/<default>...$SHA` (merge-base) and
  intersect with the push range. Measure with the PR's file list
  (`GET /repos/{o}/{r}/pulls/N/files`) x per-job median cost: one repo's
  branch-push sweeps would have dropped from 3,528 to <= 1,381 billed min.
- **"Skip the default-branch re-run when the PR already passed"** only
  saves anything if the merged tree equals the tested PR-head tree. Test it
  first: `git rev-parse <merge_commit>^{tree}` vs `<pr_head_oid>^{tree}`
  (fetch `refs/pull/N/head` if needed). In a repo merging ~40 PRs/day it
  matched 3 of 124 merges - the proposal saves nothing there.
- **Docker build + push on every branch push.** Often the biggest step
  (a Dockerfile that rebuilds the app with no layer cache). Before gating
  it to the default branch + `workflow_dispatch`, check nothing consumes
  branch images (e.g. `grep -r 'data "aws_ecr_image"' terraform/`).
- **Backlog churn.** Join CI'd branches to PRs by `headRefName` over the
  FULL PR list (`gh pr list --state all --limit N`), then group spend by PR
  state and PR age. Agents that keep dozens of old open PRs rebased
  re-run full CI on every one of them: in one repo 70% of branch CI spend
  went to open PRs created 1-3 months earlier, and one burst of such
  pushes coincided with the org budget tripping.
- **Test-suite growth.** Sample the heavy step's duration on the default
  branch, 2 runs/day, to date the step changes; attribute with
  `git diff --stat A B -- tests/`. Then profile with
  `pytest --durations=0`: in one suite 84k of the duration entries were
  < 5 ms (the "thousands of parametrized tests" were cheap) and the time
  sat in a few dozen whole-repo scan tests.

## Verification

- The window total matches the billing-admin's figure within ~10-30%.
- Every "not billed" bucket in the report header is explained (skipped,
  no-runner/budget, self-hosted).
- Each proposed saving is computed from this data (runs x billed minutes
  removed), not from a workflow read.

## Gotchas

- `billable.total_ms: 0` from `/timing` is not "free" - never use it.
- `gh pr list --search "created:>=DATE"` is correct for creation date, but
  branches CI'd this month can belong to PRs opened months earlier - don't
  conclude "branches without PRs" from it.
- `gh api rate_limit` `remaining` did not decrease across ~1,000 calls in
  one session - unexplained; don't budget calls off it.
- Profiling a CI test suite on a laptop: suites that spawn subprocesses
  pushed load average to ~200 on 12 cores - `renice` the workers, and blank
  cloud credentials (CI runs the suite without them).
- List rates are not the invoice: included minutes and discounts make the
  net lower. Past the included quota, minutes saved are saved at list rate.

## References

- Runner pricing and per-job rounding: https://docs.github.com/en/billing/reference/actions-runner-pricing
- List workflow runs (1000-result cap on filtered queries): https://docs.github.com/en/rest/actions/workflow-runs
- List jobs for a workflow run (`filter=all`): https://docs.github.com/en/rest/actions/workflow-jobs
