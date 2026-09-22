---
name: launchd-env-sync-session-leak
description: |
  Diagnose and undo a login-environment -> launchd sync that was run from
  inside a terminal multiplexer pane or an AI-agent session, so the session's
  own identity (PROMPT_COMMAND, CMUX_*, CLAUDECODE, CLAUDE_CODE_*, NODE_OPTIONS,
  GHOSTTY_*, TERMINFO) became the user-domain environment of every
  Spotlight-launched app and every launchd service bootstrapped afterwards.
  Use when: (1) a plain Terminal.app window prints
  `-bash: _cmux_prompt_command: command not found` (or any `command not found`
  naming a prompt hook) at every prompt while the same shell is fine inside
  the multiplexer; (2) `launchctl getenv PROMPT_COMMAND` or `launchctl print
  gui/$(id -u)` shows `CMUX_*`, `CLAUDE_CODE_*`, `CLAUDECODE` or a
  `NODE_OPTIONS=--require=<$TMPDIR path>`; (3) a launchd service's
  `inherited environment` carries a dead agent messaging socket or an agent
  session id; (4) `node` under a launchd service dies with `Cannot find
  module` on a `$TMPDIR` path it never asked for; (5) you maintain a sync
  script built on `compgen -e` / `env` and want the denylist that keeps it
  from ever doing this. Encodes the detection signature, the exact split
  between who is immune (multiplexer panes) and who is not (Spotlight apps,
  services), the purge, the reload order that actually clears a service, and
  the `bootout` race that leaves it DOWN.
author: Claude Code
version: 1.2.0
date: 2026-08-28
source: https://github.com/voitta-ai/skillz
source_file: skills/launchd-env-sync-session-leak/SKILL.md
---

# launchd-env-sync-session-leak

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/launchd-env-sync-session-leak/SKILL.md`).

## Problem

macOS launchd does not read `~/.bash_profile`, so people keep a sync script
that pushes the login shell's exports into launchd's user domain
(`launchctl setenv NAME VALUE` per variable) so Spotlight-launched apps and
launchd services see the same variables a terminal does. The robust way to
write that script is to read the *live* environment (`compgen -e`, `env`)
rather than to grep `^export` out of one profile file, because a text scan
misses everything sourced files define.

The live environment has a failure mode the text scan did not: **it includes
the session you run the script from.** Run it from a cmux pane hosting Claude
Code and the exported set carries:

| family | examples | what it does downstream |
|---|---|---|
| prompt hook | `PROMPT_COMMAND=_cmux_prompt_command` | every plain bash prints `command not found` at each prompt; the function only exists after the multiplexer's integration is sourced |
| multiplexer identity | ~30 `CMUX_*`: `CMUX_SURFACE_ID`, `CMUX_TAB_ID`, `CMUX_SOCKET_PATH`, `CMUX_CLAUDE_WRAPPER_SHIM`, `CMUX_AGENT_LAUNCH_*` | any multiplexer CLI call addresses a stale surface; shim paths point into a `$TMPDIR` that is gone |
| agent identity | `CLAUDECODE=1`, `CLAUDE_CODE_CHILD_SESSION=1`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_SOCKET`, `CLAUDE_CODE_MESSAGING_TOKEN`, `CLAUDE_PID`, `CODEX_COMPANION_SESSION_ID`, `AI_AGENT` | any agent CLI launched later believes it is nested inside a session that no longer exists; the socket path is dead |
| node hook | `NODE_OPTIONS=--require=$TMPDIR/<multiplexer>-node-options/restore-node-options.cjs` | every `node` on the machine depends on a `$TMPDIR` file the OS reaps after ~3 idle days; when it goes, `Cannot find module` |
| terminal | `GHOSTTY_*`, `TERMINFO=/Applications/<app>/Contents/Resources/terminfo` | curses programs read a foreign terminfo tree |

Measured on one machine: 45 names in one run. Nothing errors at sync time.

## Who is affected, exactly

- **Multiplexer panes: immune.** cmux builds each pane's environment clean and
  stamps its own per-pane identity values, so a pane started after the leak
  carries none of the leaked names even though the cmux.app process itself
  (relaunched from the Dock) inherited all of them. Verify rather than assume:
  compare the pane's login shell env (`ps -wwE -p <shell pid>`) with
  `launchctl getenv <name>` for a few names.
- **Spotlight / Dock / Login-Item launched apps: affected** from the moment of
  the sync, for every process they start later. Terminal.app is the visible
  one; IDE terminals, Electron apps, and anything that spawns `node` or an
  agent CLI are the invisible ones.
- **launchd services bootstrapped after the sync: affected and sticky.** A
  service's environment is a snapshot taken at `bootstrap`. If the service
  copies `os.environ` into its subprocesses (most do), every command it runs
  inherits the set. `launchctl kickstart -k` restarts the process but keeps
  the snapshot, so a later `unsetenv` never reaches it.

## Detect

```bash
# 1. The user domain. Exit codes lie (getenv exits 0 either way); read the block.
launchctl print gui/$(id -u) | sed -n '/^\tenvironment = {/,/^\t}/p' \
  | grep -E '^\s+(PROMPT_COMMAND|CMUX_|CLAUDE|GHOSTTY_|TERMINFO|NODE_OPTIONS|CODEX_|AI_AGENT)'

# 2. Any service you care about: what it actually holds.
launchctl print gui/$(id -u)/<label> | sed -n '/inherited environment = {/,/}/p' \
  | grep -cE '^\s+(PROMPT_COMMAND|CMUX_|CLAUDE|GHOSTTY_|TERMINFO|NODE_OPTIONS|CODEX_|AI_AGENT)'

# 3. Who ran it, and from where: the leaked CLAUDE_CODE_SESSION_ID names the
#    agent session; its transcript under ~/.claude/projects/<slug>/<id>.jsonl
#    contains the command.
launchctl getenv CLAUDE_CODE_SESSION_ID
```

A GUI app that was running *before* the sync is clean; one relaunched after
it is not. `ps -p <pid> -o lstart=` against the sync script's mtime settles
which.

## Fix, in this order

The order matters: the launchd-scheduled run of the sync script (`bash -l -c`)
inherits launchd's own environment, so with the leak still in place it will
faithfully re-publish the leaked names on its next run. Close the gate first.

1. **Denylist session-scoped names in the sync script.** For a `compgen -e`
   loop with a `SKIP` regex:

   ```bash
   SKIP='^(_|PWD|OLDPWD|SHLVL|SHELL|TERM|TERM_SESSION_ID|TERM_PROGRAM|TERM_PROGRAM_VERSION|TMPDIR|LOGNAME|USER|HOME|PS[1-4]|PROMPT_COMMAND|PROMPT_DIRTRIM|BASH.*|XPC_.*|SSH_.*|__CF.*|SECURITYSESSIONID|COMMAND_MODE|COLORTERM|CMUX_.*|CLAUDE.*|GHOSTTY_.*|TERMINFO|NODE_OPTIONS|CODEX_.*|AI_AGENT)$'
   ```

   Dry-check the gate from the worst-case shell (a pane hosting an agent)
   before trusting it:

   ```bash
   for n in $(compgen -e | sort -u); do [[ "$n" =~ $SKIP ]] || [ -z "${!n}" ] || echo "$n"; done \
     | grep -E '^(PROMPT|CMUX|CLAUDE|GHOSTTY|TERMINFO|NODE_OPTIONS|CODEX|AI_AGENT)' || echo "gate holds"
   ```

2. **Purge the user domain.** Derive the list from what is actually there,
   not from memory; leave `PATH`, `SSH_AUTH_SOCK`, and the rest alone.

   ```bash
   launchctl print gui/$(id -u) | sed -n '/^\tenvironment = {/,/^\t}/p' \
     | grep -oE '^\s+[A-Za-z_][A-Za-z0-9_]* ' | tr -d '\t ' \
     | grep -E '^(PROMPT_COMMAND|PROMPT_DIRTRIM|CMUX_|CLAUDE|GHOSTTY_|TERMINFO$|NODE_OPTIONS$|CODEX_|AI_AGENT$)' \
     | while read -r n; do launchctl unsetenv "$n"; done
   launchctl getenv PROMPT_COMMAND | wc -c     # 0
   ```

3. **Reload each affected service with bootout + bootstrap**, not kickstart.
   `bootout` returns before teardown finishes; an immediate `bootstrap` can
   fail with `Bootstrap failed: 5: Input/output error` and leave the service
   *unloaded*. Wait for the old pid to disappear, then bootstrap again:

   ```bash
   launchctl bootout gui/$(id -u)/<label>
   while pgrep -f '<service main module>' >/dev/null; do sleep 1; done
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist
   launchctl print gui/$(id -u)/<label> | grep -E 'state =|pid ='
   ```

   Then re-run the detect step 2 on it and expect `0`.

4. **GUI apps** that were relaunched during the leak keep their copy until
   their next launch. Harmless for a multiplexer that sanitises pane env; for
   anything else, relaunch it.

## Why it stays hidden

- The sync prints "N synced" and exits 0 whether N includes a dead socket
  path or not.
- The multiplexer, where the operator lives, is the one place that is immune,
  so the operator never sees it.
- The service keeps working: `NODE_OPTIONS` points at a file that exists
  *today*; `CLAUDECODE=1` changes behaviour only when an agent CLI is
  invoked; the dead socket matters only when something tries to talk on it.
  The failure arrives days later, in a subprocess, looking like a broken
  toolchain.
- `launchctl getenv` exits 0 for unset names, so a naive check says "present"
  for everything and "absent" for nothing.

## Related

- `cmux-autoresume-after-reboot` - a stray `CMUX_DISABLE_SESSION_RESTORE`
  synced into launchd is the same mechanism with a different victim.
- `cmux-node-options-tmpdir-guard` - why the `NODE_OPTIONS` `--require` target
  lives in `$TMPDIR` and what keeps it alive.
