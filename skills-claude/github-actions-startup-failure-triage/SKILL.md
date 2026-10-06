---
name: github-actions-startup-failure-triage
description: |
  Tell a broken workflow file apart from a GitHub Actions outage, and get a PR
  unstuck without bypassing branch protection. Use when: (1) a workflow run's
  conclusion is `startup_failure` and you are about to debug YAML you did not
  change, (2) `gh pr checks` reports "no checks reported on the '<branch>'
  branch" minutes after opening a PR, (3) `commits/<sha>/check-runs` shows a
  check stuck `queued` while the run itself is already `completed`,
  (4) `gh run rerun <id>` refuses with "This workflow run cannot be retried",
  (5) a PR sits at `mergeStateStatus: BLOCKED` with `mergeable: MERGEABLE` and
  a required check that has never reported, (6) you are tempted to
  force-merge or push an empty commit to make CI notice a PR, (7) a push,
  force-push, or merge produced NO run at all — `actions/runs` has nothing
  for the new sha (a dropped push event, not a failed run), (8) close/reopen
  retriggered nothing because the workflow is `on: [push]`, not
  `on: pull_request`, (9) `gh workflow run` refuses with HTTP 422 "Workflow
  does not have 'workflow_dispatch' trigger". Covers the three-signal test
  that identifies an infra failure in one minute, the githubstatus API
  one-liner that confirms it, the dropped-event variant where no run exists,
  a retrigger matrix keyed by the workflow's trigger type, why an
  apply-on-push repo needs `workflow_dispatch` as a recovery path, and why
  waiting beats an admin bypass.
author: Claude Code
version: 1.1.0
date: 2026-08-26
---

# `startup_failure` usually is not your YAML

## Problem

A pull request opens, and CI never reports. `gh pr checks` says:

```
no checks reported on the 'my-branch' branch
```

The obvious reading is that something in the PR broke the workflow — and if
the diff touched `.github/workflows/`, that is where an hour goes. But a
`startup_failure` conclusion is also what GitHub returns when its own Actions
control plane cannot start the run, and the two look identical from the PR.

The cost of guessing wrong is asymmetric. Debugging a workflow file that was
never broken is an hour; worse, the "it must be my branch" theory leads to
force-merging past a required check that simply never got the chance to run.

An outage also produces a second, quieter shape: the push event is **dropped
entirely** and no run is ever created — covered in its own section below,
because both the diagnosis and the retrigger differ.

## The three-signal test

Ask three questions. All three pointing the same way settles it in a minute.

### 1. Read the run, not the checks

The checks view lags, badly, and it lags in the direction that misleads:

```bash
gh api "repos/OWNER/REPO/commits/$(git rev-parse HEAD)/check-runs" \
  --jq '.check_runs[] | "\(.name): \(.status) \(.conclusion)"'
# → check: queued null            <- stale; polling this waits forever
```

while the authoritative view already knows the run is dead:

```bash
gh api "repos/OWNER/REPO/actions/runs?branch=$(git rev-parse --abbrev-ref HEAD)" \
  --jq '.workflow_runs[] | "\(.name) \(.status)/\(.conclusion) \(.created_at)"'
# → checks  completed/startup_failure  2026-...T15:09:43Z
# → release completed/startup_failure  2026-...T15:09:50Z
```

Poll `actions/runs`, not `check-runs`. A loop waiting on `check-runs` to leave
`queued` will spin past the point where the run has already failed — measured
at four minutes of polling `queued` against a run that was `completed` the
whole time.

### 2. Zero jobs, zero annotations

A genuine YAML error produces something to read. Infra produces nothing:

```bash
gh api "repos/OWNER/REPO/actions/runs/$RUN_ID/jobs" --jq '.jobs[].name'   # → empty
gh api "repos/OWNER/REPO/check-runs/$CHECK_ID/annotations"                # → []
```

A malformed workflow normally surfaces an annotation naming the file and line
("Invalid workflow file"). **No jobs and no annotations at all** is the
signature of a run that never started, not one that started and rejected your
config.

### 3. Did the workflow file change in this PR?

```bash
git diff --name-only origin/HEAD...HEAD -- .github/workflows/
```

Empty output, plus a green run of the same workflow on the base branch, means
the file that "failed to start" is byte-identical to one that works.

Two more corroborating signs, when several workflows exist:

- **All of them fail**, not the one you touched. A YAML error is per-file.
- **They fail within seconds of each other**, and seconds after the push —
  the control plane gives up long before a runner would have been assigned.

## Confirm with the status API

Do not eyeball the status page — the JSON is one call, greppable, and names
the component:

```bash
curl -s https://www.githubstatus.com/api/v2/summary.json | python3 -c "
import json,sys
d = json.load(sys.stdin)
print('STATUS:', d['status']['description'])
for c in d['components']:
    if c['status'] != 'operational':
        print(' component:', c['name'], '->', c['status'])
for i in d['incidents'][:3]:
    print(' incident:', i['name'], '|', i['status'], '|', i['created_at'])
"
```

```
STATUS: Partial System Outage
 component: Actions -> major_outage
 incident: Incident with Actions | investigating | 2026-...T15:11:58Z
```

Compare the incident's `created_at` against your first failed run's
`created_at`. In the case this skill is written from they were two minutes
apart, which is the whole diagnosis.

`/api/v2/status.json` is smaller but only carries the global rollup; Actions
can be in `major_outage` while the rollup still reads healthy-ish, so fetch
`summary.json` and look at the component.

### The status page lags recovery — measure, don't wait on it

The API is good evidence that an outage *started*. It is poor evidence that
one is still going. In the incident this was written from, a retriggered run
went `completed/success` in under a minute while `summary.json` still reported
`Actions -> major_outage` with the incident open and `investigating`.

So the two directions are not symmetric:

- **Red status + your runs dying** → believe it, stop debugging your YAML.
- **Red status alone** → not a reason to keep waiting. Retrigger once and read
  the run. One close/reopen costs nothing and answers the question that the
  status page is, at that moment, still guessing at.

A human saying "it's back" is worth exactly one retrigger, whatever the API says.

## The other shape: the event is dropped and no run exists

