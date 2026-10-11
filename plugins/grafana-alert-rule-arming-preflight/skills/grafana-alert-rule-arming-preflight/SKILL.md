---
name: grafana-alert-rule-arming-preflight
description: |
  Dry-run a Grafana unified-alerting rule's full query -> reduce -> threshold pipeline through
  the alerting evaluator BEFORE arming it, so a rule that fires on its first evaluation is caught
  in review instead of in Slack or PagerDuty. Use when: (1) you are about to create, port, re-home
  or un-gate Grafana alert rules (terraform grafana_rule_group, provisioning API, UI), especially
  rules ported from CloudWatch alarms; (2) a rule fires continuously although the metric is quiet,
  its state history reads `B=NaN, C=NaN`, the rules API shows value `NaN`, or the notification
  prints `Value: [no value]`; (3) a sparse counter (published only when non-zero) sits behind a
  `reduce last`/`max`/`mean`; (4) someone asks whether reduce mode dropNN or replaceNN fixes an
  empty series. Covers POST /api/v1/eval and /api/ds/query dry runs, the measured reducer table
  (strict and dropNN stay NaN on an empty labelled frame, replaceNN and sum give 0), the
  no_data_state trap (KeepLast fires new rules), explicit rule uids, and post-apply verification.
  Also: (5) CloudWatch math naming another query's `id` fails in /api/v1/eval ("ValidationError:
  Error in expression ... ID") though /api/ds/query accepts it, (6) Metrics Insights queries 500
  (plugin.downstreamError) on the AMG CloudWatch data source, (7) a SEARCH matching nothing may be
  a field-less frame (NoData) or, inside a code-mode math expression, a 0-point frame (NaN), so
  probe it, (8) you need NaN semantics of Grafana math (NaN > 0 = NaN).
  (9) a rule-group write fails with `PutAlertRuleGroup (status 500): {}` on Amazon Managed
  Grafana -- a client uid on a NEW rule, or a `__dashboardUid__` annotation without
  `__panelId__`; section 7 has the measured 400/500/200 matrix and how to read the real error.
  (10) a create_before_destroy group move fails with `403 putAlertRuleGroupForbidden {}` after
  about 2 minutes of provider retries -- the workspace alert-rule quota (AMG: 100, not adjustable)
  cannot hold both copies; check GET /api/org/quotas and see section 8 fact 4.
author: Claude Code
version: 1.5.0
date: 2026-10-01
---

# Grafana alert rule arming preflight

## Problem

A Grafana rule can be correct in review, clean in `terraform plan`, and still fire the moment it
is created. The usual cause is the CloudWatch data source (and others): on a quiet window it
returns a frame that has **labels and zero points**. That is not NoData, so `no_data_state` never
applies. `reduce last` (also `max`, `min`, `mean`) on an empty series returns NaN. The threshold
passes NaN through, and Grafana counts any condition value other than 0 as Alerting, NaN
included. Result: the rule fires on arming and re-notifies every repeat interval, forever.

Nothing in a diff shows this. The only reliable check is to evaluate the rule's own pipeline
against live data before it exists.

## Context / Trigger Conditions

- About to arm, port, move, or recreate alert rules. Moving a rule between groups or folders
  recreates it, which resets state.
- Rules ported from CloudWatch alarms that used `treat_missing_data = ignore/notBreaching`.
- Sparse counters: metrics published only when non-zero (error and timeout counts, 3xx counts).
- Symptoms of a rule already doing this: state history `Normal -> Alerting` with `B=NaN, C=NaN`,
  or instance value `NaN`.

## Solution

### 1. Dry-run each rule through the alerting evaluator

`POST /api/v1/eval` is ngalert's rule-evaluation endpoint, the one the rule editor's preview uses.
Send the rule's own `data` array exactly as provisioned. Use the same `relativeTimeRange`, and the
same `model` JSON including any reduce `settings`:

```python
body = {"condition": "C", "data": [
  {"refId": "A", "queryType": "", "relativeTimeRange": {"from": 600, "to": 0},
   "datasourceUid": "<ds-uid>", "model": {...the rule's A model...}},
  {"refId": "B", "queryType": "", "relativeTimeRange": {"from": 600, "to": 0},
   "datasourceUid": "__expr__", "model": {"refId": "B", "type": "reduce", "expression": "A",
     "reducer": "last", "settings": {"mode": "replaceNN", "replaceWithValue": 0},
     "datasource": {"type": "__expr__", "uid": "__expr__"}}},
  {"refId": "C", "queryType": "", "relativeTimeRange": {"from": 600, "to": 0},
   "datasourceUid": "__expr__", "model": {"refId": "C", "type": "threshold", "expression": "B",
     "conditions": [{"evaluator": {"params": [2], "type": "gt"}}],
     "datasource": {"type": "__expr__", "uid": "__expr__"}}}]}
# POST <grafana>/api/v1/eval  (Authorization: Bearer $TOKEN)
# read results.A/B/C frames: data.values[-1]
```

