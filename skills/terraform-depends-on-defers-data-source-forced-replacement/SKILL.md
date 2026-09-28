---
name: terraform-depends-on-defers-data-source-forced-replacement
description: |
  A terraform plan proposes `delete, create` (or "must be replaced") on a resource
  nothing in your diff touched, and the forcing attribute reads `(known after apply)`.
  Use when: (1) a plan shows `# forces replacement` on `name`, `bucket`, `identifier` or
  similar for a resource you did not edit, (2) the value is built from a `data` source
  such as `data.aws_region.current.id`, `data.aws_caller_identity.current.account_id` or
  `data.aws_availability_zones`, (3) the module declaring it has a module-level
  `depends_on`, (4) an apply already happened and a workload now fails with
  `The security token included in the request is invalid` or `The AWS Access Key Id you
  provided does not exist in our records` on a policy you can prove is correct. Covers
  why a module `depends_on` makes every data source inside it unknown at plan time, why
  that silently escalates to resource replacement, and why a replaced IAM role breaks
  running pods for up to an hour with errors that misdirect to IAM.
author: Claude Code
version: 1.0.0
date: 2026-09-22
---

# A module `depends_on` defers its data sources, which can force a resource replacement

## Problem

Terraform proposes to destroy and recreate a resource that your change has nothing to do
with. The plan shows the forcing attribute as `(known after apply)`:

```
  # module.<child>[0].aws_iam_role.<name> must be replaced
-/+ resource "aws_iam_role" "<name>" {
      ~ name = "<service>-<region>-<env>-role" -> (known after apply) # forces replacement
```

The value looks perfectly deterministic. Nothing in the diff touches it. Applied, it
recreates the resource byte-identically — same name, same policy — for no visible reason.

## Context / Trigger conditions

All three together:

1. A resource attribute that **forces replacement** when it changes (`aws_iam_role.name`,
   `aws_s3_bucket.bucket`, `aws_db_instance.identifier`, and many others).
2. That attribute is built from a **`data` source** rather than a variable or literal —
   `data.aws_region.current.id`, `data.aws_caller_identity.current.account_id`, and so on.
3. The module declaring it has a **module-level `depends_on`**, often added for ordering
   ("create the namespace before the service account").

Terraform defers **every** data source in a module whose `depends_on` target has a
pending change. Deferred means unread at plan time, which means unknown, which means the
attribute renders `(known after apply)`, which — on a replacement-forcing attribute —
means replacement. The chain is invisible unless you look for it.

The trigger is therefore *someone else's* change: any apply that modifies the depends_on
target replaces your resource, with no edit to it at all.

## The dangerous downstream case: a replaced IAM role

If the replaced resource is an IAM role assumed by running workloads, the damage outlives
the apply and **does not look like what it is**.

An `sts:AssumeRoleWithWebIdentity` session is bound to the role's internal unique id, not
its name or ARN. Deleting the role invalidates every live session immediately — but an
SDK keeps presenting its cached credentials until they expire (up to
`max_session_duration`, commonly 3600s). Terraform recreates the role with an identical
name and policy and reports success; the workload is broken and nothing says so.

The errors misdirect:

```
The security token included in the request is invalid.             (DynamoDB, 400)
The AWS Access Key Id you provided does not exist in our records.  (S3, 403)
```

Neither is `AccessDenied`. These are **dead-credential** errors, not authorization
errors — but a 403 on S3 reads exactly like a broken policy, and the natural response is
to audit a policy that is entirely correct. It then **self-heals** on credential expiry
with no intervention, which makes it easy to never diagnose at all.

## Solution

**Build replacement-forcing attributes from variables, never from data sources, in any
module that has a `depends_on`.** A variable is known at plan time regardless of what
else is changing.

```hcl
# before - name is unknown whenever this module's depends_on target changes
name = "${var.service_name}-${data.aws_region.current.id}-${var.environment}-role"
data "aws_region" "current" {}

# after - stable at plan time, always
name = "${var.service_name}-${var.region}-${var.environment}-role"
```

Pass it at the call site, where the value is usually already a literal:

```hcl
module "workload_east" {
  source = "./modules/workload"
  region = "us-east-1"
  depends_on = [module.something_else]
}
```

Alternatives when a variable is genuinely unavailable:

- Drop the module-level `depends_on` and express ordering through a resource reference,
  which defers only what actually depends on it.
- Move the data source **out** of the depending module and pass its value in.
- Add `lifecycle { ignore_changes = [name] }` — a last resort; it hides real renames too.

## Verification

The plan is the proof. Before the fix the resource shows `delete, create`; after, it
shows `update` or disappears from the plan:

```bash
terraform plan -out=tf.plan
terraform show -json tf.plan | python3 -c '
import json,sys
for r in json.load(sys.stdin)["resource_changes"]:
    if r["change"]["actions"] not in (["no-op"],["read"]):
        print(r["change"]["actions"], r["address"])'
```

Confirm the forcing attribute is now known at plan time — `after_unknown` for it must be
`false`, and the before/after values must match:

```bash
terraform show -json tf.plan | python3 -c '
import json,sys
for r in json.load(sys.stdin)["resource_changes"]:
    if r["address"] == "<address>":
        c = r["change"]
        print("name unknown at plan?:", (c.get("after_unknown") or {}).get("name", False))
        print("before:", (c.get("before") or {}).get("name"))
        print("after :", (c.get("after") or {}).get("name"))'
```

## Preventive check

Make this part of reviewing any plan, not something you remember after an incident:

```bash
terraform show -no-color tf.plan | grep -n 'forces replacement'
```

**Any `# forces replacement` on a resource your diff does not touch is the signal.** Do
not apply until you can name why.

## If you already applied it

The workload is running on dead credentials and will recover on its own at session
expiry. Two ways forward:

- **Restart the workload** to force a fresh `AssumeRoleWithWebIdentity` against the new
  role. Immediate, and safe when the workload is not serving traffic.
- **Wait out `max_session_duration`.** No action, but the workload cannot refresh any
  cached state until then.

Diagnose before choosing: the distinguishing evidence is that the errors are
`security token ... invalid` / `Access Key Id ... does not exist`, **not** `AccessDenied`,
and that they begin within seconds of an apply. A policy audit will find nothing because
there is nothing wrong with the policy.

Note that "the pods are still Ready" proves nothing here. A service whose readiness probe
reports in-memory state stays Ready while unable to refresh anything from AWS.

## Notes

- This is not specific to `aws_region`. Any data source in a `depends_on`-carrying module
  is deferred, and any replacement-forcing attribute built from one is exposed.
- It is not specific to IAM either — a replaced bucket or database identifier has its own
  consequences. IAM is the worst case because the damage is invisible and delayed.
- A resource replaced this way comes back with the **same name and ARN** but a **new
  internal unique id**. Anything keyed on the unique id (some SCPs, some bucket policies,
  live STS sessions) breaks; anything keyed on the ARN does not.
- The plan is the only place this is visible before it happens. Once applied, terraform
  reports complete success.

## References

- [Terraform: `depends_on` on modules](https://developer.hashicorp.com/terraform/language/meta-arguments/depends_on)
- [Terraform: data sources and dependency deferral](https://developer.hashicorp.com/terraform/language/data-sources#data-resource-dependencies)
- [AWS STS: AssumeRoleWithWebIdentity](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRoleWithWebIdentity.html)
- [AWS IAM: role unique identifiers](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html#identifiers-unique-ids)
