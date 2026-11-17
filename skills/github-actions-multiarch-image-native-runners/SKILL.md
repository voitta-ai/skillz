---
name: github-actions-multiarch-image-native-runners
description: |
  Make a slow multi-platform (linux/amd64 + linux/arm64) container image build in GitHub Actions fast by building each platform on its own native runner with Docker's reusable workflow (docker/github-builder), then verify what was pushed. Use when:
  (1) a build job with docker/setup-qemu-action and docker/build-push-action takes tens of minutes or hours;
  (2) the buildkit log shows a step taking seconds under `[linux/amd64 ...]` and minutes under `[linux/arm64 ...]`;
  (3) you are about to hand-write a per-platform matrix with push-by-digest and a merge job;
  (4) you want to add a layer cache to such a build, and the dependencies are not pinned;
  (5) you must check a pushed multi-platform image and its signatures on ghcr, not only that the run is green.
author: Claude Code
version: 1.0.0
date: 2026-11-17
source: https://github.com/voitta-ai/skillz
source_file: skills/github-actions-multiarch-image-native-runners/SKILL.md
---

# Multi-platform image builds on native runners

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/github-actions-multiarch-image-native-runners/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

## Problem

A workflow builds one image for `linux/amd64` and `linux/arm64` on a single
amd64 runner, with `docker/setup-qemu-action` and `docker/build-push-action`.
Every `RUN` of the arm64 image is emulated. Light steps survive that. A
CPU-bound step does not: in one project, 21 release builds took 45 minutes to
2 hours 11 minutes (median 1 hour 22 minutes). After the change below, a whole
release run took five and a half to six and a half minutes.

The fix many remember is a hand-written matrix: one job per platform, push by
digest, then a merge job. Docker's documentation no longer shows that. Docker
publishes a reusable workflow, `docker/github-builder`, that builds each
platform on a native runner, creates the manifest, signs the attestations and
can keep a layer cache. The repository is from 2025, so look its inputs up
before you rely on any list of them, this one included.

## Context / Trigger Conditions

- A build job with QEMU and `platforms: linux/amd64,linux/arm64` takes tens of
  minutes or hours.
- In the job log, the same step is fast under `[linux/amd64 ...]` and slow
  under `[linux/arm64 ...]`.
- You want a layer cache or signed attestations for a multi-platform build.
- You must say that a release is good, and all you have is a green run.

This skill does not help when the native steps are slow too. Then look at the
`Dockerfile` and the cache (step 5) first.

## Solution

### 1. Find where the time goes

Download the build job's log to a file:

```bash
gh run view <run-id> --json jobs --jq '.jobs[] | "\(.databaseId) \(.name)"'
gh run view <run-id> --log --job <job-id> > build.log
# or the raw text of one job:
gh api --allow-escape-sequences repos/<owner>/<repo>/actions/jobs/<job-id>/logs > build.log
```

Seen with gh 2.101.0: when the log holds ESC bytes, `gh api .../logs`
without that flag writes nothing and exits 1 with
`the response contains terminal escape sequences; pass --allow-escape-sequences to output it anyway`.
The colored echo of a `run:` script is enough to put ESC bytes in a log. If
you discard stderr, that looks like an empty log. A log without ESC bytes
prints without the flag, and `gh run view --log --job` printed the same log
with no flag.

Buildkit prints a header for each step and, later, a `DONE` line with the same
`#N`:

```
#19 [linux/arm64 stage-1  9/13] RUN pip install ...
#19 DONE 912.4s
```

Pair the two lines by `#N` and compare the platforms. In the project above:

| Step | amd64 (native) | arm64 (emulated) | arm64 (native, after) |
|---|---|---|---|
| Build a docs search index (embeddings with onnxruntime) | 44 s | 79 to 110 min | 20 s |
| `pip install` of the backend | about 1 min | 13 to 17 min | 85 to 92 s |

Two emulated builds of the same work differed by a factor of 1.3 to 1.4 in
every step. The cause was not found, so do not read a trend into one run.

### 2. Call Docker's reusable workflow

A reusable workflow is called at job level. It replaces the whole build job:

