---
name: github-actions-release-step-dry-run
description: |
  Run one `run:` step of a GitHub Actions job that is skipped everywhere except on a release (or on the default branch) on a real runner, before any release exists. A temporary push-triggered workflow takes the step's own text out of the real workflow file with yq and runs it against a fake CLI that records its arguments. Use when:
  (1) you added or changed a step in a job gated by `if:` or `needs:` on a release, a tag or the default branch, and the pull request shows that job as skipped;
  (2) the step publishes (`gh release upload`, `docker push`, `npm publish`) and a failure in the first real run would cost another release;
  (3) you must know what the step would upload, and that the runner has the tools it calls, without uploading anything.
author: Claude Code
version: 1.0.0
date: 2026-11-25
source: https://github.com/voitta-ai/skillz
source_file: skills/github-actions-release-step-dry-run/SKILL.md
---

# Dry-run one step of a release-gated GitHub Actions job

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/github-actions-release-step-dry-run/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

## Problem

A job that publishes runs only when a release is made, for example with
`if: needs.release.outputs.released == 'true'`. On a pull request GitHub lists
that job as skipped. So the first run of a new or changed step is the release
itself. If the step fails there, the release is out, its artifact is missing,
and the fix needs another release.

A copy of the step in a test workflow does not prove much: the copy and the
real step drift apart, and the test passes on text that the release never
runs.

## Context / Trigger Conditions

- The step is a `run:` script in a job that the pull request run skips.
- The step calls a CLI that publishes: `gh release upload`, `docker push`,
  `docker buildx imagetools create`, `npm publish`.
- You cannot, or do not want to, cut a real release to try it.

This does not fit a job that calls a reusable workflow (`uses:` at job level):
such a job has no steps to take out. Run the reusable workflow itself with its
publishing input off; `github-actions-multiarch-image-native-runners`, step 3,
shows that.

## Solution

### 1. Make the step extractable

The test runs the step's text exactly as the workflow file has it. So the text
must not need GitHub to fill anything in.

- Give the step a `name:`. The test selects the step by name.
- Keep `${{ ... }}` out of the `run:` text. GitHub replaces those expressions
  before the shell starts; a text taken out of the file still holds them. Pass
  the values through the step's `env:` and read `$NAME` in the script.

```yaml
      - name: Build the package, zip it and attach it to the release
        env:
          GH_TOKEN: ${{ github.token }}
          VERSION: ${{ needs.release.outputs.version }}
        run: |
          set -euo pipefail
          ./build.sh
          asset="$PWD/package-$VERSION.zip"
          (cd "$RUNNER_TEMP" && zip -qr "$asset" package)
          gh release upload "v$VERSION" "$asset"
```

### 2. Write a fake of the CLI that publishes

The fake records how it was called and fails when the call could not have
worked. For an upload, that means the file must exist:

```bash
#!/bin/bash
# Fake gh: record the call, and fail unless the last argument is an existing file.
echo "gh $*" >> "$GH_LOG"
for last in "$@"; do :; done
test -f "$last" || { echo "fake gh: no such file: $last" >&2; exit 1; }
```

Put it in a directory that comes first on `PATH`, under the real tool's name.

The fake replaces one tool, and only where the step calls it by name. A call
by full path (`/usr/bin/gh`) goes around it. Read the step for every command
that changes something outside the machine (`docker push`, `npm publish`, a
cloud CLI) and write a fake for each.

### 3. Run the step on your machine

Take the text out with any YAML parser and run it from the repository root.
Save the lines below as a script; do not paste them into your shell, because
they change `PATH` and exit. This example needs PyYAML:

