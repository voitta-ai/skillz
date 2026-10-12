---
name: zone-topology-spread-cannot-move-packed-pods
description: |
  A `ScheduleAnyway` zone topology spread does NOT spread pods that fit on
  existing nodes, because kube-scheduler only scores FEASIBLE nodes: if every
  untainted matching node is in one zone, every pod lands there and the node
  autoscaler is never consulted, since nothing is Pending. Use when: (1) a
  Deployment carrying a `topology.kubernetes.io/zone` spread is entirely in one
  AZ and you are about to call it a scheduler bug, (2) you are reviewing or
  writing a zone spread for a workload whose pods are small relative to a node,
  (3) you are considering `DoNotSchedule` + `minDomains` to force the spread
  and need to know what it costs during an AZ outage, (4) pods stay Pending for
  the whole duration of a zone failure and you need to know whether that is the
  spread, (5) a rolling update lands both new pods in one zone in a two-zone
  region, (6) someone calls a zone spread "AZ resilience" before checking the
  workload's dependencies. Covers why ScheduleAnyway is inert for packed pods,
  the two traps in `DoNotSchedule` + `minDomains` (`nodeTaintsPolicy` counting
  tainted zones, and a lost zone still counting as a domain), `matchLabelKeys`
  during a rollout, and the dependency check that decides whether any of it
  buys resilience.
author: Claude Code
version: 1.0.0
date: 2026-10-12
---

# A ScheduleAnyway zone spread cannot move pods that already fit

## Problem

A Deployment declares a zone spread and runs entirely in one AZ. The spread is
not being ignored -- it is being satisfied in the only way the scheduler is
allowed to satisfy it.

`kube-scheduler` scores only **feasible** nodes. A `ScheduleAnyway` constraint
is a scoring preference, not a filter. So if every untainted node matching the
pod's selectors and resources is in one zone, every replica lands in that zone,
the preference loses to there being nowhere else to go, and **the node
autoscaler is never consulted** -- because nothing is Pending. Karpenter (or
Cluster Autoscaler) only ever sees pods that failed to schedule.

Observed: a workload with a zone spread (`ScheduleAnyway`, `maxSkew: 1`) ran
3/3 in one AZ, because the NodePool it landed on (consolidation
`WhenEmptyOrUnderutilized`) had all 4 of its nodes in that AZ.

**The contrast that makes the mechanism obvious.** A pod sized to fill a node
is always Pending at rollout -- there is no feasible node until one is created
-- so the autoscaler picks the zone, and Karpenter 1.11 treats `ScheduleAnyway`
as required on that first pass. Packed pods therefore get a real spread while
small pods silently do not. Pod size, not the constraint, decides whether the
constraint does anything.

## Context / Trigger conditions

- A `topology.kubernetes.io/zone` spread on a workload whose pods are small
  relative to a node, so they always find a feasible node.
- A consolidating node pool, which concentrates nodes into fewer zones over
  time and makes this more likely the longer the cluster runs.
- Any claim of AZ resilience resting on a `ScheduleAnyway` spread.

## Solution

### Check whether the spread is doing anything at all

```bash
kubectl get pods -l <selector> -o json | jq -r '
  [.items[] | .spec.nodeName] | unique[]' | while read n; do
  kubectl get node "$n" -o jsonpath='{.metadata.labels.topology\.kubernetes\.io/zone}{"\n"}'
done | sort | uniq -c
```

One line of output is the symptom. Then check the pool's nodes, not just the
pods': if the pool itself is single-zone, the spread had nothing to work with.

### `DoNotSchedule` + `minDomains` forces it, with two traps

`DoNotSchedule` makes the constraint a filter, and `minDomains` requires a
minimum number of zones to be in play, so the scheduler leaves pods Pending
until the autoscaler provides a node in another zone. That works. Both traps
are about what counts as a domain:

**1. `nodeTaintsPolicy: Ignore` (the default) counts a zone that has ANY
node** -- including nodes tainted for another pool, or a system node group your
pods can never run on. The scheduler then pushes pods toward that zone and the
autoscaler has to launch nodes there, which may not be what the taint was
protecting.

**2. In an AZ outage, the lost zone keeps counting.** Its `NotReady` nodes
still present as a domain; and once they are removed, `minDomains` holds the
global minimum at that number anyway. Either way the surviving zone can hold
only `maxSkew` pods, so replacements and scale-out stay **Pending for the whole
outage**. This is documented semantics rather than a measured failure here, so
treat it as a design consequence to test, not as an observed incident -- but
price it: for a stream consumer it is unbounded lag, and for a request-serving
workload it is a hard cap on capacity exactly when you need headroom.

### A possibly outage-safe shape, unverified

`DoNotSchedule` with `nodeTaintsPolicy: Honor` (so `NotReady` nodes, which
carry `NoSchedule` taints, drop out of the domain count) and **no**
`minDomains`, plus a per-zone anchor workload that keeps one untainted node
alive in each zone so the spread always has domains to spread across.

The autoscaler's behaviour under that combination is **not verified**. Test it
against a drained zone before relying on it.

### Use `matchLabelKeys: [pod-template-hash]`

Without it, the old ReplicaSet's pods count toward the skew during a rolling
update. In a two-zone region that is enough to put both new pods in one zone
while the constraint reports itself satisfied.

## Verification

- Pods spread across the expected zones, counted from their nodes' zone labels
  rather than from the constraint being present.
- During a rollout, the new ReplicaSet's pods alone satisfy the skew.
- A drained or cordoned zone produces the behaviour you chose: either pods
  Pending (you accepted the availability trade) or pods rescheduled (you did
  not).

## Notes

- **Check the dependencies before calling any of this AZ resilience.** A
  workload spread across three zones that talks to a single-node cache in one
  zone does not survive losing that zone. Spreading the stateless tier is
  necessary and not sufficient, and it is the easier half to see.
- The failure is quiet in both directions: `ScheduleAnyway` reports a satisfied
  constraint while doing nothing, and `DoNotSchedule` reports Pending pods that
  look like a capacity problem rather than a spread decision.

## Related

- `targetgroupbinding-unattached-tg-readiness-wedge` -- the other way pods sit
  Pending or not-Ready for a reason that is a configuration decision rather
  than a capacity problem.
- `eks-running-image-from-amp-cadvisor` -- establishing what is actually
  running on which node, which is the input to checking a spread rather than
  assuming it.
