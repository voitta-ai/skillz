---
name: targetgroupbinding-unattached-tg-readiness-wedge
description: |
  Diagnose and unwedge Kubernetes rollouts stuck because an AWS Load Balancer
  Controller TargetGroupBinding points at a target group no listener rule
  forwards to. Use when: (1) `helm upgrade` / a Deployment rollout times out
  with "context deadline exceeded" while every container in the new pods is
  healthy, (2) new pods show `Ready=False` with reason
  `ReadinessGatesNotReady` and a readiness gate named
  `target-health.elbv2.k8s.aws/<name>`, (3) `aws elbv2
  describe-target-health` shows every target `unused` / `Target.NotInUse`,
  (4) a PodDisruptionBudget reports `ALLOWED DISRUPTIONS: 0` and node drains
  or consolidation (e.g. Karpenter) are blocked by a service that serves no
  traffic, (5) you staged a target group ahead of its listener rule "so it's
  ready for the cutover" and want to know why that wedges every future
  rollout. Core facts: the controller injects a target-health readiness gate
  into every pod a TargetGroupBinding matches; a target group attached to no
  load balancer listener keeps its targets permanently `Target.NotInUse`, so
  the gate can never pass. Unwedge with `kubectl delete targetgroupbinding`;
  durable fix is gating the binding separately from the target group and
  attaching the listener rule before the binding. Also covers the BACKWARDS
  direction - a listener rule REMOVED while its binding stays - and the case
  where the wedge is invisible to traffic: every request still returns 200
  because a second load balancer registers the same pod IPs directly and health
  checks them itself, so the Service having no endpoints never shows up.
author: Claude Code
version: 1.1.0
date: 2026-08-27
source: https://github.com/voitta-ai/skillz
source_file: skills/targetgroupbinding-unattached-tg-readiness-wedge/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/targetgroupbinding-unattached-tg-readiness-wedge/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

# TargetGroupBinding on an unattached target group wedges every rollout

## Problem

Preparing a cutover, you create an ALB target group and a hand-written
`TargetGroupBinding` (AWS Load Balancer Controller CRD) for a workload,
intending to point a listener rule at the group later. The change applies
green and nothing looks wrong - until the next time anything rolls that
workload's pods (a helm value change, an image bump, a spot reclaim, a node
replacement). Then:

```
helm upgrade ... : timed out waiting for the condition
Error: UPGRADE FAILED: context deadline exceeded
```

Nothing in the helm output, pod events, or container logs points anywhere
near the cause. The containers are all healthy.

## Mechanism

The Load Balancer Controller injects a **pod readiness gate** named
`target-health.elbv2.k8s.aws/<tgb-or-tg-name>` into pods matched by a
TargetGroupBinding's Service selector. The gate condition goes `True` only
when that pod's target is **healthy in the target group**.

A target group attached to **no load balancer listener** never health-checks
anything. Its registered targets sit permanently in:

```
State: unused    Reason: Target.NotInUse
```

`Target.NotInUse` is not a failure and will never become `healthy` - so the
readiness gate can never be satisfied. The chain:

```
containers healthy          ContainersReady=True
readiness gate unmet   ->   Ready=False   reason: ReadinessGatesNotReady
new pods never Ready   ->   Deployment stuck (e.g. 1/2 ready)
rollout never finishes ->   helm --wait: context deadline exceeded
```

The wedge is **latent**: the merge that created the binding looks clean,
because nothing rolls the pods at that moment. It detonates on the next
rollout, which may be days later and look unrelated. Observed twice in one
week in the same cluster - the second time after the binding was recreated
by a later apply.

### The blast radius is the cluster, not the service

With a PodDisruptionBudget of `maxUnavailable: 1` and only one old pod
still Ready, the PDB pins:

```
ALLOWED DISRUPTIONS: 0
```

That blocks `kubectl drain` and node consolidation (Karpenter, cluster
autoscaler) on every node hosting those pods - other workloads' node
lifecycle held hostage by a service that serves no traffic yet.

## Diagnose in three commands

```bash
# 1. The gate and its state
kubectl -n <ns> get pod <pod> \
  -o jsonpath='{.spec.readinessGates[*].conditionType}{"\n"}{range .status.conditions[*]}{.type}={.status} {.reason}{"\n"}{end}'
# look for: target-health.elbv2.k8s.aws/...   and   Ready=False ReadinessGatesNotReady

# 2. Why the gate can't pass
aws elbv2 describe-target-health --target-group-arn <tg-arn> \
  --query 'TargetHealthDescriptions[].TargetHealth' --output json
# every entry: {"State": "unused", "Reason": "Target.NotInUse"}

# 3. The collateral
kubectl -n <ns> get pdb
# ALLOWED DISRUPTIONS: 0
```

