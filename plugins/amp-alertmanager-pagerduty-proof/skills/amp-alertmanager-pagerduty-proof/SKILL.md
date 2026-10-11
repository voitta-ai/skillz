---
name: amp-alertmanager-pagerduty-proof
description: |
  Prove that an Amazon Managed Prometheus alert manager reaches PagerDuty
  (Events API v2) directly, with no SNS in between, and tear the proof down
  afterwards. Use when: (1) you are wiring AMP alerting to PagerDuty and the AWS
  docs you found say the AMP alert manager supports SNS only - two pages still
  do, while PagerDuty support launched 2025-08-29; (2) you need to show paging
  works BEFORE any real rule exists, so there is nothing to wait for and nothing
  to break; (3) an alert manager definition or rules namespace sits in CREATING
  and you do not know whether that is normal; (4) a POST to the alert manager
  returned 2xx and you are about to call that proof; (5) you deleted the rule
  and the PagerDuty incident did not resolve; (6) the routing key must never
  enter an agent transcript. Covers the KMS + Secrets Manager grant pair that
  aps.amazonaws.com needs, the SigV4 POST that fires an alert without a rule,
  measured timings for every step, and a cleanup that does not leave a customer
  KMS key behind.
author: Claude Code
version: 1.0.0
date: 2026-10-06
hosts: [claude, codex]
---

# Proving AMP alert manager to PagerDuty

## Problem

Two things make this hard to get right the first time.

**The docs are stale.** Two AWS pages still state that the AMP alert manager
supports Amazon SNS only. PagerDuty support shipped on 2025-08-29 (visible in
the doc history, not in the body). So the first answer you find is that this
cannot be done.

**The obvious proof proves nothing.** Posting an alert and getting an HTTP 2xx
says the workspace accepted the payload. It does not say the alert manager
decrypted the routing key, or that PagerDuty created an incident. Those are
separate links, and the secret fetch is the one that fails silently.

## Context / Trigger conditions

- Wiring AMP alerting to PagerDuty, having read that only SNS is supported.
- You want paging proven before writing a real rule.
- An alert manager definition or rules namespace is stuck in `CREATING`.
- A POST returned 2xx and you are about to report that as success.
- You deleted the rule and the incident stayed open.
- The routing key must not pass through an agent session.

## Solution

`scripts/amp-pd-proof.sh` runs the whole thing. It needs `AMP_ACCOUNT_ID` and
`AMP_WORKSPACE_ID` and nothing else; point it at a **non-production** workspace.

### 1. The grant pair, which is where this usually fails

The routing key lives in Secrets Manager as JSON - `{"routing_key": "..."}` -
encrypted with a **customer-managed** KMS key. `aps.amazonaws.com` needs
**both** grants, and either one missing produces the same silent failure:

- the KMS **key policy**: `kms:Decrypt`
- the secret's **resource policy**: `secretsmanager:GetSecretValue`

Each conditioned on `aws:SourceArn` = the workspace ARN and `aws:SourceAccount`
= your account. Scope them; a service principal without the source conditions is
a confused-deputy grant to every AMP workspace in every account.

### 2. Keep the routing key out of the session

`setup` creates the secret **empty**. A human sets its value in the Secrets
Manager console.

This is not ceremony. A routing key passed on a command line is written to the
transcript, and a transcript entry is not undone by rotating afterwards. Any
step that would put the key in `argv` belongs to a person, not an agent.

### 3. Fire an alert with no rule at all

POST a SigV4-signed alert straight at the alert manager - service name `aps`:

```
POST /workspaces/<id>/alertmanager/api/v2/alerts
```

This skips rule evaluation entirely, so the only thing under test is
alert manager to PagerDuty. Re-POST the same alert with `endsAt` set to now and
it auto-resolves.

### 4. Then prove a rule works too

A `vector(1)` rule with `for: 0m` fires immediately - the cheapest possible
always-true rule.

## Verification

**Verify by PagerDuty incident lookup, never by an HTTP status.** The POST's 2xx
means the payload was accepted; it says nothing about decryption or delivery.

Check `SecretFetchFailure` in the `AWS/Prometheus` namespace, dimension
`Workspace`, which is the signal that the alert manager could not read the
secret. The script's `status` subcommand reads it.

## Measured timings (one account, 2026-10-06)

Worth having, because several of these look like failures while they are normal:

| step | observed |
|---|---|
| alert manager definition `CREATING` -> `ACTIVE` | ~70 s |
| rules namespace `CREATING` -> `ACTIVE` | ~110 s |
| SigV4 POST -> PagerDuty incident open | **11 s** |
| rules namespace `ACTIVE` -> page from a `vector(1)` rule | ~50 s |
| `endsAt` re-POST -> auto-resolve | one `group_interval` (1 m here) |
| **namespace deleted -> incident resolves** | **~5 min, not immediately** |

That last row is the one that gets misread. Deleting the rule does not resolve
the incident; the alert ages out when its last refresh expires. Waiting is
correct, and re-deleting things is not.

## Cleanup

In order: delete the alert manager definition, delete the rules namespace,
force-delete the secret, then **schedule KMS key deletion** - 7 days is the
minimum window.

The KMS key is the one people leave behind. It is customer-managed, so it bills
until it is actually deleted, and a scheduled deletion is the only way to remove
it.

## Notes

- Do this in a non-production workspace. The script tags everything
  `purpose=temporary-proof` so the leftovers are findable.
- `group_interval` governs resolve latency; the proof config uses 1 m to keep
  the loop short. Production values will be longer, and the auto-resolve timing
  above scales with them.

## Related

- `alert-paging-chain-verification` - the general form: prove the chain reaches a
  human before deleting whatever it replaces. This skill is the AMP-to-PagerDuty
  instance of that, and the same rule applies - a green delivery metric is not
  an incident.
