---
name: cmux-agent-tabs
description: |
  Make AI coding agents show up as watchable tabs/panes in cmux, and explain
  why some do and some don't. Use when: (1) you spawned Claude Code agents
  (teammates or Agent-tool subagents) but no cmux tabs appeared, even though
  Codex subagents tab automatically; (2) you want every agent in a multi-agent
  run to be a visible cmux surface you can watch; (3) you set
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` and expected cmux splits but got
  none; (4) you need to name/rename agent tabs consistently from the CLI. Key
  fact: the bridge is the `cmux claude-teams` launch wrapper (it prepends a
  private tmux shim to PATH); the env var alone is NOT enough. Codex tabs come
  from `cmux codex-teams` / `cmux hooks setup codex`. Also covers the two other
  causes of "no tabs": subagents spawned via the Agent tool never tab even under
  `cmux claude-teams` (they surface in Claude Code's native agent list), and the
  tmux shim can be on PATH while the `cmux` CLI itself is not installed. Also
  use when: (5) `which tmux` returns a REAL tmux and teammates run but never
  tab; (6) the shim resolves yet dies with `exec: cmux: not found`, which reads
  as a tmux bug and is not one; (7) teammates spawned from a RESUMED pane start
  an invisible real tmux server; (8) every teammate wedges with no output, no
  error and no permission dialog because teammate mode resolved to
  `in-process`; (9) you need to tell a wedged transport apart from an agent
  that was never launched at all; (10) teammates DID tab but every tab is
  titled by agent type (`general-purpose`, `general-purpose`, ...) instead of
  the name you gave it; (11) teammates stack vertically in one column and you
  want to know whether cmux or Claude Code chose that; (12) `which tmux`
  resolves to `.../cmux-cli-shims/<uuid>/tmux` and you are not sure that is
  the shim.
author: Claude Code
version: 1.4.0
date: 2026-08-26
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-agent-tabs/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/cmux-agent-tabs/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.
>
> Companion: the [cmux setup](https://blog.debedb.com/2026/06/17/cmux-setup/)
> post covers running Claude Teams + OMX (Oh My Codex) workspaces and surviving
> reboots; this skill covers why agents do/don't appear as tabs. The follow-up
> [two-hop PATH trap](https://blog.debedb.com/2026/08/10/cmux-eight-weeks-later-the-two-hop-path-trap/)
> post is the worked example behind the two-hop section below.

# cmux-agent-tabs

## Problem
You run a multi-agent session and want each agent visible as its own cmux
surface. **Codex** subagents show up automatically. **Claude Code** agents often
do **not** - either because the session wasn't launched through the
`cmux claude-teams` wrapper, or because they were spawned via the **Agent tool**,
whose subagents run in Claude Code's own subagent runtime and never become cmux
tabs at all. The runtimes integrate with cmux asymmetrically.

## Why the asymmetry
- **Codex:** `cmux codex-teams` starts a private Codex app-server, watches live
  Codex thread-spawn subagents, and opens them (up to depth 2) as native cmux
  splits. Tabs appear with no extra work.
- **Claude Code:** the bridge is the **`cmux claude-teams` launch wrapper**, not
  an environment variable. That wrapper:
  - defaults Claude teammate mode to `auto`,
  - sets a tmux-like environment, and
  - **prepends a private tmux shim to PATH** that translates tmux window/pane
    commands into cmux workspace/split operations.

  Claude's auto teammate mode creates splits by shelling out to `tmux`; the shim
  is what turns those into cmux surfaces. If the session was started *without*
  `cmux claude-teams`, the shim is absent and teammates never reach cmux - even
  when `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set.

