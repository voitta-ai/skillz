---
name: claude-code-plugin-from-existing-repo
description: |
  Convert an existing repo that ships Claude Code slash commands and/or hooks
  (typically as a dotclaude/ or .claude/ directory the user copies into their
  project) into a Claude Code plugin so users can install with
  `/plugin marketplace add OWNER/REPO` + `/plugin install NAME@MARKETPLACE`.
  Use when: (1) repo currently has a commands/ + hooks/ layout meant for
  manual copy-into-project install, (2) you want to add plugin install
  without breaking the manual install path, (3) confused about where
  marketplace.json vs plugin.json live, (4) confused about which env var
  the plugin's hooks should reference, (5) the installed plugin shows
  "failed to load" with `Duplicate hooks file detected` after you declared
  a `hooks` pointer in plugin.json. Covers coexistence of manual and
  plugin install via a shared source directory.
author: Claude Code
version: 1.2.0
date: 2026-05-10
---

# Convert an existing slash-commands+hooks repo into a Claude Code plugin

## Problem

Many repos ship Claude Code customizations as a `dotclaude/` (or `.claude/`)
directory that users copy into their project root. Migrating to the plugin
system removes the copy step (and any rename dance for sandboxed environments
that block writing to `.claude/`). The non-obvious parts:

- Where `marketplace.json` and `plugin.json` actually live
- What the `source` field in `marketplace.json` means
- Which environment variable plugin hooks reference vs manual-install hooks
- How to keep the manual install path working alongside the plugin path

## Context / Trigger Conditions

- Repo has `dotclaude/commands/*.md` and/or `dotclaude/hooks/*` and a
  README telling users to copy + rename
- Adding plugin install without breaking existing users
- Users in sandboxed environments who couldn't write to `.claude/`
- `${CLAUDE_PLUGIN_ROOT}` vs `$CLAUDE_PROJECT_DIR` confusion

## Solution

### File layout (coexistence-friendly)

Keep the existing `dotclaude/` directory as the plugin's source. Add three
new files:

```
repo-root/
├── .claude-plugin/
│   └── marketplace.json          ← marketplace manifest (always at repo root)
├── dotclaude/                    ← unchanged manual-install dir, doubles as plugin source
│   ├── .claude-plugin/
│   │   └── plugin.json           ← plugin manifest, lives under <source>/.claude-plugin/
│   ├── commands/                 ← unchanged
│   │   └── *.md
│   ├── hooks/
│   │   ├── hooks.json            ← NEW: plugin hook registration (uses ${CLAUDE_PLUGIN_ROOT})
│   │   ├── load_X.py             ← unchanged hook scripts
│   │   └── load_X.sh
│   └── settings.json             ← UNCHANGED: still used by manual install only
```

### `.claude-plugin/marketplace.json` (at repo root)

```json
{
  "name": "my-thing",
  "owner": { "name": "my-org" },
  "description": "...",
  "plugins": [
    {
      "name": "my-thing",
      "source": "./dotclaude",
      "description": "..."
    }
  ]
}
```

**Key fact**: `source` is relative to the repo root and points at the plugin's
own root. It can be `"./"` (entire repo) OR a subdirectory like `"./dotclaude"`.
Plugin file discovery (`commands/`, `hooks/hooks.json`, `.claude-plugin/plugin.json`)
is relative to `source`, NOT to the repo root.

### `<source>/.claude-plugin/plugin.json` (e.g. `dotclaude/.claude-plugin/plugin.json`)

```json
{
  "name": "my-thing",
  "description": "...",
  "version": "0.1.0",
  "author": { "name": "my-org" },
  "homepage": "https://github.com/my-org/my-thing",
  "repository": "https://github.com/my-org/my-thing",
  "license": "MIT"
}
```

### `<source>/hooks/hooks.json`

