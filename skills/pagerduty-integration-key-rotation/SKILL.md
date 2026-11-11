---
name: pagerduty-integration-key-rotation
description: |
  Rotate a leaked PagerDuty integration key that CloudWatch alarms reach through
  SNS (an "Amazon CloudWatch" integration, subscriptions managed in Terraform)
  without a window in which pages are lost. Use when: (1) an
  `events.pagerduty.com/integration/<key>/enqueue` URL was committed to git or
  otherwise leaked; (2) you are about to click "Generate a new integration key",
  which kills the old key at once while every SNS subscription still points at
  it; (3) before deleting the old integration you need proof that alerts arrive
  through the NEW one, not just that an incident opened; (4) a test page must
  reach you rather than the on-call, and after adding a schedule override
  `/oncalls` still names the previous user minutes later.
author: Claude Code
version: 1.0.0
date: 2026-11-11
source: https://github.com/voitta-ai/skillz
source_file: skills/pagerduty-integration-key-rotation/SKILL.md
---

# Rotating a leaked PagerDuty integration key with no paging gap

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/pagerduty-integration-key-rotation/SKILL.md`). Updates go through the
> repo's worktree + PR workflow.

## Problem

Anyone who holds an integration key can open, and resolve, incidents on that
service, so a key that reached git has to be rotated. The obvious way is one
click: Edit Integration, then "Generate a new integration key". That
invalidates the old key immediately. Every SNS subscription that still posts to
the old URL then delivers into a dead endpoint until each Terraform root that
owns one is re-applied. Nothing reports it: SNS records a failed HTTPS
delivery, the alarm still shows ALARM, and nobody is paged.

The key is usually wired into more places than the file that leaked it:
several topics, more than one region, a dev topic that borrows the prod
service's integration, a second service that shares the key, and every
long-lived branch that applies the same Terraform root.

## Context / Trigger Conditions

- A `https://events.pagerduty.com/integration/<key>/enqueue` literal sits in a
  `.tf` file, a tfvars file, or git history.
- CloudWatch alarm actions publish to SNS topics that have `https`
  subscriptions to that URL.
- The rotation has to be provably gap-free, and the old key provably dead.

## Solution

The order is the point: add the new path, move every consumer to it, prove it,
and only then delete the old one.

### 0. Handle keys by fingerprint only

Never print a key, put it in argv, or write it to a file, plan, PR or chat.
Compare keys by a short sha256 prefix instead:

```bash
fp()     { printf %s "$1" | shasum -a 256 | cut -c1-8; }
key_of() { printf %s "$1" | grep -oE 'integration/[^/]+' | head -1 | cut -d/ -f2; }
redact() { sed -E 's#integration/[^/" ]+#integration/<key>#g'; }
```

Pass the PagerDuty REST token to curl through a config pipe rather than a
header argument:

```bash
curl -sS -K <(printf 'header = "Authorization: Token token=%s"\n' "$PAGERDUTY_API_TOKEN") \
  -H 'Accept: application/vnd.pagerduty+json;version=2' "https://api.pagerduty.com/..."
```

`GET /services/<id>?include[]=integrations` returns each integration's
`integration_key`, so a script can match the leaked key to its integration by
fingerprint without anyone reading the key.

### 1. Inventory every consumer

- Scan SNS in **every enabled region**, not only the ones you deploy to:
  ```bash
  for r in $(aws ec2 describe-regions --query 'Regions[].RegionName' --output text); do
    aws sns list-subscriptions --region "$r" --output json |
      jq -r '.Subscriptions[] | select(.Endpoint|test("events\\.pagerduty\\.com/integration/"))
             | "\(.TopicArn) \(.Endpoint)"' |
      while read -r topic ep; do echo "$r ${topic##*:} $(fp "$(key_of "$ep")")"; done
  done | sort | uniq -c
  ```
- Search the code: local clones, and the organisation's code search for
  `events.pagerduty.com/integration`.
- List every branch that applies each Terraform root. A long-lived deploy
  branch without the fix points SNS back at the dead key on its next apply,
  and nothing reports it.

### 2. Add a second integration; do not regenerate

Create a new integration on the same service, with the same type and vendor
(for CloudWatch: type `event_transformer_api_inbound_integration`, vendor
Amazon CloudWatch). Give it a name you can find later, such as
"Amazon CloudWatch (rotated YYYY-MM)". Both keys now work, so no later step can
drop a page.

### 3. Store the new URL in Secrets Manager

Use one secret per region that has consuming topics. When two services share
the key, let both read the same secret, so there is one value to rotate.

```bash
printf %s "$NEW_URL" | aws secretsmanager put-secret-value --region "$r" \
  --secret-id <secret-name> --secret-string file:///dev/stdin
```

- Use `printf %s`, not `echo`: the CLI stores a trailing newline as part of the
  value. Check with `--query SecretString --output json | jq 'test("\n")'`; a
  length taken from `$(...)` cannot see a trailing newline.
- Give every CI principal that runs `terraform plan` `secretsmanager:GetSecretValue`
  on the secret **before** you push the PR, because the plan reads the data
  source. Check with `aws iam simulate-principal-policy`, passing
  `--context-entries` for condition keys such as `aws:SourceIp`. An
  `implicitDeny` that lists `MissingContextValues` means "unknown", not
  "denied".

