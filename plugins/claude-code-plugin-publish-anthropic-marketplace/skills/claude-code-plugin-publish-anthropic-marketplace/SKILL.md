---
name: claude-code-plugin-publish-anthropic-marketplace
description: |
  Publish a Claude Code plugin to Anthropic's plugin directory through the
  self-serve developer portal (claude.ai/directory/manage), get it past the
  portal's validation and security scan, and keep later versions flowing. Use
  when: (1) you have a plugin repo with .claude-plugin/plugin.json and want it
  listed in the Claude directory; (2) you're about to open a PR against
  anthropics/claude-plugins-community (don't: it's a read-only mirror);
  (3) the portal blocks a version ("Secret in a shipped file", "README too
  short", "License missing", symlinks, unpinned npx/uvx) or holds it for a
  reviewer (files over 256 KiB, more than 512 files, binaries, package
  installs); (4) a listed plugin stopped picking up new versions, or the live
  version was flagged after a policy change; (5) your repo layout (symlinked
  skills, dev files, tests at the root) can't ship as-is; (6) the `claude`
  binary is shell-aliased so a script can't call it. Covers the portal flow,
  tracking and version pinning, the blocking and holding checks, what ships,
  and the built-bundle branch pattern.
author: Claude Code
version: 2.0.0
date: 2026-10-08
source: https://github.com/voitta-ai/skillz
source_file: skills/claude-code-plugin-publish-anthropic-marketplace/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/claude-code-plugin-publish-anthropic-marketplace/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.
# Publish a Claude Code plugin to Anthropic's directory

Provenance tags used below: **[V]** verified first-hand while submitting real
plugins (yolt and the skillz bundle), **[D]** taken from Anthropic's docs as of
2026-10-08 and not independently exercised.

## Problem

You have a working Claude Code plugin (a repo with `.claude-plugin/plugin.json`)
and want it installable from Anthropic's directory, not only from your own
self-hosted git marketplace. Submission is not a PR, and the portal checks
every version you publish. Several of its checks fail on ordinary repo layouts:
symlinked skills, a missing plugin README, test fixtures that look like secrets.

## Context / Trigger Conditions

- You're about to clone `anthropics/claude-plugins-community` and open a PR.
  STOP: its description says "Read-only mirror". **[V]**
- You have an older submission made through the `clau.de/plugin-directory-submission`
  form and wonder where it went. That shortlink now redirects to the
  directory docs (`claude.com/docs/directory/publish`), and earlier submissions
  show up in the portal. **[V]** The docs have a "Move an earlier submission to
  the developer portal" section for any that don't. **[D]**
- The portal shows a version as **Blocking**, **Policy hold**, "Held back from
  going live by directory policy", or "The live version no longer meets
  directory policy".
- A release script needs to call `claude` but it's aliased in your shell.

## Solution

### 1. Where and who

- **Portal:** `https://claude.ai/directory/manage` -> **Submit new**. **[V]**
  It was announced 2026-09-25 ("Build plugins for Claude with the directory
  submission portal"). **[V]**
- **Who can submit:** paid Claude plans. **[D]** Your GitHub account must be
  connected on claude.ai *in the organization you submit from*, with push
  access to the repo. **[D]**
- **Two paths** at "What would you like to submit?": **MCP connector** (one
  remote MCP server) or **Plugin bundle** (a GitHub repo holding the plugin).
  **[D]** This skill covers the plugin bundle.
- After a submission the portal shows each version's checks, review status
  and, once live, install and usage stats. **[V]**

### 2. Validate locally, then in the portal

`claude plugin validate` catches syntax and schema errors only. It doesn't
check the directory's own rules (README, license, name collisions, file
limits); the portal's **Validate** button does. **[D]** Run both.

`claude plugin validate <path> --strict` resolves a different manifest
depending on the path. Validate both: **[V]**

```bash
claude plugin validate . --strict                          # -> .claude-plugin/marketplace.json
claude plugin validate .claude-plugin/plugin.json --strict # -> the plugin manifest
```

In scripts, call the real binary. An interactive alias (for example
`claude --chrome`) doesn't apply in non-interactive shells, and the native
installer puts the binary at `~/.local/bin/claude`, a symlink to the current
version. **[V]** The old `$(npm config get prefix)/bin/claude` path is only
right for an npm-global install.

```bash
CLAUDE="$HOME/.local/bin/claude"
"$CLAUDE" plugin validate . --strict
```

In the portal, a validation report covers one commit. Push the fix, then
select **Re-validate**. **[D]**

### 3. What blocks a version, and what holds it

Results are **Blocks** (fix before submitting, or the version can't go live),
**Policy hold** (a reviewer reads that version before it can go live; not a
rejection, and it can recur on each new version), **Warning** or **Note**.
**[D]** The ones that bite ordinary repos:

**Blocks** **[D]**

- Symbolic links, git submodules or LFS pointers where the plugin loads the
  entry. A bundle whose `skills/` are symlinks to a shared tree fails here.
  **[V]** for the skillz bundle.
- No README of at least 40 words in the plugin folder (words in code blocks
  don't count), or no license (`LICENSE` file or `license` in `plugin.json`).
- A non-ASCII plugin `name`.
- A reserved name: `claude`, `anthropic`, `official`, `plugin`, `mcp` or `test`
  as the whole name, or a name already taken. Separately, `claude plugin
  validate --strict` (CLI 2.1.294) rejects any plugin name that *starts with*
  `claude-`, `anthropic-`, `anthropics-` or `cc-plugin-`, and flags names that
  merely contain `claude`. **[V]** A marketplace repo whose older plugins
  carry such names fails strict validation as a whole, even when the plugin
  you are submitting is fine.
- An unpinned package launcher: `npx`, `uvx`, `bunx`, `pnpm dlx`, `pipx run`
  without an exact version, or `uv run` without `--locked`/`--frozen`.
- A secret-shaped string in **any** shipped file, documentation and tests
  included. In the report it's "Secret in a shipped file". **[V]**
- `.DS_Store`, `Thumbs.db` and similar system files in the plugin folder.

**Held for a reviewer** **[D]**

- Hooks or scripts that install packages, or a lockfile install
  (`package.json` next to a lockfile at the plugin root).
- Any non-image, non-font file over 256 KiB.
- More than 512 files in the plugin folder.
- Binaries other than PNG/JPEG/GIF/WebP images and fonts (`.ico`, `.pdf`,
  `.zip`, executables).
- Even an exactly pinned `npx`/`uvx` package is always held, because its own
  dependencies resolve at install time.

### 4. The plugin folder is everything that ships

The plugin folder is the one holding `.claude-plugin/plugin.json`. Installs get
that folder and nothing else, and the checks and the security scan read all of
it. **[D]** If the plugin is the repo root, `tests/` ships and gets scanned. **[V]**

What happened to yolt (a credential-redacting plugin) **[V]**: its
`tests/test_secret_redact.py` held fake tokens written as single string
literals. The portal flagged them as "Secret in a shipped file". That blocked
every version after the live one, and the live version was then flagged too
("The live version no longer meets directory policy"), putting the whole plugin
on hold: "Newer versions won't go live until Anthropic clears the hold." The
portal's suggested fix (move the value to `userConfig` with `sensitive: true`)
makes no sense for a test fixture.

- Splitting a fake token across concatenated strings got it past the scanner
  in the same file. That is evasion, not a fix: the scanner can't tell a
  fixture from a leak, and hiding the shape defeats it for everyone.
- The honest fix is to keep test fixtures out of the shipped folder.
- Moving the plugin into a subfolder for that has a cost. For a subfolder
  plugin, hook and MCP command paths must be written in full from
  `${CLAUDE_PLUGIN_ROOT}` (blocking), and non-shell programs that hooks run
  are held for a reviewer. **[D]**

### 5. Repos that can't ship as-is: publish a built bundle branch

If the repo layout depends on symlinks, or carries dev files you don't want to
ship, build a self-contained plugin folder in CI and commit it to a dedicated
branch. Then point the submission's **Branch or tag** at that branch. skillz does
this: `scripts/build-directory-bundle.py` copies the bundle with every symlink
dereferenced, adds a generated README and the LICENSE, and checks the file
limits. `.github/workflows/directory-branch.yml` appends the result to the
`directory` branch on each push to master. **[V]**

Append to that branch, never force-push it. Published versions are pinned to
commit SHAs, so every SHA the directory has seen must stay reachable.

### 6. Tracking, versions and publishing

- **Tracked branch or tag:** the submission follows one branch (the default
  branch if left empty) or one tag. **[D]** You can't change the repository or
  folder after submitting; you can change the tracked branch or tag on the
  **Settings** tab, except while a reviewer has the plugin. **[D]**
- **New commits:** the directory checks the tracked ref on a schedule. In
  practice that was about every 6 hours **[V]**; the docs don't give an
  interval. With the GitHub push webhook (the default choice at submit; needs
  repo admin to install) it also checks on each push. **[D]** **Check for new
  commits** on the plugin's page forces a check. **[D]**
- **Pinning:** each version is pinned to a commit SHA. **[V]** If `plugin.json`
  sets `version`, raise it every release. **[D]**
- **Publishing:** a passing version isn't live until it's published. The
  **Auto-publish** setting controls whether later passing versions go live
  without manual approval. By default a reviewer publishes each version; a
  reviewer can switch the plugin to auto-publish after the first one. **[D]**
- **The listing keeps serving the last published version** while a newer one
  is blocked or held. If the security scan fails a new version, later versions
  also wait until a reviewer clears the plugin. **[D]**, and **[V]** for yolt.

### 7. Self-hosted marketplace and directory listing coexist

The same repo can be its own marketplace (`.claude-plugin/marketplace.json`,
users run `/plugin marketplace add owner/repo`) and be listed in the directory.
**[V]** The self-hosted path updates installed copies when the `version` string
in `plugin.json` moves. The directory publishes per commit SHA, under its own
checks and publish setting. A release bumps `version`, tags and pushes; the
self-hosted marketplace has it immediately, and the directory picks it up at
its next check.

## Verification

- `claude plugin validate . --strict` and
  `claude plugin validate .claude-plugin/plugin.json --strict` both pass.
- The portal's **Validate** report has no **Blocking** findings for the commit
  you are about to submit.
- After submitting, the plugin's **Versions** tab lists the commit with its
  checks, and the overview says whether it is live or why not.

## Notes

- Portal facts change; reconfirm a check's exact result in
  `claude.com/docs/plugins/pre-submission-checklist` before relying on it.
- Keep account names, IDs and install numbers from the portal out of anything
  public.
- Distinct from `claude-code-plugin-from-existing-repo` (turn a repo into an
  installable plugin) and `claude-code-plugin-update-flow` (how installed
  copies pick up a release). This skill is about getting and staying listed.

## References

- Developer portal: https://claude.ai/directory/manage (sign-in required)
- Submit your plugin: https://claude.com/docs/plugins/submit
- Pre-submission checklist: https://claude.com/docs/plugins/pre-submission-checklist
- Publish to the directory: https://claude.com/docs/directory/publish
- Submission statuses: https://claude.com/docs/directory/submission-status
- Announcement (2026-09-25): https://claude.com/blog/build-plugins-for-claude
- Read-only community mirror: https://github.com/anthropics/claude-plugins-community
- `claude plugin validate`: https://code.claude.com/docs/en/plugins/cli-reference

## Related

- `claude-code-plugin-from-existing-repo`: producing the plugin this skill
  submits.
- `claude-code-plugin-release-automation`: tags and releases in your own repo.
  Independent of the directory, which tracks commits on its own schedule.
- `claude-code-plugin-update-flow`: how an installed copy picks up what you
  publish, and why nothing moves if the version never changed.
- `claude-code-codex-plugin-parity`: Codex has no self-serve directory, so a
  dual-host plugin is distributed asymmetrically.