```yaml
jobs:
  image:
    needs: release                 # the job that decides a build is due
    if: needs.release.outputs.released == 'true'
    uses: docker/github-builder/.github/workflows/build.yml@v1
    permissions:
      contents: read
      packages: write              # push to ghcr.io
      id-token: write              # the workflow signs the image's attestations
    with:
      output: image
      push: true
      platforms: linux/amd64,linux/arm64
      cache: true                  # read step 5 before you turn this on
      meta-images: ghcr.io/${{ github.repository }}
      meta-tags: type=raw,value=${{ needs.release.outputs.version }}
      meta-flavor: latest=false
    secrets:
      registry-auths: |
        - registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
```

What it does, and what follows from that:

- `distribute: true` is the default. It runs one build job per platform on a
  native GitHub-hosted runner, then a `finalize` job that creates the
  multi-platform manifest. Nothing runs under QEMU.
- Its jobs declare no `permissions`, so they get the calling job's. The
  calling job must hold what the push and the signing need.
- It builds from the Git context at the triggering ref, not from a checkout.
  A file that an earlier job or step generated is not in the build.
- The job is a `uses:`, so it has no `steps`. Whatever ran after the build
  moves to another job with `needs:` (step 4 is an example).
- `meta-tags` uses the syntax of `docker/metadata-action`.
  `meta-flavor: latest=false` stops it from adding `latest`.
- `sign: auto` is the default. It signs the attestation manifests when it
  pushes, and it needs `id-token: write`.

Check that your plan has GitHub-hosted arm64 runners for this repository.

### 3. Test it without publishing

Push a throwaway branch that carries one extra workflow, triggered by that
branch only. Use the same inputs with `push: false`, no `packages: write` and
no `registry-auths`:

```yaml
name: build-test
on:
  push:
    branches: [test/native-build]
permissions:
  contents: read
jobs:
  build:
    uses: docker/github-builder/.github/workflows/build.yml@v1
    permissions:
      contents: read
      id-token: write              # the cache entries are signed
    with:
      output: image
      push: false
      platforms: linux/amd64,linux/arm64
      cache: true
      meta-images: ghcr.io/${{ github.repository }}
      meta-tags: type=raw,value=build-test
      meta-flavor: latest=false
```

This run cannot publish: the push is off, and the job has no registry login
and no packages scope. The registry login and the signing are skipped. It
shows the native build time. To see the cache work, push a second commit with
a one-line change to the code: the steps before the change print `CACHED`.

Afterwards delete the branch and its cache entries
(`gh cache list --ref refs/heads/<branch>`, then `gh cache delete <id>`). Two
runs of a 1.1 GB image left 56 entries, 3.2 GB.

### 4. Move `latest` in a job of its own

Builds of releases that are cut close together overlap, and the one that
finishes last would take `latest`. Let only the newest version move it:

```yaml
  latest-tag:
    needs: [release, image]
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ github.token }}
      - name: Move latest to this version if it is the newest release
        env:
          IMAGE: ghcr.io/${{ github.repository }}
          VERSION: ${{ needs.release.outputs.version }}
        run: |
          set -euo pipefail
          newest=$(git ls-remote --tags --refs origin 'v*' \
            | sed 's#.*refs/tags/v##' | grep -E '^[0-9]+(\.[0-9]+)+$' | sort -V | tail -1)
          if [ "$newest" = "$VERSION" ]; then
            docker buildx imagetools create --tag "$IMAGE:latest" "$IMAGE:$VERSION"
          else
            echo "::notice::v$VERSION is not the newest final release (v$newest is); :latest is left alone."
          fi
```

`imagetools create` points `latest` at the same index, so the two tags then
have the same digest. The `grep` keeps final versions only, so a build of a
pre-release such as `1.11.0-beta` never takes `latest`.

### 5. The layer cache: order the Dockerfile, and say what the cache changes

`cache: true` keeps the layers in the GitHub Actions cache, one scope per
platform. With neither `cache-scope` nor `target` set, the scopes are
`buildkit-linux-amd64` and `buildkit-linux-arm64`: the workflow builds the
name from `cache-scope`, else `target`, else `buildkit`, and adds the
platform. The names do not contain the tag, so the releases of one branch
share them.

The cache can reuse a layer only if nothing before it changed. Install the
dependencies before you copy the code. For an editable Python install:

