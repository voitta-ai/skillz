---
name: cloudwatch-metric-filter-dimensions-default-value-exclusive
description: |
  Catch the CloudWatch Logs metric-filter constraint that terraform cannot:
  a metric transformation may carry dimensions OR a default_value, never
  both - and the AWS provider has no plan-time guard, so the mistake sails
  through validate and plan and detonates only at apply. Use when: (1) an
  apply (often a merge-to-main auto-apply in CI) fails with
  "InvalidParameterException: Invalid metric transformation: dimensions and
  default value are mutually exclusive properties", (2) you are reviewing an
  aws_cloudwatch_log_metric_filter whose metric_transformation sets both
  default_value and dimensions, (3) you are deciding which of the two to
  drop and several environments publish the same metric name into one
  account+region. Core facts: the provider (verified on hashicorp/aws
  6.56.0) declares no ConflictsWith between the arguments; the constraint
  can be settled empirically in seconds with `aws logs put-metric-filter`
  on a scratch log group; keep the dimension and drop default_value when
  the dimension is what separates environments - dropping the dimension
  instead blends their series into one.
author: Claude Code
version: 1.0.0
date: 2026-08-27
source: https://github.com/voitta-ai/skillz
source_file: skills/cloudwatch-metric-filter-dimensions-default-value-exclusive/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/cloudwatch-metric-filter-dimensions-default-value-exclusive/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

# Metric filter dimensions + default_value: passes plan, fails apply

## Problem

A PR adds log-derived metrics:

```hcl
resource "aws_cloudwatch_log_metric_filter" "rejected" {
  name           = "token-exchange-rejected"
  log_group_name = aws_cloudwatch_log_group.access.name
  pattern        = "{ $.statusCode = 4* }"

  metric_transformation {
    name          = "TokenExchangeRejected"
    namespace     = "app/gateway"
    value         = "1"
    default_value = "0"                      # zero-fill quiet periods
    dimensions = {                           # separate the environments
      Environment = "$.env"
    }
  }
}
```

`terraform validate` passes. `terraform plan` passes. The apply fails:

```
InvalidParameterException: Invalid metric transformation:
  dimensions and default value are mutually exclusive properties
```

CloudWatch rejects the combination outright: a filter that publishes
dimensions cannot also have a default value.

## Why it reaches apply

The AWS provider (verified on `hashicorp/aws` 6.56.0) declares **no
`ConflictsWith`** between `default_value` and `dimensions` on
`metric_transformation`, so there is no schema-level or plan-time check.
The first thing that enforces the constraint is the CloudWatch API itself.

That timing is what makes it expensive: in repos where CI runs
`terraform apply -auto-approve` on merge to the default branch, the
failure lands exactly at **merge-to-main apply** - a red main and a
half-applied change, after every review already passed.

## Settle it empirically in seconds

No terraform needed - the API answers directly on a scratch log group:

```bash
LG=/tmp/probe-metric-filter
aws logs create-log-group --log-group-name "$LG"

# both set -> the exact error
aws logs put-metric-filter --log-group-name "$LG" \
  --filter-name probe --filter-pattern '{ $.code = 4* }' \
  --metric-transformations \
  'metricName=Probe,metricNamespace=probe,metricValue=1,defaultValue=0,dimensions={Env=$.env}'
# InvalidParameterException: Invalid metric transformation:
#   dimensions and default value are mutually exclusive properties

# dimensions only -> succeeds
aws logs put-metric-filter --log-group-name "$LG" \
  --filter-name probe --filter-pattern '{ $.code = 4* }' \
  --metric-transformations \
  'metricName=Probe,metricNamespace=probe,metricValue=1,dimensions={Env=$.env}'

aws logs delete-log-group --log-group-name "$LG"   # clean up
```

Worth the thirty seconds whenever the answer decides a review comment -
"the API rejects it" ends the argument in a way provider-doc archaeology
does not.

## Which one to drop

**Drop `default_value`, keep `dimensions`** - whenever the dimension is
load-bearing. The common trap is the reverse call: "drop the dimension,
each environment has its own account/region anyway." Check that premise -
when dev and prod publish the same metric name into the **same
account+region**, the dimension is the only thing separating their
series; dropping it blends both environments into one metric and quietly
breaks per-environment alarms.

Losing `default_value` means no zero-fill for periods with no matching
log events. Compensate in the consumer, not the filter:

- Alarms: set `treat_missing_data` explicitly (`notBreaching` for
  "no rejections = fine", `breaching` for heartbeat-style metrics).
- Dashboards/queries: `FILL(m1, 0)` in metric math where a continuous
  series is needed.

## Review heuristic

Grep any diff that touches metric filters:

```bash
grep -rn 'default_value' --include='*.tf' | grep -B2 -A2 'dimensions'
```

Both present in one `metric_transformation` = guaranteed apply failure,
regardless of what validate and plan say.

## Caveats

- This is an API constraint, not a provider bug that will age out of a
  pinned version - though a future provider release may add the
  `ConflictsWith`; absence verified on 6.56.0.
- `aws logs describe-metric-filters` over an account showed existing
  filters with dimensions-only and default-value-only, never both -
  consistent with the API refusing the combination, useful as a quick
  sanity sweep in an unfamiliar account.
- The same passes-plan-fails-apply shape applies to other API-side-only
  constraints; when a reviewer asks "will AWS accept this?", the scratch
  probe pattern above generalizes.