For each hook registered by the existing manual `settings.json`, mirror the
registration here BUT swap the env var:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/load_X.py\""
          }
        ]
      }
    ]
  }
}
```

**Critical env var distinction**:
- Manual install (`dotclaude/settings.json`): hook command references
  `$CLAUDE_PROJECT_DIR/.claude/hooks/...` because the hook script lives
  inside the user's project copy of `.claude/`.
- Plugin install (`<source>/hooks/hooks.json`): hook command references
  `${CLAUDE_PLUGIN_ROOT}/hooks/...` because the hook script lives inside
  the plugin's source directory (Claude Code clones the marketplace
  somewhere and sets this env var to that path).

Hook **scripts themselves** typically read `CLAUDE_PROJECT_DIR` to find files
in the user's project root (e.g. `GOAL.md`) — that still works under plugin
install because Claude Code sets it for both install modes.

### Do NOT also declare `hooks` in plugin.json when the file is at the auto-load path

`<source>/hooks/hooks.json` is discovered automatically. Declaring it a second
time in `plugin.json`:

```json
"hooks": "./hooks/hooks.json"
```

makes the loader resolve the same file twice, and the whole plugin fails to
load — `claude plugin list` shows it as failed, with:

```
Duplicate hooks file detected: ./hooks/hooks.json resolves to already-loaded file
```

The failure is easy to misread as a marketplace or update problem because it
surfaces after an install/update, but it is the manifest: delete the `hooks`
line from `plugin.json`. Reserve that field for a hooks file at a
NON-default path; when the file already sits at `<source>/hooks/hooks.json`,
the pointer is not merely redundant, it is fatal.

## Verification

1. From a fresh Claude Code session in any directory:
   ```
   /plugin marketplace add OWNER/REPO
   /plugin install NAME@MARKETPLACE
   ```
2. Verify the slash commands appear (e.g. `/my-command`)
3. Verify the hook fires (check expected stdout in a new session)
4. `/plugin uninstall NAME@MARKETPLACE` cleans up

## Example

Worked example: converting a forked repo that ships a `dotclaude/`
directory into a plugin:

- Added `.claude-plugin/marketplace.json` with `source: "./dotclaude"`
- Added `dotclaude/.claude-plugin/plugin.json`
- Added `dotclaude/hooks/hooks.json` for SessionStart, referencing
  `${CLAUDE_PLUGIN_ROOT}/hooks/load_goal.py`
- Left `dotclaude/settings.json` untouched (still works for manual install)
- README gained "Install as a Claude Code plugin (recommended)" section;
  existing manual install demoted to "(legacy)"

Total diff: 4 files, 76 insertions.

## Notes

- The marketplace.json `source` field NEVER includes a trailing slash in
  the canonical examples.
- `${CLAUDE_PLUGIN_ROOT}` is set per-plugin, not per-marketplace; if a
  marketplace ships multiple plugins, each has its own root.
- If a single repo ships ONE plugin and you don't already have a
  `dotclaude/` directory, set `source: "./"` and put everything at repo
  root — this is the common single-plugin-at-repo-root layout.
- To enable issues on a fork before filing PR-related issues, see
  `gh-fork-issues-disabled` in [voitta-ai/skillz-memory](https://github.com/voitta-ai/skillz-memory). It moved
  there in skillz#91 as a memory-tier specific and is no longer a skill in
  this catalog.

## References

- [Claude Code plugins documentation](https://code.claude.com/docs/en/plugins)
- Reference pattern: a single-plugin repo using `source: "./"` (everything at repo root)
- Reference pattern: a repo using `source: "./dotclaude"` with manual-install coexistence

## Related

The plugin lifecycle, in the order you hit it. This skill is step one.

- `claude-code-plugin-python-bootstrap` — next, if any hook you just packaged
  imports a third-party module. `/plugin install` succeeds and the hook silently
  no-ops on a machine without it.
- `claude-code-codex-plugin-parity` — porting the result to Codex CLI, and what
  the two plugin systems share versus what has to be written twice.
- `claude-code-plugin-release-automation` — making the repo tag and publish
  itself once it is a plugin, and making the version bump non-optional.
- `claude-code-plugin-update-flow` — why an unbumped version means your merges
  never reach anyone, which is the failure the step above exists to prevent.
- `claude-code-plugin-publish-anthropic-marketplace` — getting listed in
  Anthropic's directory, which is a submission, not a PR.
