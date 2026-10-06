---
name: claude-code-plugin-release-automation
description: |
  Make a Claude Code / Codex plugin repo tag itself and publish release
  notes from its manifest version, and make the version bump non-optional.
  Use when: (1) the repo has merges piling up with no tags, no GitHub
  releases, or tags that exist but have no release attached, (2) a
  CONTRIBUTING/CLAUDE.md rule says "bump the version on every shipping
  merge" and nothing enforces it, (3) you are hand-running `git tag -a
  vX.Y.Z <squash-sha> && git push origin vX.Y.Z` after every merge,
  (4) you are about to add a CHANGELOG.md to a repo whose PR titles
  already say what changed, (5) users report `claude plugin update` says
  "up to date" while master has moved, and you want CI to catch the
  missing bump instead of users catching it months later, (6) you need the
  tag to land on the squash commit in a squash-merge repo, (7) two PRs
  merged minutes apart and the second one's release never appeared even
  though every check is green. Covers the two-job workflow (PR-side bump
  gate + push-side tag-and-release), `paths-ignore` as the docs-only
  exemption, why the gate must NOT be a required status check, idempotence
  for re-runs and the same-version concurrent-merge gap it leaves (the
  second tag-and-release run reports success while creating nothing -
  verify the tag's tree, then ship a bump-only PR), queueing several
  bumping PRs against the gate (rebase + re-bump; a green gate goes stale
  because base-branch movement does not re-trigger PR CI), and the
  multi-plugin case where per-plugin versions are separate cache keys the
  gate cannot see. Pairs with claude-code-plugin-update-flow, which
  explains why the version is load-bearing in the first place.
author: Claude Code
version: 1.3.0
date: 2026-08-27
---

# Claude Code plugin repos: automatic tags and release notes

## Problem

A plugin repo has a version field in `.claude-plugin/plugin.json` that is
already load-bearing — it is the cache key for
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, so an
unchanged version means no install re-extracts and every user keeps running
the old build (see `claude-code-plugin-update-flow`).

Two things go wrong around that field, and both are silent:

1. **The bump is honour-system.** A repo can document "every shipping merge
   bumps the version" and still merge fifty PRs without one, because nothing
   checks. The failure surfaces months later as "your fix never reached me".
2. **Tagging and release notes are manual, so they don't happen.** Repos end
   up with tags and no releases, or no tags at all, and the only record of
   what shipped is `git log`.

The fix for both is the same observation: **the version is already in the
repo and already changes in the PR.** Nothing else needs to be invented — no
CHANGELOG.md, no release-drafter, no semantic-release, no separate VERSION
file. CI can read the field and do the rest.

## Context / Trigger conditions

- `gh release list` is empty on a repo that has been shipping for months.
- `git tag` shows tags with no matching releases.
- Your contributing docs describe a manual tag-after-merge sequence.
- You are tempted to add a CHANGELOG.md that duplicates PR titles.
- You want a merge to be blocked when the author forgot the bump.

## Solution

One workflow file, two jobs, opposite triggers.

```yaml
name: release

on:
  push:
    branches: [master]          # or main
  pull_request:
    branches: [master]
    # Docs/CI-only exemption: users never execute these paths, so a PR
    # touching nothing else is not shipping and owes no bump. Mirror
    # whatever exemption your contributing docs already state.
    paths-ignore:
      - '.github/**'
      - 'tests/**'

permissions:
  contents: read

env:
  VERSION_FILE: .claude-plugin/plugin.json

jobs:
  version-bumped:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Version must advance
        env:
          BASE: ${{ github.base_ref }}
        run: |
          git fetch --no-tags --depth=1 origin "$BASE"
          old=$(git show "FETCH_HEAD:$VERSION_FILE" | jq -r .version)
          new=$(jq -r .version "$VERSION_FILE")
          if [ "$old" = "$new" ]; then
            echo "::error::$VERSION_FILE#version is still $old - bump it."
            exit 1
          fi
          if [ "$(printf '%s\n%s\n' "$old" "$new" | sort -V | head -1)" != "$old" ]; then
            echo "::error::$new does not advance past $old."
            exit 1
          fi
          echo "$old -> $new"

  tag-and-release:
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Tag and release if the version is new
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          version=$(jq -r .version "$VERSION_FILE")
          if git rev-parse -q --verify "refs/tags/v$version" >/dev/null; then
            echo "v$version is already tagged; nothing to release."
            exit 0
          fi
          gh release create "v$version" \
            --title "v$version" \
            --generate-notes \
            --target "$GITHUB_SHA"
```

### The five decisions inside that file

**`gh release create --target "$GITHUB_SHA"` creates the tag itself.** This
is the whole reason the job exists rather than a local `git tag`. In a
squash-merge repo, a tag made on the feature branch points at a commit that
never lands on the default branch; `--target` puts it on the squash commit
by construction. No `git push --tags`, and `contents: write` is the only
permission needed.

**`--generate-notes` is the changelog.** GitHub builds the notes from PR
titles merged since the previous tag, with authors and links. That is why
there is no CHANGELOG.md to keep in sync — and why **a lazy PR title is now
a lazy release note.** Say so in your contributing docs; it changes how
people write titles. If flat lists get long later, add a `.github/release.yml`
to group by label — still native, still no dependency.

**The gate reads the base via `FETCH_HEAD`, not `origin/<branch>`.** An
explicit `git fetch --no-tags --depth=1 origin "$BASE"` followed by
`git show "FETCH_HEAD:$VERSION_FILE"` works no matter what depth or refspec
the checkout action used. `git show "origin/$BASE:..."` is the version that
breaks on a shallow PR checkout.

**`sort -V` catches a backwards bump, not just a missing one.** A version
that goes *down* re-uses a cache directory that already has old content —
the same silent staleness, harder to spot. One line prevents it.

**Idempotence is the concurrency story — for re-runs.** The push job exits 0
when the tag exists, so re-runs and replays converge instead of colliding,
and no state is needed anywhere. But that same exit 0 has a documented blind
spot when two merges land close together carrying the *same* version — the
next section is that failure, observed in this catalog.

### Where idempotence fails: two merges, one version

Observed in this repo, 2026-08-20 (#182 and #183, repaired by #184): two
skill PRs were opened against the same base, both bumped the bundle to the
same next version, both showed `version-bumped: pass`, and both were merged
about ten seconds apart.

- The first merge's push job tagged `v1.16.0` on its squash commit.
- The second merge's push job found the tag existing, logged
  `v1.16.0 is already tagged; nothing to release.`, and exited 0 — a green
  check that created nothing.
- Result: the tag sat one commit behind the default branch. The second
  merge's new skill resolved fine at the default branch and **404'd at
  `?ref=v1.16.0`** — anyone installing from the tag got a release missing
  the content it was meant to ship, with every check green.

Why the gate did not catch it: both PRs were green *against the base as it
was when their CI last ran*. Merging the first PR moved the base, but **a
merge to the default branch does not re-trigger `pull_request` workflows on
other open PRs** — the second PR's green `version-bumped` was stale by the
time it merged, and nothing re-evaluated it.

**Detect it** any time merges land close together (seconds to minutes):

```bash
git fetch --tags -q
v=$(jq -r .version "$VERSION_FILE")
git rev-parse "v$v" HEAD        # differing SHAs = the tag is behind
# does the released tree contain the newest addition?
gh api "repos/<owner>/<repo>/contents/<path-added-by-second-merge>?ref=v$v" --jq .name
# 404 here while the same path resolves at the default branch = the gap
```

**Repair it** with an immediate version-bump-only PR (bump *both* manifests
in a dual-host repo, nothing else). Merging it runs `tag-and-release`
normally, which tags the new version on the current head — the previously
missed content ships in that release. This is the whole fix; do not move or
delete the existing tag.

**Why not harden the push job instead:** the job cannot cheaply distinguish
"same version because this merge was docs-only/exempt" (a legitimate no-op,
by design) from "same version because a stale-gated shipping merge slipped
through". That distinction is exactly what the PR-side gate exists to make,
and it runs pre-merge. Harden the *process*: treat any second merge landing
with an already-tagged version as the trigger for the bump PR above, and
queue bumping PRs as described next.

### Queueing several bumping PRs against the gate

The version field makes every bumping PR contend for the same next number:
whoever merges second is stale *by construction*, however disjoint the
content. The gate is effectively a serialization lock discovered at merge
time. Working protocol when more than one bumping PR is open:

1. Better than pre-assigning: **derive the number at merge time**, not when
   the branch is written. A version chosen an hour ago is a claim on a value
   someone else has already taken.

   ```bash
   base=$(git show origin/master:$VERSION_FILE | jq -r .version)
   next=$(echo "$base" | awk -F. '{printf "%d.%d.0", $1, $2+1}')
   ```

   Pre-assigned versions are fine as long as they are treated as provisional —
   only the first survives contact with the base.
2. After each merge, **rebase the next PR onto the moved base and re-bump
   past the new current version** before merging it. (Observed shape: a
   branch's `1.15.0 -> 1.16.0` bump conflicting with a base already at
   `1.17.0` resolves by taking the base's manifests and bumping to
   `1.18.0` — the version files are typically the *only* conflict when the
   catalog edits were made as in-place insertions.)
3. Expect the queued PR's `version-bumped` to still show green while stale —
   base movement does not re-trigger `pull_request` CI. Green is evidence
   about the past, not the present; re-run the check (push any commit, or
   re-run the workflow) after rebasing.
4. The platform-native alternative is branch protection's "require branches
   to be up to date before merging", which forces the re-run — at the cost
   of an update-and-wait cycle on every queued PR, and it does not combine
   well with making the gate a required check (see Notes).

### Three merge mechanics that report success and do nothing

Observed in one afternoon of four sessions merging into one catalog, and each
one costs a full rebase cycle to discover:

- **A rebase can delete your bump entirely.** Not "the numbers are now equal" —
  when the base took the *identical* version change, git applies your hunk as
  already-applied and drops it, so the manifest disappears from
  `git diff <base>...HEAD` and there is nothing left to notice. The gate then
  passes a PR that ships no bump at all. After every rebase, re-read the
  version out of the file rather than trusting that you set it once.

- **`gh pr merge --auto` is a silent no-op when auto-merge is disabled on the
  repository.** It exits 0 and prints nothing useful; `gh pr view --json
  autoMergeRequest` stays `null` while you wait for a merge that was never
  armed. Either check that field, or watch the checks and merge explicitly.

- **`--delete-branch` deletes the branch even when the merge did not happen.**
  Deleting the head branch of an open PR closes it, so a silently-failed merge
  plus a successful delete removes the PR from the queue with its content
  unmerged. Merge, confirm `state == MERGED`, then delete — as separate steps:

  ```bash
  gh pr merge "$pr" --squash
  [ "$(gh pr view "$pr" --json state --jq .state)" = MERGED ] || exit 1
  gh api -X DELETE "repos/$OWNER/$REPO/git/refs/heads/$branch"
  ```

  The `gh api` form also sidesteps a `pre-push` hook that would otherwise run
  the full publish gate against whatever tree the current checkout happens to
  be on — deleting a ref ships no content, so there is nothing for that gate
  to check.

If `gh pr merge` itself fails rather than no-ops (its GraphQL call has flaked
repeatedly), the REST path works:

```bash
gh api -X PUT "repos/$OWNER/$REPO/pulls/$pr/merge" -f merge_method=squash
```

### Where `VERSION_FILE` points

- **Single-plugin repo:** `.claude-plugin/plugin.json`. Done.
- **Multi-plugin repo** (a catalog shipping one plugin per skill, plus a
  bundle): point it at the **bundle** plugin's manifest. That gives one
  release stream — one tag, one release per shipping merge — whose notes
  name whatever changed. Do not try to keep every plugin's version in
  lockstep; in a real catalog they diverge on purpose.

  **Know the gap this leaves.** Each single-skill plugin's own version is
  *that plugin's* cache key. A PR that bumps only the bundle passes the gate
  and still leaves that plugin's users on a stale cache forever. The gate
  cannot see this. Document it where contributors will read it, and if it
  bites often enough, add a changed-path-to-plugin-version check — but that
  is a second, bigger check, not a tweak to this one.

### If the repo ships to Codex as well

A dual-host repo carries a second manifest, `.codex-plugin/plugin.json`, and
Codex pins on *its* version string exactly the way Claude Code pins on the
other one. Bump only one and the other runtime's installs freeze on a cached
copy — the same silent failure, now on a host you are not testing.

Gate both in the same job:

```yaml
env:
  VERSION_FILE: .claude-plugin/plugin.json
  CODEX_VERSION_FILE: .codex-plugin/plugin.json
```

```bash
codex=$(jq -r .version "$CODEX_VERSION_FILE")
if [ "$codex" != "$new" ]; then
  echo "::error::$CODEX_VERSION_FILE is $codex, expected $new - bump both manifests."
  exit 1
fi
```

This is worth automating rather than documenting: "keep both manifests in
lockstep" is easy to write down, easy to follow for a while, and invisible
when it lapses. See `claude-code-codex-plugin-parity` for the rest of the
two-runtime contract.

## Verification

On the PR, expect exactly this split:

```
version-bumped    pass
tag-and-release   skipping
```

`skipping` on the push-only job is correct, not a misconfiguration.

On an exempt PR (only `paths-ignore` paths touched), expect the release
workflow **not to appear at all** — `paths-ignore` skips the workflow, it
does not run it and pass it.

After the merge:

```bash
gh release list -R <owner>/<repo> -L 3
gh api repos/<owner>/<repo>/releases/latest --jq .body | head
```

And on a merge that did not change the version, the push job should log the
no-op rather than failing:

```
v1.0.1 is already tagged; nothing to release.
```

**After any close-together merge pair**, add the tag-tree check from the
same-version section above: the newest tag must contain the newest merge's
files. A green second `tag-and-release` run is not evidence of a release —
the no-op log line and the success tick look identical from the checks tab.

## Notes

- **Do not make `version-bumped` a required status check.** `paths-ignore`
  means the job never reports on an exempt PR, and a required check that
  never reports leaves the PR unmergeable forever. The gate blocks by
  failing, which is enough. If you truly need it required, you need a
  separate always-running job that reports the same check name — more
  machinery than the problem deserves.
- **`paths-ignore` beats a skip label** for the docs-only exemption: it is
  native, needs no bash, and cannot be forgotten. It fires only when *every*
  changed path matches, so a PR touching docs *and* shipped code still runs
  the gate. Keep the ignore list and your contributing docs in sync — they
  are two copies of one policy.
- **First release on a repo with no prior tag contains the entire history.**
  `--generate-notes` has no earlier tag to diff against. Expected, one-time,
  and harmless; later releases are deltas.
- **Adding this workflow in a PR means the gate runs on that PR.** For
  `pull_request` events GitHub uses the workflow file from the PR branch. If
  the PR touches anything outside the ignore list, it must bump its own
  version. That is a free live test of the mechanism.
- **Existing tags stay releaseless** unless you backfill:
  `gh release create v1.0.0 --generate-notes --verify-tag`, once per tag.
- **`gh pr create` / `gh pr merge` can fail with `HTTP 503 ... api.github.com/graphql`**
  while the REST API is fine. Fall back to
  `gh api repos/{owner}/{repo}/pulls -X POST -f title=... -F body=@body.md -f head=... -f base=...`
  and `gh api repos/{owner}/{repo}/pulls/{n}/merge -X PUT -f merge_method=squash`.
  See `gh-pr-graphql-401-rest-fallback` in
  [voitta-ai/skillz-memory](https://github.com/voitta-ai/skillz-memory) for the same fallback under a 401. It
  moved there in skillz#91 and is no longer a skill in this catalog.
- This skill assumes the version field matters. If you have not read
  `claude-code-plugin-update-flow`, read it first — it explains why an
  unbumped version is a silent, permanent failure rather than untidy
  bookkeeping.

## References

- [Automatically generated release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes)
- [Events that trigger workflows — `paths-ignore`](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)
- [`gh release create`](https://cli.github.com/manual/gh_release_create)
- [About protected branches — required status checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)

## Related

- `claude-code-plugin-update-flow` — **read this first.** It is why an unbumped
  version is a silent permanent failure rather than untidy bookkeeping, and
  therefore why the gate this skill builds is worth building.
- `claude-code-codex-plugin-parity` — the paired-manifest rule the release gate
  has to enforce: Codex pins on its own version, so a bump that moves only the
  Claude manifest freezes one host with no error.
- `claude-code-plugin-from-existing-repo` — the repo shape this automation
  assumes.
- `claude-code-plugin-publish-anthropic-marketplace` — the separate,
  human-reviewed step for directory listing. Automating your own tags does not
  automate that.
- `parallel-agent-session-collisions` — the wider pattern (several agent
  sessions moving one repo) that produces the same-version merge pair in the
  first place.
