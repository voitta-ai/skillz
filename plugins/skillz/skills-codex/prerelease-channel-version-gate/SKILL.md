---
name: prerelease-channel-version-gate
description: |
  Add pre-release (beta, rc) builds to a release workflow that reads its
  version from one file, gates PRs on a version bump, and publishes on push
  to the default branch. Use when: (1) you want a beta build of a PR branch
  without merging it and without the beta becoming everyone's "Latest"
  download, (2) a version gate built on `sort -V` would reject the final
  release after a beta (it ranks 0.2.0 below 0.2.0b1 and below 0.2.0-beta),
  (3) a briefcase (BeeWare) app ships an installer named 0.2.0b0 while the
  tag and Info.plist say 0.2.0-beta, (4) a release job refuses
  non-default-branch refs and you need an exception for pre-releases only,
  (5) you are choosing between "0.2.0-beta", "0.2.0b1" and semver
  pre-release spellings. Covers a PEP 440 gate with packaging.Version plus a
  canonical-spelling check, `gh release create --prerelease=<bool>`, and
  dispatching a pre-release from a branch.
author: Claude Code
version: 1.0.0
date: 2026-09-30
---

# Pre-release channel for a version-gated release workflow

## Problem

A common release setup works like this:
- the version lives in one file (pyproject.toml, plugin.json, package.json);
- a PR job fails unless the version advanced;
- a push to the default branch tags `v<version>` and publishes a release.

Adding a beta channel to it breaks three things at once, all silently.

1. **`sort -V` misorders pre-releases.** It ranks `0.2.0` *below* both
   `0.2.0b1` and `0.2.0-beta`, because a string that ends sorts before one
   that continues. Take a gate written as "the old version sorts first". It
   accepts 0.1.16 -> 0.2.0b1, then rejects 0.2.0b1 -> 0.2.0, so the final
   release after a beta can never pass. Measured: GNU coreutils 9.4
   (`ubuntu:24.04`, the GitHub runner family) and Apple's sort 2.3 agree.
2. **Tools normalize the version; the workflow does not.** briefcase parses
   the version with `packaging.version.Version` and names the installer
   `{formal_name}-{app.version}.dmg`, so `0.2.0-beta` produces
   `App-0.2.0b0.dmg`. A workflow that tags from the raw string publishes
   `v0.2.0-beta`. A build script that stamps Info.plist from the raw string
   writes `0.2.0-beta`. One version ends up with three spellings.
3. **The beta becomes "Latest".** Without `--prerelease`, `gh release
   create` marks the newest release as latest. Every `releases/latest` link
   (README, install scripts) then hands out the beta.

There is a fourth obstacle: the usual "release only from master" guard
blocks the one thing a beta is for, which is testing a signed build of an
unmerged PR.

## Context / Trigger Conditions

- Someone asks for "a beta build of this PR", "bump to X-beta" or "an rc".
- A PR gate does `printf '%s\n%s\n' "$old" "$new" | sort -V | head -1`.
- A briefcase app's installer name ends in `b0` while its tag ends in `-beta`.
- `releases/latest` suddenly points at a beta.

## Solution

### 1. Spell versions in canonical PEP 440 (`0.2.0b1`, `0.2.0rc1`)

This is the only spelling that every layer agrees on: packaging, briefcase,
pip, the tag and Info.plist. In a Python project, enforce
`str(Version(v)) == v`. In a semver ecosystem such as npm, use `1.2.0-beta.1`
with a semver comparator instead. Either way, compare versions with the
ecosystem's own library, never with `sort -V`.

### 2. Gate with the real comparator, and enforce canonical spelling

```yaml
  version-bumped:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Version must advance
        env:
          BASE: ${{ github.base_ref }}
        run: |
          set -euo pipefail
          pip install -q packaging
          git fetch --no-tags --depth=1 origin "$BASE"
          old=$(git show "FETCH_HEAD:$VERSION_FILE" | grep -m1 -E '^version = ' | sed -E 's/^version = "([^"]+)"/\1/')
          new=$(grep -m1 -E '^version = ' "$VERSION_FILE" | sed -E 's/^version = "([^"]+)"/\1/')
          python - "$old" "$new" <<'EOF'
          import sys
          from packaging.version import InvalidVersion, Version

          def fail(msg):
              print(f"::error::{msg}")
              sys.exit(1)

          old, new = sys.argv[1], sys.argv[2]
          try:
              parsed = Version(new)
          except InvalidVersion:
              fail(f"{new} is not a PEP 440 version.")
          if str(parsed) != new:
              fail(f"Spell the version {parsed}, not {new}.")
          if parsed <= Version(old):
              fail(f"{new} does not advance past {old}.")
          print(f"{old} -> {new}")
          EOF
```

`setup-python` provides a Python that `pip install` can write to. Ubuntu
24.04's system Python is marked externally managed (PEP 668).

### 3. Publish pre-releases as GitHub prereleases

```yaml
      - name: Resolve version and tag
        id: ver
        run: |
          set -euo pipefail
          version=$(grep -m1 -E '^version = ' "$VERSION_FILE" | sed -E 's/^version = "([^"]+)"/\1/')
          echo "version=$version" >> "$GITHUB_OUTPUT"
          echo "tag=v$version" >> "$GITHUB_OUTPUT"
          if [[ "$version" =~ (a|b|rc)[0-9]+$ ]]; then
            echo "prerelease=true" >> "$GITHUB_OUTPUT"
          else
            echo "prerelease=false" >> "$GITHUB_OUTPUT"
          fi

      # ... build ...

          gh release create "$TAG" --generate-notes --target "$GITHUB_SHA" \
            --prerelease="${{ steps.ver.outputs.prerelease }}" "$ASSET"
```

`--prerelease` is a boolean flag, so `--prerelease=false` is valid and one
code path serves both cases. GitHub never marks a prerelease as "Latest".

### 4. Let only pre-releases run from a branch

Resolve the version **before** the ref guard, then exempt pre-releases from
it:

```yaml
      - name: Restrict final releases to master
        run: |
          if [ "${{ github.ref }}" != "refs/heads/master" ] && [ "${{ steps.ver.outputs.prerelease }}" != "true" ]; then
            echo "::error::Only pre-release versions may be released from ${{ github.ref }}."
            exit 1
          fi
```

To build a beta from a PR branch without merging it, run
`gh workflow run release.yml --ref <branch>`.
- `workflow_dispatch` runs the workflow file as it exists on that ref, so the
  guard change works before it merges. The workflow must already exist on the
  default branch with a `workflow_dispatch` trigger.
- The tag lands on the branch commit.
- Each new beta needs a new `bN`. If a tag already has its asset, the job
  skips.

## Verification

- Before pushing, run the gate's Python against the cases that matter:

  | Old -> new | Expected |
  |---|---|
  | `0.1.16 -> 0.2.0b1` | pass |
  | `0.2.0b1 -> 0.2.0b2` | pass |
  | `0.2.0b1 -> 0.2.0` | pass |
  | `0.2.0 -> 0.2.0b1` | fail |
  | `0.1.16 -> 0.2.0-beta` | fail: "Spell the version 0.2.0b0" |
  | `0.1.16 -> banana` | fail |

- After the dispatch, run
  `gh release view vX --json isPrerelease,targetCommitish,assets`. Check for
  `isPrerelease: true`, the branch SHA, and an asset named with the same
  spelling as the tag.
- Then run
  `curl -s https://api.github.com/repos/<owner>/<repo>/releases/latest | jq -r .tag_name`.
  It must still return the last final version. Check that field: a green run
  does not tell you which release GitHub now calls "Latest".

## Example

Worked case: a briefcase macOS app with a workflow that releases a signed,
notarized DMG (PR gate plus push-to-master release). One PR:
1. bumped 0.1.16 -> 0.2.0b1;
2. changed the gate and the guard as above;
3. was dispatched from its branch.

The run published prerelease `v0.2.0b1` with `App-0.2.0b1.dmg` at the branch
SHA, and `releases/latest` stayed on `v0.1.16`.

## Notes

- The bash regex `(a|b|rc)[0-9]+$` covers PEP 440 a, b and rc. `.devN` is
  also a PEP 440 pre-release; add it if you publish dev builds.
- `[[ =~ ]]` works in macOS's bash 3.2. Avoid expanding an empty array under
  `set -u` there: bash older than 4.4 calls it unbound. That is one more
  reason to prefer `--prerelease=<bool>` over a conditional flag array.
- Related: `claude-code-plugin-release-automation` describes the two-job
  workflow this extends. Its `sort -V` gate is exactly the one that breaks
  once a pre-release is involved.
