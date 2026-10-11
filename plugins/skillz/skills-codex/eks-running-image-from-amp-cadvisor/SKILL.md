---
name: eks-running-image-from-amp-cadvisor
description: |
  Read which container image an EKS workload is actually running, per cluster
  and region, with no Kubernetes API or RBAC access, by querying Amazon Managed
  Service for Prometheus (AMP) for cAdvisor's `container_start_time_seconds`,
  whose series carry an `image` label. Use when: (1) a monitor, audit, batch
  task (Airflow/MWAA, Lambda, CI) must know what image prod EKS runs, but its
  IAM role has no EKS access entry or kubeconfig and granting one means a
  cluster-side change; (2) a deploy-freshness or drift check is reading a
  stale proxy instead of the pods - e.g. an ECS task definition that
  skip_destroy keeps ACTIVE after an ECS-to-EKS migration, so its
  registeredAt freezes and the check measures a fleet nothing runs;
  (3) the app's own CloudWatch metrics carry no version dimension; (4) you
  need the image across several regions in one pass. Covers the PromQL
  filter (drop the pod-level cgroup and pause-sandbox rows), SigV4-signing
  the AMP query with botocore + urllib (no new dependency), finding the
  workspace by alias (ListWorkspaces' alias filter is a PREFIX match),
  dating each image by ECR imagePushedAt in its own regional registry, the
  IAM grant (aps:QueryMetrics is resource-scoped, aps:ListWorkspaces is "*"
  only), and why zero series must read as UNMEASURABLE, never as fresh.
author: Claude Code
version: 1.0.0
date: 2026-09-30
---

# Read the image an EKS workload runs, from AMP cAdvisor metrics

## Problem

You need "which image is prod running, and how old is it" from a process that
cannot talk to the cluster: no `eks:DescribeCluster`, no access entry, no RBAC.
Getting that access means an access-entry or RBAC change on the prod clusters,
plus network reach to their API endpoints. The usual shortcuts read something
other than the pods:

- An ECS task definition's `registeredAt`. After a migration to EKS,
  `skip_destroy` keeps the last revision ACTIVE forever, so the age keeps
  growing whatever EKS runs. The check fires false alarms on its schedule,
  and a genuinely stale EKS image stays invisible.
- A tfvars version, a git tag, or "what CI last pushed". A Deployment can be
  rolled outside terraform, and a rollout can fail after the version was
  recorded.

If the cluster ships cAdvisor to AMP (the AMP managed scraper's `cadvisor`
node job, or any Prometheus scraping kubelet `/metrics/cadvisor`), every
running container already reports its image.

## Context / Trigger Conditions

- The caller's IAM role simulates `implicitDeny` for `eks:DescribeCluster`,
  or has no access entry on the cluster.
- `container_start_time_seconds` is kept by the scrape config. It is commonly
  on the keep-list, because it is also the restart signal.
- CloudWatch has no image or version dimension for the service. Check with
  `list-metrics --namespace <ns> --recently-active PT3H` and collect every
  dimension name.

## Solution

1. **Confirm the signal and see its shape.** Run
   `count by (container, image) (container_start_time_seconds{namespace="<ns>"})`.
   Expect three kinds of row:
   - `{container="<app>", image="<acct>.dkr.ecr.<region>.amazonaws.com/<repo>:<tag>"}`
     for each app container. This is the one you want.
   - `{}` (no container, no image): the pod-level cgroup series.
   - `{image=".../eks/pause:<v>"}` with no container: the pause sandbox.

   Filter with `container!=""`. Naming the Deployments' containers is better,
   `container=~"<app>|<app>-canary"`, so a debug pod or Job in the namespace
   cannot contribute a foreign image.

2. **Find the workspace by alias, exactly.** `amp.list_workspaces(alias=...)`
   filters by PREFIX, so `...-prod` also matches `...-prod-2`. Exact-match
   the alias and require exactly one hit:

   ```python
   ws = session.client("amp", region_name=region).list_workspaces(alias=alias)["workspaces"]
   ids = [w["workspaceId"] for w in ws if w["alias"] == alias]
   if len(ids) != 1:
       raise LookupError(f"expected 1 AMP workspace aliased {alias} in {region}, found {len(ids)}")
   ```

3. **Sign and send the query with the libraries you already have:**

   ```python
   import json, urllib.parse, urllib.request
   from botocore.auth import SigV4Auth
   from botocore.awsrequest import AWSRequest

   url = f"https://aps-workspaces.{region}.amazonaws.com/workspaces/{ids[0]}/api/v1/query"
   body = urllib.parse.urlencode({"query": promql})
   signed = AWSRequest(method="POST", url=url, data=body,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
   SigV4Auth(session.get_credentials().get_frozen_credentials(), "aps", region).add_auth(signed)
   req = urllib.request.Request(url, data=body.encode(), headers=dict(signed.headers), method="POST")
   with urllib.request.urlopen(req, timeout=30) as resp:
       payload = json.load(resp)
   if payload.get("status") != "success":
       raise RuntimeError(f"AMP query failed in {region}: {payload}")
   rows = payload["data"]["result"]
   ```

   The SigV4 service name is `aps`. `Content-Length` does not need signing:
   `SigV4Auth` signs only the headers present when it runs, and urllib adds
   `Content-Length` afterwards without touching a signed header.
   `session` is any boto3 Session. In Airflow that is
   `AwsBaseHook(aws_conn_id=...).get_session()`.

4. **Date each image in its own registry.** Parse the host
   (`<acct>.dkr.ecr.<region>.amazonaws.com`), so each regional copy is dated
   where it lives:

   ```python
   registry, _, repo_tag = image.partition("/")
   repo, _, tag = repo_tag.rpartition(":")
   ecr = session.client("ecr", region_name=registry.split(".")[3])
   pushed = ecr.describe_images(repositoryName=repo,
                                imageIds=[{"imageTag": tag}])["imageDetails"][0]["imagePushedAt"]
   ```

5. **Aggregate conservatively.** The service's age is the OLDEST running image
   across all regions and tiers (main plus canary). Any of the following makes
   the whole service **unmeasurable**, surfaced loudly (a separate 0/1 gauge
   plus an alert line):
   - a region with zero series,
   - an image that cannot be parsed or dated,
   - any AMP or ECR error.

   Never compute an age from the regions that happened to answer. An empty
   region reported as "the other region's age" reads as fresh, which is the
   exact failure a freshness monitor exists to catch.

6. **IAM.** For the caller:

   ```hcl
   statement {                     # the /api/v1/query call; resource-scoped
     actions   = ["aps:QueryMetrics"]
     resources = ["arn:aws:aps:*:<account-id>:workspace/*"]
   }
   statement {                     # finding the workspace by alias; no resource-level form
     actions   = ["aps:ListWorkspaces"]
     resources = ["*"]
   }
   ```

   Add `ecr:DescribeImages` if the role lacks it. From private subnets, the
   caller also needs egress to `aps-workspaces.<region>.amazonaws.com`, through
   NAT or an `aps-workspaces` interface endpoint.

## Verification

- **Compare with the cluster once**, using operator credentials:
  `kubectl -n <ns> get deploy -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}'`
  in each region. The AMP images must match. Seen in practice:
  4 main + 1 canary pods in one region and 3 + 1 in the other, all matching.
- **Prove the absent path, not just the happy path.** Query a selector that
  matches nothing. AMP returns `status: success` with `data.result: []`: zero
  series, which is not a zero value. Your code must turn that into
  unmeasurable. Assert it in a unit test with an injected query function, and
  mutation-check it: removing the empty-region guard, or taking `min` instead
  of `max`, must turn the test red.
- **Verify the grant against the real resource.** `simulate-principal-policy
  --resource-arns '*'` (and the default with no `--resource-arns`) reports
  `implicitDeny` for `aps:QueryMetrics` even when the grant is applied,
  because the grant is scoped to workspace ARNs. Simulate against
  `arn:aws:aps:<region>:<account-id>:workspace/<id>` before concluding the
  grant failed.

## Example

A daily deploy-freshness DAG measured an EKS service by the `registeredAt` of
its old ECS task definition, kept ACTIVE by `skip_destroy` after the ECS
services were torn down. The DAG was moved to the recipe above: per region,
`count by (image) (container_start_time_seconds{namespace="<ns>",
container=~"<app>|<app>-canary"})` against that region's AMP workspace, then
ECR `imagePushedAt`. The first run logged the same tag in both regions, 13.4
days since push. That replaced a frozen 12.7-day reading that would have
crossed the 45-day nudge threshold on its own, whatever EKS was running. The
change needed one IAM statement pair on the caller and no cluster-side change.

## Notes

- **Image age is not deploy age.** Push time measures how old the running
  code is. A redeploy of an old image does not reset it, and a deploy of a
  fresh image resets it even when the rollout was late. Say which one your
  threshold means.
- **Lookback.** An instant query sees series with a sample in the last 5
  minutes. A scrape outage longer than that yields zero series, which is
  unmeasurable (correct). `last_over_time(...[15m])` survives short gaps, but
  keeps recently terminated pods, so the old image lingers for about 15 minutes
  after a rollout.
- **ECR retention.** If lifecycle policy expired the running tag,
  `describe_images` raises `ImageNotFoundException`, and the service goes
  unmeasurable exactly when it is most stale. Check the repository's lifecycle
  rules, e.g. "keep the last N images". Immutable tags plus a generous N keep
  old tags datable.
- **Digest references.** An image written as `repo@sha256:...` needs
  `imageIds=[{"imageDigest": ...}]`. The tag parse above only handles
  `repo:tag`.
- **Meshed pods.** A sidecar (e.g. `istio-proxy`) is a separate container
  with its own image. Name the app containers in the selector, rather than
  taking every container in the namespace.

## References

- [AMP ListWorkspaces API](https://docs.aws.amazon.com/prometheus/latest/APIReference/API_ListWorkspaces.html):
  `alias` filters to workspaces whose names start with the value.
- [Actions, resources, and condition keys for Amazon Managed Service for Prometheus](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amp.html):
  `QueryMetrics` requires the `workspace` resource type.
- [AMP query APIs](https://docs.aws.amazon.com/prometheus/latest/userguide/AMP-onboard-query-APIs.html)
- [cAdvisor Prometheus metrics](https://github.com/google/cadvisor/blob/master/docs/storage/prometheus.md)

## Related

- `metrics-zero-provenance-audit` - the same discipline one level up:
  before believing a zero (or an empty result), establish whether the
  source could have reported anything at all.
