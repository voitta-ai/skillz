---
name: claude-code-codex-plugin-parity
description: |
  Port a Claude Code plugin to the OpenAI Codex CLI (or vice versa), and
  understand where the two plugin systems are identical vs where they diverge.
  Use when: (1) you have a Claude Code plugin (.claude-plugin/plugin.json +
  marketplace.json + hooks/hooks.json) and want it to also work under Codex
  CLI, (2) you are writing a .codex-plugin/plugin.json and wonder if you can
  reuse the existing hooks.json, (3) a ported plugin installs under Codex but
  its hooks misbehave or do nothing, (4) you need to confirm which plugin-root
  env vars a hook sees under Codex, (5) you need to know whether "submit to the
  official marketplace" has a Codex equivalent. Covers the manifest/marketplace
  parity, the version-pin release discipline shared by both, the plugin-root
  env-var compatibility aliases, and the runtime-protocol caveat.
author: Claude Code
version: 1.2.0
date: 2026-06-11
---

# Claude Code <-> Codex CLI plugin parity

## Problem

Codex CLI (plugins added ~v0.117) ships a plugin system that looks almost
identical to Claude Code's - close enough that you assume a Claude Code plugin
drops into Codex unchanged. The manifest and the hook *registration* shape do
port directly, and Codex even sets compatibility env-var aliases so a
`${CLAUDE_PLUGIN_ROOT}` hook path still resolves. The one thing that can still
bite is the hook *runtime protocol* (the stdin payload and the stdout/exit
decision contract). This skill is the map of what is shared vs what is not, so
a port is a 20-minute job, not a day of guessing.

## Context / Trigger Conditions

- Porting a Claude Code plugin to Codex CLI or vice versa.
- Writing a `.codex-plugin/plugin.json` alongside an existing
  `.claude-plugin/plugin.json`.
- A hook works under Claude Code but does nothing under Codex.
- A ported hook misbehaves under Codex and you suspect an env-var or
  hook-protocol difference.
- Deciding how to distribute / release a plugin for both runtimes.

## What is IDENTICAL (copy almost verbatim)

