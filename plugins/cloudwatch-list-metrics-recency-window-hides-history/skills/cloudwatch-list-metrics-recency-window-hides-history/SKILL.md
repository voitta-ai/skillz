---
name: cloudwatch-list-metrics-recency-window-hides-history
description: |
  Enumerate what a CloudWatch metric has EVER reported, given that
  `list-metrics` only returns metrics with datapoints in roughly the last two
  weeks. Use when: (1) building a symbol, route, endpoint, or status-code
  inventory from `list-metrics` and treating what is absent as never having
  happened; (2) concluding a code path, error branch, or endpoint is dead
  because it does not appear in the dimension list; (3) a metric you expect is
  missing from `list-metrics` but you have not probed its history; (4) querying
  `get-metric-statistics` and getting empty datapoints for something you know
  is live. Covers the verified case of a status code with real history that
  `list-metrics` does not surface, the exact-dimension-match trap where an
  under-specified query returns empty instead of erroring, and the live-control
  pattern that tells a broken query apart from a dead code path.
author: Claude Code
version: 1.0.0
date: 2026-09-12
---

# CloudWatch list-metrics hides history

## Problem

`aws cloudwatch list-metrics` is a **recency-filtered view**, not a catalog. It
returns metrics that have had datapoints published in roughly the last two
weeks. Anything quieter than that is absent from the listing while its history
remains fully queryable.

That breaks any inventory built from it. If you enumerate a service's observed
HTTP status codes from the `status` dimension and treat the rest as never
having occurred, you are reporting on the last fourteen days and calling it all
time.

## Verified

On a Micronaut service publishing `http.server.requests.count` to CloudWatch:

| dimension set | in `list-metrics` | history via `get-metric-statistics` |
|---|---|---|
| `uri=/api/v1/config status=200` | yes | 236 days, last datapoint today |
| `uri=/api/v1/config status=503` | **no** | 1 day, last datapoint 65 days ago |

The 503 happened. It is retrievable. It is not in the listing. An inventory
built from `list-metrics` would have reported that this endpoint has only ever
returned 200.

## Do this instead

Seed the inventory from the source, not from the metric backend. Parse the
declared surface out of the code (route annotations, declared response codes,
enum values), then probe each declared item against history explicitly:

```bash
aws cloudwatch get-metric-statistics \
  --namespace "$NS" --metric-name http.server.requests.count \
  --dimensions Name=exception,Value=none Name=method,Value=GET \
               Name=status,Value=503 Name=uri,Value=/api/v1/config \
  --start-time "$(date -u -v-400d +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time   "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --period 86400 --statistics Sum --no-cli-pager
```

Empty datapoints from a **fully specified** query over a long window is
evidence. Absence from `list-metrics` is not.

Reserve `list-metrics` for discovering the dimension **schema** — which
dimension names exist, and what a complete set looks like. That is what it is
good for, and you need it for the next section.

## The second trap: dimension matching is exact

`get-metric-statistics` requires the **complete** dimension set. Pass a subset
and it returns zero datapoints with no error and no warning. That reads as a
hard zero and is indistinguishable from a dead code path.

This is easy to hit when the same metric name carries different dimensions on
different platforms. The same Micronaut metric published from ECS carried
`exception, method, status, uri`; published from EKS it carried `exception,
fleet, method, pod, status, uri`. A query written against the ECS shape returns
empty on EKS, forever, for everything.

Always take the dimension list from `list-metrics` and pass it back verbatim:

```python
for metric in paginate(cw.list_metrics(Namespace=ns, MetricName=name)):
    dims = metric["Dimensions"]          # complete set, unmodified
    cw.get_metric_statistics(Namespace=ns, MetricName=name, Dimensions=dims, ...)
```

To probe a value that does **not** appear in the listing, clone a complete set
from one that does and substitute the single dimension you are probing. Do not
hand-write the set.

## Carry a live control

The safeguard that actually fires. Alongside the metric you suspect is dead,
query one you are certain is live, **through the same code path**. If the
control reads zero, the query is broken, not the code.

This caught a false finding in practice: a probe for a suspected-dead 404
returned zero over 400 days, and the same query shape run for status 200
returned zero too. Status 200 was serving eight million requests. The query was
under-specified; without the control it would have been recorded as a finding.

## One more counting trap

A single logical symbol can have **many** dimension sets. On Kubernetes, one
route appears once per pod. Code that builds a dict keyed by route and assigns
the dimension set silently keeps the last one and counts one pod:

```python
seen[route] = metric["Dimensions"]          # wrong: drops all but one
seen.setdefault(route, []).append(metric["Dimensions"])   # right: sum across
```

Symptom is a denominator that looks plausible but is a fraction of real
traffic, which makes every ratio and confidence bound wrong without ever
looking obviously wrong.

## Checklist

- Inventory seeded from source, not from `list-metrics`
- Every `get-metric-statistics` call passes a complete dimension set
- All dimension sets per symbol summed, not just one
- A live control queried through the same path, and it reads non-zero
- Evidence window reported as the metric's first datapoint, not the probe length