### 4. Read the URL from the secret in Terraform

```hcl
data "aws_secretsmanager_secret_version" "pagerduty" {
  secret_id = "<secret-name>"
}

resource "aws_sns_topic_subscription" "pagerduty" {
  topic_arn              = aws_sns_topic.alert.arn
  protocol               = "https"
  endpoint               = data.aws_secretsmanager_secret_version.pagerduty.secret_string
  endpoint_auto_confirms = true # PagerDuty confirms the subscription itself; the apply waits for it

  lifecycle {
    create_before_destroy = true # subscribe the new URL, and confirm it, before removing the old one
  }
}
```

- Without `create_before_destroy` the replacement is destroy-then-create
  (`-/+` in the plan), and the topic has no PagerDuty subscription for a few
  seconds. With it, the plan shows `+/-`.
- The endpoint shows as `(sensitive value)` in plans and CI logs from now on.
- Merge the change to every branch that applies the root.

### 5. Apply, then check the subscriptions on AWS

Apply each root. If a root carries unrelated drift, target just the
subscription resources, and check that every targeted address appears in a
`# <address> must be replaced` line: a target that matches nothing raises no
error. Then check AWS itself. Each topic's PagerDuty subscription must have a
real ARN (not `PendingConfirmation`) and the new fingerprint.
`ConfirmationWasAuthenticated=false` is normal for PagerDuty endpoints.

### 6. Prove delivery through the new integration

1. **Make yourself primary on-call for the test**, so it does not page someone
   else:
   ```
   POST /schedules/<schedule-id>/overrides
   {"overrides": [{"start": "<now>", "end": "<now + 60 min>", "time_zone": "UTC",
                   "user": {"id": "<your-user-id>", "type": "user_reference"}}]}
   ```
   Then poll `GET /oncalls?schedule_ids[]=<schedule-id>` until it names you.
   It lagged about 6.5 minutes behind the override, while
   `GET /schedules/<id>?since=...&until=...` showed the override in
   `final_schedule` at once. Which view incident routing uses during that lag
   was not measured, so wait for `/oncalls`.
2. **Force one alarm.** Pick an alarm in OK whose `AlarmActions` and
   `OKActions` are exactly the PagerDuty topic, so nothing else fires
   (autoscaling, a Lambda). Set it with `aws cloudwatch set-alarm-state
   --alarm-name <alarm> --state-value ALARM --state-reason "<integration key
   rotation test, not a real alarm>"`, and set it back to OK from a
   `trap ... EXIT`. Every other subscriber of the topic, such as a chat relay,
   sees the test too, which is why the reason has to say what it is.
3. **Check the integration, not just the incident.** The old integration
   still works, so an incident on the service proves nothing by itself. List
   the incidents on the service since the test started, and for each one read
   `GET /incidents/<id>/alerts`. Require an alert whose `.integration.id` is
   the new integration's id.
4. Setting the alarm back to OK resolves the incident. It took 8 seconds.
5. Delete the override when you are done:
   `DELETE /schedules/<id>/overrides/<override-id>` truncates a running
   override to now.

### 7. Delete the old integration

Re-run the all-region scan first. Require zero subscriptions on the old
fingerprint, every subscription confirmed, and no applying branch that still
holds the literal. Then:

```
DELETE /services/<service-id>/integrations/<old-integration-id>   -> 204
GET    /services/<service-id>/integrations/<old-integration-id>   -> 404: the old key is dead
```

A REST token whose user had base role `limited_user` and team role manager on
the owning team was enough to create the integration and the override, and to
delete the old integration.

## Verification

- The all-region scan shows every PagerDuty subscription on the new
  fingerprint, and none on the old one.
- No integration on the service matches the old fingerprint, and a GET of the
  old integration id returns 404.
- At least one incident has an alert whose `integration.id` is the new
  integration.

## Example

Two services, two Terraform repos, eight SNS topics across two regions, and one
leaked key per repo. For each service:

1. Added "Amazon CloudWatch (rotated)" through the API.
2. Wrote its URL to one secret per region.
3. Changed the subscription to read the data source, with
   `create_before_destroy`, and merged it to both deploy branches.
4. Targeted applies: `2 to add, 0 to change, 2 to destroy` per root.
5. Override, forced alarm, and an incident whose alert came in through the new
   integration, resolved in 8 s.
6. All-region scan clean; old integration DELETE 204, then GET 404.

## Notes

- A dev topic subscribed to the prod service's integration is a consumer too.
- When several roots read one secret, a later apply of any of them moves its
  subscriptions to whatever the secret holds. That is safe only while both
  integrations exist.
- Plan and apply logs can hold sensitive values; keep them out of shared
  places and delete them after use.

## References

- PagerDuty, Services and Integrations (Edit Integration, "Generate a new
  integration key"):
  https://docs.pagerduty.com/incident-management/services/services-and-integrations
- PagerDuty, Amazon CloudWatch Integration Guide:
  https://docs.pagerduty.com/integrations/amazon-cloudwatch-integration-guide
- PagerDuty API, Create one or more overrides:
  https://docs.pagerduty.com/developer/api/reference/rest/schedules/create-schedule-override
- Terraform AWS provider, `aws_sns_topic_subscription`:
  https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sns_topic_subscription