```dockerfile
COPY backend/pyproject.toml backend/pyproject.toml
RUN mkdir -p backend/app \
 && touch backend/app/__init__.py \
 && python -m venv backend/.venv \
 && backend/.venv/bin/pip install --no-cache-dir -e backend
COPY backend/app backend/app
```

The install runs against an empty package. It is editable, so the code that
is copied afterwards is what gets imported. Prove that with the comparison in
Verification, step 4.

**Tell the owner what the cache changes before you turn it on.** If the
dependency file sets lower bounds only and there is no lock file, a build
without a cache installs the newest versions at every release. With a cached
dependency layer, a release keeps the versions of the day that layer was
built, until the dependency file changes or GitHub removes the entry.
Measured between consecutive uncached releases of one project: five packages
moved in two days, then 41 packages moved and one was replaced in 22 hours.

Costs to know:

- The first build is slower, not faster. With an empty cache the upload of a
  1.1 GB image took 72 to 84 s per platform: that release run took 6 min 38 s,
  and the one before it, without a cache, 5 min 31 s.
- The build passes `--cache-to type=gha,ignore-error=true,...,mode=min`. A
  failed upload does not fail the build, so look at the entries
  (Verification, step 5).
- A late `RUN chown -R` over the application directory writes the whole
  virtual environment into a second layer (about 425 MB compressed per
  platform in that project). It comes after the code, so no release can reuse
  it, and every release that changes the code writes it to the cache again.
- GitHub removes cache entries that were not accessed for over 7 days, and
  the default limit is 10 GB per repository (GitHub's documentation, read
  2026-11-17). A project that releases less often than weekly gets no hit.
- Whether a build may write the cache depends on its trigger. The same
  documentation lets only `push`, `workflow_dispatch`, `repository_dispatch`,
  `delete`, `registry_package`, `page_build` and `schedule` create or
  overwrite entries in the default branch's scope. A run on the default
  branch that another event started, `workflow_run` for example, can read
  them only. With `ignore-error=true` such a build should pass and write
  nothing. That was not run here: the example builds on `push`.

### 6. Before you merge: the version check can be stale

If the release is driven by a version file and another pull request merged
while yours waited, look at the version again. When both took the same
number, your bump is gone after a rebase or a squash merge, because both
sides made the same edit. What git says depends on the shape (git 2.39.5,
tried on a synthetic repository):

| Your bump | The same bump on the default branch | `git rebase` prints |
|---|---|---|
| A commit of its own | A commit of its own | `warning: skipped previously applied commit <sha>` |
| A commit of its own | Inside a larger commit | `dropping <sha> <subject> -- patch contents already upstream` |
| Inside a larger commit | Either | Nothing. The commit keeps its subject and loses the version hunk |

A squash merge without a rebase (`git merge --squash`) also stages your
change without the version file. So do not wait for a message. Ask git:

```bash
git fetch origin
git diff --quiet origin/<default branch> -- <version file> && echo "no bump left"
```

The "version must advance" check on your pull request ran against the old
base, so it is still green. Take the next number, push, and let the check run
on the new head. A merge whose version is not new releases nothing, and the
run is still green.

Then read what the other pull request changed
(`git diff --stat <old base> origin/<default branch>`) before you trust the
tests that you ran against the old base.

## Verification

A green run says the jobs ended without an error. Check the result itself.

1. **The push.** Ask the registry. For a public package on ghcr an anonymous
   token is enough:

   ```bash
   T=$(curl -s "https://ghcr.io/token?scope=repository:<owner>/<image>:pull" | jq -r .token)
   curl -s -H "Authorization: Bearer $T" \
     -H "Accept: application/vnd.oci.image.index.v1+json" \
     "https://ghcr.io/v2/<owner>/<image>/manifests/<tag>" \
     | jq '.manifests[] | {digest, platform, annotations}'
   ```

   Expect one image manifest per platform, and one attestation manifest per
   image: platform `unknown/unknown`, annotation
   `vnd.docker.reference.type: attestation-manifest`, and
   `vnd.docker.reference.digest` naming the image it belongs to.

