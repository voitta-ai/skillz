---
name: agent-traffic-log
description: |
  An append-only event log of agent-to-agent traffic, plus a live pane over it,
  so a fleet of agents has an org-wide view instead of N private conversations.
  Every session appends JSONL; no daemon, no lock, no coordination. Use when:
  (1) agents message each other and you want one place showing who asked whom,
  about what, and whether it was answered; (2) a per-workspace status pill tells
  you about one session but you need the whole run; (3) you want a durable
  record of how a run went, not just its outcome - the retrospective input that
  is otherwise lost when contexts end; (4) you need "who is blocked right now"
  derived from history rather than tracked separately; (5) you are about to add
  a lock or a daemon to make concurrent appends safe and want to know why
  neither is needed; (6) agents keep forgetting to log and you want the
  record to stop depending on their discipline - `scripts/xs-hook` wires the
  log to Claude Code's `PostToolUse` hook on `SendMessage`, which fires for
  subagents too; verified on a real team run, where it caught every message
  of a ten-message exchange with no agent calling `xs log`. Ships `scripts/xs`
  (log, tail, recent, status, prune) and `scripts/xs-hook`.
author: Claude Code
version: 1.5.0
date: 2026-09-11
source: https://github.com/voitta-ai/skillz
source_file: skills/agent-traffic-log/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/agent-traffic-log/SKILL.md`). Updates go through the repo's worktree
> + PR workflow - open an issue, branch, PR.

# agent-traffic-log

## Why events, not state

A status pill answers "what is *this* session doing". It cannot answer "what is
the *run* doing", because a pill is per-workspace and a run is many workspaces.

Recording **events** rather than current state costs almost nothing extra and
buys two things state cannot:

- **The org view.** Current state is a fold over events, so events subsume it -
  `xs status` derives who is waiting on whom from the log rather than tracking
  it separately, which means the two can never disagree.
- **A retrospective input.** When a context ends, everything it knew about how
  the run went goes with it. An append-only log outlives the sessions that
  wrote it, which is the difference between "the run succeeded" and "here is
  where it stalled".

## The log

```
${XDG_STATE_HOME:-~/.local/state}/agent-xs/events.jsonl
```

JSONL, one event per line, mode 0600. Read it with anything.

```json
{"ts":"2026-08-21T20:38:49-0700","ev":"send","from":"main","to":"api-worker",
 "kind":"Q","topic":"which port for dev server","ws":"2E7F43AF-..."}
```

| Field | Meaning |
|---|---|
| `ev` | `send` `recv` `answered` `expired` `note` |
| `kind` | `Q` question, `WO` work order, `FYI` status, `RE` reply |
| `from` / `to` | agent names, matching what `ListAgents` shows |
| `topic` | short human-readable subject |
| `ws` | `$CMUX_WORKSPACE_ID`, so an event maps back to a surface |

## Why there is no lock and no daemon

Many sessions append to one file concurrently. That is safe because POSIX
guarantees a single `write()` of at most `PIPE_BUF` bytes to a descriptor
opened `O_APPEND` is not interleaved with another writer's.

So the writer does exactly that: `os.open(..., O_WRONLY|O_APPEND|O_CREAT)`, one
`os.write()`, close. Lines are capped at 2048 bytes, comfortably under the
4096-byte `PIPE_BUF` floor, and the cap is enforced by **truncating the topic**
rather than rejecting the event - a dropped event is worse than a clipped
topic, because the log's whole value is being complete.

**Measured, not assumed:** 24 concurrent writers x 40 events = 960 lines
produced 960 parseable lines, 0 torn, 960 distinct. If you change the writer,
re-run that test; it is the only property the design depends on.

Two consequences worth knowing:

- A reader may see a partial *file* but never a partial *line*, so `tail` is
  safe at any moment.
- `prune` rewrites via temp + `os.replace`, which is atomic, but an appender
  racing a prune can lose a line. Prune when the fleet is quiet.

## Commands

```bash
xs log send --to api-worker --kind Q --topic "which port for dev server"
xs log recv --to main       --kind Q --topic "which port for dev server"
xs log answered --to api-worker --kind RE --topic "port is 5173"
xs log expired  --to db-worker            --topic "no reply within subscription"

