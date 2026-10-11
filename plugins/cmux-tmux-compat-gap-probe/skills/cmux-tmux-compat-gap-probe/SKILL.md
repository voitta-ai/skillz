---
name: cmux-tmux-compat-gap-probe
description: |
  Decide, before installing anything, whether a tool that drives tmux from the
  outside (workmux, tmux-based agent orchestrators, tmuxinator-style layout
  tools, status sidebars, wait/handshake helpers) will work under cmux's tmux
  impersonation layer (`cmux __tmux-compat`, the shim behind `cmux
  claude-teams`). Use when: (1) you are evaluating a tmux-native tool for a
  cmux desk and want the compat delta enumerated rather than discovered one
  crash at a time, (2) a tmux-driving tool fails inside cmux with
  "Unsupported tmux compatibility command: <verb>" or "Workspace target not
  found" and you need to know how many more such failures are behind it,
  (3) a tool's tmux format strings (`#{socket_path}`, `#{pid}`,
  `#{client_session}`, `#{pane_current_command}`) come back empty under cmux,
  (4) you are about to file a compat-extension issue against cmux (or an
  option-free mode against the tool) and need the exact verb list. Procedure:
  grep the tool's source for the tmux subcommands and `#{...}` variables it
  emits, diff against cmux's `docs/cli-contract.md` table, then probe every
  read-only verb live from a cmux pane. Verified on cmux 0.64.22 against
  workmux v0.1.259.
author: Claude Code
version: 1.0.0
date: 2026-09-08
source: hq#143 desk research (workmux vs cmux), 2026-09-08
source_file: skills/cmux-tmux-compat-gap-probe/SKILL.md
---

# cmux tmux-compat gap probe

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/cmux-tmux-compat-gap-probe/SKILL.md`).

## Problem

cmux is not tmux. It impersonates tmux well enough for Claude Code's agent
teams to spawn tabs (`tmux -V` answers `tmux 3.4`, `list-windows` enumerates
workspaces), and that success invites the next step: pointing a real
tmux-driving tool at it. The impersonation is a hand-written subset. A tool
that shells out to thirty tmux verbs will fail at the first unsupported one,
tell you about that one, and say nothing about the other nine. Installing
the tool, running it, and reading one error at a time is the slow way to
learn the size of the gap, and it leaves hook installers and state files
behind on your machine.

The gap can be enumerated from source and from read-only probes without
installing the tool.

## Context / Trigger Conditions

- You run cmux and want a tmux-native tool (worktree-per-task managers,
  agent status sidebars, orchestrators with a `wait` verb, layout tools).
- Inside a cmux pane a tool prints
  `Error: Unsupported tmux compatibility command: <verb>` or
  `Error: Workspace target not found: <name>`.
- A tool's tmux-format output has empty fields where a real tmux fills them.
- You are drafting an issue against cmux asking for compat coverage, or
  against the tool asking for a reduced-tmux mode, and need the list.

## Solution

### 1. Enumerate what the tool asks of tmux

Clone the tool's source (shallow is fine) and grep for subcommand string
literals and format variables. Counts matter: a verb used 28 times is the
tool's spine; one used once is a corner.

```bash
git clone -q --depth 1 <tool-repo> tool-src
grep -rhoE '"(new-window|split-window|rename-window|kill-window|select-window|capture-pane|send-keys|display-message|list-windows|list-panes|list-sessions|has-session|new-session|select-pane|resize-pane|respawn-pane|set-option|set-window-option|show-options|show-environment|set-environment|switch-client|select-layout|run-shell|if-shell|wait-for|paste-buffer|load-buffer|set-buffer|kill-pane|kill-session|kill-server|rename-session|pipe-pane|break-pane|join-pane|swap-pane|info)"' tool-src/src \
  | sort | uniq -c | sort -rn
grep -rhoE '#\{[a-z_]+\}' tool-src/src | sort | uniq -c | sort -rn
```

Also find how the tool picks its backend and its tmux binary. The common
shape is "backend = tmux when `$TMUX` is set; binary = whatever `tmux` is on
PATH", which is exactly what the cmux shim provides. Confirm rather than
assume:

```bash
grep -rn 'env::var("TMUX")\|getenv("TMUX")\|os.environ.get("TMUX")' tool-src/src
grep -rn 'Command::new("tmux")\|which("tmux")' tool-src/src
```

### 2. Read cmux's declared contract

`docs/cli-contract.md` in `manaflow-ai/cmux` has a "tmux compatibility
commands" table plus the basic verbs listed under command families. It is the
authority for what is *meant* to work, and it lags the code in both
directions, so it is a starting list, not the answer.

```bash
curl -sL https://raw.githubusercontent.com/manaflow-ai/cmux/main/docs/cli-contract.md \
  | grep -nE '^\| `[a-z-]+`' | cut -c1-120
```

### 3. Probe every read-only verb live

From inside a cmux pane, call the compat dispatcher directly with the
bundled CLI. Nothing here changes state. Feed it the tool's own format
strings so you see which fields come back empty.

```bash
C=/Applications/cmux.app/Contents/Resources/bin/cmux
$C __tmux-compat -V
$C __tmux-compat list-windows -F '#{window_id}|#{window_name}|#{window_active}|#{window_flags}'
$C __tmux-compat list-panes -a -F '#{session_name}|#{window_id}|#{pane_id}|#{pane_current_path}|#{pane_current_command}'
$C __tmux-compat display-message -p '#{session_id}|#{socket_path}|#{pid}|#{start_time}|#{client_session}'
$C __tmux-compat capture-pane -p -t "$($C __tmux-compat display-message -p '#{pane_id}')" | head -3
for v in list-sessions show-environment info show-options list-commands; do
  echo "--- $v"; $C __tmux-compat $v 2>&1 | head -2
done
$C __tmux-compat has-session -t <a-workspace-name>
```

`scripts/tmux-compat-probe` runs steps 1 and 3 together against a source
tree and prints a three-column verdict (verb, uses, cmux result).

Do **not** probe the mutating verbs (`set-option`, `new-window`, `kill-*`,
`send-keys`, `respawn-pane`, `switch-client`) on a desk with live agents. A
verb that *is* supported will do what it says to whatever pane it resolves,
and the compat layer's target resolution is part of what you are testing.
Their status comes from the contract table and from the tool's first real
run in a throwaway cmux workspace.

### 4. Write the delta as three buckets

- **Supported and verified live** (safe to rely on).
- **Unsupported** (`Unsupported tmux compatibility command`). Each is a
  filed-issue line against cmux, or a reason to ask the tool for a mode that
  avoids it.
- **Supported but semantically shifted.** cmux maps tmux *sessions* to its
  *workspaces*, so `has-session -t <name>` answers about a workspace, and
  `#{session_name}` is always `cmux`. A tool that models one tmux session
  holding many windows will find the hierarchy one level off.

## Verification

Measured on cmux 0.64.22 (2026-09-08) against workmux v0.1.259's source:

| workmux verb (uses in `src/`) | cmux `__tmux-compat` |
|---|---|
| `display-message` (28), `list-panes` (14), `list-windows` (11), `capture-pane` (1) | works, verified live; `#{session_name}` `#{session_id}` `#{window_id}` `#{window_name}` `#{window_active}` `#{window_flags}` `#{pane_id}` `#{pane_current_path}` fill |
| `wait-for` (6, the pane-ready handshake), `paste-buffer`, `load-buffer`, `resize-pane`, `respawn-pane`, `new-window`, `split-window`, `send-keys`, `kill-window`, `kill-pane`, `rename-window`, `select-window`, `select-pane` | listed in the contract; not probed (mutating) |
| `set-option` (28, all `@workmux_*` user options), `show-options` | `Unsupported tmux compatibility command` |
| `list-sessions`, `show-environment`, `info`, `list-commands` | `Unsupported tmux compatibility command` |
| `has-session -t <name>` | resolves against workspaces: `Workspace target not found: <name>` |
| `new-session`, `kill-session`, `rename-session`, `kill-server`, `switch-client`, `set-window-option`, `select-layout`, `if-shell`, `run-shell` | not in the contract table; unverified |
| `#{socket_path}` `#{pid}` `#{start_time}` `#{client_session}` `#{pane_current_command}` | accepted, return empty |

Verdict for that pair: the tool would stop at its first `set-option`. The
gap is user options (`@name` get/set), session verbs mapped onto
workspaces, and five format variables. Small enough to file, large enough
that "just try it" would have cost an install, a hook merge into
`~/.claude/settings.json`, and a state directory.

## Example

Evaluating workmux (worktree-per-task + `wait` verb) as a layer over cmux
rather than a replacement for it. Twenty minutes of grep and probes produced
the table above and two candidate issues (cmux: user options + session
mapping; workmux: an option-free mode that keeps `@workmux_*` state in its
own XDG files, which it already half does) before anything was installed.
The blog post's experiment list then starts from "expected first failure:
`set-option`" instead of from zero.

## Notes

- The dispatcher's error text is the only oracle for "unsupported"; it does
  not print a supported-verb list (`list-commands` is itself unsupported).
- The contract table under-reports: `list-windows`, `list-panes`,
  `new-window` are documented in the command-families section, not the
  compat table. Grep the whole file.
- Version-date every probe. The compat layer is the most-changed surface in
  cmux (see the two-hop PATH trap and the tmux-compat entries in its
  changelog); a verb unsupported on 0.64.22 may exist on the next build.
- The same procedure applies to any tmux impersonator, not only cmux: swap
  the dispatcher invocation for the impersonator's entry point.
- Related: `cmux-agent-tabs` (why the shim exists and how it is found on
  PATH), `cmux-session-self-identity` (why `#{session_name}` is flat).

## References

- cmux CLI contract: https://github.com/manaflow-ai/cmux/blob/main/docs/cli-contract.md
- cmux tmux-compat sources: `CLI/CMUXCLI+TmuxCompatSupport.swift`, `CLI/CMUXCLI+TmuxCompatStore.swift`
- workmux: https://github.com/raine/workmux (`src/multiplexer/tmux.rs`, `src/multiplexer/handshake.rs`, `src/multiplexer/mod.rs`)
- tmux format variables: https://man.openbsd.org/tmux#FORMATS