## The other cause: Agent-tool subagents never tab
Missing tabs are **not** always a launch-wrapper problem. Subagents spawned via
Claude Code's **Agent tool** run in Claude Code's own subagent runtime, which
does not shell out to `tmux` at all. Launching correctly through
`cmux claude-teams` does not make them tab - a run started that way, with the
shim on PATH and `TMUX` set, can spawn six Agent-tool subagents and produce zero
new windows:
```bash
~/.cmuxterm/claude-teams-bin/tmux list-windows -a   # only your pre-existing windows
```
They are still watchable and steerable - just elsewhere. They render in Claude
Code's in-TUI agent list under the `main` node with live elapsed time, and are
addressable by name via `SendMessage`:
```
● main
○ yolt-67-dev  You are the DEVELOPER for issue #67 ...   2m 59s
○ yolt-68-dev  You are the DEVELOPER for issue #68 ...   2m 34s
```
So: **teammate spawning + `cmux claude-teams` => cmux tabs; Agent tool => native
agent list.** Diagnose the spawn path before re-launching the session.

**Version note (Claude Code 2.1.24x):** with agent teams enabled, an Agent-tool
call that carries a `name` (`Agent(name: "pinger", subagent_type:
"general-purpose", ...)`) is a *teammate* spawn and **does** tab - the lead
reports "2 background agents launched" and two panes open through the shim.
The never-tabs case above is the unnamed subagent. Look at the `Agent` input
in the transcript before concluding which path was taken.

## Diagnose in 5 seconds
Run inside the session's shell:
```bash
echo "AGENT_TEAMS=${CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS:-<unset>}  TMUX=${TMUX:-<unset>}"
which tmux        # the cmux claude-teams shim, if active
which cmux        # the cmux CLI itself - separate from the shim
```
- `tmux: command not found` and/or `TMUX` unset => the `claude-teams` shim is
  **not** active => Claude teammates will NOT tab. (The env var may still be set
  and is a red herring on its own.)
- `which tmux` resolves to a **real tmux** (e.g. `/opt/homebrew/bin/tmux`) =>
  the shim is *shadowed*, not missing. This is hop one below, and it is the
  case a "command not found" check silently passes.
- Shim present and `TMUX` set, but `cmux: command not found` => **not merely a
  naming problem.** The shim body execs bare `cmux`, so tmux itself fails. This
  is hop two below.
- Shim present, `TMUX` set, `cmux` CLI present, and **still** no new tabs => the
  agents were spawned through **Claude Code's Agent tool**, not teammate
  spawning. See the section above - this is a different cause and the launch
  wrapper is not the problem.

## The two-hop PATH trap

The bridge rests on `PATH` resolution in **two** places, and winning one hop
buys nothing if the other loses. Both failures present as "teammates don't
tab", and neither is a missing-shim error.

### Hop one: which `tmux` wins

The shim lives at `~/.cmuxterm/claude-teams-bin/tmux`:

```bash
#!/usr/bin/env bash
exec "${CMUX_CLAUDE_TEAMS_CMUX_BIN:-cmux}" __tmux-compat "$@"
```

cmux also sets `$TMUX` to a synthetic socket path. No tmux server exists
anywhere - Claude Code thinks it is talking to tmux, cmux answers, and each
`new-window` becomes a tab. When healthy, `tmux -V` returns `tmux 3.4` and
`tmux list-windows` enumerates your cmux workspaces as tmux windows.

If the launching process resolves `tmux` to a **real** tmux instead of the
shim, real tmux tries to connect to a socket that was never a socket:

```
error connecting to /tmp/cmux-claude-teams/... (No such file or directory)
```

Teammates then run but do not tab - no watchable panes. Typical cause is a
`PATH` re-prepend that floats a package manager's `bin` ahead of the shim,
from the workspace command itself, from `.bash_profile`, or from `path_helper`
re-floating it after cmux prepends.

Fix by prepending the shim directory in the launch command:

```bash
export PATH="$HOME/.cmuxterm/claude-teams-bin:$PATH"
```

**Version note:** on cmux 0.64.16 `cmux claude-teams` already puts the shim at
`PATH` position 1 itself. The prepend is belt-and-braces on current builds, not
the load-bearing fix - which matters, because assuming it is the fix sends you
looking in the wrong place.

**Version note (cmux 0.64.22): the shim moved.** `cmux claude-teams` now writes
`tmux` into the launching surface's private shim directory,
`$TMPDIR/cmux-cli-shims/<surface-uuid>/` (next to the `claude` and `codex`
wrappers it already keeps there), and puts that directory first on `PATH`. In a
real team lead, `which tmux` resolves there, not to
`~/.cmuxterm/claude-teams-bin/tmux`. Consequences:

- A `which tmux` pre-flight must accept **either** location as "shim present".
- Anything you hang on the legacy path - a logging wrapper, an
  `CMUX_CLAUDE_TEAMS_CMUX_BIN` export in the workspace command - never runs.
  A wrapper installed there logged zero bytes through a real spawn. The
  per-surface shim honours `CMUX_CLAUDE_TEAMS_CMUX_BIN` only if it is set in
  the *teammate's* environment, and `cmux claude-teams` sets it itself.
- The old directory still exists and still works when reached; it is simply
  no longer what gets called.

A same-session `export PATH=` does **not** help: the parent `claude` already
resolved its environment, and each teammate spawn does a fresh `execvp("tmux")`
against the parent's `PATH`, not a subshell's. Fix it in the launch path and
relaunch.

### Hop two: the shim's own `cmux`

Look at the shim again - it execs **bare `cmux`**. The bundled binary is at
`/Applications/cmux.app/Contents/Resources/bin/cmux`, which is **not** on a
normal login shell's `PATH`:

```bash
$ env -i HOME=$HOME /bin/bash -lc 'command -v cmux'
$
```

So winning hop one buys you nothing if hop two loses:

```bash
$ env -i HOME=$HOME /bin/bash -lc \
    'export PATH="$HOME/.cmuxterm/claude-teams-bin:$PATH"; tmux -V'
.../claude-teams-bin/tmux: line 3: exec: cmux: not found
```

One symlink fixes it (it shadows nothing):

```bash
ln -s /Applications/cmux.app/Contents/Resources/bin/cmux ~/.local/bin/cmux
```

**Test both hops in one shot** - this is the check that matters, and it must
print `tmux 3.4`:

```bash
env -i HOME=$HOME /bin/bash -lc \
  'export PATH="$HOME/.cmuxterm/claude-teams-bin:$PATH"; tmux -V'
```

The general law, worth carrying to any shim-based transport: **a shim that is
on `PATH` but whose own dependency is off `PATH` fails in a way that reads as a
bug in whatever subsystem the shim impersonates.** Here it reads as a tmux
problem and is not one.

## Telling "wedged" apart from "never launched"

A queued teammate and a shadowed shim look identical from outside: the pane
sits there, nothing tabs. One check separates them.

**If `ps` shows no `__tmux-compat` process ever appeared, the spawn never
reached tmux - so `PATH` is not your problem.** A launcher pane showing
`manual mode on` leaves teammates at their pending marker indefinitely, having
called nothing at all. Check this before spending an evening on `PATH`.

The companion habit: **read the live process environment, not the shell's.** A
pane's shell will happily report a `PATH` the long-running agent inside it
never saw.

```bash
ps -Eww -o command= -p <pid> | tr ' ' '\n' | grep -E '^(TMUX|PATH)='
```

## Resumed panes are a different, weaker case

An agent-hook-resumed pane has **neither `$TMUX` nor the shim directory** -
confirmed by reading the live process env as above. With no `$TMUX`, a `tmux`
teammate mode there starts a **real tmux server**, whose windows are invisible
from cmux.

Two consequences:

- A CLI flag in the workspace command covers only freshly opened workspaces.
  cmux's `agent-hook` rewrites each pane's resume command to call `claude`
  directly rather than the `cmux claude-teams` wrapper, so resumed panes never
  see that flag.
- **Operating rule: start team runs from the `claude-teams` workspace command,
  never from a resumed pane.**

## Teammate mode: `auto` can silently pick `in-process`

Distinct from `PATH`, same symptom class, worse failure. The wrapper defaults
teammate mode to `auto`, and `auto` can resolve to **`in-process`** - which
gives the teammate no cmux pane and therefore **no TTY**. Every background
subagent then wedges: first tool call never returns, no result, no error, no
timeout, and no permission dialog or pending indicator anywhere in the TUI,
because a prompt has nowhere to render.

