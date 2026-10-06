---
name: claude-session-three-names
description: |
  Give a Claude Code (or Codex) session one name in all three places a human
  or a peer might look: the peer-address name that ListAgents and SendMessage
  use (Claude Code's session display name), the Remote Control session name,
  and the cmux tab title. Nothing keeps them in sync by default, so a peer
  told to "ask the ctox session" cannot find it while the tab and the Remote
  Control list both say "ctox". Use when: (1) ListAgents shows a session under
  a folder-derived name like "hq-3c" or "git-2b" while its tab or Remote
  Control entry has a meaningful name; (2) a peer reports "no session named X"
  although you can see X on screen; (3) you rename a session and a peer's next
  SendMessage fails with "No agent named ... is reachable"; (4) you want every
  session opened in cmux to be named once, with a prompt only when the name
  collides; (5) you need to know which live session sits in which cmux tab.
  Ships scripts/cc and scripts/cx (launch wrappers that set all three from one
  value), scripts/cc-names (who / pick / sync, and the Stop-hook that pushes a
  mid-session /rename to the tab), and scripts/cc-who.
author: Claude Code
version: 1.0.0
date: 2026-09-14
source: two sessions on one machine (a ctox session and a cmux session) reconciling names after a peer routed around an unfindable session; mechanism built and verified in the cmux session
source_file: skills/claude-session-three-names/SKILL.md
---

> **Canonical source.** `voitta-ai/skillz`, `skills/claude-session-three-names/SKILL.md`.

# Claude Code session: three names, one value

## Problem

A human names things by what is on screen: the cmux tab title, or the Remote
Control session name in the Claude app. Peer sessions address each other by a
third string, the session's display name, which defaults to the working
directory's basename plus a short hash (`hq-3c`, `git-2b`). None of the three
updates the others. The result is a peer that is told "ask the ctox session",
lists agents, finds no "ctox", and routes the question somewhere else, while
the session it wanted was in plain view the whole time.

| Name | Where it shows | Set by |
|---|---|---|
| Peer address | `ListAgents` rows, `SendMessage` `to` | `claude -n <name>` at launch, `/rename <name>` in-session; default `<cwd-basename>-<hash>` |
| Remote Control name | Remote Control session list in the Claude app | `claude --remote-control <name>` at launch, `/remote-control <name>` in-session |
| cmux tab title | cmux sidebar and tab bar | `cmux tab-action --action rename --surface <ref> --title <name>`, or the human |

## Where the peer-address name actually lives

Every interactive session writes `~/.claude/sessions/<pid>.json`. It carries
`name`, `nameSource` (`user` after `-n` or `/rename`, `derived` otherwise),
`status`, `cwd`, `sessionId` and `messagingSocketPath`. `ListAgents` reads
these files for peers; a session's *own* name is held in memory, so editing
the file changes what peers see until the process rewrites it and nothing
else. Treat the file as read-only. It is the join key everything below uses:
pid -> tty (`ps`) -> cmux surface (`cmux tree --all` prints each terminal
surface's tty) -> tab title.

## Solution

### 1. Launch through `cc` (Claude) or `cx` (Codex)

```
cc [NAME] [claude args...]
cx [NAME] [codex args...]
```

`cc` resolves the name, renames the cmux tab the terminal lives in, and execs
`claude -n NAME --remote-control NAME ...`. Resolution order, from
`cc-names pick`:

1. the argument, if given;
2. the tab's current title, if a human set it (anything that is not a shell
   name and not the folder basename);
3. the folder basename.

It then checks the name against every live session's peer name and every
tab that hosts a live session. On a collision it prompts, showing the
resolved name as the default. `CC_PROMPT=always` prompts on every launch,
`CC_PROMPT=never` never does (`cc` then launches with the colliding name,
which the peer address book disambiguates by `[ref]`). `CC_REMOTE_CONTROL=0`
skips Remote Control.

`cx` does the same resolution and tab rename, exports `CX_NAME`, and execs
`codex`. Codex has no display-name flag and no peer address book; for a Codex
session the tab title *is* the name, so `cx` covers what can be covered.

Make them the default way a tab starts an agent in cmux. In
`~/.config/cmux/cmux.json`:

```json
"actions": {
  "agents.claudeNamed": {
    "type": "command", "title": "Claude (named)",
    "subtitle": "claude -n X --remote-control X, tab renamed to X",
    "command": "cc", "target": "newTabInCurrentPane", "shortcut": "cmd+shift+n"
  },
  "agents.codexNamed": {
    "type": "command", "title": "Codex (named)",
    "subtitle": "codex in a tab renamed to X",
    "command": "cx", "target": "newTabInCurrentPane"
  }
}
```

then `cmux reload-config`. A new tab opened this way starts in the folder of
the current tab, so the default name is that folder's basename, and the
prompt appears only when that name is already taken. If you want a plain
`claude` in any shell to behave the same, alias it in your profile:
`alias claude='cc'` (interactive shells only; cmux's own agent launcher and
`cmux claude-teams` do not read aliases).

### 2. Push a mid-session `/rename` to the tab (Stop hook)

`/rename` is a user slash command: nothing outside the session can trigger
it, and the model cannot invoke it. So the tab cannot drive the session, but
the session can drive the tab. `cc-names sync --hook` reads the Claude Code
hook JSON on stdin, finds the session by `session_id` in the registry, and,
if `nameSource` is `user`, renames the caller's cmux surface (resolved with
`cmux identify`, which works from a hook subprocess) to the session name. In
`~/.claude/settings.json`:

```json
"hooks": {
  "Stop": [
    { "matcher": "", "hooks": [ { "type": "command", "command": "cc-names sync --hook", "timeout": 5, "async": true } ] }
  ]
}
```

Idempotent and cheap (one `cmux identify`, one `cmux tab-action`). It also
re-asserts the title after every turn, which is what stops cmux's own
`cmux hooks claude auto-name` Stop hook from retitling a named session's tab.
It never touches tabs of sessions whose name is still `derived`.

Remote Control has no equivalent: `/remote-control <name>` is also a user
command, and the registry does not record the Remote Control name. Set it at
launch or accept that it can drift after a `/rename`.

### 3. See the state at any time

```
$ cc-names who
PID    NAME           SRC      STATUS  TTY      WORKSPACE  TAB    MATCH
24342  ctox           user     idle    ttys004  work       ctox   ok
87131  voitta:agents  user     waiting ttys005  voitta     agents differs
92678  hq-50          derived  idle    ttys008  work       blog   differs
```

(Values illustrative.) `differs` with `SRC=user` means step 2 has not run
yet for that session; `cc-names sync --all` fixes every such row at once
(`--dry-run` prints the renames). `differs` with `SRC=derived` means the
human named the tab and nobody named the session: the only fix is `/rename`
in that session, or relaunching it through `cc`. The pid is what a peer
message's `from="uds:/tmp/cc-socks/<pid>.sock"` carries, so a message can be
tied to a tab without asking. `cc-who` is a shim over `cc-names who`.

### 4. Tell peers when you rename

A rename takes effect at once and the old name stops resolving: the next
`SendMessage` to it fails as unreachable. After renaming a session that others
talk to, send each active peer one line: "address this session as <new>."
Replies to an earlier message still reach the renamed session, because they go
to the socket in the message's `from=`, not to the name.

## Verification

- `CC_PROMPT=never CC_CLAUDE=echo cc probe` prints
  `--remote-control probe -n probe` and `cmux tree --all` shows the tab
  titled `probe`.
- `echo probe2 | CC_CLAUDE=echo cc <a-live-name>` reports the collision and
  launches as `probe2`.
- `ListAgents` in a session launched by `cc` prints `This session is <name> [<ref>]`.
- `echo '{"session_id":"<id>"}' | cc-names sync --hook --dry-run` prints the
  `cmux tab-action` it would run, for a session whose name is user-set.
- `cc-names who` shows `ok` on that session's row.

## Notes

- Verified on Claude Code 2.1.266 and 2.1.271, cmux 0.64.22, macOS 26.
  `claude --help` lists `-n, --name <name>` ("Set a display name for this
  session"), `--remote-control [name]`, and
  `--remote-control-session-name-prefix <prefix>`.
- cmux's Claude wrapper and session restore launch `claude --session-id <uuid>`
  with no `-n`, so cmux-launched and auto-resumed sessions get folder-derived
  peer names. The Stop hook does not help those until someone runs `/rename`;
  launching through `cc` is what prevents it.
- The registry file is per pid, and stale entries for exited pids remain
  until cleanup; `cc-names` drops any whose pid has no tty.
- Sessions outside cmux (Terminal.app, launchd, cloud) show `-` for workspace
  and tab; `sync` skips them.
- Keep real workspace layouts out of shared docs: tab names, pids and ttys
  together are machine topology. The examples here are illustrative.

## Related

- `claude-code-cross-session-messaging` covers the `ListAgents`/`SendMessage`
  address book this skill makes readable.
- `cmux-session-self-identity` covers how a session names its own workspace and
  tab. This skill joins that namespace to the peer-address one.
- `cmux-agent-tabs` covers why some agents get no cmux surface at all; `cc-names who`
  shows those as `-`.
- `cmux-runbook-in-sibling-tab` is where `cmux identify` from a subprocess and
  the keystroke-channel rules are documented.
