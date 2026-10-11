---
name: terraform-ecs-capacity-provider-staged-teardown
description: |
  Tear down an ECS-on-EC2 stack (cluster + capacity provider + ASG + launch template
  + service) with terraform when a single apply deadlocks. Use when: (1) deleting the
  ECS resources from config and applying fails with `ResourceInUseException` on
  `aws_ecs_cluster_capacity_providers` or `aws_ecs_capacity_provider`, (2) the capacity
  provider "is in use by a service" even though you deleted the service from config in
  the same change, (3) you are tempted to reach for `-target` or a manual
  `aws ecs delete-service` to break the cycle, (4) the launch template's user_data
  references the ECS service (e.g. `ECS_INSTANCE_ATTRIBUTES`), which inverts the destroy
  order. Root cause: destroy order is the reverse of the dependency graph, so the compute
  layer tears down BEFORE the workload -- exactly backwards from what the capacity
  provider's in-use check requires. Fix: split into two sequential applies (two stacked
  PRs), workload first, infra second. Each stays a clean untargeted apply.
author: Claude Code
version: 1.2.0
date: 2026-07-27
---

# Staged teardown of an ECS capacity-provider stack

## Problem

You delete the whole ECS-on-EC2 stack from terraform in one change — service, task
definitions, cluster, capacity provider, ASG, launch template — and the apply fails:

```
Error: deleting ECS Cluster Capacity Providers (...): ResourceInUseException:
The capacity provider cannot be deleted because it is associated with a service.
```

The service *is* deleted in this change. It just hasn't been deleted **yet**, and
terraform will not reorder it for you.

## Context / Trigger conditions

- Removing `aws_ecs_service` + `aws_ecs_cluster_capacity_providers` +
  `aws_ecs_capacity_provider` + `aws_autoscaling_group` in a single apply.
- `ResourceInUseException` naming the capacity provider or its cluster association.
  The AWS provider **retries for ~10 minutes** before erroring, so the apply looks
  hung on `Still destroying...` rather than failed.
- `DeleteTargetGroup ... ResourceInUse: Target group '...' is currently in use by a
  listener or a rule`, destroying `aws_lb_target_group`. Retries ~2 minutes, then
  errors. Same inversion, different resource: the rule that references the target
  group outlives it in destroy order.
- `Error: Cycle:` naming a **kept** resource (classically `aws_ecr_repository`
  picking up tag drift) alongside `create_before_destroy` ASG and launch-template
  destroys. A retained resource that is *also changing* in the same apply gets
  pulled into their destroy graph. Caught at graph-build time, so **0 resources
  change** — the state is untouched and the fix is purely to split the apply.
- `Error acquiring the state lock`, after a previous attempt was SIGTERM'd.
- Any `-target` / manual `aws ecs delete-service` workaround is on the table.

## Why one apply can't work

Terraform destroys in **reverse dependency order**: if A depends on B, A is destroyed
first. The create-time graph in this stack runs

```
ecs_service  <-  launch_template  <-  autoscaling_group  <-  capacity_provider
```

whenever the launch template's user_data interpolates the service — a common pattern for
placement attributes:

```hcl
user_data = base64encode(join("", [
  "#!/bin/bash\n",
  "echo ECS_CLUSTER=", aws_ecs_cluster.ecs_cluster.name, " >> /etc/ecs/ecs.config\n",
  "echo ECS_INSTANCE_ATTRIBUTES={\\\"app\\\":\\\"", aws_ecs_service.ecs_service["default"].name,
  "\\\"}  >> /etc/ecs/ecs.config\n",
  ...
]))
```

Reversed for destroy, that becomes `capacity_provider -> autoscaling_group ->
launch_template -> ecs_service`: the capacity provider is destroyed **first** and the
service **last**. AWS refuses, because the service still references the capacity provider.

The graph is doing exactly what it's told. There is no ordering you can express *within
one apply* that satisfies both terraform's reverse-dependency rule and AWS's in-use check
— the constraint runs in the opposite direction from the data dependency. Deleting the
resources from config doesn't help: once they're gone from config there's no edge left to
order them by at all.