Allowed values (not in `claude --help`; obtain them by passing an invalid one):
`auto, tmux, iterm2, in-process`.

**Fix it in settings, not with a CLI flag.** `teammateMode` is a top-level
Claude Code settings key, so it applies to every launch path including resumed
panes:

```jsonc
// ~/.claude/settings.json
{ "teammateMode": "tmux" }
```

Setting the mode is necessary but not sufficient - the shim must also win both
`PATH` hops above. And do **not** reach for a bypass-permissions flag here:
issuing the same operation from a pane that *does* have a TTY returns
instantly, which proves the parent is already permissive and the call never
reached the permission layer at all. Bypassing that layer fixes nothing and
costs real safety.

## Fix
- **Claude agents as tabs:** launch the root session through the wrapper:
  ```bash
  cmux claude-teams [claude-args...]      # e.g. cmux claude-teams --model opus
  ```
  Then teammate spawns auto-open as cmux splits. There is no config-file toggle;
  it must be in the launch path. (Claude Code cmux hooks are injected
  automatically by this wrapper.)
- **Codex agents as tabs:** run under `cmux codex-teams`, or install the hook:
  ```bash
  cmux hooks setup codex        # also: grok, gemini, opencode, amp, cursor, ...
  ```

## Tabs titled by agent type, not by name

Symptom: teammates tab, but every tab reads `general-purpose` (or whatever
`subagent_type` was), and only the pane's own footer shows `@pinger`.

Claude Code's tmux backend names each teammate pane right after creating it:

```
split-window -d -t <leader> -h -l 70% -P -F '#{pane_id}' -- <cmd>
select-pane -t <pane> -T <name>
set-option -p -t <pane> pane-border-format '#[fg=<color>,bold] #{pane_title} #[default]'
```

cmux's compat layer (through 0.64.22) accepts `select-pane -T` with exit 0 and
does nothing. Check it yourself, on your own tab, and it is harmless:

```bash
P=$(cmux __tmux-compat display-message -p '#{pane_id}')
cmux __tmux-compat select-pane -t "$P" -T probe; echo rc=$?   # rc=0
cmux list-panels                                             # title unchanged
```

So the name is dropped and the tab falls back to the auto-title, which is the
teammate TUI's identity line `@<agent_type>`. Five agents of one type give five
identical tabs.

- **Workaround that sticks:** `cmux tab-action --action rename --tab surface:N
  --title <name>` after each spawn (custom names beat auto-titles).
- **Upstream:** manaflow-ai/cmux#10190, fixed by PR #10198 (merged
  2026-08-17) by reading `--agent-name` from the teammate's argv - not by
  honouring `-T`, which stays a no-op. Unreleased as of 0.64.22; the same PR
  also runs teammate respawns through `/bin/sh -lc`, so teammate hooks get the
  login `PATH` (until then, hooks that call bare `node` fail in teammate
  panes with `/bin/sh: node: command not found`).

## The vertical stack is Claude Code's layout, not cmux's

Teammates appear stacked in one column to the right of the leader. That is the
layout Claude Code asks for, faithfully applied: first teammate
`split-window -h -l 70%` off the leader; each later one splits the *middle*
teammate (`-v` on odd counts, `-h` on even); then `select-layout main-vertical`
and `resize-pane -x 30%` on the leader. There is no Claude-side setting for it
(`main-horizontal`, `teammateLayout` do not exist in the binary; the only knob
in that area is `CLAUDE_CODE_TEAMMATE_COMMAND`). Rearranging is a cmux action
after the spawn, and a feature request in either project, not a config fix.

## Name and rename tabs from the CLI
Consistent naming makes a multi-agent run legible. A useful convention is
`<project>-<issue>-<role>` (e.g. `dd-93-dev`, `dd-93-rev`, `dd-93-qa`).
```bash
cmux tree --all                                              # list surfaces + refs
cmux tab-action --action rename --tab surface:16 --title "dd-integrator"
cmux tab-action --action clear-name --tab surface:16        # revert to auto title
```
`--tab` accepts `surface:<n>` or `tab:<n>`; defaults to `$CMUX_TAB_ID` /
`$CMUX_SURFACE_ID` / the focused tab.