xs recent -n 20      # last N, formatted
xs tail              # follow - this is what a traffic pane runs
xs status            # who is waiting on whom, derived from events
xs path              # where the log lives
xs prune --keep 5000
```

Identity comes from `$XS_NAME`, else `$CMUX_TAB_TITLE`, else
`$CMUX_WORKSPACE_NAME`, else a short workspace id. Set `XS_NAME` to the same
name `ListAgents` shows and the log lines up with the address book. When the
hook (below) is doing the logging you rarely need any of these: it resolves
names from Claude Code's own session registry.

## The pane

```bash
cmux new-workspace --name traffic --command "xs tail"
```

or as a split beside what you are watching:

```bash
cmux new-split right --command "xs tail"
```

`tail` polls rather than using inotify/kqueue: no dependency, and since the
file only grows by appends a byte offset stays valid. It restarts cleanly if
the file shrinks under it (a prune), rather than replaying everything.

## Instrumentation, not discipline

Everything above works if every agent remembers to call `xs log`. They do not.
`scripts/xs-hook` removes the requirement.

```jsonc
// ~/.claude/settings.json
"PostToolUse": [
  {"matcher": "SendMessage",
   "hooks": [{"type": "command", "command": "~/.local/bin/xs-hook"}]}
]
```

**Why one hook covers a whole team.** Claude Code runs the session's configured
tool hooks inside subagents as well, and the payload carries `agent_id` and
`agent_type` naming the subagent that made the call. So a single entry in a
single settings file instruments the main conversation *and* every teammate it
spawns - including background agents that own no surface, which are exactly the
ones the pill cannot see. There is nothing to install per teammate and nothing
for a teammate to remember.

`matcher` takes the bare tool name: `SendMessage` is matched as an exact
string, not a regex.

**Sender identity inside a teammate** comes from the payload's `agent_id`
(`<name>@<team>`, so `pinger`), falling back to `agent_type`. The first real
run logged both teammates as `general-purpose` because the hook read only the
type; two agents of one type are indistinguishable that way, so the name wins
when it exists. `$XS_NAME` still overrides both.

**Names for plain sessions, both directions.** A session that is neither a
teammate nor a subagent has no `agent_id`, and used to fall through to the
env-based guess -- in cmux that logs `ws:<uuid>`, a workspace, not a speaker.
And a session that *replies* by copying the incoming `from="uds:/tmp/cc-socks/
<pid>.sock"` attribute used to log a socket path as the recipient. The hook now
resolves both against Claude Code's session registry (`~/.claude/sessions/
*.json`, the same source `ListAgents` names come from): the payload's
`session_id` names the sender, `messagingSocketPath` names a `uds:` recipient.
Observed before the fix: a real two-session exchange logged as
`ws:7862422F -> hq-50` and `ws:6D4B9D5E -> uds:/tmp/cc-socks/59961.sock` --
half-blind in a log whose whole point is who spoke. An address the registry
cannot resolve is kept verbatim: a wrong name is worse than an ugly one.
`CLAUDE_SESSIONS_DIR` overrides the registry location (tests use it).

**Do not pin the hook path.** If a settings entry or a wrapper points at the
plugin cache, glob `~/.claude/plugins/cache/<mkt>/<plugin>/*/...` and take the
highest version: cache dirs are per-version and prunable, and for a logger a
dangling pinned path fails silently -- logging just stops.

### What it maps

The hook reads the `cmux-cross-session-visibility` envelope out of
`SendMessage`'s `summary` field, so the same grammar that makes a message
legible in the UI is what makes the log line accurate.

| Message | Event | Why |
|---|---|---|
| `Q ->peer: topic` | `send` | an ask, outstanding until answered |
| `WO ->peer: topic` | `send` | delegated work, same |
| `RE <-peer: gist` | `answered` | **load-bearing.** `status` clears a wait only on `answered`/`expired` - a reverse `send` does not clear the forward ask, so a reply logged as `send` leaves every question outstanding forever |
| `FYI ->peer: topic` | `note` | the envelope defines FYI as expecting no answer; a `send` would park a wait nothing will ever clear |
| `notify_when_idle` with no message | `note` | a pure subscription asks nothing |
| no envelope | `send` | see below |

**Unlabelled traffic is logged as `send` on purpose.** The hook cannot tell an
unlabelled question from an unlabelled aside, and guessing `note` would drop
real waits - the failure this hook exists to remove. So unlabelled messages sit
in `status` until answered, and that accumulating noise is the feedback that
someone is skipping the envelope. Under-reporting is silent; over-reporting
complains.

### The one contract

**The hook never fails the tool call.** Every error path exits 0 and prints
nothing: unparseable payload, missing `xs`, `xs` itself erroring. A hook that
blocked `SendMessage` to protect its own log would have the priorities
backwards - a missing line is a gap, a blocked message is an outage.

It also resolves `xs` as `$XS_BIN`, then the copy beside itself, then `PATH` -
in that order, because a hook subprocess does not necessarily inherit the
interactive shell's `PATH`, and "silently does nothing" is the most likely way
for this to fail.

### What it still does not catch

- **Receipt.** `PostToolUse` fires on the sender. `recv` remains unhooked, so
  the log records what was sent, not what landed.
- **Expiry.** Nothing fires when an idle subscription expires, so a wait that
  ended in *unknown* stays outstanding. Log `expired` by hand, or accept that
  `status` over-reports.
- **Failed sends.** `PostToolUse` is the success path (`PostToolUseFailure` is
  a separate event this does not wire), so a send that errored is not logged as
  having happened - which is correct, and worth knowing when a line is missing.

## How this fits with the other two halves

Three layers, each useful alone:

| Layer | Surface | Answers |
|---|---|---|
| Envelope | the message itself | what is this about |
| Pill | one workspace's sidebar | is *this* session blocked |
| **Log** | one pane, or any reader | what is the *run* doing, and what happened |

See `cmux-cross-session-visibility` for the envelope and pill, and
`claude-code-cross-session-messaging` for the transport underneath. Log the
same `kind` you put in the message summary, so a pane line and a transcript
line describe the same event in the same vocabulary.

`expired` is worth logging explicitly. An idle subscription that expires means
*unknown*, not answered - recording it is what stops `xs status` from showing a
wait that nobody is actually waiting on.

## Acceptance test

Static tests prove the writer; only a real run proves the conventions. Run this
on a **fresh cmux launch**, not a resumed one - resumed panes have neither
`$TMUX` nor the shim directory, so a team spawned from one behaves differently
(see `cmux-agent-tabs`).

**1. A team, per the documented shape.** From the palette, launch
`cmux claude-teams`, give the main agent a task, and let it spawn a squad:
architect first (its deliverable is the parallel set), then per work item a
developer in its own worktree, an **adversarial reviewer that is a different
agent**, an SDET, and a productivity engineer. The dev/reviewer split is the
load-bearing part; the instant the context that wrote the code also reviews it,
the review is theater.

Expected in the traffic pane: `send`/`recv` pairs between main and each
teammate, `kind=WO` for delegated work, `answered` when each reports back.

**2. Cross-workspace question.** With workspace 1 / tab 1 mid-task, have
workspace 2 / tab 2 ask it a question. Expected: one `send` from ws2, one `recv`
on ws1, one `answered`, and `xs status` showing the ask outstanding in between
and nothing after.

**Passes if:** every message that happened appears exactly once; `xs status` is
empty when the run is idle; no torn lines; and reading the pane alone tells you
what the run did without opening a transcript.

**First real run (2026-08-26, Claude Code 2.1.247, cmux 0.64.22).** A lead
spawned two teammates and had them play five rounds of ping-pong over
`SendMessage`. With only the hook installed - no agent called `xs log` - the
log holds the kickoff, all ten messages in order, and the final report to the
lead, each exactly once, no torn lines. Two things it exposed, both now
addressed or documented: senders were logged by type, not name (fixed above);
and `xs status` kept every message as an outstanding wait because nobody used
the `Q`/`RE` envelope - the predicted over-reporting, working as designed.

**Fails informatively if** the log is short. With `xs-hook` installed, a gap
is no longer an agent forgetting - it is the hook not firing, so check that
`matcher` is `SendMessage` and that the command path resolves before blaming
anyone's discipline. Without the hook, gaps mean what they always meant.

## Caveats

- **Unhooked, there is no guarantee.** Without `scripts/xs-hook`, nothing
  observes `SendMessage`: an agent that does not call `xs log` leaves no trace
  and the log silently under-reports rather than erroring. Installed, the send
  side is instrumented; receipt and expiry still are not.
- **Identity is best-effort.** Two sessions can pick the same name. `ws`
  disambiguates after the fact.
- **Not a security boundary.** Mode 0600 keeps it to your user; topics are
  written by agents, so keep secrets out of them exactly as you would a commit
  message.
- **`status` is a fold, so it inherits gaps.** An unlogged `answered` leaves a
  wait outstanding forever. Prefer logging `expired` over logging nothing.

## Related

- `cmux-cross-session-visibility` — the human-facing half of the same problem.
  This skill is the durable event log; that one is the sidebar pill and message
  envelope that make "who is blocked on whom" answerable at a glance.
- `claude-code-cross-session-messaging` — how the messages this log records are
  actually addressed and delivered.
- `parallel-agent-session-collisions` — what the log is *for* in the end:
  noticing that two sessions are converging before they collide.
- `subagent-no-report-channel` — the failure this log cannot fix on its own, an
  agent with a finding and nowhere to send it.