## Solution — split into two applies

**Apply 1 — remove the workload.** Delete `aws_ecs_service`, the task definitions, the
service's app-autoscaling resources and alarms, and the task role/log group. Critically,
**also cut the launch-template -> service reference** in the same change (drop the
`ECS_INSTANCE_ATTRIBUTES` line, or hardcode the value). Keep the cluster, capacity
provider, ASG, and launch template.

After this apply the capacity provider is no longer in use by anything.

**Apply 2 — remove the infrastructure.** Delete the cluster, capacity provider and its
cluster association, ASG, launch template, instance role/profile, and any service mesh /
target groups / dashboards / alarms that referenced them. Nothing is in use, so it lands
in one pass.

As two stacked PRs, PR A is the workload removal and PR B (based on A) is the infra
removal. Both are clean **untargeted** applies — no `-target`, no
`aws ecs delete-service`, no `terraform state rm`.

If the ASG has `managed_termination_protection = "ENABLED"` on the capacity provider,
scale the ASG to 0 before apply 2 (or in apply 1) so there are no protected instances
left to block the delete.

## Recovery, when an apply is already stuck mid-teardown

The staged split is the fix; these unstick a teardown that has already jammed.

- **Stale lock** — `terraform force-unlock <LOCK_ID>`. A SIGTERM'd apply never
  releases the DynamoDB/S3 lock.
- **Association still "in use"** — `aws ecs delete-service --cluster <c>
  --service <s> --force` deletes and drains immediately, which unblocks
  `PutClusterCapacityProviders`. This is the one manual step worth taking; it
  resolves the deadlock rather than hiding it.
- **Target group "in use by a listener or a rule"** — apply just the rules first
  (`terraform apply -target='...aws_lb_listener_rule.<r>'`, or every address from
  `terraform state list | grep listener_rule`), then run the full apply against
  now-unreferenced target groups.
- **Give it time.** Service drain plus EC2 termination plus cluster delete
  legitimately runs many minutes. A 5-10 minute command timeout SIGTERMs the apply
  mid-flight and leaves exactly the stale lock above — the timeout manufactures the
  next failure.

## Verification

Prove the split actually works rather than assuming it. From a restored baseline:

1. Apply the **pre-teardown** config (the default branch) to a non-prod env — it should
   report only adds/changes.
2. Apply **PR A** alone. Expect changes + destroys, zero errors. This is the step that
   proves the split is real: if it succeeds standalone, apply 2 is unblocked.
3. Apply **PR B** on top. Expect the remaining destroys, zero errors.

Record the three add/change/destroy triples in the PR bodies. Confirm the *replacement*
workload (the thing you migrated to) stayed healthy across all three — for a k8s target,
pod restart count should still be 0 afterwards.

## Notes

- The same inversion appears without a launch template whenever any retained resource
  interpolates the service — an alarm dimension, an output, an IAM policy naming the
  service ARN. Grep for references to the service resource before assuming one apply
  will work.
- Deleted capacity providers report `INACTIVE` for a while before disappearing; a
  provider still `ACTIVE` after apply 2 was probably never in state. See
  `terraform-state-version-apply-forensics` for telling untracked orphans from failed
  destroys.
- Stacked PRs have their own trap at merge time: merging PR A with branch deletion
  **auto-closes** PR B rather than retargeting it. Retarget B to the default branch
  *before* deleting A's branch — see
  `gh-pr-merge-delete-branch-closes-dependent-pr`.
- Resist `-target`. It hides the ordering problem for one run and leaves the next
  engineer with the same deadlock plus drift.

## Related

- `terraform-state-version-apply-forensics` — prove which stage was actually applied.
- `gh-pr-merge-delete-branch-closes-dependent-pr` — the stacked-PR merge cascade.
- `multi-phase-feature-pr-worktrees` — worktree conventions for stacked PRs.
