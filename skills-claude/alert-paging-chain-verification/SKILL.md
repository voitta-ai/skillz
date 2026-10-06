---
name: alert-paging-chain-verification
description: |
  Prove a migrated or newly-created alert actually reaches a human BEFORE deleting the
  alarm it replaces. Use when: (1) porting CloudWatch alarms to Grafana/Prometheus rules,
  (2) about to delete a monitor because "the replacement is live", (3) routing new rules
  to an SNS topic or webhook an existing alarm already uses, (4) a migration PR claims
  "routing parity" from matching rule counts or matching alarm_actions counts, (5) an
  alert has never fired and you are treating that as healthy. Catches the failure where
  delivery succeeds, every count matches, and no incident is ever created.
author: Claude Code
version: 1.0.0
date: 2026-09-28
---

# Alert Paging Chain Verification

## Problem

A monitoring migration deletes the old alarm because the new rule is "live and verified".
The new rule is live. It reaches nobody. Nothing reports this, because every check people
habitually run passes:

- rule count matches alarm count
- each rule declares a notification target
- the target exists
- the transport reports **successful delivery**

The break is in the last link — *target receives the message* to *a human is notified* —
and that link is the one nobody checks, because checking it means causing a real page.

Observed end state: 35 production alarms deleted, their 16 paging replacements unable to
page, invisible for hours, discovered only by accident.

## Context / Trigger Conditions

Use this skill when any of these are true:

- Migrating alarms between monitoring systems (CloudWatch -> Grafana/Prometheus, or any
  equivalent) and the replacement routes to the **same** topic/queue/webhook the original
  used.
- A PR or ticket justifies a deletion with "coverage parity" or "routing parity" derived
  from counts.
- You are about to delete, disable or `terraform destroy` an alarm that has an action
  attached.
- A rule or alarm has sat quiet and that silence is being read as evidence of health.
- The destination integration was configured for a *different producer* than the one now
  sending to it.

## Solution

### Verify five links, not one

| # | link | how to verify | what a pass looks like |
|---|---|---|---|
| 1 | rule -> notification target | read the rule's rendered config | every rule names a target; count them |
| 2 | target -> transport endpoint | resolve the target's topic/URL | it exists and resolves |
| 3 | transport -> delivery | the transport's own delivery metrics | published > 0, delivered > 0, **failed = 0** |
| 4 | delivery -> **incident** | query the incident system for the window | **an incident exists** |
| 5 | incident -> **human** | ask the person whose phone it is | they received it |

Links 1–3 are the ones usually checked and they prove nothing on their own. **Link 4 is
the whole point.** Link 5 exists because incident systems under-report (see Notes).

### The decisive trick: make the producer's payload the thing under test

A destination integration is usually built for a *specific producer's payload shape*. Point
a different producer at it and it will often accept the message, return HTTP 200, and emit
nothing. Delivery metrics then show success.

So test with the **real producer**, not a hand-rolled API call:

1. Use the monitoring system's own "test notification" / "test contact point" endpoint, or
   let a real rule fire.
2. Identify the resulting incident by something only that producer generates — most tools
   prefix or template the title (e.g. a `[FIRING:n]` prefix). If the incident carries the
   producer's formatting, the producer genuinely reached the incident system.
3. A hand-rolled call to the destination API proves the *destination* works. It does not
   prove your *producer* can reach it. Do both and keep them separate in your head.

### Establish a control

Query the incident system's history for that destination. If it has **ever** created
incidents, note what those look like — their titles usually reveal which producer's schema
the integration parses. An integration with a long history of incidents from producer A and
none from producer B is your answer.

If the destination has no history at all, you have no control: absence of incidents proves
nothing either way, and you must generate one.

### Sequence the migration so a failure is survivable

1. Arm the replacement. **Leave the original in place.**
2. Verify links 1–5 on the replacement.
3. Only then delete the original.

Duplicate alerts for a short window are cheap. A silent gap is not. If steps are already
out of order, the original is your safety net — do not delete it to "finish the cleanup".

## Verification

You are done when you can point at a specific incident record, created by the new rule,
through the production notification path, and the on-call confirms it arrived.

Anything short of that — including "the topic exists", "delivery succeeded", "the counts
match" — is not verification.

## Example

Migrating alarms to a new rule engine, both routing to the same message topic:

```
link 1  12 rules, each naming the paging contact point            OK
link 2  contact point resolves to the topic                       OK
link 3  published 2, delivered 4, failed 0                        OK
link 4  incidents created in that window: 0                       <-- FAIL
        control: 17 incidents from the OLD producer, 6 months     integration works,
                 every title in the old producer's schema         just not for us
```

Diagnosis: the destination's integration parses the old producer's payload schema and
silently discards anything else. Fix: add a native integration for the new producer and
route to that, bypassing the shared topic.

Re-verified after the fix: an incident appeared carrying the new producer's own title
formatting — proof it originated there rather than from a test harness.

## Notes

Traps that make this harder than it looks:

- **Delivery success is not an incident.** Most transports record a 2xx as success. A
  destination that accepts and discards looks identical to one that acts.
- **Incident-system notification logs are not exhaustive.** One system's per-incident
  notification log listed only push, chat and email while SMS and a voice call had
  actually been delivered. Do not use such a log to prove a notification did *not* fire —
  ask the human.
- **Acknowledging halts the remaining notification rules.** A test incident that is acked
  or resolved quickly never exercises the later escalation legs. If the rules are staged
  (e.g. push at 0 min, email at 1, SMS at 2, voice at 3), the incident must stay open and
  unacknowledged past the longest leg you want to prove.
- **Escalation to a *secondary* is a different test** and pages a colleague. Know the
  escalation delay before holding an incident open, so you do not reach them by accident.
- **"It has never fired" is not evidence of health.** It may be structurally unable to
  fire — wrong unit, a dimension set the metric never publishes, or a metric that does not
  exist for that resource. Check whether it *can* fire before trusting its silence.
- **A no-data state that "keeps the last state" has no last state on first evaluation**
  and may resolve to Alerting, so a brand-new rule whose query returns nothing can fire the
  instant it is created. Prefer an explicit OK-on-no-data when porting an alarm whose
  original treated missing data as benign — and note that an alarm sitting in an
  insufficient-data state typically fires *no* action at all, so "keep last" is not parity.
- **Query engines differ on dimension matching.** A CLI that requires an exact dimension
  set will report "no data" where the monitoring system's datasource, matching on the
  dimensions given, returns series. Validate a ported threshold by reading the **rule's own
  state** over a bake period, never by re-querying the metric store with the dimensions the
  rule declares.
- **Cumulative counters break `>= 1` thresholds.** A per-container restart counter never
  decreases, so any resource that has ever restarted inside the window keeps such a rule
  firing forever.

## References

- PagerDuty Events API v2 — the native-integration path that avoids payload-shape
  mismatches: https://developer.pagerduty.com/docs/events-api-v2-overview
- Grafana alerting, contact points and notification testing:
  https://grafana.com/docs/grafana/latest/alerting/configure-notifications/
- Amazon SNS delivery metrics (`NumberOfMessagesPublished`,
  `NumberOfNotificationsDelivered`, `NumberOfNotificationsFailed`):
  https://docs.aws.amazon.com/sns/latest/dg/sns-monitoring-using-cloudwatch.html
- CloudWatch alarm states and actions — note that `INSUFFICIENT_DATA` triggers only
  `insufficient_data_actions`:
  https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/AlarmThatSendsEmail.html
