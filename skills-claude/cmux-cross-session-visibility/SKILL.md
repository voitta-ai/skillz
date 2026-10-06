---
name: cmux-cross-session-visibility
description: |
  Make agent-to-agent traffic visible to the human watching, so "who is asking
  whom, about what, and is anyone blocked" is answerable at a glance instead of
  by reading transcripts. Two halves that reinforce each other: a structured
  message envelope every agent writes, and a cmux sidebar status pill every
  agent maintains. Use when: (1) agents message each other across cmux
  workspaces and you cannot tell from the outside that a conversation is
  happening at all; (2) a spawned team scatters across workspaces and the
  launcher pane gives no sign of what it is waiting on; (3) you want to know
  whether a session is blocked on a peer versus merely busy; (4) an idle notice
  or transcript line tells you a message was sent but not what it was about;
  (5) you are about to build a notification or dashboard for this and want the
  cheap conventions first. Also covers why a stale pill is the main failure
  mode and what must clear it.
author: Claude Code
version: 1.1.0
date: 2026-08-21
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-cross-session-visibility/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/cmux-cross-session-visibility/SKILL.md`). Updates go through the
> repo's worktree + PR workflow - open an issue, branch, PR.

# cmux-cross-session-visibility

## The problem

Agent-to-agent messaging is invisible from the outside. A session can ask a
peer a question, wait on it, and answer it, and the only trace a human sees is
prose buried in two different transcripts. Nothing on any surface says a
conversation is in progress, who started it, or whether anyone is blocked.

This gets worse with spawned teams rather than better. cmux's tmux-compat layer
maps a tmux **window** to a cmux **workspace**, so teammates spawned by a main
agent land in *separate workspaces*, not as tabs beside the launcher. Team
traffic is therefore cross-workspace traffic by construction, and the launcher
pane - the one you are actually watching - shows nothing about what its team is
doing.

## Two conventions, not a system

Both are cheap, need no new infrastructure, and are worth doing before any
notification or dashboard work.

| | What it changes | Answers |
|---|---|---|
| **Envelope** | what agents *write* | what is this about, who asked, what kind of ask |
| **Pill** | what the sidebar *shows* | is this session waiting on someone, or being waited on |

The envelope makes messages legible once you are reading them. The pill draws
your eye. Neither substitutes for the other.

## Half 1: the envelope

`SendMessage` already takes a **`summary`** field - 5-10 words, rendered as a
one-line preview in the UI. That is the natural carrier and it is free. Use a
fixed grammar so summaries sort and scan:

```
<kind> <arrow><peer>: <topic>
```

- `kind` is one of `Q` (question, answer expected), `WO` (work order,
  delegated), `FYI` (status, no answer expected), `RE` (reply).
- `arrow` is `->` for outbound, `<-` when replying to whoever asked.

```jsonc
{"to": "api-worker", "summary": "Q ->api-worker: which port for dev server",
 "message": "..."}
{"to": "api-worker", "summary": "WO ->api-worker: rebase onto main, report conflicts",
 "message": "..."}
{"to": "gregory-f6", "summary": "RE <-gregory-f6: port is 5173",
 "message": "..."}
```

In the **message body**, lead with one header line so the envelope survives
anywhere the summary does not reach - a raw transcript, a log, a paste:

```
[xs] from=<me> to=<them> kind=Q re=<short topic>
```

Then the actual content. Keep it one line; this is a label, not a protocol.

**Why bother when the tool already shows a sender:** the sender is not the
question. An `[Cross-session idle notice]` reporting a peer's harness summary
can read `Sent to <other>` and tell you nothing about what was asked or whether
your own request was ever answered. The envelope is what makes those lines mean
something.

## Half 2: the pill

cmux ships sidebar status pills, per workspace:

```bash
cmux set-status <key> <value> [--icon <name>] [--color '#hex'] [--priority <n>]
cmux clear-status <key>
cmux list-status
```

They default to `$CMUX_WORKSPACE_ID`, so each session maintains its own without
coordinating. **Use a key nothing else owns.** cmux itself manages a
`claude_code` key - `list-status` on a live pane shows
`claude_code=Running icon=bolt.fill color=#4C8DFF` - so writing that key
clobbers the app's own pill. Use `xs`.

Two states worth showing, and only two:

```bash
# outbound: I asked someone and I am waiting
cmux set-status xs "-> api-worker (Q)" --icon arrow.up.right --color '#ff9500' --priority 70

# inbound: someone asked me and owes an answer from me
cmux set-status xs "<- gregory-f6 asks" --icon arrow.down.left --color '#4C8DFF' --priority 70

# nothing outstanding
cmux clear-status xs
```

With more than one outstanding, collapse to a count rather than listing them -
`-> 3 pending`. A pill is a glance, not a log.

`--priority` sorts pills; keep it below whatever your build/test tooling uses
so a transient message state cannot hide a failing build.

### The failure mode is a stale pill

Nothing clears a pill for you. A session that sets `xs` and then crashes,
finishes its turn, or simply forgets leaves a pill claiming it is blocked on a
peer forever - and a pill that lies is worse than no pill, because it trains
you to stop reading it.

Clear on **every** exit from the waiting state, not just the happy one:

- a reply arrived (the `<cross-session-message>` landed),
- you answered the inbound ask,
- the idle subscription expired (which means *unknown*, so the honest pill is
  cleared, not left claiming a live wait),
- your turn ended with the question still outstanding - say so in prose to your
  user instead of leaving a pill to say it.

If you can hook it, clear `xs` unconditionally at turn end; a pill that must be
re-set each turn cannot go stale for longer than one turn.

## What this deliberately does not do

- **No toasts.** Transient by definition, so they answer nothing durably. Worth
  adding only if you find you are missing messages in unfocused tabs.
- **No traffic pane / no shared log.** The org-wide view - who asked whom, when,
  answered or not - needs an append-only log that does not exist yet, and a
  pane to tail it. That is the build worth doing next, and it is the only one
  that produces a record you could mine later.
- **No automatic hooking.** There is no cmux event on message receipt, so both
  halves are agent discipline enforced by this skill, not infrastructure. If a
  host hook fires on cross-session receipt, wire the pill to it and the whole
  convention stops depending on an agent remembering.

## Quick reference

| Situation | Do |
|---|---|
| Asking a peer | `summary: "Q ->peer: topic"`, header line, set `xs` outbound |
| Delegating | `summary: "WO ->peer: topic"`, set `xs`, subscribe with `notify_when_idle` |
| Answering | `summary: "RE <-peer: gist"`, then `clear-status xs` |
| Reply arrived | `clear-status xs` |
| Subscription expired | `clear-status xs` - unknown is not waiting |
| Several outstanding | `set-status xs "-> N pending"` |
| Check what you are claiming | `cmux list-status` |

## Related

- `claude-code-cross-session-messaging` - the transport these conventions
  decorate: addressing, `notify_when_idle`, and why the reply and the idle
  notice are different signals.
- `cmux-agent-tabs` - why teammates land in separate workspaces at all, and
  the `PATH` failures that stop them appearing anywhere.
