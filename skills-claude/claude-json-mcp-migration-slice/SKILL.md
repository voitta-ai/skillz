---
name: claude-json-mcp-migration-slice
description: |
  Identify the exact slice of ~/.claude.json that carries MCP configuration
  for cross-machine migration, profile snapshots, or team sync. Use when:
  (1) building a tool that copies MCP servers between machines, (2) deciding
  which keys in ~/.claude.json to back up vs leave behind, (3) trying to
  reproduce someone else's MCP setup without copying their entire personal
  Claude Code state, (4) writing a redact/export step over ~/.claude.json
  and unsure which keys are "config" vs "session bookkeeping". Naive
  approaches go wrong in two ways: copying the whole file leaks 89-project
  history, userID, and 30+ unrelated keys; copying only top-level
  `mcpServers` silently drops per-project .mcp.json approval state and
  per-project user-scope additions. Confirmed against ~/.claude.json on
  Claude Code as of May 2026.
author: Claude Code
version: 1.0.0
date: 2026-05-07
---

# Claude Code MCP migration slice for ~/.claude.json

## Problem

`~/.claude.json` is the canonical source of truth for Claude Code's MCP
configuration, but it ALSO holds everything from project bookkeeping and
chat history hints to startup counters and feature-flag caches. A naive
"carry the whole file" approach leaks personal state and produces a
~200KB file dominated by irrelevant content. A naive "carry only top-level
`mcpServers`" approach silently drops per-project state that materially
changes which MCP servers are active.

## Context / Trigger Conditions

Use this skill when:

- Designing a config-migration / pack-and-unpack / profile snapshot tool
  for Claude Code (e.g. a profile-sync or dotfile manager).
- About to `cp ~/.claude.json` between machines and worried about leaking
  personal state.
- A colleague asks "how do I share my MCP setup without sharing my chat
  history" and you need to give them an exact key list.
- Building a sync layer that diffs MCP config between two Claude Code
  installs and you need to know which keys to compare.

## Solution

The MCP-relevant slice of `~/.claude.json` is exactly **4 keys** across
two scopes. Carry these; drop everything else.

### User scope (top level of `~/.claude.json`)

| Key | What it holds |
|---|---|
| `mcpServers` | Map of `name -> server config` for all user-scope MCP servers (the ones you `claude mcp add` without `--project`). On a working dev box this typically has 10-30 entries: `filesystem`, `github`, `playwright`, vendor MCPs, etc. |

### Project scope (each `projects[<absolute-path>]` entry)

| Key | What it holds |
|---|---|
| `mcpServers` | Map of `name -> server config` for project-specific user-scope additions. NOT the same as the project's `.mcp.json` file — these are entries the user added while working in that project that are scoped to that project. |
| `enabledMcpjsonServers` | List of server names from the project's checked-in `.mcp.json` file that the user has approved. Without this list, the team-shared `.mcp.json` servers stay disabled on the new machine even though the file is present. |
| `disabledMcpjsonServers` | List of server names from the project's `.mcp.json` that the user has explicitly disabled. Carried so a new machine reproduces the same disabled-state, not silently re-enables them. |

### Everything else is NOT MCP state

These keys appear at the top level or under `projects[<path>]` and should
**not** be carried for MCP migration:

- Top level: `numStartups`, `installMethod`, `autoUpdates`,
  `hasSeenTasksHint`, `hasUsedStash`, `customApiKeyResponses`,
  `tipsHistory`, `memoryUsageCount`, `cachedDynamicConfigs`,
  `cachedGrowthBookFeatures`, `cachedStatsigGates`, `firstStartTime`,
  `userID`, `appleTerminalSetupInProgress`, `hasCompletedOnboarding`,
  `subscriptionNoticeCount`, `changelogLastFetched`,
  `lastReleaseNotesSeen`, etc.
- Per project: `allowedTools`, `mcpContextUris`, `hasTrustDialogAccepted`,
  `projectOnboardingSeenCount`, `hasClaudeMdExternalIncludesApproved`,
  `lastTotalWebSearchRequests`, history-shaped lists.

These are session bookkeeping, feature flags, or volatile machine-local
state. Carrying them either leaks personal info or causes incorrect
behavior on the new machine.

## Verification

```python
import json
from pathlib import Path

with open(Path.home() / ".claude.json") as f:
    full = json.load(f)

slice_ = {}
if full.get("mcpServers"):
    slice_["mcpServers"] = full["mcpServers"]

projects_out = {}
for path, project in (full.get("projects") or {}).items():
    project_slice = {}
    for key in ("mcpServers", "enabledMcpjsonServers", "disabledMcpjsonServers"):
        value = project.get(key)
        if value:
            project_slice[key] = value
    if project_slice:
        projects_out[path] = project_slice
if projects_out:
    slice_["projects"] = projects_out

print("slice top-level keys:", list(slice_.keys()))
print("user-scope server count:", len(slice_.get("mcpServers", {})))
print("projects with mcp state:", len(slice_.get("projects", {})))
print("slice size vs full:",
      len(json.dumps(slice_)), "/", len(json.dumps(full)))
```

Expected on a populated box: slice keys are exactly `["mcpServers",
"projects"]`, slice JSON is ~5-15% the size of the full file, and
nothing in the slice resembles personal history or session bookkeeping.

To verify the slice is sufficient (round-trip), merge it into a synthetic
fresh `~/.claude.json` on a target machine and confirm `claude mcp list`
shows the same servers and Claude Code respects the same project-scope
.mcp.json enable/disable choices.

## Example

A migration tool's pack/unpack uses exactly this slice — an
`extract_slice` / `merge_slice` pair over `~/.claude.json`, paired with a
backup-before-write pattern that retains the last 10 versions of
`~/.claude.json` under a tool-owned backups directory.

A naive `cp ~/.claude.json` on a real dev box copies ~200KB of which
~85-95% is irrelevant. Slice extraction reduces it to a few KB and
removes all personal state.

## Notes

- **`.mcp.json` files are separate.** `~/.claude.json`'s
  `enabledMcpjsonServers`/`disabledMcpjsonServers` lists reference server
  names that come from a project's checked-in `.mcp.json` file. Migrating
  the lists without the underlying `.mcp.json` files leaves dangling
  references; migrating the `.mcp.json` files without the lists leaves
  them all disabled. For a complete project-scope sync, both must travel.

- **Truffaldino's Claude Code adapter is stale.** Truffaldino's docs
  describe Claude Code as "uses `claude mcp` CLI commands (no config
  file)". That predates Claude Code consolidating MCP config to
  `~/.claude.json`. New tooling should write directly against
  `~/.claude.json`, not shell out to `claude mcp`.

- **Backup before write.** `~/.claude.json` is also where Claude Code
  persists onboarding state, feature flags, and project trust prompts.
  Mutating it without a backup risks losing user state that lives
  alongside the MCP slice. Snapshot the file before any merge.

- **Secrets live in `mcpServers[*].env`.** Server entries can carry API
  tokens in their `env` map (e.g. `<server>.env.<SERVER>_API_TOKEN`).
  Any export/migration must redact these. A key-name blacklist of
  `token`, `secret`, `password`, `passwd` (case-insensitive substring
  match) catches the common cases.

- **Validated** against `~/.claude.json` produced by Claude Code as of
  May 2026 (89-project file, 19 user-scope MCP servers).

## References

- [Claude Code MCP documentation](https://docs.claude.com/en/docs/claude-code/mcp) — official MCP integration docs
- Where MCP configuration *lives* (settings.json vs .claude.json vs
  .mcp.json) is a separate concern; this skill complements it by
  enumerating which keys *travel* for migration.
