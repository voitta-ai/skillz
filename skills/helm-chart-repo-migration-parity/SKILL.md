---
name: helm-chart-repo-migration-parity
description: |
  Prove that a new Helm chart repository serves the same chart bytes your
  releases already run, even when the old repository is unreachable, and
  predict whether switching to it rolls any workload. Use when: (1) a vendor
  moves or blocks its chart host and installs or upgrades fail with
  `failed to fetch https://<old-host>/.../index.yaml : 403 Forbidden` (Istio
  left storage.googleapis.com for blob.istio.io in 2026, with "scream test"
  blackouts first); (2) a reviewer asks for checksum parity between the old
  and new repos while the old one is down; (3) you change only
  `helm_release.repository` (Terraform) or a `helm repo add` URL and need to
  know whether pods restart. Decodes the deployed release secret and
  byte-compares the stored chart with the new repo's tarball.
author: Claude Code
version: 1.0.0
date: 2026-10-13
source: https://github.com/voitta-ai/skillz
source_file: skills/helm-chart-repo-migration-parity/SKILL.md
---

# Helm chart repository migration: prove parity against what is deployed

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/helm-chart-repo-migration-parity/SKILL.md`). Updates go through the
> repo's worktree + PR workflow — open an issue, branch, PR.

## Problem

A chart host moves: a vendor retires a bucket, a mirror changes, charts move to
OCI. The obvious proof is to download the same chart version from the old and
the new repository and compare checksums. It fails exactly when you need it,
because the old host is already blocked or gone. That is often why you are
switching in the first place: the vendor blocks the old host for test windows
before it removes it, and every chart fetch fails during those windows.

So the question "does the new repo serve the same chart?" needs a reference
that does not depend on the old host. You already have one: **Helm 3 stores the
chart it installed inside every release record.** The deployed revision's chart
came from the old repository, so comparing it byte for byte with the new
repository's tarball proves parity without ever reaching the old host.

## Context / Trigger Conditions

- An install, upgrade, `terraform plan/apply` or CI job fails at chart fetch:
  `failed to fetch https://<old-host>/charts/index.yaml : 403 Forbidden` (or 404),
  before anything changes in the cluster.
- A vendor announcement names a new chart home.
- A review finding reads like "unverified repository; may serve different
  artifacts; require checksum parity before merge".
- You want to know in advance whether a repository-only change restarts pods.

## Solution

### 1. Take the new URL from the vendor's own announcement

Use the vendor's blog post, release notes or docs, not a third-party mirror.

### 2. Check the new index

```bash
NEW=https://<new-host>/<path>/charts
curl -sSL "$NEW/index.yaml" -o index.yaml          # -L: hosts often redirect
python3 -I - index.yaml <<'EOF'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
for chart, version in [("<chart>", "<version>")]:
    for e in d["entries"].get(chart, []):
        if e["version"] == version:
            print(chart, version, e.get("digest"), e.get("urls"))
EOF
```

- The version you run must be listed.
- **The entry's `urls` must point at the new host**, or be relative. An index
  copied verbatim from the old host still points at it, so Helm would read the
  new index and then fetch the tarball from the dead host.
- Redirects are fine. Helm's Go HTTP client follows 301, 302, 307 and 308.
  Check where they land with `curl -sS -o /dev/null -D - <url>`.
- Download each tarball and check that its `sha256` equals the entry's `digest`.

### 3. Compare with the deployed release

The release record is a Secret named `sh.helm.release.v1.<release>.v<revision>`,
with labels `owner=helm`, `name=<release>`, `status=deployed|superseded` and
`version=<revision>`. Its `data.release` is base64 twice (once by Helm, once by
the Kubernetes API) around gzip'd JSON. Pipe it straight into the comparison
script, without saving it: it contains the rendered manifests and the release's
user-supplied values.

```bash
tar -xzf <chart>-<version>.tgz -C ./extracted
kubectl -n <ns> get secret -l owner=helm,name=<release>,status=deployed \
    -o jsonpath='{.items[0].data.release}' | base64 -d | base64 -d | gunzip \
  | python3 -I scripts/helm-release-chart-diff.py ./extracted/<chart>
```

The script compares:

- every template and file;
- `values.schema.json`, which the release keeps in `chart.schema`, not in `files`;
- the default `values.yaml`, which the release keeps in `chart.values`;
- `Chart.yaml` name, version and appVersion.

It ends with `RESULT: IDENTICAL` (exit 0), `DIFFERENT` (exit 1) or `INCOMPLETE`
(exit 2). INCOMPLETE means a part could not be compared, for example because
PyYAML is missing, and it names that part on a `COULD NOT compare` line. It
never reports IDENTICAL in that case.

If you have already switched and upgraded, the `deployed` revision came from the
new repository and proves nothing. Select the newest revision that the old
repository installed instead: `-l owner=helm,name=<release>,version=<N>`. Helm
keeps the older revisions as `status=superseded`, up to the history limit.

### 4. Check the default images

Vendors often move images at the same time as charts. Read the image
registry/hub and tag defaults in the new chart's `values.yaml` (step 3 already
proves they equal the old defaults). If your own values do not pin them, a
changed default would re-point every image on the next upgrade.

### 5. Predict the rollout

With an identical chart and unchanged values, `helm upgrade` renders identical
manifests, so the only change is a new release revision. The exception is a
chart whose templates use `.Release.Revision`, `lookup` or random functions;
grep the extracted templates for them. In Terraform's helm
provider, a change to `repository` alone plans as an in-place update of the
`helm_release`, not a replacement. Changes that arrive in the same apply still
roll whatever they touch, so read the plan's `values` diff separately.

## Verification

- `RESULT: IDENTICAL` for every release you switch.
- The plan shows `repository` as the only changed input (besides computed
  `metadata`) on releases with no other pending change.
- After the apply, the workloads of a repository-only release have unchanged
  `metadata.generation` and pod-template-hash.

## Example

Istio 1.29.2, October 2026:

- **The failure.** `https://istio-release.storage.googleapis.com/charts`
  answered 403 during Istio's second scream test (2026-10-13, 15:00-18:00 UTC).
  Terraform failed at `helm_release.istiod: Modifying...` with
  `failed to fetch .../charts/index.yaml : 403 Forbidden`, and the cluster was
  unchanged.
- **The new index.** `https://blob.istio.io/istio-release/charts` answers 308
  to `istio-release.r2.istio.io`. Its index lists `base`, `istiod` and `gateway`
  1.29.2 with URLs on `blob.istio.io`, and each tarball's sha256 equals its
  index digest.
- **The comparison.** The releases installed from the old repository all came
  back `RESULT: IDENTICAL`:
  - `istio-base` rev 1: 23 files
  - `istiod` rev 6: 51 files
  - `istio-ingressgateway` rev 2: 26 files plus the schema
- **The images.** The new `istiod` chart defaults to `docker.io/istio`, tag
  1.29.2, the same images that were running.
- **The plan.** On `istio-base`, the only change was `repository`.
- **The review.** This evidence refuted an adversarial reviewer's high-severity
  "unverified repository" finding on the change.

## Notes

- **Subcharts** under `charts/` are not serialized into the release record:
  Helm's chart dependencies are not part of its JSON form. The script skips
  them. Cover them with the tarball digest, or render both versions with
  `helm template` and diff the output.
- **Lock files.** `Chart.lock` and `requirements.lock` sit in `chart.lock`, not
  in `files`, and the script does not compare them.
- **RBAC and sensitivity.** Reading release secrets needs `get secrets` in the
  release namespace. The decoded JSON holds rendered manifests, including any
  Secret the chart renders from your values, so treat it like a Secret.
- **A render-level diff is the noisier alternative.** Compare `helm get manifest`
  with `helm template ... -f <(helm get values <release>)`. `.Release.Revision`,
  `lookup`, capability checks and random or generated values make that diff
  noisy. The byte-level chart comparison is exact.
- **Scream tests come in rounds.** A vendor that blocks the old host for
  windows before removing it will do so more than once. Switch before the next
  window, not after the final removal date.

## References

- Istio, "ACTION REQUIRED FOR GOOGLE CONTAINER REGISTRY USERS, scream tests,
  and our move to AWS" (2026-08-21):
  https://istio.io/latest/blog/2026/retirement-of-gcp/
- Helm storage backends (release records are Secrets by default):
  https://helm.sh/docs/topics/advanced/#storage-backends