| Concern | Claude Code | Codex CLI |
|---|---|---|
| Manifest path | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json` |
| Manifest fields | `name`, `version`, `description`, `author`, `homepage`, `repository`, `license`, `keywords` + component pointers | **same fields** |
| Component pointers | (varies) | `skills: "./skills/"`, `hooks: "./hooks/hooks.json"`, `mcpServers: "./.mcp.json"`, `apps: "./.app.json"` |
| Marketplace file | `.claude-plugin/marketplace.json` | `marketplace.json` (local: `~/.agents/plugins/marketplace.json`) |
| Hook registration shape | `hooks.json` with `PreToolUse` + `"matcher": "Bash"` + `{"type":"command","command":...}` | **same shape, same event names** (`PreToolUse`, `PostToolUse`, `SessionStart`, `Stop`, `UserPromptSubmit`, ...) |
| Version pinning | pins on the `version` string | **same** |
| Install cache | marketplace clone | `~/.codex/plugins/cache/$MARKETPLACE/$PLUGIN/$VERSION/` |

### Shared version-pin release discipline

Both runtimes **pin on the `version` string in plugin.json**: pushing new
commits without bumping `version` leaves existing installs on the cached
copy. Omit `version` entirely and the runtime falls back to the commit /
short SHA (Codex curated-cache entries use short SHAs; local installs use
`$VERSION = local`). So the same "bump version + tag" release step works for
both - a release script should bump **both** manifests in lockstep when a
repo distributes to both ecosystems.

## What DIFFERS (the actual port work)

1. **Plugin-root env var (now a compatibility alias, not a trap).** Codex's
   native variable is **`PLUGIN_ROOT`** ("a Codex-specific extension that
   points to the installed plugin root", per the Codex hooks doc), but Codex
   **also sets `CLAUDE_PLUGIN_ROOT` "for compatibility with existing plugin
   hooks"** (and likewise exposes `PLUGIN_DATA` with a `CLAUDE_PLUGIN_DATA`
   alias). So a `hooks.json` that references `${CLAUDE_PLUGIN_ROOT}` **does
   resolve under Codex** - you do NOT need to fork a separate Codex hooks file
   just for the env var, and the same `hooks.json` can be aliased across both
   runtimes. Prefer the native `${PLUGIN_ROOT}` in new Codex-only hooks, but a
   ported Claude hook keeps working via the alias.

2. **Hook runtime protocol is the real divergence to check.** Matching
   *registration* shape (same event names, same `matcher`, same
   `type: command`) does NOT by itself guarantee *behavioral* parity. Codex
   documents its own hook I/O contract: stdin carries `session_id`,
   `transcript_path`, `cwd`, `hook_event_name`, `model`, `permission_mode`
   plus event-specific fields (`tool_name` / `tool_input` for `PreToolUse`);
   on stdout, exit 0 + JSON applies decisions (`continue`, `systemMessage`,
   and event-specific fields like `PreToolUse`'s `permissionDecision` /
   `updatedInput`), exit 0 + plain text is added as context
   (`SessionStart`, `UserPromptSubmit`), and **exit 2 signals block/deny with
   the stderr message recorded as the reason**. This is close to Claude Code's
   contract but verify the exact fields your hook emits against the Codex
   hooks doc before declaring parity.

3. **No self-serve official Codex marketplace (yet).** Anthropic has an
   official-marketplace submission form (claude.ai/settings/plugins/submit,
   platform.claude.com/plugins/submit). The Codex docs say an official Plugin
   Directory and self-serve publishing are "coming soon"; for now you
   distribute via a repo- or user-scoped `marketplace.json`
   (`.agents/plugins/marketplace.json` or `~/.agents/plugins/marketplace.json`)
   added with `codex plugin marketplace add <owner/repo>`, or via Codex-app
   workspace sharing to named teammates. So "submit to the official
   marketplace" has a Claude Code path but, as of mid-2026, no Codex
   equivalent - only the repo/marketplace path maps.

## Solution (port checklist, CC -> Codex)

1. Add `.codex-plugin/plugin.json` mirroring `.claude-plugin/plugin.json`
   (same name/version/description/author/homepage/repository/license;
   add `keywords` for discovery).
2. You CAN point the Codex `hooks` pointer at the same `hooks.json`: Codex's
   `CLAUDE_PLUGIN_ROOT` compatibility alias means a `${CLAUDE_PLUGIN_ROOT}`
   command path resolves. Use `${PLUGIN_ROOT}` only when you want the native
   Codex name in a Codex-specific hooks file.
3. Verify the hook's stdin/stdout/exit contract under an actual Codex run
   before declaring parity (see the documented contract above).
4. Keep both manifests' `version` in lockstep; bump both per release.
5. Distribute via a repo- or user-scoped `marketplace.json` added with
   `codex plugin marketplace add <owner/repo>`; there is no
   official-marketplace submission to do.

## Verification

- `codex plugin marketplace add <owner/repo>` then `codex plugin marketplace
  list` shows the marketplace; open the `codex plugin` browser to install the
  plugin and confirm its `name` / `version` / enabled state.
- Trigger the hooked event and confirm the hook command actually runs - echo
  `$PLUGIN_ROOT` (and `$CLAUDE_PLUGIN_ROOT`, which should match) from the hook
  to confirm both are populated under Codex.

## Notes

- Codex plugin CLI: `codex plugin marketplace add|list|upgrade|remove` manages
  marketplaces; `codex plugin` opens an interactive browser to install /
  enable / disable individual plugins. Plugins can bundle skills, MCP servers,
  apps, and hooks.
- Cross-pollination already exists: OpenAI ships `codex@openai-codex` as a
  *Claude Code* plugin (the rescue bridge), so the two marketplaces reference
  each other.
- Worked example: a plugin's repo added `scripts/release.sh` in one PR
  (version bump + tag for the shared pin-on-version model) and a metadata-only
  `.codex-plugin/plugin.json` scaffold in a follow-up PR, leaving the `hooks`
  pointer out pending only hook runtime-protocol verification. No env-var
  rewrite is needed first: the `CLAUDE_PLUGIN_ROOT` compatibility alias means
  the existing `hooks.json` resolves under Codex, so switching to
  `${PLUGIN_ROOT}` is an optional native-style change, not a prerequisite.

## References

- Codex plugins overview: https://developers.openai.com/codex/plugins
- Codex build plugins (manifest, marketplace, distribution): https://developers.openai.com/codex/plugins/build
- Codex hooks (PLUGIN_ROOT + CLAUDE_PLUGIN_ROOT compat alias; hook I/O contract): https://developers.openai.com/codex/hooks
- Codex changelog (plugin feature history): https://developers.openai.com/codex/changelog
- Community plugin list + "no self-serve marketplace submission" note: https://github.com/hashgraph-online/awesome-codex-plugins
- Claude Code plugin marketplaces (version resolution / SHA pinning): https://code.claude.com/docs/en/plugin-marketplaces

## Related

- `claude-code-plugin-from-existing-repo` — producing the Claude Code plugin
  this skill ports.
- `claude-code-plugin-python-bootstrap` — the hook-side concern that carries
  across both hosts unchanged, unlike the manifests.
- `claude-code-plugin-update-flow` — the Claude Code half of "why does the
  install still run old code". Codex pins on its own manifest's version
  independently, which is why the two must be bumped together.
- `claude-code-plugin-release-automation` — automating that paired bump so the
  two manifests cannot drift.
- `agent-host-skill-loading` — the third case: a host with neither plugin
  system, reading `SKILL.md` files directly.
