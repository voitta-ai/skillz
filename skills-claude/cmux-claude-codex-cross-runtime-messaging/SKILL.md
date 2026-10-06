---
name: cmux-claude-codex-cross-runtime-messaging
description: |
  Run a Claude Code agent and a Codex CLI agent as peers in cmux panes that
  message each other (e.g. ping-pong, dev/reviewer pairs), with both sides
  named as tabs and both sides in the agent traffic log. Use when: (1) you need
  Claude <-> Codex agent-to-agent traffic and discover Codex has no
  SendMessage/ListAgents, (2) a Codex TUI launched into a cmux split never
  starts a thread (no ~/.codex/sessions rollout file, "configWarning" in
  ~/.codex/logs_2.sqlite) and you cannot see its screen, (3) the traffic log
  shows only the Claude half, (4) you must collect the on-disk transcripts of
  a lead, a Claude teammate and a Codex session afterwards. Encodes the
  keystroke-injection transport (cmux send + send-key Enter), the self-naming
  step for tabs, explicit xs logging for the Codex side, and where each log
  lives.
author: Claude Code
version: 1.0.0
date: 2026-08-27
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-claude-codex-cross-runtime-messaging/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/cmux-claude-codex-cross-runtime-messaging/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

# Claude Code <-> Codex CLI cross-runtime messaging in cmux

## Problem

Claude Code's native `ListAgents` / `SendMessage` only reaches Claude sessions.
Codex CLI has no equivalent tool, and Claude's peer socket
(`/tmp/cc-socks/<pid>.sock`) requires an auth handshake, so a Codex process
cannot write to it. `codex:codex-rescue` subagents have Bash only and cannot
report back either. Yet you want the two runtimes to exchange messages, each
visible as a named cmux tab, and both halves in the `xs` traffic log.

## Context / Trigger Conditions

- "Make Claude and Codex talk to each other" / cross-runtime demo or pairing.
- Codex TUI started in a cmux split is alive (`ps -t ttysN`) but no rollout
  file appears under `~/.codex/sessions/YYYY/MM/DD/` and
  `~/.codex/logs_2.sqlite` shows `app-server event: configWarning` at start.
- `xs tail` shows the Claude side only (PostToolUse on `SendMessage` cannot
  observe Codex).
- Both teammate tabs read `general-purpose` / `Terminal`.

## Solution

Transport = **keystroke injection into the peer's pane**. Each agent runs one
Bash helper per message; the helper logs to `xs`, appends to a shared
transcript, then types the text into the peer's surface and presses Enter.
Both runtimes treat injected text as an ordinary user turn.

1. **Lead prepares a shared dir** `$PP` with `scripts/pp-send`, `scripts/pp-register`,
   an empty `addr/` and `transcript.log`.
2. **Create the Codex pane and name it before launching Codex:**
   ```bash
   cmux new-split right --workspace workspace:N --focus false   # -> "OK surface:M ..."
   cmux tab-action --action rename --surface surface:M --title ponger
   echo surface:M > $PP/addr/ponger
   ```
   Sanity-check the transport on the bare shell first:
   `cmux send --surface surface:M "echo hi > $PP/t"; cmux send-key --surface surface:M Enter`.
3. **Launch Codex from a script typed into that pane** (avoids shell quoting
   through `cmux send`):
   ```bash
   cd "$PP" && exec codex -a never -s danger-full-access \
     -c 'projects."'"$PP"'".trust_level="trusted"' "$(cat "$PP/ponger-prompt.md")"
   ```
   The brief: first turn prints "ready" only; on each `ping N` run exactly
   `$PP/pp-send ponger pinger "pong N"`; stop after 5; ignore anything else.
   `danger-full-access` is needed because the seatbelt sandbox blocks the
   cmux unix socket and `~/.local/state` writes; keep the cwd a scratch dir.
4. **If no rollout file appears within ~30 s**, the TUI is parked on a startup
   modal. cmux has no read-screen command and `screencapture` needs TCC, so
   don't try to look; send one Enter: `cmux send-key --surface surface:M Enter`.
   Verified: thread started immediately. Confirm with the newest
   `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (assistant message "ready").
5. **Spawn the Claude side as a named teammate** (`Agent(name: "pinger", ...)`
   under `cmux claude-teams`, `teammateMode: tmux`). Its brief starts with
   `$PP/pp-register pinger` (resolves its own surface via `cmux identify`
   `caller.surface_ref`, writes `addr/pinger`, renames its tab) and a
   `SendMessage` to `team-lead` saying "ready at surface:K". It then waits for
   "start" and plays with `$PP/pp-send pinger ponger "ping N"`; replies arrive
   as plain user input "pong N".
6. **Lead sends "start"** with `SendMessage` and watches
   `$PP/transcript.log` / `xs recent` rather than the panes.
7. **Collect logs afterwards:**
   - lead and teammate: `~/.claude/projects/<cwd-slug>/<session-id>.jsonl` —
     the teammate has its *own* session id in the *lead's* cwd slug; identify
     it by its first user message (`<teammate-message teammate_id="team-lead">`)
     or `find ~/.claude/projects -name '*.jsonl' -mmin -15`.
   - Codex: the rollout file from step 4; `~/.codex/state_5.sqlite` `threads`
     table maps thread id -> `rollout_path`.
   - traffic: `xs path` (`~/.local/state/agent-xs/events.jsonl`).
   Condense before posting (raw JSONL carries CLAUDE.md system-reminders,
   which may hold account ids); GitHub comments cannot take attachments.

## Verification

- `xs recent` shows alternating `pinger -> ponger Q ping N` /
  `ponger ok pinger RE pong N` lines with real names on both sides.
- `cmux tree --all` lists surfaces titled `pinger` and `ponger`.
- Codex rollout has one `exec_command` per ping, exit 0; teammate JSONL has
  one Bash call per pong. Measured: ~10 s per round trip, 5 rounds in 50 s.

## Example

See `scripts/pp-send` and `scripts/pp-register`. `pp-send <me> <peer> "<text>"`
classifies `pong*` as `answered/RE` and everything else as `send/Q`, so
`xs status` is clean when the run ends.

## Notes

- The hook path (`PostToolUse` on `SendMessage`) still logs the Claude side;
  make sure the installed hook reads `agent_id` (skillz agent-traffic-log
  >= 1.2.0) or the lead<->teammate lines show as `general-purpose`.
- Teammate panes may print `Stop hook error: /bin/sh: node: command not found`
  on cmux 0.64.22 (manaflow-ai/cmux#10198, unreleased) — cosmetic.
- Codex also reads `~/.codex/AGENTS.md` on top of the brief.
- This is terminal input, not a runtime messaging API: no delivery receipt,
  and a message injected mid-turn queues as the next user turn.
- `pp-register` uses `cmux identify` `caller.surface_ref`; `$CMUX_TAB_ID` can
  alias the workspace id, so do not rename with the default target.

## References

- Claude Code cross-session messaging: skill `claude-code-cross-session-messaging`
- Tab naming recipe and `select-pane -T` no-op: skill `cmux-agent-tabs`
- Traffic log and hook: skill `agent-traffic-log`
