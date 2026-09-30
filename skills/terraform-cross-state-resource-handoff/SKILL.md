---
name: terraform-cross-state-resource-handoff
description: |
  Move live resources from one Terraform state (repo A) to another (repo B) without
  destroying or recreating them, using config-driven `removed { lifecycle { destroy = false } }`
  in A and `import {}` blocks in B instead of `terraform state rm` / `terraform import` CLI
  surgery. Use when: (1) a resource's only remaining consumer now lives in another repo and
  ownership should follow it (for example an SNS topic that alerting now publishes to after the
  alarms that used it were retired); (2) the source resources sit inside a counted module
  (`count = env == "prod" ? 1 : 0`) you also want to delete; (3) dev and prod share one cloud
  account and one environment auto-applies on merge; (4) an attribute of the moved resource
  embeds a secret (a webhook or events URL with a key) that must not be committed to B;
  (5) a reviewer or AI review claims `removed.from` needs `[0]`, or that an import `to` with
  `[0]` on a count-gated resource "breaks dev". Covers apply order, the double-ownership
  window, prevent_destroy, env-gated import for_each, plan output that prints the secret on
  import, and create-is-idempotent adoption hazards.
author: Claude Code
version: 1.0.0
date: 2026-09-29
source: https://github.com/voitta-ai/skillz
source_file: skills/terraform-cross-state-resource-handoff/SKILL.md
---

# Terraform cross-state resource handoff (removed + import)

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/terraform-cross-state-resource-handoff/SKILL.md`).


## Problem

A live resource must change owners between two Terraform states (two repos, two backends)
and must never be destroyed or recreated on the way: other systems depend on its identity
(ARN, subscription ids). The classic way is `terraform state rm` in A plus `terraform import`
in B, run by hand. That is two unreviewed state mutations, and between them no state manages
the resource.

## Context / trigger conditions

- Terraform >= 1.7 in A (for `removed`) and >= 1.7 in B (for `import` with `for_each`;
  a plain `import` block needs 1.5). Check `required_version` in both repos and the CLI that
  CI installs.
- The resource sits in a module in A that is being deleted, often a counted module that
  only exists in one environment.
- B auto-applies one environment on merge (commonly dev), and that environment shares the
  cloud account with prod.

## Solution

### Repo A (current owner): forget, do not destroy

1. Delete the module call (or resource) and add one `removed` block **per resource**:

   ```hcl
   removed {
     from = module.alerts_us_east_1.aws_sns_topic.topic   # no [0], even though the module had count
     lifecycle {
       destroy = false
     }
   }
   ```

   - `from` takes **no instance keys**. Terraform rejects `[0]` there, and the block covers
     every instance. Verified on 1.14: a block naming `module.m.aws_x.y` binds to state address
     `module.m[0].aws_x.y` after the counted module call has been deleted from config.
   - Use **resource-level** blocks, not one `removed { from = module.m }`. A module-level block
     forgets *everything* still in the module's state. If another change still has resources
     in that module waiting to be destroyed (for example alarms a sibling PR deletes), a
     module-level block orphans them in the cloud silently. With resource-level blocks, any
     leftover resource shows up in the plan as a destroy, where you can see it.
2. Delete `moved` blocks that point into the deleted module, but only after confirming that
   their `from` addresses exist in no state (`terraform state list`). A `moved` block whose
   source is already migrated is a no-op, and its dangling `to` is dead code.
3. Plan in each environment. It must list exactly the handed-off objects as
   `will no longer be managed by Terraform, but will not be destroyed (destroy = false is set in
   the configuration)`, plus a `Warning: Some objects will no longer be managed by Terraform`,
   and nothing else. Note that the `Plan: X to add, Y to change, Z to destroy` line does
   **not** count forgets. Read the resource list, not the summary line.

### Repo B (new owner): adopt, gated to the one environment that owns it

```hcl
resource "aws_sns_topic" "topic" {
  count = var.env == "prod" ? 1 : 0
  name  = "<service>-<region>"
  # ... attributes copied verbatim so the import plans no real change
  lifecycle {
    prevent_destroy = true
  }
}

