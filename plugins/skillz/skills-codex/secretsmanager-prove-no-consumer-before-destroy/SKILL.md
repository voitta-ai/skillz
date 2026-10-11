---
name: secretsmanager-prove-no-consumer-before-destroy
description: |
  Prove, with evidence, that nothing consumes an AWS Secrets Manager secret before a
  terraform plan destroys it. Use when: (1) a plan shows
  `aws_secretsmanager_secret.X will be destroyed` and you must decide whether that is
  safe, (2) you ran `describe-secret` and a populated `LastAccessedDate` makes you
  think a live consumer exists, (3) `LastAccessedDate` renders as an odd local time
  like `17:00:00-07:00` and you are treating it as a real access timestamp,
  (4) you are about to justify a destroy with "nothing should be using it" and want
  a fact instead, (5) you need to tell your own terraform refresh apart from a real
  caller. Key finding: a secret with ZERO `GetSecretValue` events over its entire
  lifetime can still report a `LastAccessedDate`, so that field cannot be used as
  proof of use in either direction. Read-only; safe against prod.
author: Claude Code
version: 1.0.0
date: 2026-08-20
---

# Prove a Secrets Manager secret has no consumer before destroying it

## Problem

A terraform plan wants to destroy a secret. The reason is usually legitimate (the
caller it belonged to was removed from the config), but "legitimate in the config" is
not the same as "nothing reads it in production". The obvious check --
`describe-secret` and look at `LastAccessedDate` -- gives an answer that looks
authoritative and is not.

## Context / Trigger Conditions

- `terraform plan` lists `aws_secretsmanager_secret.<name>["<key>"] will be destroyed`
- `describe-secret` returns a recent-looking `LastAccessedDate` and you are inferring
  a live consumer from it
- The timestamp looks strange in local time -- e.g. `2026-08-18T17:00:00-07:00`, which
  is exactly `2026-08-19T00:00:00Z`. It is day-granular and stamped at UTC midnight,
  so it always reads as "late the previous afternoon" in US Pacific
- AWS's API reference says the field "is omitted if the secret has never been
  retrieved in the Region" -- do not rely on this; see Verification below

## Solution

1. **Do not use `LastAccessedDate` as evidence.** Measured on a secret with zero
   `GetSecretValue` calls in its entire lifetime, the field was still populated. It is
   day-granular, and non-consumer activity appears to move it.

2. **Ask CloudTrail about the specific resource.** Management events are queryable for
   90 days:

   ```bash
   aws --no-cli-pager cloudtrail lookup-events \
     --lookup-attributes AttributeKey=ResourceName,AttributeValue=<secret-name> \
     --start-time <secret-creation-date> --max-items 50 \
     --query 'Events[].{Time:EventTime,Event:EventName,User:Username}' --output table
   ```

   Confirm the oldest row returned is the `CreateSecret` -- that proves you covered the
   full lifetime and did not silently truncate on `--max-items`.

3. **Classify the event names. Only one of them means "a consumer".**

   | event | meaning |
   |---|---|
   | `GetSecretValue` | someone read the secret VALUE. The only real signal. |
   | `DescribeSecret`, `GetResourcePolicy` | metadata only. Your own CLI, and security posture scanners on a fixed daily cadence. Not consumption. |
   | `CreateSecret`, `PutSecretValue` | writes, usually your own terraform. |

4. **Subtract yourself.** `terraform plan`/`apply` refreshing an
   `aws_secretsmanager_secret_version` calls `GetSecretValue`, and those rows DO appear.
   So the test is not "any `GetSecretValue`" -- it is "any `GetSecretValue` by a
   principal that is not you, not your CI role, and not a scanner". Zero rows of ANY
   kind is the strongest possible answer.

5. **Check reversibility separately from usage.** These are independent questions:
   - `aws_secretsmanager_secret` with no `recovery_window_in_days` -> AWS default 30-day
     recovery window; the delete is scheduled and reversible.
   - A companion `aws_cognito_user_pool` with no `deletion_protection` -> provider
     default `INACTIVE`; the delete is **irreversible** and the pool id is gone, so any
     token ever minted against it becomes unverifiable.

## Verification

Run the same lookup against a secret you believe IS in use, as a control. The two
should look obviously different:

```
unused secret : DescribeSecret / GetResourcePolicy only, 0 x GetSecretValue,
                LastAccessedDate STILL POPULATED
used secret   : 9 x GetSecretValue alongside the metadata calls
```

That contrast is the proof that the lookup surfaces `GetSecretValue` correctly (so an
absence is real) AND that `LastAccessedDate` is not a usage signal.

## Notes

- A daily `DescribeSecret` + `GetResourcePolicy` pair at a near-constant time of day is
  a posture scanner, not an application.
- CloudTrail Event history covers 90 days. If the secret is older than that, absence
  over the window is weaker evidence -- say so rather than overstating it.
- Same shape of reasoning transfers: KMS (`Decrypt`/`GenerateDataKey` vs `DescribeKey`),
  IAM roles (`RoleLastUsed` from `get-role`), S3 (server access logs / CloudTrail data
  events, which are NOT on by default).
- A caller that has not migrated may legitimately never read its secret yet, while
  still being entitled to it later. "No consumer today" justifies a destroy only when
  the config removed the caller on purpose.

## References

- [DescribeSecret - AWS Secrets Manager API Reference](https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_DescribeSecret.html)
- [describe-secret - AWS CLI Command Reference](https://docs.aws.amazon.com/cli/latest/reference/secretsmanager/describe-secret.html)
