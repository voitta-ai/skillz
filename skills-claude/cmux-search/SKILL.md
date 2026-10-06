---
name: cmux-search
description: |
  Search across every open cmux workspace, tab, and pane at once - both live
  terminal scrollback and (optionally) agent conversation transcripts. Use when:
  (1) you remember seeing an error / URL / value in "some pane" but not which,
  (2) you want to grep the output of all surfaces simultaneously, (3) the
  built-in `cmux find-window --content` misses matches because it only scans
  workspace titles and the visible viewport, not scrollback. Covers enumerating
  surfaces with `cmux tree --all`, dumping each with `cmux read-screen
  --scrollback` (tmux alias `capture-pane`), and grepping Claude/Codex agent
  transcripts on disk for full, clean conversation history.
author: Claude Code
version: 1.1.0
date: 2026-06-10
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-search/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/cmux-search/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

# cmux-search

## Problem
A cmux window can hold dozens of terminal surfaces across many workspaces and
tabs. You recall seeing something - an error, a URL, a value, a command - in
"one of the panes" but not which. The built-in `cmux find-window --content <q>`
only matches workspace **titles** and the **visible viewport**, so anything
scrolled off-screen is silently missed.

## The three commands
- **Enumerate** every window/workspace/pane/surface (with refs + titles + ttys):
  ```bash
  cmux tree --all
  ```
- **Dump** one surface's buffer (visible screen, or full scrollback):
  ```bash
  cmux read-screen --surface <ref> --scrollback [--lines <n>]   # alias: capture-pane
  ```
  Works on ANY surface from ANY pane - pass `--surface surface:<n>` from the tree.
- **Built-in search** (shallow - titles + current viewport only, NOT scrollback):
  ```bash
  cmux find-window --content <query>        # add --select to jump to first match
  ```

Resolve the cmux binary: use `cmux` if on PATH (it is inside a cmux pane); else
`${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}`.

## Recipe 1 - grep every surface's scrollback
For real search (full scrollback, all surfaces, line-level hits), loop the tree:

```bash
#!/usr/bin/env bash
# cmux-search.sh <regex>   - grep scrollback of every open cmux surface
set -u
q="${1:?usage: cmux-search <regex>}"
cmux() { if command -v cmux >/dev/null 2>&1; then command cmux "$@";
         else "${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}" "$@"; fi; }
strip_ansi() { sed $'s/\x1b\\[[0-9;?]*[ -/]*[@-~]//g'; }

tree=$(cmux tree --all 2>/dev/null)
printf '%s\n' "$tree" | grep -oE 'surface:[0-9]+' | sort -u -t: -k2 -n | while read -r s; do
  title=$(printf '%s\n' "$tree" | grep -m1 -E "surface ${s} " | sed -E 's/.*\] "([^"]*)".*/\1/')
  cmux read-screen --surface "$s" --scrollback 2>/dev/null | strip_ansi \
    | grep -niC1 -- "$q" | sed "s|^|[${s} ${title}] |"
done
```

Notes:
- Strip ANSI (above) because agent TUIs (Claude Code, Codex) render redrawn
  color frames; raw `read-screen` output is full of escape codes.
- The surface you run this from will match its own command echo - ignore that line.

## Recipe 2 - search agent conversation history (clean + complete)
Live scrollback of an agent pane is redrawn TUI frames - noisy and lossy. The
clean, full record is the transcript on disk:

- **Claude Code:** `~/.claude/projects/<slug>/*.jsonl`, where `<slug>` is the
  project cwd with every `/` and `.` replaced by `-`
  (e.g. cwd `/Users/me/.config/cmux` -> `-Users-me--config-cmux`).
  ```bash
  grep -rl -- "<query>" ~/.claude/projects/*/*.jsonl    # which transcripts match
  ```
- **Codex:** sessions live under its own config dir (`~/.codex/`); grep there.
- Map a cmux pane -> transcript by its cwd (from `cmux tree` / the pane's
  `resumeBinding.cwd`) -> slug, when you need a specific pane's history.

## Caveats
- A surface never focused since launch may have no PTY yet (its resume command is
  queued, cmux#4187) -> `read-screen` returns empty. Focus it once to populate.
- Scrollback depth is bounded by the ghostty scrollback setting (older lines are
  gone from the buffer - use Recipe 2 for full history).
- `read-screen` returns the rendered screen, not raw bytes; very wide lines wrap.
- Read-only and safe. Do NOT add `--select` to `find-window` when only searching -
  it changes focus.

## Quick reference
| Goal | Command |
|---|---|
| List all surfaces | `cmux tree --all` |
| Dump one surface | `cmux read-screen --surface surface:N --scrollback` |
| Shallow built-in find | `cmux find-window --content <q>` |
| Deep grep all panes | Recipe 1 |
| Full agent history | Recipe 2 (transcripts on disk) |

## Related

- `cmux-session-self-identity` — this skill finds *which* surface holds a match;
  that one answers the inverse, which surface you are currently in.
- `cmux-agent-tabs` — why some agents have a searchable surface and some do not.
  A search that finds nothing may be searching a set that never included the
  agent.
- `cmux-session-restore-forensics` — recovering the transcript of a session
  whose pane is gone, which Recipe 2 can still search on disk.