`POST /api/ds/query` with `{"from": "now-10m", "to": "now", "queries": [A, B, C]}` gives the same
answer, since it uses the same server-side expression engine. It is handy for trying reducer
variants side by side.

Read **C** for every series:

- `0`: quiet. OK to arm.
- `1`: it will go Pending/Firing now. That may be a real breach, so decide before arming.
- `null` in JSON (NaN): **it will fire.** Fix the pipeline, not the threshold.

Also read **A**'s point count. `labels present, 0 points` is the empty-labelled-frame shape.

### 2. Pick a reducer that survives the empty series

Measured on one empty labelled CloudWatch frame (A: 1 frame, 0 points), 2026-09-29:

| B reducer | B | C (threshold `> 2`) |
|---|---|---|
| `last`, strict (default) | NaN | NaN (fires) |
| `last`, `mode: dropNN` | NaN | NaN (fires) |
| `max`, strict | NaN | NaN (fires) |
| `last`, `mode: replaceNN`, `replaceWithValue: 0` | 0 | 0 |
| `sum`, strict | 0 | 0 |
| `last` strict + C as math `!is_nan($B) && $B > 2` | NaN | 0 |

So **dropNN does not fix an empty series. replaceNN does.** For count-like metrics, where absence
means zero, use `replaceNN` with 0, or `sum` if a window total is the intended semantics. For
gauges where absence is suspicious, do not paper over it. Alert on absence explicitly instead.

### 3. Set `no_data_state = "OK"`, not `KeepLast`

`KeepLast` has no last state on a rule's first evaluation and resolves to Alerting. A new rule
whose query returns true NoData fires on creation. A CloudWatch alarm in `INSUFFICIENT_DATA`
notified only `insufficient_data_actions`, which ports rarely set, so `OK` is the parity choice.

### 4. Rule uids (terraform): pin EXISTING rules only

`grafana_rule_group` matches `rule` blocks to state by position. Deleting or reordering a rule
slides its neighbours onto each other's uids, which scrambles silences and state history. So pin
uids on rules that already exist, using the uid Grafana assigned.

**Do not put an explicit uid on a rule that does not exist yet**, at least on Grafana 10.4.x
(Amazon Managed Grafana). Observed 2026-09-29: one apply created 7 rule groups whose new rules
carried derived uids (`substr(sha1(...), 0, 14)`). Every create failed with `PutAlertRuleGroup 500`,
after the same apply had destroyed the groups those rules replaced. Root cause, traced to Grafana
10.4 `pkg/services/ngalert/store/deltas.go`: a submitted rule that carries a uid is treated as an
update of an existing rule, and an unknown uid returns `ErrAlertRuleNotFound`, which the
provisioning API surfaces as `500 {}`. Create without `uid`, then pin the assigned uid in a
follow-up before reordering. Newer Grafana versions may accept client-chosen uids on create. Check
yours before relying on it. When
moving rules between groups or folders, never destroy the old group in the same apply that creates
the new one unless the create has been proven on this Grafana version.

**Inserting a new rule in the MIDDLE of an existing group hands the next rule's uid to the new
rule.** Position matching is not only a delete/reorder hazard - an in-place group update does it
too, and this one changes what an existing uid means rather than merely moving it. Measured
2026-10-01 to 10-06 on Grafana 10.4.7, provider 4.45.2, inserting at index 2 of a 3-rule group:

- the old index-2 rule's uid now carries the NEW rule's title, query and receiver - in the measured
  case a non-paging rule became paging;
- the displaced rule was re-created at the end with a fresh uid, so its **state history reset**;
- the original uid's annotation history now mixes two different rules.

The tell in `terraform plan` is an **in-place** group update where an existing rule shows
`~ title = "A" -> "B"` alongside a changed query and receiver, and a new rule block is appended at
the end. That reads like a rename plus an addition. It is neither.

Mitigation: **append new rules at the END of the group**, or pin the existing uids before
inserting. And when reading alert history across such a change, filter by **title**, not by uid -
the uid is no longer a stable identity for the rule it used to name.

### 5. Prove the rendered instance count