```bash
#!/bin/bash
# Runs one step of the workflow file with a fake gh. Uploads nothing.
set -euo pipefail
out=$(mktemp -d)
mkdir "$out/bin" "$out/runner-temp"

# The fake of step 2, under the real tool's name.
cat > "$out/bin/gh" <<'EOF'
#!/bin/bash
echo "gh $*" >> "$GH_LOG"
for last in "$@"; do :; done
test -f "$last" || { echo "fake gh: no such file: $last" >&2; exit 1; }
EOF
chmod +x "$out/bin/gh"

python3 - .github/workflows/release.yml "<job id>" "<the step's name>" > "$out/step.sh" <<'EOF'
import sys
import yaml

path, job, name = sys.argv[1:4]
steps = yaml.safe_load(open(path))["jobs"][job]["steps"]
found = [s["run"] for s in steps if s.get("name") == name]
assert len(found) == 1, "expected exactly one step with that name"
sys.stdout.write(found[0])
EOF

export PATH="$out/bin:$PATH"
# Stop unless gh now means the fake. A fake that is missing or not executable
# would let the real, logged-in gh run the upload. The -x test is needed too:
# with no other gh on PATH, `command -v` names a file that cannot run.
if [ ! -x "$out/bin/gh" ] || [ "$(command -v gh)" != "$out/bin/gh" ]; then
  echo "gh does not resolve to the fake; the step was not run" >&2
  exit 1
fi

status=0
GH_LOG="$out/gh.log" RUNNER_TEMP="$out/runner-temp" VERSION=9.9.9 \
  bash -e "$out/step.sh" || status=$?
echo "== recorded calls =="
cat "$out/gh.log" 2>/dev/null || echo "(none)"
exit "$status"
```

- **Only the faked tool is fake.** Every other command of the step runs for
  real on your machine: it builds, writes files in the checkout and may call
  the network. Read the step before you run it.
- **A missing token does not protect you.** A real `gh` that has run
  `gh auth login` needs no token variable, and `docker` and `npm` keep stored
  logins too. What keeps the real tool out is the `command -v` check: when the
  fake is missing, misnamed or not executable, the script stops before the
  step starts. Add one such check for each tool you fake.
- The script ends with the step's exit status. The fake logs a call before it
  checks it, so a rejected call still shows in the log, and the script still
  fails.
- Set every variable of the step's `env:` that the script reads, and every
  runner variable (`RUNNER_TEMP` here). Leave token variables unset.
- Start the script as the runner does. GitHub's workflow syntax reference
  gives `bash -e {0}` for a step without a `shell:` key and
  `bash --noprofile --norc -eo pipefail {0}` for `shell: bash`. The runner log
  prints the line, for example `shell: /usr/bin/bash -e {0}`.
- `/bin/bash` on macOS is 3.2. A script that uses newer bash features fails
  there and passes on the runner.

This proves the script's logic and what it would upload. It does not prove
that the runner has the tools, or that the job's `uses:` steps work.

### 4. Run the same text on a real runner

Add one workflow file to the pull request branch. It runs on a push to that
branch only:

```yaml
# Temporary: runs one step of release.yml on a real runner with a fake gh.
# Nothing is uploaded. Remove this file before the merge.
name: tmp-step-test

on:
  push:
    branches: [<this branch>]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # ... the real job's setup steps (toolchains), copied by hand.
      # Never a login step, and nothing that reads `secrets.*` ...
      - name: Run the real step with a fake gh
        env:
          STEP_NAME: Build the package, zip it and attach it to the release
          VERSION: 9.9.9
        run: |
          set -euo pipefail
          mkdir -p "$RUNNER_TEMP/fake-bin"
          cat > "$RUNNER_TEMP/fake-bin/gh" <<'EOF'
          #!/bin/bash
          echo "gh $*" >> "$GH_LOG"
          for last in "$@"; do :; done
          test -f "$last" || { echo "fake gh: no such file: $last" >&2; exit 1; }
          EOF
          chmod +x "$RUNNER_TEMP/fake-bin/gh"
          export GH_LOG="$RUNNER_TEMP/gh.log"
          export PATH="$RUNNER_TEMP/fake-bin:$PATH"
          # Stop unless gh now means the fake. Two lines on purpose: in an
          # `A && B` list, `set -e` does not stop the script when A fails.
          test -x "$RUNNER_TEMP/fake-bin/gh"
          test "$(command -v gh)" = "$RUNNER_TEMP/fake-bin/gh"

          yq '.jobs["<job id>"].steps[] | select(.name == strenv(STEP_NAME)) | .run' \
            .github/workflows/release.yml > "$RUNNER_TEMP/step.sh"
          test -s "$RUNNER_TEMP/step.sh"
          bash -e "$RUNNER_TEMP/step.sh"

          cat "$GH_LOG"
          grep -qx "gh release upload v$VERSION $PWD/package-$VERSION.zip" "$GH_LOG"
          unzip -l "package-$VERSION.zip"
          test "$(unzip -Z1 "package-$VERSION.zip" | grep -vc '/$')" = "16"
```

Why each part is there:

- **A push trigger on this branch.** A workflow file that exists only on a
  branch runs for a push to that branch. `workflow_dispatch` would not: GitHub
  starts it only when the file is on the default branch.
