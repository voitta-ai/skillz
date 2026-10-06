---
name: claude-code-plugin-publish-anthropic-marketplace
description: |
  Publish a Claude Code plugin to Anthropic's plugin marketplace, and run
  the pre-submission validation. Use when: (1) you have a plugin repo with
  .claude-plugin/plugin.json (and optionally its own marketplace.json) and
  want users to install it via Anthropic's directory, (2) you're unsure
  whether to "open a PR" against an anthropics marketplace repo (you do
  NOT — it's a read-only mirror; you submit via a web form), (3) you need
  to know the difference between claude-plugins-official (curated,
  invite-only, no submission path) and claude-plugins-community
  (submission-gated, accepts third-party plugins), (4) `claude plugin
  validate` behaves differently depending on the path you give it,
  (5) the `claude` binary isn't on PATH or is shell-aliased so a script
  can't call it. Covers self-hosted marketplace vs Anthropic listing
  coexistence and how each pins versions.
author: Claude Code
version: 1.1.0
date: 2026-06-11
source: https://github.com/voitta-ai/skillz
source_file: skills/claude-code-plugin-publish-anthropic-marketplace/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/claude-code-plugin-publish-anthropic-marketplace/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.
# Publish a Claude Code plugin to Anthropic's marketplace

## Problem

You have a working Claude Code plugin (a repo with `.claude-plugin/plugin.json`)
and want it discoverable/installable through Anthropic's official plugin
directory — not just via your own self-hosted git marketplace. The process
is non-obvious: there is no "app store" upload, the submission is not a PR,
and there are two Anthropic marketplaces with very different acceptance
models.

## Context / Trigger Conditions

- You're about to `git clone anthropics/claude-plugins-community` and open a
  PR to add your plugin — STOP, that repo is a read-only mirror.
- You want users to run `/plugin install NAME@claude-community`.
- You're unsure which Anthropic marketplace accepts submissions.
- `claude plugin validate` validates the "wrong" manifest depending on the
  path argument.
- A release script needs to call `claude` but it's not on `$PATH` (often
  aliased to something like `claude --chrome` in an interactive shell).

## Solution

### 1. Know the two Anthropic marketplaces (only one is submittable)

| Marketplace | Submittable? | How |
|---|---|---|
| `claude-plugins-official` | **No** | Anthropic-curated, invite-only. No application/form. |
| `claude-plugins-community` | **Yes** | Submit via web form. Anthropic-hosted, review-gated. |

The git-based model still underlies everything: any repo with a
`.claude-plugin/marketplace.json` is itself a marketplace that users add
with `/plugin marketplace add owner/repo`. The Anthropic community
marketplace is an *additional* listing on top of that, not a replacement.

### 2. Validate locally first (path-polymorphic command)

`claude plugin validate <path> --strict` resolves a DIFFERENT manifest
depending on what you point it at. Validate BOTH before submitting:

```bash
claude plugin validate . --strict                          # -> marketplace.json (dir resolves to the marketplace manifest)
claude plugin validate .claude-plugin/plugin.json --strict # -> the plugin manifest
```

`--strict` treats warnings (unrecognized fields, missing metadata) as
errors — use it so you catch what Anthropic's pipeline catches. Exit 0 +
"Validation passed" on each is the green light.

If `claude` is not on `$PATH` (common in non-interactive shells / scripts,
or when your interactive shell aliases it, e.g. `claude --chrome`), resolve
the real binary at the npm global prefix:

```bash
CLAUDE="$(npm config get prefix)/bin/claude"   # e.g. ~/.nvm/versions/node/vX/bin/claude
"$CLAUDE" plugin validate . --strict
```

### 3. Submit (NOT a pull request)

The `anthropics/claude-plugins-community` repo is a **read-only mirror**.
Its own repo description carries the canonical submission link:

> "Read-only mirror — submit plugins at **clau.de/plugin-directory-submission**."

So the authoritative entry point is **https://clau.de/plugin-directory-submission**.
It routes to a submission form (reported destinations, lower confidence than
the shortlink: `https://platform.claude.com/plugins/submit` for individual
authors; `https://claude.ai/admin-settings/directory/submissions/plugins/new`
for Team/Enterprise orgs with directory-management access). Always prefer
the `clau.de` shortlink — it's the one Anthropic publishes and will track if
the backing forms move.

The form is multi-step (Back / Next). One step ("Plugin details") asks for
(verified first-hand 2026-06-12):

- **Plugin homepage** (optional) — public homepage/docs URL; the repo URL is
  fine.
- **Plugin name** * (required) — display name; "check it's not already taken,
  and don't use brand names you don't own." Can be a human-friendly name
  (e.g. "Voitta YOLT"), not necessarily the `plugin.json` `name`.
- **Plugin description** * (required) — one/two sentences; the `plugin.json`
  description works.
- **Example use cases** * (required, and easy to miss) — free text in an
  "Example 1: ... / Example 2: ..." format. Pre-write 3-4 concrete scenarios
  BEFORE opening the form; sourcing them from a README "Example use cases"
  section keeps them reusable and reviewable.

### 4. What happens after approval

- Your plugin is pinned to a specific **commit SHA** in
  `anthropics/claude-plugins-community`.
- The community catalog (`.claude-plugin/marketplace.json` in that repo)
  **syncs nightly** — expect ~24h before it appears.
- CI **auto-re-pins** the SHA as you push new commits to your repo. You do
  NOT manage SHAs by hand.
- Users install with:

```
/plugin install NAME@claude-community
```

### 5. Self-hosted + Anthropic listing coexist off ONE repo

You don't choose one or the other. The same repo can be:

- **Its own marketplace** (`.claude-plugin/marketplace.json`, `source: ./`):
  users add `owner/repo` directly; a pushed release is immediately live;
  upgrades pull via `/plugin marketplace update NAME`. This path pins on the
  **`version` string** in `plugin.json` — so bump it every release or
  existing users stay on the cached copy.
- **Listed on `claude-plugins-community`**: pins on **commit SHA**, re-pinned
  by CI on push, nightly sync.

Two different pin mechanisms, same `plugin.json` as the source of the
displayed version. A typical release: bump `plugin.json` version + tag +
push (serves the self-hosted marketplace); the community listing re-pins
itself.

## Verification

- `claude plugin validate . --strict` and
  `claude plugin validate .claude-plugin/plugin.json --strict` both exit 0.
- After submission + approval + ~24h, your name appears in
  `https://github.com/anthropics/claude-plugins-community/blob/main/.claude-plugin/marketplace.json`.
- A clean machine can run `/plugin install NAME@claude-community`.

## Example

For the `yolt` plugin (repo `voitta-ai/voitta-yolt`, already its own
marketplace):

```bash
CLAUDE="$(npm config get prefix)/bin/claude"
"$CLAUDE" plugin validate . --strict                            # marketplace.json -> passed
"$CLAUDE" plugin validate .claude-plugin/plugin.json --strict   # plugin.json -> passed
# then: open https://clau.de/plugin-directory-submission and submit voitta-ai/voitta-yolt
# after approval, users: /plugin install yolt@claude-community
```

## Notes

- Provenance of these facts (be honest when applying): the path-polymorphism
  of `claude plugin validate`, the `claude`-binary-location workaround, and
  the existence + read-only nature + `clau.de/plugin-directory-submission`
  link of `anthropics/claude-plugins-community` were verified first-hand
  (the last via `gh repo view anthropics/claude-plugins-community`). The
  exact downstream form URLs (`platform.claude.com/plugins/submit`,
  `claude.ai/admin-settings/...`) and the nightly-sync / auto-re-pin CI
  behavior came from Claude Code docs research, not from a completed
  end-to-end submission — treat as high-but-not-certain and re-confirm at
  the `clau.de` link.
- "Community marketplace is read-only" is the single most important thing
  to internalize: do not waste time forking it or opening a PR.
- This is distinct from the sibling skills: `claude-code-plugin-from-existing-repo`
  (convert a copy-into-project repo into an installable plugin) and
  `claude-code-plugin-update-flow` (the `/plugin marketplace update` + reload
  upgrade path). This skill is specifically about getting LISTED on
  Anthropic's directory.

## References

- `anthropics/claude-plugins-community` (verify the live submission link in
  its repo description): https://github.com/anthropics/claude-plugins-community
- Canonical submission link: https://clau.de/plugin-directory-submission
- Plugin docs: https://code.claude.com/docs/en/plugins.md
- Marketplace docs: https://code.claude.com/docs/en/plugin-marketplaces.md

## Related

- `claude-code-plugin-from-existing-repo` — producing the plugin this skill
  submits.
- `claude-code-plugin-release-automation` — tags and releases in your own repo.
  Independent of directory listing: automating one does nothing for the other.
- `claude-code-plugin-update-flow` — how an installed copy picks up what you
  publish, and why a listing does not help if the version never moved.
- `claude-code-codex-plugin-parity` — Codex has no self-serve marketplace
  submission, so a dual-host plugin is distributed asymmetrically.
