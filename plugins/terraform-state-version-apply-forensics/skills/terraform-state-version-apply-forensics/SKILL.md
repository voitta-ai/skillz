---
name: terraform-state-version-apply-forensics
description: |
  Prove (or disprove) that a terraform change was actually applied to an environment,
  without trusting a PR description or a human's memory. Use when: (1) someone asks
  "did we test/apply this on dev?" and the only evidence is prose in a PR body,
  (2) you need to know WHICH variant of a change was applied and in what order
  (e.g. a stacked PR pair applied separately vs. all at once), (3) live AWS shows
  resources that a teardown was supposed to delete and you must tell "apply never ran"
  apart from "resource was never terraform-managed", (4) you suspect a manual env apply
  was later reverted or overwritten by a CI apply. Method: census the versioned S3
  tfstate objects over time (serial + resource-type counts per version) and cross-check
  with CloudTrail delete/create events. Read-only; safe to run against prod.
author: Claude Code
version: 1.2.0
date: 2026-09-17
---

# Terraform state-version apply forensics

## Problem

A PR body says "applied end-to-end on dev". Maybe it was. Maybe it was applied and then
reverted, or applied in a different order than claimed, or a CI apply on the default
branch put everything back an hour later. `terraform plan` only tells you where the
environment is *now* — not what happened, when, or in what order.

Meanwhile the live cloud API shows resources the change was supposed to delete, and you
can't tell whether the apply silently failed or those resources were never in state.

## Context / Trigger conditions

- "Did we test this on dev?" with no plan/apply log attached.
- Stacked PRs (A, then B on top of A) where the claim is "each applies cleanly on its own"
  and you need to confirm A was applied *alone* at some point.
- Teardown/destroy work where live resources survive: is that a failed destroy or an
  untracked orphan?
- Suspicion of the manual-apply-then-CI-reapply race.
- Catching a lagging environment up: what does prod not have that dev does, and will the
  plan rename those resources or destroy-and-recreate them? (step 6)
- You are about to **assert**, in a commit body, a PR or a review, that a resource is or
  is not in state. A state read without a refresh is a claim about the last apply, not a
  claim about AWS. Date the snapshot (step 0) before the assertion leaves your terminal.
  This is the trigger that fires *earliest*: the other entries assume you already suspect
  something, and this one catches the case where you do not.

Prerequisite: the S3 backend bucket has **versioning enabled** (standard for TF backends).
Without versioning you get only the current object and this method degrades to CloudTrail
alone.

## Solution

### 0. Date your snapshot before trusting it

```bash
aws s3api head-object --bucket <backend-bucket> --key <state-key> \
  --query LastModified --output text
```

One call. If `LastModified` predates any event you are reasoning about, your read
**structurally cannot see that event** and you have no basis for an absence claim -
escalate to the census below.

Observed: a merged commit body asserted "no us-east-1 counterpart exists in state or in
AWS" about a CloudWatch alarm. The AWS half was right. The state half was wrong -
`module.us_east_1.<svc>_iterator_age` was in the state file at serial 60. The alarm was
missing from AWS because someone deleted it by hand from the console, and the state
object's `LastModified` predated that deletion by a day. Nobody ran a bad census; nobody
ran one at all. The author read current state, saw what they expected, and shipped the
claim. One `head-object` would have caught it.

### 1. Locate the state object

Backend config is in the `terraform { backend "s3" {...} }` block plus the per-env
`-backend-config` file (bucket in the block, `key` usually in `env/<env>-backend.tfvars`).

### 2. List state versions over the window of interest

```bash
aws s3api list-object-versions \
  --bucket "$BUCKET" --prefix "$KEY" --profile "$PROFILE" --no-cli-pager \
  --query 'Versions[?LastModified>=`YYYY-MM-DD`].{v:VersionId,t:LastModified}' \
  --output text | sort -k2
```

Each apply writes at least one new version. Bursts of 2-3 versions seconds apart are one
apply (terraform writes state more than once per run) — read the burst, not each line.

### 3. Census each version by resource type

This is the step that makes it evidence rather than a guess. Download each version and
count the resource types you care about:

```bash
aws s3api get-object --bucket "$BUCKET" --key "$KEY" \
  --version-id "$VID" --profile "$PROFILE" --no-cli-pager /tmp/s.json >/dev/null

python3 -c "
import json
s = json.load(open('/tmp/s.json'))
res = s.get('resources', [])
hits = [r['type'] for r in res if any(k in r['type'] for k in ['ecs','autoscaling_group','appmesh','launch_template'])]
print('serial=%-5s total=%-4d matched=%-3d %s' % (s.get('serial'), len(res), len(hits), sorted(set(hits))))
"
```

Swap the keyword list for whatever the change adds or removes. Build a table:

| time | serial | total resources | matched types |
|---|---|---|---|

The **shape of the matched set** identifies *which* variant was applied. Example: a state
holding `ecs_cluster` + `autoscaling_group` + `appmesh_*` but **no** `ecs_service` and no
`ecs_task_definition` is unambiguously "PR A applied alone" — no other config produces
that combination. That is how you confirm a stacked pair was exercised separately.

### 4. Cross-check with CloudTrail

State says what terraform *recorded*. CloudTrail says what AWS *did*, and by whom:

```bash
aws cloudtrail lookup-events --region "$REGION" --no-cli-pager \
  --lookup-attributes AttributeKey=EventName,AttributeValue=DeleteAutoScalingGroup \
  --start-time YYYY-MM-DD \
  --query 'Events[].{t:EventTime,u:Username,r:Resources[0].ResourceName}' --output text
```