A rule group gated by `for_each`/`count` on a variable, such as a contact-point interlock, renders
zero instances when the variable is empty. In a diff that looks identical to "armed". Show the
render: `terraform plan -out=p`, then `terraform show -json p | jq` over `.resource_changes[]`.
List each group's rules with `uid`, `no_data_state`, `notification_settings[0].contact_point`,
and the B model's `settings`.

If prod state is off-limits (another session is mid-apply, an incident), render the locals
offline instead. Copy `terraform/`, substitute the datasource uids with their live values,
delete the `backend` block, `terraform init`, then pipe
`jsonencode(local.<rules>)` into `terraform console -var-file=env/prod.tfvars
-var '<contact_point_var>=<name>'`. You get no state, no lock, and the same `data` arrays for
`/api/v1/eval`.

A green PR build is not this proof. In your alerting repo, a branch run plans DEV only; every
`(prod)` step reads `skipped` in the job's step list, so "Build: pass" says nothing about prod.
Run the prod plan yourself, read-only (`-lock=false` takes no state lock), twice: once as merged,
and once with the interlock variable set. Read both with `terraform show -json`. Example from
2026-09-29 (a measured prod run): as merged, 2 to add and 1 to change, the SNS topic, its subscription
and a dashboard. With `<service>_alert_contact_point` set, 7 to add: those, the folder and four groups
of 2 and 14 rules per region, every rule `uid` unknown.

### 6. Four more traps, measured on AMG (Grafana 10.4) 2026-09-29

1. **The alerting evaluator does not batch separate CloudWatch queries.** A CloudWatch
   metric-math query that names another query's `id` (`IF(FILL(incoming, 0) > 0, ...)` over
   separate `incoming`/`age` queries) fails in `POST /api/v1/eval` with `ValidationError: Error in
   expression 'lag': ID ...`. The same query set works in `/api/ds/query`, so a dashboard-shaped
   check proves nothing. Make each CloudWatch query self-contained and pull its inputs with
   exact-schema SEARCH:
   `IF(FILL(SUM(SEARCH('{AWS/Kinesis,StreamName} MetricName="IncomingRecords"
   StreamName="s"', 'Sum', 60)), 0) > 0, ...)`. Or combine separate self-contained queries in
   Grafana math.
2. **Metrics Insights 500s.** A `metricQueryType: 1` / `sqlExpression` query returns
   `plugin.downstreamError` (HTTP 500) from the AMG CloudWatch data source. Use `SUM(SEARCH(...))`
   instead. That is legal in a Grafana rule, because Grafana reads through GetMetricData; only
   CloudWatch *alarms* reject SEARCH.
3. **Two different absence shapes.** A pinned-dimension read that published nothing is a
   labelled frame with 0 points, and replaceNN turns it into 0 (section 2). A SEARCH that matched
   nothing is a frame with **no fields at all**. Every downstream expression inherits it, so the
   rule evaluates to **NoData** and `no_data_state` decides. That is the right lever when absence
   *is* the breach, such as a consumer whose metrics namespace vanished: set `Alerting` on that
   rule only. When probing, distinguish `schema.fields == []` (NoData) from a null value (NaN).
   Printing both as "NaN" hides which knob applies.

   **Not every empty SEARCH is NoData.** Measured 2026-09-30 on AMG 10.4.7: the code-mode
   expression `100 * MAX(SEARCH(a)) / MAX(SEARCH(b))` over a namespace that does not exist came
   back as a frame WITH a value field and 0 points. It carried labels from the model's
   `dimensions` when that field was present, and `{}` without it. That is the NaN shape, not
   NoData. So replaceNN turned it into 0 and `no_data_state` never applied. An "absence =
   Alerting" rule built on an expression like this stays silent. Probe your exact expression
   against a name that matches nothing, and read `schema.fields` before you choose the knob.

   **An idle window is not an absence test.** When the SEARCH matches metrics that are active
   today, a replay into a window where they were silent still returns the full series.
   `FILL(SUM(SEARCH(...)), 0)` came back as 118 zero points (measured 2026-09-30 by replaying
   a stalled-consumer rule into the 09-16 and 09-18 idle stretches), not NoData.
   That is the answer you want for "idle stream: stay quiet", but it proves nothing about
   "metrics vanished". Test that case separately, with a name that matches nothing. CloudWatch
   keeps 1-minute data for only 15 days, so replay a 60 s-period rule before its window ages out.
