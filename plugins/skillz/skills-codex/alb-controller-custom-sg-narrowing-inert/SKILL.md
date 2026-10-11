---
name: alb-controller-custom-sg-narrowing-inert
description: |
  Recognize and fix the trap where supplying a custom security group to an
  AWS Load Balancer Controller ingress (annotation
  alb.ingress.kubernetes.io/security-groups) delivers NO security narrowing,
  because the controller's shared backend SG stays attached and security
  groups are additive. Use when: (1) a "narrow the ALB's security groups"
  change applied clean but the ALB still carries a controller-managed SG
  (tag elbv2.k8s.aws/resource=backend-sg) with all-protocol 0.0.0.0/0
  egress, (2) you are reviewing a diff that adds a custom SG to an ingress
  while alb.ingress.kubernetes.io/manage-backend-security-group-rules is
  "true", (3) after doing the narrowing properly, new backends go
  "unhealthy: Target.Timeout" because the health-check port was never
  opened, (4) a terraform apply that flips the annotation and adds
  replacement node-SG rules could race and close the front door mid-apply.
  Core facts: effective SG posture is the UNION of attached SGs - adding a
  narrow SG beside a broad one changes nothing; the real fix is to stop the
  controller attaching/managing the backend SG and author the node-side
  rules yourself, with explicit depends_on ordering; measure the live SGs
  before and after, never trust the diff.
author: Claude Code
version: 1.0.0
date: 2026-08-27
source: https://github.com/voitta-ai/skillz
source_file: skills/alb-controller-custom-sg-narrowing-inert/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/alb-controller-custom-sg-narrowing-inert/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

# Custom SG on an ALB ingress narrows nothing while backend-sg stays attached

## Problem

An ALB created by the AWS Load Balancer Controller carries the controller's
shared **backend SG** (tagged `elbv2.k8s.aws/resource=backend-sg`,
`elbv2.k8s.aws/cluster=<cluster>`): all-protocol `0.0.0.0/0` egress on the
ALB side, and one wide shared port-range ingress rule on the node/cluster
SG admitting it. A security PR adds a terraform-owned narrow SG via:

```yaml
alb.ingress.kubernetes.io/security-groups: <your-sg>
alb.ingress.kubernetes.io/manage-backend-security-group-rules: "true"
```

The PR's claim: ALB egress is now `tcp/<app-port>` to the cluster SG only.
The apply is clean, the controller's generated *frontend* SG is gone,
your SG is attached - and the posture is **identical**.

## Mechanism

Two facts compose:

1. With `manage-backend-security-group-rules: "true"`, the controller
   **keeps attaching its shared backend SG** to the ALB alongside your
   custom SGs, and keeps managing the node-SG rule that admits it. Your SG
   rides shotgun; the broad one still drives.
2. **Security groups are additive.** Effective permissions are the union
   of every attached SG. A narrow SG added beside a broad one subtracts
   nothing.

Net: one fewer *generated* SG, a narrow SG added beside the broad shared
one, effective reachability unchanged. The change ships inert, and the
repo now contains a comment claiming a narrowing that never happened.

## Measure, don't trust the diff

Before and after any SG change on a controller-managed ALB:

```bash
# which SGs the ALB actually carries
aws elbv2 describe-load-balancers --names <alb-name> \
  --query 'LoadBalancers[0].SecurityGroups' --output text

# what each one allows (look for the backend-sg tag and -1/0.0.0.0/0)
aws ec2 describe-security-groups --group-ids <sg...> \
  --query 'SecurityGroups[].{id:GroupId,tags:Tags,egress:IpPermissionsEgress}'

# node/cluster SG: which source SGs are admitted, on which ports
aws ec2 describe-security-groups --group-ids <node-sg> \
  --query 'SecurityGroups[0].IpPermissions[].{ports:[FromPort,ToPort],src:UserIdGroupPairs[].GroupId}'
```

The narrowing is real only when (a) the backend-sg is **absent** from the
ALB, (b) the ALB's sole remaining egress is your intended `tcp/<port>` to
the node SG, and (c) the node SG admits your SG - not the shared one - on
exactly that port.

## The real fix

Two halves, both required:

1. **Stop the controller attaching/managing the backend SG** for this
   ingress: set `alb.ingress.kubernetes.io/manage-backend-security-group-rules: "false"`
   alongside your `security-groups` annotation. The controller then
   detaches its shared backend SG from this ALB.
2. **Author the node-side rules yourself**, because the shared rule that
   admitted the ALB disappears with it:

```hcl
resource "aws_vpc_security_group_ingress_rule" "alb_to_nodes" {
  security_group_id            = var.node_security_group_id
  referenced_security_group_id = aws_security_group.ingress.id
  ip_protocol                  = "tcp"
  from_port                    = var.app_port
  to_port                      = var.app_port
}
```

### The ordering race - add depends_on

In terraform, the ingress annotation flip and the replacement node rules
are siblings with **no dependency edge** - terraform may flip the
annotation (controller detaches backend-sg, deleting the shared node rule
that admitted the ALB) before your replacement rule exists. In that window
the front door is closed. Make the ingress depend on the node rules:

```hcl
resource "kubernetes_ingress_v1" "public" {
  # ...
  depends_on = [aws_vpc_security_group_ingress_rule.alb_to_nodes]
}
```

In the observed apply the race never fired - which is exactly the outcome
that makes it impossible to prove the `depends_on` was needed. Have it
anyway; the failure mode is a closed front door.

### Every new backend port needs explicit pairs - including health check

Once the broad SG is gone, nothing implicit opens paths anymore. Adding a
new backend (say a gateway workload with traffic on `8000` and its status
endpoint on `8100`) needs **both directions on both ports**:

- ALB SG **egress** `tcp/8000` and `tcp/8100` -> node SG
- node SG **ingress** `tcp/8000` and `tcp/8100` <- ALB SG

SGs are stateful, but statefulness does not span two different groups'
rule sets - each side needs its rule. Omitting the health-check port is
the classic miss: targets sit

```
unhealthy    Target.Timeout
```

for a reason invisible in the target group's own configuration.

## Bonus behavior worth knowing

The controller recomputes the shared backend rule's port range from
whoever still uses it. When one ingress leaves the shared SG, the wide
node-SG rule narrows for every remaining rider (observed: `tcp/80-8100`
-> `tcp/80-8080` after one workload's exit). Your narrowing can shrink the
blanket for neighbors - nice, but also means their reachability changed
without their repo changing; announce it.

## Verification checklist (after the real fix)

- Backend-sg absent from the ALB; sole SG is yours.
- ALB egress = your intended ports only.
- Node SG admits your SG on exactly those ports; the shared-rule entry for
  this ALB is gone.
- `aws elbv2 describe-target-health`: targets `healthy` before AND after,
  with no transition through `unhealthy` (watch during the apply).
- End-to-end request through the ALB still succeeds.

## Caveats

- The additive-SG trap generalizes: ANY "attach a narrower SG" change on
  any AWS resource is inert while the broader SG remains attached.
  Narrowing means *detaching* or *editing* the broad one.
- A prior review that measured this on an earlier cut of the same change
  is evidence worth hunting for before re-merging a re-cut - the finding
  survives the re-cut.
- `manage-backend-security-group-rules: "false"` transfers permanent
  ownership of node-rule hygiene to you: future port changes are your
  diff, not the controller's.
