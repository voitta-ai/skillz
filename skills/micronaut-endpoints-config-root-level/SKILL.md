---
name: micronaut-endpoints-config-root-level
description: |
  A Micronaut management endpoint (`/prometheus`, `/health`, `/metrics`, `/info`,
  `/loggers`) returns 401 Unauthorized even though the application has no
  security dependency and you set `sensitive: false`. Use when: (1) you added
  `micronaut-management` plus a registry such as
  `micronaut-micrometer-registry-prometheus` and the scrape endpoint answers 401,
  (2) a Prometheus/AMP collector reports the target down or `up == 0` and a
  manual `curl` from inside the pod also returns 401, (3) `endpoints.*` settings
  appear to be ignored entirely — enabling, disabling or exposing an endpoint has
  no effect, (4) you are copying endpoint config next to `micronaut.metrics.*`
  because that is where the metrics settings live. Root cause: Micronaut reads
  `endpoints.*` from the YAML DOCUMENT ROOT, while `micronaut.metrics.*` is
  nested under `micronaut:` — so endpoint config placed under `micronaut:` binds
  to nothing, silently, and the endpoint keeps its DEFAULT sensitivity. There is
  no warning, no startup error and no unknown-property complaint.
author: Claude Code
version: 1.0.0
date: 2026-09-15
---

# Micronaut `endpoints.*` is root-level; nested under `micronaut:` it binds to nothing

## Problem

You add a management endpoint — most often the Prometheus scrape endpoint — and
configure it to be unauthenticated:

```yaml
micronaut:
  metrics:
    enabled: true
    export:
      prometheus:
        enabled: true
  endpoints:          # <-- WRONG LEVEL
    prometheus:
      enabled: true
      sensitive: false
```

The application starts cleanly. Nothing warns. And the endpoint answers:

```
$ curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/prometheus
401
```

401 with **no security library on the classpath** is the tell. There is no
authentication to fail; the endpoint is refusing because it still considers
itself *sensitive*, which is the framework default for management endpoints.
Your `sensitive: false` was never read.

## Context / Trigger conditions

- `micronaut-management` is on the classpath (directly, or dragged in by a
  micrometer registry starter) and an endpoint returns 401.
- `grep -rn "micronaut-security" build.gradle pom.xml` finds nothing — so no
  authentication mechanism exists that *could* have produced a 401.
- Changes to `endpoints.*` have no effect at all: disabling an endpoint leaves
  it reachable, enabling one leaves it 404.
- A metrics collector reports the target as down. Because the scrape failure is
  per-target, the symptom is a *missing* fleet on a dashboard rather than an
  error anywhere.
- Especially likely if the endpoint config was written next to
  `micronaut.metrics.export.*`, which is genuinely nested under `micronaut:`.

## Solution

Move the block to the document root. `endpoints` is a sibling of `micronaut`,
not a child:

```yaml
micronaut:
  metrics:            # stays nested — this one IS under micronaut
    enabled: true
    export:
      prometheus:
        enabled: true
        step: PT1M

endpoints:            # root level
  all:
    enabled: false    # keep everything else shut
  prometheus:
    enabled: true
    sensitive: false  # "no authentication required"
```

Two things worth deciding at the same time:

* **`all.enabled: false` first, then re-enable only what you need.**
  `micronaut-management` ships `env`, `beans`, `loggers`, `refresh` and friends;
  on a service that parses untrusted input, an `env` endpoint is configuration
  disclosure waiting to be found.
* **`sensitive: false` means "no authentication".** Correct for a scrape on a
  port your load balancer does not route; wrong for anything reachable from
  outside the perimeter. Check what your ingress actually forwards before
  relying on "it's internal".

## Verification

Assert the config binds, not just that the file looks right — the whole failure
mode is silent binding:

```bash
# 1. the YAML actually parses with endpoints at the root
python3 -c "import yaml;d=yaml.safe_load(open('src/main/resources/application.yml'));\
print('root keys:', list(d)); print('nested (must be None):', d['micronaut'].get('endpoints'))"

# 2. the endpoint answers
curl -s -o /dev/null -w 'http=%{http_code}\n' http://localhost:8080/prometheus   # expect 200

# 3. it actually carries series, and how many
curl -s http://localhost:8080/prometheus | grep -vc '^#'
```

Step 3 matters for a second reason: scrape configs commonly cap a target
(Prometheus `sample_limit`), and a target that exceeds the cap fails its own
scrape and reports `up == 0` — which looks exactly like the 401 you just fixed.
Knowing the series count tells the two apart.

## Example

A Micronaut 4 / Java service adding Prometheus alongside an existing CloudWatch
Micrometer registry. The endpoint block was written inside `micronaut:`, three
lines under `micronaut.metrics.export.prometheus`, which is where the registry
settings correctly live.

Result: `http=401`, from a service with no security dependency at all. The
misreading it invites is "the collector needs credentials" — so the next hour
goes into the scrape config, the service account, and the collector's IAM,
none of which are involved.

Moving the same six lines to the document root, changing nothing else:

```
http=200  bytes=35189
series lines: 335
```

## Notes

* This is a *binding* failure, not a syntax failure. `micronaut.endpoints.*` is
  a perfectly valid YAML path that no `@ConfigurationProperties` claims, and
  Micronaut does not reject unknown configuration keys, so nothing complains at
  startup.
* The same root-vs-nested split applies to other root-level Micronaut
  configuration (`endpoints`, `netty`), which is why "it's a Micronaut setting,
  so it goes under `micronaut:`" is a reasonable-sounding rule that is wrong.
* If the endpoint is served but your metrics are missing, the cause is
  different and usually build-time: Micronaut AOT's `optimizeServiceLoading`
  prunes registries discovered at runtime, so the app runs fine and publishes
  nothing.

## References

- [Micronaut: Management Endpoints](https://docs.micronaut.io/latest/guide/#management)
- [Micronaut Micrometer: Prometheus registry](https://micronaut-projects.github.io/micronaut-micrometer/latest/guide/#prometheus)