4. **NaN is not falsy in Grafana math.** Measured with constant expressions (`0/0` is NaN):
   `NaN > 0` = NaN, `!NaN` = NaN, `1 && NaN` = NaN, `0 && NaN` = 0, `1 || NaN` = 1,
   `0 || NaN` = NaN, `is_nan(0/0)` = 1. So "negate a positive test" does not guard anything. Use
   `is_nan`:
   - quiet on NaN: `!is_nan($B) && ($B > X)`;
   - breach on NaN: `is_nan($B) || ($B < 1)`.

   Then `threshold > 0` on the boolean. NaN still arises from arithmetic, for example a 0/0 ratio.

### 7. Rule-group write failures on AMG (Grafana 10.4.7), measured 2026-09-29

A `grafana_rule_group` create or update is one `PUT /api/v1/provisioning/folder/<uid>/rule-groups/<name>`.
AMG returns `500 {}` with no body, so the cause is invisible. **Read the real error by replaying the
same PUT against a local `grafana/grafana:<same version>` container** (version from
`GET /api/frontend/settings` -> `buildInfo.version`); the server log prints the message AMG hides.

| Payload | 10.4.7 result |
|---|---|
| client `uid` on a rule that does not exist yet | **500** -- "failed to update rule with UID ... because could not find alert rule" (section 4) |
| annotation `__dashboardUid__` without `__panelId__` | **500** -- "both annotations __dashboardUid__ and __panelId__ must be specified" (`SetDashboardAndPanelFromAnnotations`) |
| plain `dashboard_url` annotation instead | 200 |
| `contact_point` naming a receiver that does not exist | 400 |
| two rules with the same title in one folder | 400 |
| a `datasource_uid` that does not exist | **200** -- not validated on write; the rule errors at evaluation |
| new rules that would cross the `alert_rule` quota (`/api/org/quotas`) | **403 {}** -- the provider retries it for about 2 min first (section 8 fact 4) |

Consequences:
- A group move (rename or new folder) is destroy-then-create. A create that fails after the destroy
  is an outage: this cost one service all of its rules for about an hour.
- Dry-run before arming; `terraform show -json` of the saved plan should show every new rule's
  `uid` as unknown and no `__dashboardUid__` without `__panelId__`.

### 8. Moving rule groups to another folder (measured on 10.4.7, 2026-09-30)

`name` and `folder_uid` are ForceNew on `grafana_rule_group` (provider 4.45.2), so every group move
is a replace and its rules get new uids. Three facts decide how to do it safely:

1. **A group PUT carrying an EXISTING uid from another group MOVES that rule.** `deltas.go` does not
   find the uid in the target group, looks it up globally ("Rule can be from other group or
   namespace") and treats it as an update: the rule lands in the new group with its uid. An unknown
   uid still 500s (section 4). Tested on a local `grafana/grafana:10.4.7`.
2. **The provider's delete GETs the old group LIVE** and deletes only the rules still in it
   (`deleteAlertRuleGroup`). With `lifecycle { create_before_destroy = true }` a pinned rule has
   already moved, so the delete removes only the unpinned copies. Destroy-first instead deletes the
   pinned rule, and then the create 500s on the now unknown uid: the outage shape above. If EVERY rule
   of the old group is pinned, the group no longer exists when the delete runs, and the GET 404s into
   a failed apply.
3. **The `grafana_folder` label is the immediate folder's title.** Moving rules into region folders
   (`.../VRS/us-east-1`) changes that label on every instance from the service name to `us-east-1`,
   so instance identity and the default notification grouping (`[grafana_folder, alertname]`) change
   too. A firing rule resolves and re-fires, which for a PagerDuty route is a new incident. Check
   `/api/v1/provisioning/policies`, silences and templates for `grafana_folder` matchers, and gate
   the apply on "no paging rule Pending/Firing". Renaming a folder that holds rules
   (FolderTitleUpdated) changes the label the same way.

4. **`create_before_destroy` needs quota headroom equal to the group's size.** The workspace has an
   alert-rule quota (`GET /api/org/quotas`, target `alert_rule`). On AMG it is **100 per workspace
   and not adjustable**.

   **The quota counts RULES, not rule instances** - measured, and contrary to the
   AWS wording. `/api/org/quotas` read `alert_rule` used 81 while
   `/api/prometheus/grafana/api/v1/rules` showed **126 instances** across those 81
   rules, all evaluating. The AWS docs say "rule instances"; the 403 tracks the
   rule count. So a multi-dimensional rule SAVES quota, and sizing against
   instances will under-use the workspace. Trust `/api/org/quotas`, not the doc.

   While both copies of a group exist, the count is `used + group size`. A create that would cross the quota
   returns **`403 putAlertRuleGroupForbidden {}`** with no body. Provider 4.x retries 403 for about
   2 minutes (`Still creating... [02m10s elapsed]`) before failing. Measured 2026-10-01 on
   a measured prod run with 81 of 100 used: 11 groups of 1-5 rules replaced fine; groups of **22 and 19
   were both refused**, so do not plan on reaching exactly 100. The failed creates left the old
   groups intact (terraform restored them; re-plan showed exactly the 2 replaces), with no partial
   new group. Nothing paged.

   **The quota counts RULES, not alert instances**, although the AWS quota page says "rule
   instances". Measured 2026-10-01: `/api/org/quotas` read `used 81`, which matched the 81 rules in
   `/api/v1/provisioning/alert-rules`. `/api/prometheus/grafana/api/v1/rules` `totals` showed 126
   instances on those rules, all evaluated (124 normal, 1 alerting, 1 pending). So when a port does
   not fit, fold per-series rules into one multi-dimensional rule (`sum by (label) (...)`; for
   several counters, `label_replace(...)` each one and `or` them). It costs one rule and keeps one
   instance per label set.

Recipe: check `/api/org/quotas` first. Replace with `create_before_destroy` every group whose size
fits the headroom. Prove the rule bodies unchanged from the saved plan,
comparing semantically: Go durations as seconds; `null`, `""`, `[]` and `0` all as unset. The
provider writes `for = "1h40m0s"` into state for a config `"100m"`, and `0s` for an omitted `for`.
Then run the section-1 dry run on every rule just before the apply.

For a group too big for the headroom, go delete-first, one group at a time, smallest first, and only
with an OK for the gap. Use two saved plans: `plan -destroy -target='<group>' -out=d`, check that it
holds exactly that one delete, apply it; then `plan -target='<group>' -out=c`, check exactly one
create with no client uids, apply it. Measured gaps on 2026-10-01: about 40 s (19 rules) and 33 s
(22 rules) with no rules for that region. Only do this when no rule of the group is pinned (fact 2).
A pinned rule would be deleted with the old group.

## Verification (after apply)

1. `GET /api/v1/provisioning/alert-rules/<uid>` for each rule. Check the receiver,
   `no_data_state`, and that `settings.mode == "replaceNN"` survived on the reduce node.
   Provider-written rules keep it.
2. After 2–3 evaluation intervals, read `/api/prometheus/grafana/api/v1/rules` and
   `/api/annotations?type=alert`. Every evaluated value must be a number, never `NaN`.
   A quiet rule shows no number in either place: on AMG 10.4.7 the rules API leaves `value`
   empty for Normal instances, and annotations are written only on state changes (observed
   2026-09-30). There, check `health: ok`, `state: inactive` and a `lastEvaluation` later than
   the apply. A NaN condition would read Pending or Alerting, not inactive. To get the actual
   number, POST the LIVE rule's `data` (from `GET /api/v1/provisioning/alert-rules/<uid>`) to
   `/api/v1/eval` and read B and C.
3. Only then move the rules to a paging contact point.

## Example

A ported "error count > 2 for 4m" rule on a CloudWatch counter that published 23 datapoints in 452
days. Dry-run with `reduce last` gave C = NaN, so it would have fired forever from creation. With
`settings: {mode: replaceNN, replaceWithValue: 0}`, C = 0, both via `/api/ds/query` and via
`POST /api/v1/eval`. A Prometheus-backed sibling (`sum(increase(x[3m]))`) was already C = 0,
because PromQL over no series returns no frame (true NoData), which `no_data_state = OK` handles.

## Notes

- Empty-result shapes differ by data source. PromQL `sum(...)` over no series gives no frame,
  i.e. NoData. CloudWatch gives a labelled frame with 0 points, i.e. NaN. Test the data source
  you are actually using.
- This skill checks that a rule EVALUATES correctly. Whether its notification REACHES a human
  (contact point -> topic -> PagerDuty incident) is a separate check: see
  `alert-paging-chain-verification`. Run both before retiring the alarm a rule replaces.
- The table above was measured on one Amazon Managed Grafana workspace (Grafana 10.x era). Re-run
  the dry run on your version before relying on it.
- Sibling for dashboards: `dashboard-query-preflight`.

## References

- Grafana docs, "Write expression queries", Reduce: "If the series has no values then returns
  NaN". Modes Strict / Drop Non-numeric / Replace Non-numeric:
  https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/query-transform-data/expression-queries/
- grafana/grafana#67665 (NaN is evaluated as Alerting; replaceNN as the workaround):
  https://github.com/grafana/grafana/issues/67665