During the same incident class, some push events are throttled away entirely
("delayed queues are burning down; some customers will continue to see
increased delays" is the incident language for it). Then there is no
`startup_failure` to find — there is **nothing**:

```bash
git ls-remote origin <branch>          # the sha IS on the remote
gh run list --repo OWNER/REPO --branch <branch> --limit 10 \
  --json headSha,status,conclusion,workflowName
# → no row at all for your sha; older shas have runs
```

Observed in one incident for a force-push to a PR branch AND for merge
commits landing on the default branch — where the missing run is the
dev-deploy/apply. Absence reads exactly like repo or org misconfiguration
("why did CI ignore my push?"), and it is inconsistent across repos: one
repo's merge fired on its own (`ev=push`) while a sibling repo's merge
minutes earlier never fired. Inconsistency across repos is what throttling
looks like — check `summary.json` (section above) before rewiring anything.

### Retrigger matrix — keyed by the workflow's `on:` triggers

Read the workflow's `on:` block first; the right retrigger depends on it.

- **`on: pull_request`** → close/reopen works (next section).
- **`on: [push]`** (with or without `workflow_dispatch`) → close/reopen does
  **nothing**: it emits `pull_request` events the workflow does not listen
  to. Observed directly — after a close/reopen, only an unrelated
  `pull_request`-triggered check fired; the push-triggered CI stayed absent.
  Dispatch it instead:

  ```bash
  gh workflow run <workflow-name-or-file> --repo OWNER/REPO --ref <branch>
  ```

  Steps gated on the ref (e.g. a deploy step under
  `if: github.ref == 'refs/heads/main'`) behave according to the ref you
  dispatch on — dispatching on the default branch still runs the deploy,
  which is usually what you want after a dropped merge event.
- **No `workflow_dispatch` in `on:`** → the dispatch is refused:

  ```
  HTTP 422: Workflow does not have 'workflow_dispatch' trigger
  ```

  There is no clean retrigger left: wait for the queue to drain, or create a
  new push event (an empty commit on a PR branch; on the default branch that
  means landing another merge).

### Hardening: apply-on-push repos need a second door

A repo whose **only** path to deploy/apply is the push trigger has no
recovery at all when that one event is dropped — the 422 above is a dead
end. The fix is one line with no behavior change:

```yaml
on:
  push:
    branches: [main]
  workflow_dispatch:
```

Add it during calm weather, not mid-incident.

## Getting the run to happen again

Once the incident clears, the PR still needs runs. Three options, in order of
preference — note these assume `on: pull_request` workflows; for
push-triggered workflows use the matrix in the previous section.

**1. `gh run rerun` — try it, but expect refusals.**

```bash
gh run rerun "$RUN_ID"
# → run 32984245179 cannot be rerun; This workflow run cannot be retried
```

Refusal is inconsistent: of two runs that failed the same way seconds apart,
one accepted the rerun and the other refused it. Do not read the refusal as
"your run is specially broken" — just move to the next option. (A dropped
event has no run id at all, so this option does not exist there.)

**2. Close and reopen the PR.** This is the retrigger that costs nothing:

```bash
gh pr close  "$PR"
gh pr reopen "$PR"
```

`on: pull_request` with no explicit `types:` includes `reopened`, so every
such workflow re-fires. No commit, no rewritten history, no churn for
reviewers.

Two caveats worth expecting. The re-fired runs do **not** all appear at once —
one workflow showed up immediately and its sibling about three minutes later.
And if the incident is still open, the new runs die exactly like the old ones;
close/reopen is a retrigger, not a repair. Confirm the status API is clean
first.

**3. Push an empty commit** (`git commit --allow-empty`) only if the first two
fail. It works, but it puts a content-free commit in the history of a PR
someone has to review.

## Why not just merge it

A required status check that never reported leaves a PR in a state that reads
like a contradiction:

```bash
gh pr view "$PR" --json mergeable,mergeStateStatus
# → {"mergeable":"MERGEABLE","mergeStateStatus":"BLOCKED"}
```

`MERGEABLE` is about the diff (no conflicts). `BLOCKED` is about the rules.
Both are true and neither is a bug.

The temptation is an admin bypass, and it is worth naming why that is the
wrong move even when you have the button:

- The check has not failed. It has not *run*. Bypassing asserts a result
  nobody measured — and the diff that most wants CI is the one CI never saw.
- Branch protection that gets bypassed during every incident is not branch
  protection. The repo's own docs likely say "including for repo admins";
  the bypass is a decision about the repo's rules, not about your PR.
- The outage is bounded. A merge with unknown CI status is not.

Report the blockage with the evidence — the incident, the run conclusion, the
diff that does not touch `.github/` — and wait. If a genuine emergency needs
the merge anyway, that is the repo owner's call to make explicitly, not a
side effect of an agent unblocking itself.

## Verification

You have correctly diagnosed infra, not your PR, when all of these hold:

1. `actions/runs` shows `completed/startup_failure`, not `queued` — or, in
   the dropped-event shape, shows no run at all for a sha that is verifiably
   on the remote.
2. `runs/$ID/jobs` is empty and the check's `annotations` is `[]` (when a
   run exists).
3. `git diff --name-only origin/HEAD...HEAD -- .github/workflows/` is empty.
4. The same workflow's most recent run on the base branch is `success`.
5. `summary.json` reports the Actions component degraded, with an incident
   whose `created_at` brackets your first failed (or missing) run.

And you have confirmed recovery when a re-triggered run reaches
`completed/success` — check the run's `created_at`, since a stale
`startup_failure` from during the incident stays in the list forever and is
easy to re-read as a fresh failure.

## Notes

- This is not the same as `action_required`, which is the "approve running
  workflows for this contributor" gate and reports a real, actionable status.
  `startup_failure` has no button.
- The same zero-jobs signature does have a non-infra cause: a workflow file
  that is invalid at the merge ref specifically — for instance valid on your
  branch but broken once merged with the base. Signal 3 covers this; if the
  workflows *were* touched, validate the merged result before blaming GitHub.
- Runs that died at startup keep no logs, so `gh run view --log` returns
  nothing useful. Do not spend time there.
- `gh pr checks --watch` inherits the staleness in signal 1: it watches the
  checks view, so it can sit on a run that has already failed. Prefer a loop
  over `actions/runs` when scripting a wait.
- When hunting a run for a merge commit rather than a branch head, filter
  `gh run list --json headSha` by the sha — branch filters follow the
  triggering event and can hide the row you want.
- Do not conclude "this org is dropping push triggers" from one repo's
  silence — that theory was voiced and wrong in the incident this section
  was written from; the platform incident explained every repo's behavior,
  including the inconsistency.