2. **The signatures.** Each build job logs
   `Signing attestation manifest <image>@sha256:<digest>`,
   `Attestation signature uploaded to Rekor transparency log: ...logIndex=<n>`
   and `Signature manifest verified: ...`. The log of the `finalize` job holds
   ready commands of this form:

   ```
   cosign verify --experimental-oci11 \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com \
     --certificate-identity-regexp '^https://github.com/docker/github-builder/.github/workflows/build.yml.*$' \
     <image>@sha256:<attestation digest>
   ```

   On ghcr the referrers API (`/v2/<owner>/<image>/referrers/<digest>`)
   answers 404. The signature is under the tag
   `sha256-<attestation digest hex>`: an index with one manifest whose
   `artifactType` is `application/vnd.dev.sigstore.bundle.v0.3+json`.

3. **`latest`.** Send a `HEAD` request for the manifest of `latest` and of the
   version tag, and compare the `docker-content-digest` headers.

4. **The image, on every platform.** Registry metadata and a build log show
   that an image was built, not that it starts. Pull each platform by its
   manifest digest, so that the local tag does not move:

   ```bash
   docker pull <image>@sha256:<manifest digest of the platform>
   docker run --rm --platform linux/amd64 --entrypoint uname <image>@sha256:<digest> -m
   ```

   Compare the platforms with each other and with the previous release: the
   list and SHA-256 of the application files, `pip freeze`, how the package is
   installed, owners and modes, and the image config. Then start a container
   and call its health endpoint.

   Decide first what must match. Some differences are not regressions: the
   dates of files that the build creates, random ids, and floating-point
   results that differ in the last digit between CPU types.

   On an Apple Silicon Mac the Docker VM can run amd64 containers through
   Rosetta (`ls /proc/sys/fs/binfmt_misc` in the VM lists `rosetta`). Say in
   the report that the image ran through Rosetta, not on an amd64 CPU. Start
   test containers with `--rm`, or remove them with `docker rm -f -v`: an
   image with a `VOLUME` leaves an anonymous volume otherwise.

5. **The cache.** After the first build on the default branch,
   `gh cache list --ref refs/heads/<default branch>` lists
   `buildkit-blob-...` entries and one `index-buildkit-linux-<arch>-...` entry
   per platform. The next build that changes only the code prints `CACHED`
   for the dependency step.

## Example

A FastAPI backend whose last `RUN` builds a docs search index with onnxruntime
embeddings. Its release builds took 45 minutes to 2 hours 11 minutes.

1. The log showed the index step at 44 s on amd64 and 79 to 110 minutes on
   emulated arm64.
2. A throwaway branch with `push: false` built both platforms in 6 min 11 s,
   and in 4 min 6 s after a one-line code change, with the dependency step
   `CACHED`.
3. The build job became a call to `docker/github-builder`, and `latest` moved
   to a job of its own. The next two releases took 6 min 8 s and 5 min 31 s
   for the whole run.
4. Checked on ghcr: an index with both platforms, two signed attestation
   manifests, `latest` equal to the version tag. Both platforms were pulled
   and run. The application files were byte-identical between the platforms,
   and the health endpoint answered 200 on each.
5. The owner was told that the dependency versions would stay fixed between
   changes of the dependency file. Then the dependency install moved before
   the code copy and `cache: true` was added. Another pull request had taken
   the same version number minutes before the merge; the rebase dropped the
   bump, and the next number was taken (step 6).
6. That release took 6 min 38 s with an empty cache. Both platforms had the
   same application files and the same 219 package versions as the release
   before it, and the default branch had 37 cache entries, 2.1 GB.

Not observed when this was written: a cache hit between two releases on the
default branch. The hit was seen between two runs on the test branch.

## Notes

- A release that a workflow creates with `GITHUB_TOKEN` does not trigger
  other workflows. Keep the image job in the workflow that creates the
  release, with `needs:`, and do not wait for a `release` event.
- GitHub's documentation says that a workflow run can restore cache entries
  of its own branch and of the default branch. So a test branch should read
  what a release on the default branch wrote, and not the other way round.
  That was not tested here.

## References

- Docker, "Multi-platform image with GitHub Actions":
  https://docs.docker.com/build/ci/github-actions/multi-platform/
- `docker/github-builder` (the reusable workflow and its inputs):
  https://github.com/docker/github-builder
- GitHub, "Dependency caching reference" (which branches a run can restore
  from, limits and eviction):
  https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching
