---
name: rare-error-onset-replicaset-attribution
description: |
  Find which deploy change made a rare per-pod error start, or become more
  frequent, on Kubernetes: compute the error's rate per ReplicaSet against an
  exposure count (scrapes, requests), then diff the ReplicaSet pod templates.
  Use when: (1) a rare WARN or exception "came up recently" and the new image
  is the default suspect; (2) Prometheus `up=0` / failed scrapes must be split
  into pod startup/shutdown noise and steady-state failures; (3) you have a
  handful of events and must judge whether a before/after difference is real.
author: Claude Code
version: 1.0.0
date: 2026-10-12
---

# Rare error onset: attribute by ReplicaSet, not by image

## Problem

A rare error (a few events a week) shows up after a deploy. The image is the
obvious suspect. But a Deployment's pod template also carries resources, node
selectors, env and JVM flags, and any of them can change a timing race. Counting
events per day or per image hides that. With n of about 4, eyeballing a timeline
is not evidence.

## Context / Trigger Conditions

- A handful of identical log events (often one WARN plus a stack trace) on
  different pods, all first seen recently.
- A metrics `up` series shows failed scrapes, most of them around rollouts.
- Several ReplicaSets of one Deployment ran in the window: canary and main,
  or a chain of rollouts.

## Solution

1. **Get every event with its pod.** Pull all occurrences in the retention
   window with pod name, image and timestamp. Example (CloudWatch Logs
   Insights on a Container Insights application log group):
   `filter @message like /<error text>/ | stats count(*), min(@timestamp), max(@timestamp) by kubernetes.pod_name`.
   Before trusting any zero, check that the query really scanned data:
   status `Complete`, `recordsScanned` > 0, no skipped records.
2. **Get exposure per pod.** Use a denominator on which the error can occur.
   For scrape failures, count raw samples: `count_over_time(up{...}[30d])`.
   Instant `up` evaluations reuse the last sample inside the lookback, so one
   failed scrape shows as several evaluation points. For request errors, use
   the increase of the request counter.
3. **Remove lifecycle noise (scrape failures only).** Run a `query_range` with
   `step=3600` over `count_over_time(up[1h]) - sum_over_time(up[1h])` per pod.
   A failure in the pod's first non-empty window is startup; one in its last
   window is shutdown; anything else is mid-life. Explain only the mid-life
   failures. They should match the log events one to one.
4. **Group by ReplicaSet.** The pod name minus its last `-xxxxx` segment is the
   ReplicaSet:
   `label_replace(<expr>, "rs", "$1", "pod", "(.*)-[a-z0-9]+")`.
   For each ReplicaSet, get exposure, first and last seen, and event count.
   Check that the per-ReplicaSet exposure adds up to the global total.
5. **Diff the templates.** Old ReplicaSets stay in the cluster at 0 replicas
   (`revisionHistoryLimit`, default 10), so the history survives the rollout:

   ```bash
   kubectl -n <ns> get rs -o json > rs.json
   t() { jq -S --arg n "$1" '.items[] | select(.metadata.name==$n) | .spec.template
         | del(.metadata.labels["pod-template-hash"])' rs.json; }
   diff <(t <old-rs>) <(t <new-rs>)
   jq -r '.items[] | [.metadata.name, (.spec.template.spec.nodeSelector | tostring),
         .spec.template.spec.containers[0].resources.requests.cpu,
         .spec.template.spec.containers[0].image] | @tsv' rs.json
   ```

6. **Compare fairly.** Pool the ReplicaSets by the candidate variable: a
   template field, or the image. Prefer a comparison that holds the other
   variable constant: same image with a different template, or the same time
   window. Expected events in the comparison group = observed rate x that
   group's exposure. P(0 events) is about e^-expected. A value under about 1%
   means the difference is unlikely to be chance, even with n = 4.
7. **Report the variable, not a story.** Say which template field moved with
   the rate, with the exposure numbers. If you have not verified the mechanism
   that links them, write "unexplained".

## Verification

- Each mid-life failure maps to one log event: same pod, and the log time falls
  inside that scrape (sample timestamp plus scrape duration).
- The sum of per-ReplicaSet exposure equals the global exposure, so no pods
  were lost in the grouping or a join.

## Example

A Java service logged `IOException: Read end dead` from its metrics endpoint 4
times in 30 days, all on the newest image, and the image was blamed. Of 195
failed scrapes, 191 were in startup or shutdown windows. The 4 mid-life ones
were exactly the 4 log events. Per ReplicaSet: 4 events in 43.6K scrapes on
ReplicaSets whose template had changed the CPU request from 4 to 3400m and
added an `instance-size: xlarge` node selector (4-vCPU nodes). The previous
template had 0 events in 580K scrapes, and 187K of those ran the same image:
expected about 17 events, P(0) about 4e-8. The image was not the variable. The
move to 4-vCPU nodes was.

## Notes

- PromQL join gotcha: `a * on(pod) group_left(image) b` multiplies the values.
  To borrow a label without changing the value, join against `(b > bool 0)`.
- Without kube-state-metrics, cAdvisor series (`container_last_seen`,
  `container_start_time_seconds`) carry `pod` and `image` labels. See
  `eks-running-image-from-amp-cadvisor` for querying Amazon Managed Service
  for Prometheus without extra dependencies.
- The grouping regex assumes Deployment-owned pods. StatefulSet pods end in an
  ordinal, and bare pods have no suffix; check the exposure sum.
- A rate change tied to node size or CPU count fits a timing race: fewer CPUs
  change thread scheduling. Treat that as a hypothesis until a reproduction or
  a trace confirms it.

## References

- Kubernetes Deployment revision history:
  https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#clean-up-policy
- Prometheus automatically generated `up` series:
  https://prometheus.io/docs/concepts/jobs_instances/#automatically-generated-labels-and-time-series