Repeat per destructive API (`DeleteAutoScalingGroup`, `DeleteLaunchTemplate`,
`DeleteCapacityProvider`, `DeleteService`, …). Timestamps should line up with the state
bursts from step 2.

### 5. Discriminate orphans from failed destroys

If a live resource looks like it should have been destroyed, check the **exact name**
against the names in the CloudTrail delete events and in the module's naming scheme.

Real signal from this pattern: a live ASG named `<svc>-<region>-dev-asg` survived, while
CloudTrail showed deletes of `<svc>-<region>-dev-default-asg` and `-dev-canary-asg`. The
survivor used an **older naming scheme** — never in current state, so terraform never
touched it. Corroborate with `CreatedTime` (predates the module's current shape) and with
the resource referencing an already-deleted dependency (e.g. an ASG pointing at a launch
template ID that no longer exists).

Also useful: provider `default_tags` (`application` / `environment` / `terraform-repo`)
usually appear on TF-managed resources. Absent tags are a hint — but not proof, since some
resource types (notably `aws_autoscaling_group`) don't receive provider default tags.

**The mirror direction: in state, absent from the API.** The above handles a live resource
that should be gone. The inverse — terraform believes it exists, the API says it does not —
is almost always a manual console deletion:

```bash
aws cloudtrail lookup-events --region <region> \
  --lookup-attributes AttributeKey=EventName,AttributeValue=Delete<Thing> \
  --start-time <iso>
```

Actor, timestamp, source IP and user agent in one call. **The user agent is the tell**: a
browser user agent means a console click, while a terraform or SDK delete carries an
`aws-sdk-go` agent instead.

Filter on the exact resource name, not a project substring. A first pass grepping a repo
name matched 4,428 rows, because DynamoDB `AutoScaling-ManageAlarms` churn dominates
`DeleteAlarms` in any account with provisioned-capacity tables.

### 6. Diff two environments against each other

Same census, different axis: instead of one environment over time, compare two
environments *now*. This answers "how far behind is prod?" without running
`terraform init` against either backend -- so there is no local `.terraform`
reconfigure to undo afterwards, and no chance of leaving a checkout pointed at the
wrong environment.

```bash
for e in dev prod; do
  aws s3 cp "s3://$BUCKET/$(key_for "$e")" - --profile "$PROFILE" --no-cli-pager 2>/dev/null \
  | jq -r --arg e "$e" '
      "=== \($e): serial=\(.serial) tfver=\(.terraform_version) resources=\(.resources|length) ===",
      (.resources[] | ((.module // "root")+" "+.mode+"."+.type+"."+.name))' > "states-$e.txt"
done
diff <(tail -n +2 states-dev.txt | sort) <(tail -n +2 states-prod.txt | sort)
```

A large `serial` gap plus a **strict-subset** resource list is the signature of an
environment that has not applied in a while: everything the lagging one has, the leading
one has too, plus whole stacks it is missing entirely.

**Then read the `for_each` index keys.** This is the part a resource-address diff misses:

```bash
jq -r '.resources[]
  | select((.instances|length)>1 or (.instances[0].index_key? != null))
  | .type+"."+.name+": "+([.instances[].index_key|tostring]|sort|join(", "))' state.json
```

Two things fall out that neither an address diff nor a resource-type census can see:

1. **Membership drift.** Same resource, same instance count, different keys -- a
   `for_each` over a caller/tenant/account list where the lagging environment still holds
   a member that was removed from the config and lacks one that was added. A count census
   reports "5 vs 5, no change"; the plan is a 10-resource create plus a 10-resource
   destroy.

2. **A pre-refactor shape.** An address with **no** index key, where the current config
   uses `for_each`, means that environment predates the refactor to a map. Terraform has
   no rename to offer: absent a `moved` block it plans a **destroy + create**, not an
   in-place change. Seeing this before the apply is the difference between an expected
   churn line and a surprise.

Neither shows up in the plan's summary counts either -- `N to add, M to destroy` does not
tell you the destroys are the same logical objects returning under new keys.

## Verification

You have an answer when you can state: at time T the state held N resources including
{types}, at T+1 it held M including {types}, and CloudTrail shows the corresponding API
calls by user U at the same timestamps. If state and CloudTrail disagree, trust CloudTrail
for "what AWS did" and treat the gap as drift or an out-of-band change.

## Notes

- **A description of the thing is not the thing.** A state file is a record of the last
  apply; a name prefix is a convention someone may have departed from; a cached manifest
  is a snapshot of whenever it was written. None of them is the API. Every failure this
  skill covers is the same substitution made somewhere different, so when an answer
  matters, query the resource rather than the record of it - and when you must use the
  record, date it first.
- The downloaded state files contain **secret values in plaintext** --
  `aws_secretsmanager_secret_version.secret_string`, DB passwords, client secrets. Delete
  them when the census is done (`shred -u`, or `rm` at minimum), and do not leave them in
  a shared or synced scratch directory.
- `moved` / `removed` blocks defeat `-target` scoping -- they are full-or-nothing. So a
  shape migration found by step 6 cannot be applied surgically alongside unrelated drift.

- Entirely read-only. Safe against prod.
- Cheap: a state file is typically well under 1 MB; a dozen versions is a few seconds.
- If the answer is "it was applied, then main's CI re-applied and put it back", the state
  table shows it directly as a resource count that goes down and then up again.
- Re-running the actual applies afterwards is still the stronger proof — this method tells
  you whether you *need* to.
- `Resources[0].ResourceName` in CloudTrail is null for some APIs (e.g.
  `DeleteCapacityProvider`); fall back to timestamp + username correlation there.