- **`permissions: contents: read`, no `secrets.*`, no login step.**
  `permissions` limits `GITHUB_TOKEN` and nothing else. A run that a push to a
  branch of the repository itself starts can also use the repository's secrets
  wherever the file names them, so a login step copied from the real job (a
  registry password, a cloud key, a personal token) would give this test real
  publishing rights. Keep `secrets.*` and every login step out of the file,
  and do not add `id-token: write`, which an OIDC login needs. If the step
  cannot run without a login, fake that tool as well. The fake and its
  `command -v` check are the protection; the token limit backs them up for
  `GITHUB_TOKEN` only. (The part about secrets is from GitHub's documentation
  and was not tried in a run.)
- **`yq ... strenv(STEP_NAME)`.** The step is found by its name, and the text
  that runs is the text in the real file. This is the syntax of mikefarah's yq
  (v4), which `ubuntu-latest` had in both runs below.
- **`test -s`.** A name that matches nothing gives an empty file, and an empty
  script exits 0. Without this line a typo in the name makes the test pass.
- **The `grep -qx` and the checks on the artifact.** They let the test fail.
  Check the exact call, and what is inside the artifact, not only that the
  step ended.

Commit the file, push, and wait for the run:

```bash
gh run list --branch <this branch> --limit 5
gh run watch <run id> --exit-status
gh run view <run id> --json conclusion --jq .conclusion
```

If you pipe `gh run watch` into another command, the exit status you see is
that command's. Read the conclusion with the third line.

### 5. Remove the test, and say what it did not cover

Remove the file in the next commit (`git rm`, commit, push). No further run
starts. With a squash merge the default branch never holds the file or the two
commits. With a merge commit or a rebase merge both commits land in the
history; use a separate branch off the pull request head for the test then,
and delete that branch afterwards.

The dry run does not cover:

- the real publishing call, and whether the job's `permissions` allow it;
- any login of the real job: the test must not log in, so a wrong secret name
  or an expired credential shows only in the real run;
- the job's `needs:`, `if:` and outputs;
- the `uses:` steps: the test copies them, so they can drift.

So the first real run is still a first run. After it, check the result itself:
the asset exists, and holds what the dry run produced.

## Verification

- The run's conclusion is `success`, read with `gh run view`, and the log
  shows the recorded call and the artifact listing.
- Change the expected call in the `grep -qx` line once, or point the fake at a
  missing file: the run on the runner must fail, and the local script must
  exit non-zero. A test that cannot fail proves nothing.
- The `command -v` check of the local script was tried with a harmless
  stand-in for the real tool later on `PATH`: with the fake's `chmod` line
  left out, the script stopped before the step started. Do not try this with
  a real, logged-in tool.
- On the pull request, the release-gated job appears in the checks list as
  skipped. That shows GitHub parsed the new job, and nothing more.

## Example

A release workflow got a new job that builds a browser extension, zips it and
attaches the zip to the release.

1. On the developer's machine the step ran from the workflow file's text with
   a fake `gh`: the zip was there, and the recorded call was
   `gh release upload v<version> <path to the zip>`.
2. A temporary workflow on the pull request branch ran the same text on
   `ubuntu-latest` in 32 s. The zip held the same 16 files, and the build
   output had the same SHA-256 as on the developer's machine.
3. The file was removed and the pull request was squash-merged. The job's
   first real run took 27 s, and the uploaded asset held the same files as the
   local run.

Nine days earlier the same method tested a step that moves an image's `latest`
tag only when the release is the newest one. The fake was a `docker` that
records its arguments: one case had to make no call, and a control case had to
make the expected one. That run took about a minute and passed the first time.

## Notes

- To put the fake in front of several steps, write its directory to
  `$GITHUB_PATH` in an earlier step instead of exporting `PATH`.
- The finished run stays in the repository's Actions history after the file is
  gone, and the two commits stay in the pull request's commit list. In a
  shared or public repository, tell the owner before you push a test like
  this.
- While the file is on the branch, every push to the branch runs it again.

## References

- GitHub, "Events that trigger workflows" (`workflow_dispatch` needs the file
  on the default branch; read 2026-11-25):
  https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- GitHub, "Workflow syntax for GitHub Actions", `jobs.<job_id>.steps[*].shell`
  (the command behind each shell; read 2026-11-25):
  https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- GitHub, "Using secrets in GitHub Actions" (apart from `GITHUB_TOKEN`,
  secrets are not passed to a run that a fork triggered; read 2026-11-25):
  https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets
