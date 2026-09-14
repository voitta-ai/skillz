---
name: claude-code-plugin-update-flow
description: |
  Get an installed Claude Code plugin to actually run new code, and — as
  a plugin author — make sure your merges reach installs at all. Use when:
  (1) `claude plugin update <plugin>@<marketplace>` reports "up to date"
  but the plugin still behaves like an old build, (2) `claude plugin
  marketplace update <name>` succeeds yet the running session's hooks /
  commands / skills are unchanged, (3) you merged commits to the plugin
  repo and no user, including you, ever sees them, (4) `/plugin update
  <plugin>@<marketplace>` opens the plugin-discovery picker instead of
  updating (older builds), (5) you're unsure whether `plugin update`,
  `/reload-plugins`, or a restart is what's needed. Root cause for the
  "up to date" case: the installed copy lives at
  `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`, keyed on
  `.claude-plugin/plugin.json#version`, so an unchanged version means
  nothing re-extracts. Also covers why checking the marketplace clone is
  NOT valid verification, and the release-tagging order for squash-merge
  repos.
author: Claude Code
version: 1.4.0
date: 2026-08-17
---

# Claude Code: Updating an Installed Plugin

## Problem

Two failures wear the same face — "the new code isn't running" — and
they have different causes.

**As a user:** you pulled the marketplace, the CLI said it worked, and
the plugin still behaves like the old build.

**As an author:** you merged commits, maybe many, and nobody is running
them. `claude plugin update` cheerfully reports "up to date" to every
user, forever. This is the more dangerous one, because nothing anywhere
reports an error — you only notice when a bug you fixed months ago is
still biting you.

## Context / Trigger Conditions

- `claude plugin update <plugin>@<marketplace>` prints "up to date" but
  a feature you know is on master is missing.
- `claude plugin marketplace update <name>` prints success and the
  running session is unchanged.
- A hook keeps making a decision you already fixed upstream.
- You are the plugin author and cannot tell whether users have your
  change.
- Older builds only: `/plugin update <plugin>@<marketplace>` opens the
  discovery picker (`Discover plugins (1/N) / Search...`).

## The layout that explains everything

Three locations, and conflating them is the whole trap:

| path | what it is |
|---|---|
| `~/.claude/plugins/marketplaces/<marketplace>/` | git clone of the marketplace repo — the **fetched source** |
| `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` | extracted install — **what actually executes** |
| `~/.claude/plugins/cache/.../<version>/.in_use/` | stamped by live sessions; identifies which copy is loaded |

`claude plugin marketplace update` refreshes the **clone**.
`claude plugin update` re-extracts from clone into **cache** — but only
if the version differs, because the cache path is keyed by version.

So the decision is a string comparison: installed `0.1.0` vs available
`0.1.0` → "up to date", no work done. The clone can be a hundred commits
ahead and it changes nothing.

## Solution

### If you are the plugin author

**Bump `.claude-plugin/plugin.json#version` on every merge that changes
a file users receive.** There is no other mechanism. A merge without a
bump is invisible.

Suggested split for a pre-1.0 plugin, where the contract is "what does
it do, and how do I configure it" rather than a code API:

- **patch** — nothing a user could observe at runtime: refactors, docs,
  log fields, message wording. Still required; shipped is shipped.
- **minor** — user-visible behavior: changed decisions or defaults, new
  commands, new config keys or environment variables.
- **major** — reserved for declaring a config-file format stable at
  1.0, and for breaking it afterwards.

Files users never execute — `tests/`, `.github/`, maintainer notes —
don't need their own bump; fold them into the next real one.

**Tagging under squash merges.** A release script that rewrites the
version, commits, *and* tags in one step does not fit a squash-merge
repo: the tag lands on a feature-branch commit that the squash never
puts on master. Correct order:

1. Edit the version as part of the PR's own changes.
2. Squash-merge.
3. Tag master's squash commit and push the tag:
   ```bash
   git tag -a v0.2.0 -m "Release v0.2.0" <squash-sha>
   git push origin v0.2.0
   ```

Tagging creates no commit, so this stays compatible with a
no-direct-commits-to-master policy.

**Prefer automating steps 2-3 away.** Doing this by hand is exactly the
step that gets skipped, which is how a repo ends up with tags and no
releases — or no tags. `claude-code-plugin-release-automation` turns the
version field into the trigger: CI fails a PR whose version did not
advance, then cuts the tag and a GitHub release with generated notes on
the squash commit. Reach for the manual sequence above only when you are
backfilling a tag or the repo has no CI.

### If you are the user

```bash
claude plugin marketplace update <marketplace-name>
claude plugin update <plugin>@<marketplace>
```

then restart the session (the CLI says so explicitly:
`Restart to apply changes.`). In-session, `/reload-plugins` may be
enough on builds that have it.

Run the two commands **separately**. Pasting both at once lets the first
`claude` process consume the second line off stdin, so it silently never
executes — you get the marketplace output, no update output, and an
unchanged cache.

If `plugin update` says "up to date" and you know master has moved, the
author didn't bump the version. Nothing on your side will fix that; the
only local workaround is deleting the stale cache directory to force a
re-extract, and that is a hack — the fix belongs upstream.

## Verification

**Check the cache, not the clone.** The marketplace clone being current
is *not* evidence the install updated; that check reports success in
exactly the case that's broken.

```bash
# A directory named for the new version should exist:
ls ~/.claude/plugins/cache/<marketplace>/<plugin>/
# 0.1.0   0.2.0

# And it should contain a symbol only the new code has:
grep -c "<new-symbol>" \
  ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/hooks/<file>
```

A successful `claude plugin update` also states the transition outright
— `Plugin "<name>" updated from 0.1.0 to 0.2.0 for scope user.` Absence
of that line means nothing happened.

To confirm *which* copy a running session loaded, look for the
`.in_use/` directory under each cached version and compare mtimes.

## Example

A plugin's version had not moved off `0.1.0` since the commit that first
shipped it; no tags existed. Over the following ~40 commits, five merged
behavior changes accumulated. Every install, including the author's own
dogfooding session, kept running the original build — while
`claude plugin update` reported "up to date" each time it was tried.

Diagnosis took three commands:

```bash
grep -rl "<new-symbol>" ~/.claude/plugins/marketplaces/<marketplace>/  # found
grep -c  "<new-symbol>" ~/.claude/plugins/cache/<mkt>/<plugin>/0.1.0/hooks/<file>  # 0
ls -la ~/.claude/plugins/cache/<mkt>/<plugin>/0.1.0/   # .in_use/ stamped today
```

Clone current, cache stale, stale copy live. Bumping to `0.2.0` and
re-running `claude plugin update` produced a `0.2.0/` directory beside
the old one, containing the merged code.

## Notes

- **Legacy builds:** some older Claude Code versions had no
  `plugin update` subcommand at all; `/plugin update <anything>` fell
  through the slash-command matcher to the discovery picker, which is
  for *installing*. If you see the picker, the flow is
  `/plugin marketplace update <name>` + `/reload-plugins` or a restart.
  Current builds have working `claude plugin marketplace update` and
  `claude plugin update` CLI subcommands.
- **Re-pointing a marketplace at a different repo is three places, not
  one.** The name stays the same (it comes from the repo's
  `.claude-plugin/marketplace.json`), so nothing looks wrong:
  1. `~/.claude/settings.json` -> `extraKnownMarketplaces.<name>.source.repo`
  2. `~/.claude/plugins/known_marketplaces.json` -> the same field
  3. `~/.claude/plugins/marketplaces/<name>` -> the **cached clone**, whose
     git `origin` remote still points at the old repo:
     `git -C ~/.claude/plugins/marketplaces/<name> remote set-url origin <new>`
     then `git fetch && git reset --hard origin/<default-branch>`.

  Edit only the JSON and `marketplace update` keeps `git pull`-ing the old
  repo. There is no error: the catalog silently freezes at the old repo's
  HEAD, which is invisible when the two repos were recently in sync and only
  diverge later. Verify with
  `git -C ~/.claude/plugins/marketplaces/<name> remote get-url origin`, not
  with the settings file you just edited.
- `marketplace update` is a `git pull` on the clone. Editing files
  under `~/.claude/plugins/marketplaces/<name>/` by hand (don't) can
  make it fail or merge oddly.
- Plugins distributed through more than one marketplace have one clone
  per marketplace, each needing its own update.
- If your plugin's wrapper script caches state (a bootstrap-deps
  marker, for instance), new code may need to invalidate it — key the
  cache on a content hash of the relevant file, e.g.
  `requirements.txt`, so a dependency bump re-bootstraps by itself.
- Anthropic's community marketplace pins a commit SHA and re-syncs on
  push, but users installing from it are still served a versioned
  plugin — the bump discipline applies the same way.

## References

- [Claude Code plugins](https://code.claude.com/docs/en/plugins)

## Related

- `claude-code-plugin-release-automation` — the author-side fix for what this
  skill diagnoses: make the version bump non-optional in CI so a merge cannot
  ship without one.
- `claude-code-codex-plugin-parity` — the same cache-key-is-the-version rule on
  Codex, which pins on its own manifest. Bump one and not the other and exactly
  one host freezes, silently.
- `claude-code-plugin-from-existing-repo` — the layout the cache mirrors.
- `claude-json-mcp-migration-slice` — the neighbouring "which file actually
  holds this state" question, for MCP config rather than plugin installs.