## Caveats
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` being present does **not** imply the
  cmux bridge is active - always check for the tmux shim.
- The tmux shim and the `cmux` CLI install separately, and a missing CLI is
  **not** merely a lost-tooling inconvenience: the shim execs bare `cmux`, so
  with the CLI off `PATH` the shim itself dies with `exec: cmux: not found` and
  tabbing fails outright. See the two-hop section.
- "No tabs" has **six** distinct causes - wrong launch path, Agent-tool spawn
  path, shadowed shim (hop one), shim's own `cmux` off `PATH` (hop two), a
  resumed pane with no `$TMUX`, and a teammate mode that resolved to
  `in-process`. Only the first is fixed by re-launching alone, and the
  never-launched case is fixed by nothing environmental at all.
- `cmux open <path-or-url>` opens files/dirs/URLs (markdown/file/browser
  previews); it is **not** a way to spawn a terminal running a chosen command in
  a titled tab. Don't reach for it to "open an agent in a tab."
- The shim translates a supported subset of tmux window/pane commands; exotic
  tmux usage may not map.

## Quick reference
| Goal | Command |
|---|---|
| Claude teammates -> cmux tabs | launch via `cmux claude-teams ...` |
| Claude Agent-tool subagents | unnamed: never tab - native agent list, steer via `SendMessage`. Named (`Agent(name: ...)`, 2.1.24x + agent teams): teammates, they tab |
| Tabs all say `general-purpose` | cmux <= 0.64.22 ignores `select-pane -T`; rename with `cmux tab-action --action rename`, or update past cmux PR #10198 |
| Teammates stacked in a column | Claude Code's `main-vertical` layout; no setting |
| `which tmux` -> `.../cmux-cli-shims/<uuid>/tmux` | the shim, on 0.64.22+ (moved from `~/.cmuxterm/claude-teams-bin`) |
| Codex agents -> cmux tabs | `cmux codex-teams ...` or `cmux hooks setup codex` |
| Is the Claude bridge active? | `which tmux` (shim present) + `TMUX` set |
| Can I name tabs at all? | `which cmux` (CLI present, separate from the shim) |
| Both PATH hops healthy? | `env -i HOME=$HOME /bin/bash -lc 'export PATH="$HOME/.cmuxterm/claude-teams-bin:$PATH"; tmux -V'` -> `tmux 3.4` |
| Shim shadowed by real tmux? | `which tmux` -> must NOT be `/opt/homebrew/bin/tmux` |
| Shim's own `cmux` reachable? | `ln -s /Applications/cmux.app/Contents/Resources/bin/cmux ~/.local/bin/cmux` |
| Wedged or never launched? | `ps` for a `__tmux-compat` process; absent => spawn never reached tmux |
| What env did the agent really get? | `ps -Eww -o command= -p <pid> \| tr ' ' '\n' \| grep -E '^(TMUX\|PATH)='` |
| Teammates wedge with no prompt | set `"teammateMode": "tmux"` in `~/.claude/settings.json` |
| List surfaces + refs | `cmux tree --all` |
| Rename a tab | `cmux tab-action --action rename --tab surface:N --title "..."` |

## Related

- `cmux-session-self-identity` — once an agent *has* a tab, working out which
  one it is from inside the session. The environment lies in the same ways this
  skill's `PATH` trap describes.
- `cmux-session-restore-forensics` — what happens to those tabs across a
  quit/relaunch, and how to recover the ones that do not come back. The
  "resumed panes are a different, weaker case" section above is the short form.
- `cmux-autoresume-after-reboot` — the reboot-specific version of the same
  question, including the gate that returns panes as fresh agents.
- `cmux-search` — grepping across every tab this skill helped you create.
- `claude-code-cross-session-messaging` and `cmux-cross-session-visibility` —
  addressing and watching the agents once they are on surfaces.
- `cmux-config-silent-drop-triage` — when the palette action or surface button
  that would create one of these tabs is defined, validates clean, and simply
  is not there.