import {
  for_each = var.env == "prod" ? toset(["arn:aws:sns:<region>:<account-id>:<service>-<region>"]) : toset([])
  to       = aws_sns_topic.topic[0]
  id       = each.value
}
```

- **Gate both the resource and the import** on the owning environment. If the account is
  shared and the create API is idempotent (SNS `CreateTopic` on an existing name returns the
  existing topic; so do several other "create-if-absent" APIs), an ungated resource in the
  other environment silently **co-owns** the live object, and a later destroy there deletes
  the prod one. An error would have been kinder than this success.
- `to = resource[0]` behind an empty `for_each` is fine. Zero import instances means no
  address is ever resolved. Prove it with the other environment's plan: no import, no
  resource.
- For a resource in another region, put `provider = aws.<alias>` on the resource **and** on
  the import block.
- **`prevent_destroy = true`** on every adopted object. The handoff is exactly when someone
  "finishes the cleanup". Lift it in its own reviewed change if the object really has to go.
- **Secret-bearing attributes** (an HTTPS subscription endpoint that embeds an integration
  key): do not commit the value. Put a placeholder in config and add
  `lifecycle { ignore_changes = [endpoint] }`. The imported state keeps the real value, and
  the placeholder is never sent unless the object is created from scratch, which
  `prevent_destroy` blocks. Say so in a comment next to the placeholder.

### Apply order

1. Apply B first (import). From then until step 2, **both** states hold the object. That is
   safe as long as neither config destroys it. They may differ in provider default tags, so
   each apply flips `tags_all` to its own defaults. That ping-pong is harmless, but it shows
   up as an unexpected in-place change in any A plan made during the window, so warn whoever
   applies A next.
2. Apply A (forget). B is now the single owner.

Reversing the order is not destructive. It leaves a window in which no state manages the
object. State which order you chose, and any such window, in both PRs.

## Verification

- A's plan lists only the forgotten objects (plus any destroys that belong to other changes
  and are expected).
- B's plan for the owning environment shows `# <addr> will be updated in-place (imported from
  "<id>")`. The only changes should be tag defaults and provider-local attributes (for example
  `confirmation_timeout_in_minutes` and `endpoint_auto_confirms` on `aws_sns_topic_subscription`,
  which are not cloud attributes). B's plan for the other environment shows nothing.
- After both applies, B's re-plan reads `No changes`, A's state no longer lists the objects,
  and the objects' ids are unchanged in the cloud (the same ARNs and subscription ids).

## Notes

- **The import plan prints the secret.** Terraform displays identifying attributes of an
  imported resource even when they are under `ignore_changes`, so the plan output contains the
  real endpoint and its key. Redact saved plan text (`sed -E 's#/integration/[0-9a-f]{20,}/#/integration/<redacted>/#g'`)
  before sharing or attaching it anywhere. A saved binary plan (`-out`) holds every value in
  cleartext: keep it outside the repo and delete it after use.
- AI reviewers repeatedly flag two things here, confidently and wrongly: "`removed.from` omits
  `[0]`, so it will not bind and the resources get destroyed", and "import `to` with `[0]` on a
  count=0 resource hard-fails the other environment". Answer both with the plans themselves:
  the bound `no longer managed` lines, and the other environment's empty import list.
- A CI identity with an explicit deny on the resource's delete action (for example
  `sns:DeleteTopic`) is a useful backstop, but not a plan. Prod applies of either half should
  still be manual and gated.
- Related: `terraform-noninteractive-prod-apply` (apply a saved plan, not `yes |`),
  `terraform-state-version-apply-forensics` (read what an apply actually changed).

## References

- Terraform `removed` block: https://developer.hashicorp.com/terraform/language/resources/syntax#removing-resources
- Terraform `import` block (incl. `for_each`, 1.7+): https://developer.hashicorp.com/terraform/language/import
- AWS SNS `CreateTopic` idempotency: https://docs.aws.amazon.com/sns/latest/api/API_CreateTopic.html
