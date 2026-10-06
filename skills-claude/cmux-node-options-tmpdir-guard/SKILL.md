---
name: cmux-node-options-tmpdir-guard
description: |
  Keep cmux's Claude NODE_OPTIONS restore guard alive when it lives under $TMPDIR.
  Use when: (1) a long-lived cmux/Claude session suddenly has every `node`/`claude`
  invocation fail with a missing `--require` target, (2) NODE_OPTIONS points at
  /var/folders/.../T/cmux-claude-node-options/restore-node-options.cjs on a cmux
  build that predates manaflow-ai/cmux#3699, (3) reboot-surviving cmux sessions
  break after ~3 days idle. Root cause: macOS reaps $TMPDIR files untouched ~3
  days; the required guard file vanishes while NODE_OPTIONS still references it.
  Stopgap: persistent HOME copy + a LaunchAgent that recreates and mtime-refreshes
  the $TMPDIR file daily. Retire once on a build that writes the guard under $HOME.
author: Claude Code
version: 1.0.0
date: 2026-07-25
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-node-options-tmpdir-guard/SKILL.md
---

# cmux NODE_OPTIONS $TMPDIR guard survival

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/cmux-node-options-tmpdir-guard/SKILL.md`).


## Problem

cmux launches Claude Code with a `--require` shim to restore the user's original
`NODE_OPTIONS` inside the agent:

```
NODE_OPTIONS=--require=$TMPDIR/cmux-claude-node-options/restore-node-options.cjs --max-old-space-size=4096
```

That required `.cjs` lives under `$TMPDIR` (`/var/folders/.../T`). macOS reaps
files there that go untouched for ~3 days. A cmux/Claude session that outlives that
window (exactly what a reboot-surviving setup encourages) loses the file while
`NODE_OPTIONS` still points at it, so **every** subsequent `node`/`claude`
invocation in the session dies on a missing `--require` target.

Upstream fix: [manaflow-ai/cmux#3699](https://github.com/manaflow-ai/cmux/pull/3699)
(closes #3463) writes the guard under `$HOME/.claude/cmux` instead. Builds predating
it still use `$TMPDIR`.

## Context / Trigger Conditions

- `echo $NODE_OPTIONS` shows a `--require=/var/folders/.../T/cmux-claude-node-options/...` path.
- `~/.claude/cmux/` does not exist (fix #3699 not present).
- Node/Claude subprocesses fail referencing a missing `restore-node-options.cjs`.
- Applies to macOS + a cmux build older than the one that lands #3699.

## Solution

The guard content is static and session-independent, so one persistent copy under
`$HOME` covers every session. A LaunchAgent recreates the `$TMPDIR` file and
refreshes its mtime daily — well inside the ~3-day reap window.

1. Persistent copy (source of truth):

```bash
mkdir -p ~/.claude/cmux/cmux-claude-node-options
cp "$TMPDIR/cmux-claude-node-options/restore-node-options.cjs" \
   ~/.claude/cmux/cmux-claude-node-options/restore-node-options.cjs
```

2. Refresh script `~/.claude/cmux/refresh-node-options-guard.sh` (chmod +x):

```bash
#!/usr/bin/env bash
set -euo pipefail
src="$HOME/.claude/cmux/cmux-claude-node-options/restore-node-options.cjs"
tmpbase="$(getconf DARWIN_USER_TEMP_DIR 2>/dev/null || echo "${TMPDIR:-/tmp}")"
dst_dir="${tmpbase%/}/cmux-claude-node-options"
dst="$dst_dir/restore-node-options.cjs"
[ -f "$src" ] || exit 0
mkdir -p "$dst_dir"
cp -f "$src" "$dst"   # cp refreshes mtime, resetting the reaper clock
```

3. LaunchAgent `~/Library/LaunchAgents/<label>.plist` (RunAtLoad + `StartInterval`
   86400), `ProgramArguments` = `/bin/bash <script>`. Load with the modern API:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist
launchctl kickstart -k gui/$(id -u)/<label>
```

## Why it works (key subtlety)

A LaunchAgent runs in the **same per-user launchd context** as the GUI app, so
`getconf DARWIN_USER_TEMP_DIR` inside it returns the **same** `/var/folders/.../T`
base cmux used — verified equal to `$TMPDIR`. That is what lets the agent target
the right file without hardcoding the (per-boot) path. `cp` updating mtime is what
resets the reaper's idle clock; a bare `touch` of an existing file would also work
but `cp` additionally self-heals a partially-deleted dir.

## Verification

```bash
rm -f "$TMPDIR/cmux-claude-node-options/restore-node-options.cjs"
bash ~/.claude/cmux/refresh-node-options-guard.sh
ls "$TMPDIR/cmux-claude-node-options/"    # file back, content identical, mtime=now
launchctl print gui/$(id -u)/<label> | grep 'last exit'   # last exit code = 0
```

## Notes

- Stopgap only. Once on a build with #3699, the guard lives under `$HOME`; the
  LaunchAgent becomes a harmless no-op and can be removed:
  `launchctl bootout gui/$(id -u)/<label>`.
- `StartInterval` 86400 (daily) is well inside the ~3-day reap window; do not
  stretch it near 3 days.
- Do not use deprecated `launchctl load -w`; use `bootstrap`/`kickstart`/`bootout`.

## References

- [manaflow-ai/cmux#3699](https://github.com/manaflow-ai/cmux/pull/3699) (closes #3463)
- `launchd-env-sync-session-leak` - the same class of failure from the other
  direction: a stale value synced *into* launchd rather than a guard file
  reaped out from under one.
