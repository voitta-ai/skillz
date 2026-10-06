---
name: cloudwatch-per-host-stat-single-host-vs-fleet
description: |
  Decide whether a CloudWatch alarm on a per-host application metric (Micrometer,
  Dropwizard, StatsD) reflects a fleet-wide incident or ONE sick host, and stop
  misreading its magnitude. Use when: (1) a per-host gauge/timer alarm fires and the
  Average looks catastrophic (e.g. an "average latency" of 21,242 when baseline is 2),
  (2) you are about to call an incident fleet-wide based on a CloudWatch Average,
  (3) a latency/queue-depth/pool-saturation metric spikes but request throughput and
  error counts stay flat, (4) you need to know the UNIT of a metric and get-metric-data
  did not return one. Covers the unweighted-mean-across-hosts trap, the
  Maximum/Sum concentration ratio, and SampleCount as a host-census signal.
author: Claude Code
version: 1.0.0
date: 2026-08-26
---

# CloudWatch per-host stats: one sick host vs. the whole fleet

## Problem

An application publishes a metric per host. CloudWatch aggregates those per-host
datapoints into one series. Two independent traps then make a single-host blip look
like a fleet-wide outage:

1. **The Average is an unweighted mean ACROSS HOSTS**, not across requests. One host
   at 21 s and fourteen hosts at 2 ms does not read as "mostly fine" - it reads as a
   fleet average of roughly 1.4 s, and if the healthy hosts publish fewer datapoints it
   reads far worse. The number is real; the *scope* it implies is not.

2. **The unit is not in the metric name and `get-metric-data` never returns it.**
   A name ending in `.rate` may be publishing `Milliseconds`. Reading `21242` as
   microseconds instead of milliseconds is a 1000x error in the incident writeup.

The combination produces a confident, precise, wrong statement: "average latency hit
21 seconds fleet-wide."

## Context / Trigger Conditions

- A per-host gauge/timer/counter alarm fires (pool saturation, in-flight count,
  queue depth, executor active, latency).
- The Average or Maximum is orders of magnitude above baseline, BUT:
  - request throughput is flat,
  - error counters are flat or zero,
  - the alarm self-resolves in a few minutes.
- You have no `Unit` in your query output because you used `get-metric-data`.
- Symptom phrasing that should trigger this: "the fleet average latency was N seconds",
  "every host was saturated", "the whole cluster degraded".

## Solution

### Step 1 - Get the unit. `get-metric-data` cannot give it to you.

The `GetMetricData` response (`MetricDataResult`) carries only
`Id / Label / Timestamps / Values / StatusCode / Messages`. There is **no `Unit` field**.
`GetMetricStatistics` returns one per datapoint:

```bash
aws cloudwatch get-metric-statistics --no-cli-pager --region "$REGION" \
  --namespace "$NS" --metric-name "$METRIC" \
  --start-time 2026-01-01T00:00:00Z --end-time 2026-01-01T00:05:00Z \
  --period 60 --statistics Average Maximum \
  --query 'Datapoints[].[Timestamp,Average,Maximum,Unit]' --output text
```

Do this before quoting any magnitude. Do not infer the unit from the metric name.

### Step 2 - Pull SampleCount, Sum and Maximum at the SAME period.

```bash
aws cloudwatch get-metric-data --no-cli-pager --region "$REGION" \
  --start-time <aligned> --end-time <aligned> --output json \
  --metric-data-queries '[
    {"Id":"n",  "MetricStat":{"Metric":{"Namespace":"NS","MetricName":"M","Dimensions":[...]},"Period":60,"Stat":"SampleCount"}},
    {"Id":"sum","MetricStat":{"Metric":{"Namespace":"NS","MetricName":"M","Dimensions":[...]},"Period":60,"Stat":"Sum"}},
    {"Id":"mx", "MetricStat":{"Metric":{"Namespace":"NS","MetricName":"M","Dimensions":[...]},"Period":60,"Stat":"Maximum"}}
  ]'
```

Align `--start-time` to a period boundary - `get-metric-data` anchors its buckets to the
query start, so two unaligned queries can share zero timestamps.

### Step 3 - Compute the concentration ratio `Maximum / Sum`.

For an **additive** per-host stat (in-flight count, active threads, queue depth,
connection count) each host contributes one datapoint per period, so:

| `Maximum / Sum` | Reading |
|---|---|
| near **100%** | ONE host holds essentially all of it. Single-host episode. |
| near **1/N** (N = host count) | Evenly spread. Genuinely fleet-wide. |
| in between | A subset. Count them as roughly `Sum / Maximum`. |

`SampleCount` is your host census for that minute. Compare it to the fleet size you
expect.

### Step 4 - Read a SampleCount DROP as a symptom, not a gap.

If `SampleCount` falls (15 hosts -> 8) during the spike, that is usually not missing
data - it is hosts too busy, GC-thrashing, or restarting to publish. A drop concurrent
with the spike is corroborating evidence of severity **on those hosts**, and it also
inflates every remaining Average, because the surviving publishers are the sick ones.

### Step 5 - Cross-check against a request-weighted metric.

Per-host means lie about scope; per-request counters do not. Confirm with throughput
(calls/min), error counts, and any fallback/degradation counter. If throughput held and
errors stayed at zero while the "average" exploded, the excursion did not reach the
serving path fleet-wide.

## Verification

You have correctly classified the incident when all of these agree:

- `Maximum / Sum` near 1.0 AND `SampleCount` at expected fleet size => single host.
- Request throughput flat across the window => no fleet-wide serving impact.
- The unit came from `get-metric-statistics`, not from the metric name.

## Example

A bounded HTTP connection-pool gauge (`executor.active.value`, additive, one datapoint
per host per minute) alarmed at a `Maximum` threshold. Fleet ~15 hosts.

```
UTC     SampleCount   Sum   Max   Max/Sum
09:10             8   465   351      75%   <- also: census fell 15 -> 8
13:36            15    93    93     100%
13:40            15   200   190      95%
13:43            15    66    62      94%
```

Every window: one host carrying 75-100% of the concurrency. Meanwhile the paired
latency timer read `21242` with `Unit: Milliseconds` - 21 seconds, but as an unweighted
mean over hosts, so it was one host at ~21 s beside fourteen at ~2 ms. Request rate held
flat at ~1.87M calls/min and the error counter stayed at 0 for the entire window.

Correct conclusion: repeated **single-host** episodes that self-recovered, not a
fleet-wide outage - while still being genuine early instances of the failure mode the
alarm was built to catch.

## Notes

- The `Maximum / Sum` ratio is only meaningful for **additive** per-host stats. For a
  per-host *latency* or *percentile*, `Sum` is not physically meaningful; use
  `SampleCount` plus a request-weighted counter instead.
- Micrometer publishes several derived series per timer (`.avg`, `.max`, `.count`,
  `.sum`, `.percentile.value`). CloudWatch then aggregates those AGAIN across hosts.
  You are looking at a statistic of a statistic - `Average` of `.avg` is not the
  request-weighted mean latency and never was.
- A `.rate`-suffixed name publishing `Milliseconds` is common; naming reflects the
  in-process meter, not the published unit.
- Related: skills covering additive-dimension blanking, missing env dimensions causing
  misattribution, and fleet-dimension setup for Dropwizard/Micrometer publishers.

## References

- [GetMetricData - MetricDataResult](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_MetricDataResult.html) (no `Unit` member)
- [GetMetricStatistics - Datapoint](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_Datapoint.html) (has `Unit`)
- [CloudWatch statistics definitions](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Statistics-definitions.html)