If step 2 shows `unused`, also confirm the target group has no listener:
`aws elbv2 describe-target-groups --target-group-arns <arn>` returns an
empty `LoadBalancerArns` list.

## Unwedge (instant, safe)

```bash
kubectl -n <ns> delete targetgroupbinding <name>
```

The controller removes the gate requirement, the stuck pods go Ready within
seconds, the Deployment completes, and the PDB's allowed disruptions
recover. This is safe precisely because the target group is unattached -
deleting the binding can't drop traffic that doesn't exist.

## Durable fix

Gate the binding separately from the target group, and sequence the
cutover so the gate can actually pass:

- Two flags, not one: `enable_target_group` (safe to pre-create; an
  unattached TG is inert) and `enable_target_group_binding` (defaults
  off; belongs to the cutover change).
- Cutover order: create target group -> point the listener rule at it ->
  **then** enable the binding. Registration takes seconds at flip time;
  pre-registering pods into an unattached group buys nothing and arms the
  wedge.
- Record the one-line unwedge next to the flag, because "context deadline
  exceeded on a helm release whose containers are all healthy" points
  nowhere near the cause.

## Corollary: `unused` is not a health verdict

`Target.NotInUse` is what a target group reports when nothing forwards to
it - it is a statement about attachment, not about the pods. Two
consequences:

- Do not write "pods register healthy in the target group" as a
  done-criterion for a change that creates an unattached group; that state
  is structurally unobservable until a listener rule attaches. Either
  accept registration as the bar and say so, or attach a throwaway rule
  once to observe health.
- A comment claiming an unattached group "health checks the pods" is
  wrong; it health-checks nothing.

## The backwards direction: the rule goes away later

The durable fix above orders things at CREATION. The case that actually bites is
the rule going away LATER, and this is the arrow people get wrong, because nobody
re-reads a binding when deleting a listener rule.

Observed: an apply removed the listener rule forwarding to a target group while
the binding that referenced it was still enabled. Same wedge, opposite arrow.

**Detaching a target group and deleting its binding belong in the same change.**

## The wedge can be invisible to traffic

The trigger list above assumes a rollout that has already timed out. It does not
have to. Dev sat wedged from one apply until it was found days later, and **every
request returned 200 the whole time**.

Both proxy pods were `Ready=False` with the gate condition
`target-health.elbv2.k8s.aws/<tg>` reading `False`, reason `Target.NotInUse`,
`"Target group is not configured to receive traffic from the load balancer"`.
The Service had **zero** ready endpoints - both pod IPs sat in
`notReadyAddresses`.

Traffic kept working because a separate, newly created load balancer registered
the same pod IPs directly with `target-type: ip` and health checked them itself.
**Pod-IP registration plus its own health check does not consult pod readiness**,
so a Service with no endpoints is irrelevant to it. A smoke test cannot see this.

Detection, cheapest first:

```bash
# 1. the cheap one, and the one that works when the service looks fine
kubectl get endpoints <svc> -n <ns> -o json | jq '{ready: .subsets[0].addresses, notReady: .subsets[0].notReadyAddresses}'

# 2. the gate CONDITION on the pod -- not the spec
kubectl get pods -n <ns> -o json | jq '.items[].status.conditions[]|select(.type|startswith("target-health"))'

# 3. root cause
aws elbv2 describe-target-groups --target-group-arns <arn> --query 'TargetGroups[].LoadBalancerArns'
```

A populated `notReadyAddresses` against an empty `addresses` is the signature.
`LoadBalancerArns: []` is the cause.

**Check the condition, never the spec, and never a request.** After the binding
is deleted the pods keep `readinessGates` in their SPEC - it is injected at
admission and is immutable - and the controller resolves the CONDITION to True.
No restart is needed, so "the gate is gone" is only visible on the pod's status
conditions and the Service endpoints.

## Caveats

- Readiness-gate injection is normally opt-in via the namespace label
  `elbv2.k8s.aws/pod-readiness-gate-inject: enabled`, but controller
  configuration can inject without it - observed on namespaces carrying no
  such label. Do not rely on the label's absence for safety; check the
  pods' `readinessGates` directly.
- Deleting the binding is the right unwedge only while the group is
  unattached. If a listener rule already forwards to it, deleting the
  binding deregisters live targets.
- After deleting a binding that terraform/GitOps still declares, the next
  apply recreates it - re-arming the wedge. Fix the flag in the same
  motion, or the second rollout wedges again (this is how it bit twice).
