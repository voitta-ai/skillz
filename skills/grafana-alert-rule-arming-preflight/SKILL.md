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
author: Claude Code
version: 1.0.1
date: 2026-09-29
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

### 5. Prove the rendered instance count

A rule group gated by `for_each`/`count` on a variable, such as a contact-point interlock, renders
zero instances when the variable is empty. In a diff that looks identical to "armed". Show the
render: `terraform plan -out=p`, then `terraform show -json p | jq` over `.resource_changes[]`.
List each group's rules with `uid`, `no_data_state`, `notification_settings[0].contact_point`,
and the B model's `settings`.

## Verification (after apply)

1. `GET /api/v1/provisioning/alert-rules/<uid>` for each rule. Check the receiver,
   `no_data_state`, and that `settings.mode == "replaceNN"` survived on the reduce node.
   Provider-written rules keep it.
2. After 2–3 evaluation intervals, read `/api/prometheus/grafana/api/v1/rules` and
   `/api/annotations?type=alert`. Every evaluated value must be a number, never `NaN`.
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
