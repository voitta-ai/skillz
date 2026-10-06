---
name: claude-code-cross-session-messaging
description: |
  Talk to another Claude Code session that is already running - ask it a
  question, hand it a fact, delegate a unit of work - using the native
  `ListAgents` + `SendMessage` pair rather than a headless `claude -p` call or
  a terminal-scraping bridge. Use when: (1) you want one agent session to
  consult or delegate to another and are reaching for `claude -p`, a tmux
  send-keys bridge, or a third-party agent-to-agent plugin; (2) a delegated
  agent has gone silent with no output, no error and no timeout, and you need
  to know whether it is wedged or merely busy; (3) you need to wait for another
  session to finish without polling; (4) you are deciding between the native
  transport and a launch-a-callee tool and want the actual dividing line; (5) a
  peer refuses or cannot answer and you must not fabricate its reply. Encodes
  the addressing rules, the three call shapes, the no-TTY law that kills
  headless and in-process transports, the idle-subscription primitive that
  replaces polling, and the permission-laundering boundary.
author: Claude Code
version: 1.1.0
date: 2026-08-20
source: https://github.com/voitta-ai/skillz
source_file: skills/claude-code-cross-session-messaging/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/claude-code-cross-session-messaging/SKILL.md`). Updates go through the
> repo's worktree + PR workflow - open an issue, branch, PR.

## The short version

Claude Code ships agent-to-agent messaging. Two tools, no install:

- `ListAgents` - enumerate reachable agents: in-process subagents you spawned,
  **other local Claude Code sessions on this machine**, and cloud sessions.
- `SendMessage` - deliver text to one of them by name.

Before building or installing anything that shells out to `claude -p`, drives a
multiplexer with send-keys, or scrapes a pane, check whether the target is
already a listed peer. If it is, the native path is strictly better: real TTY,
no credit spend on programmatic usage, no scraping, no delivery guesswork.

## This does not replace team orchestration

Point-to-point messaging and spawn-a-team orchestration solve different halves
and a good setup runs both:

| | Spawned team (watchable tabs) | Cross-session messaging |
|---|---|---|
| Target | work that does not exist yet | a session already open |
| Surface | new pane/tab per agent, watchable | no new surface at all |
| Cost | a launch per agent | one message |
| Steering | attach to the pane and type | reply into the conversation |

Reach for orchestration when you are dividing *new* work and want each worker
visible and steerable on its own surface. Reach for messaging when the thing
you need is already running and you only want a fact, an answer, or a handoff.
Using messaging where a team belongs gets you one overloaded session; spawning
a team where a message belongs pays a launch to ask a one-line question.

## Prerequisite

Native cross-session messaging landed in **Claude Code 2.1.224**. Check with
`claude --version` before designing around it; on older builds `ListAgents`
will not show peer sessions and the whole approach collapses back to a
launch-a-callee transport.

## Addressing

`ListAgents` output is the address book. Every row leads with `name [ref]`, and
**the name is the address** - there is no separate address syntax.

```
Peer sessions (4):
  <name-a> [ab12cd]  ·  interactive  ·  waiting  ·  started 15h ago
  <name-b> [ef34gh]  ·  interactive  ·  busy     ·  started 17h ago
  <name-c> [ij56kl]  ·  interactive  ·  idle     ·  started 15h ago
```

Rules that are easy to get wrong:

- Send the **bare name**. Append ` [ref]` only when the listing shows two rows
  sharing a name, or an error explicitly asks you to disambiguate.
- **A ref you did not just read from a listing or an error will not resolve.**
  Do not reconstruct one from memory, from a transcript, or from a prior
  session - refs are not stable identifiers you can cache.
- If a name matches both an in-process agent and a peer session, **the bare
  name resolves to the in-process one**. Disambiguate deliberately.
- Rows are labeled by kind. A cloud session **receives your message but cannot
  message any session back**. Do not ask it to reply; read its answer in its
  own transcript. Designing a request/response round trip against a cloud peer
  produces a wait that never ends.

## The three call shapes

Borrowed vocabulary, because it maps cleanly onto what the transport can do:

| Shape | What you send | How you get the answer |
|---|---|---|
| **Quick question** | one message, answer expected | peer replies with its own `SendMessage`; arrives to you automatically |
| **Work order** | delegated unit of work, no answer expected now | `notify_when_idle: true`, then read the result |
| **Conference** | multi-turn collaboration | repeated exchanges; each side replies via the `from` attribute |

There is no separate API per shape. The shape is a convention about *what you
say and how you wait*, not a different call.

## Replying: copy the `from` attribute

An inbound message is delivered to you wrapped:

```
<cross-session-message from="<sender-name>">...</cross-session-message>
```

**To reply, copy that `from` value verbatim into your `to`.** This is the whole
reply protocol. Do not guess the sender's name from context, and do not reply
in plain prose - your plain text output is not visible to other agents. If you
did not call `SendMessage`, you did not answer.

## Waiting without polling

The primitive that replaces every hand-rolled wait loop:

```json
{"to": "<peer>", "notify_when_idle": true}
```

- One-shot and opt-in. Exactly one `[Cross-session idle notice]` arrives when
  that session next goes idle or exits.
- **Omit `message` entirely** for a pure subscription - it costs the target
  session nothing. Include a `message` to deliver work *and* subscribe in one
  call. That combination is the whole work-order shape.
- Only works against a session **on this machine**, and only from the main
  conversation (not from inside a background subagent).
- If the target never signals within the subscription's lifetime, the notice
  says the subscription expired. That is not proof of success or failure - it
  means unknown, and the target may still be busy, may refuse inbound requests,
  or may have ended abruptly.

**Never poll `ListAgents` in a loop, and never send "are you done?" messages.**
Both burn tokens on both sides and are strictly worse than the subscription.

### The reply and the idle notice are two different signals

Easy to conflate, and conflating them makes you wait for something that already
happened. They are separate, and they arrive in this order:

1. **The peer's reply** arrives on its own, delivered at the peer's next tool
   round, wrapped as `<cross-session-message from="...">`. This carries the
   answer. Nothing you do makes it arrive sooner.
2. **The idle notice** arrives later, when that session finishes its *turn*.
   It carries no answer - only "that session is done for now", plus whatever
   one-line summary its harness reports.

So: **read the answer from the reply, not from the notice.** A quick question
needs no subscription at all - the reply is the whole mechanism. Subscribe when
you care that the peer has gone quiet (a work order whose result you will read
from the repo, a handoff you must not follow up on too early), not when you are
waiting for text.

Observed directly: a peer answered a read-only question at its tool round, and
the idle notice landed afterwards reporting unrelated work it had moved on to.
Treating the notice as the answer signal would have meant waiting past an
answer already in hand, then reading a summary that was about something else.

An idle notice is also **not** a completion guarantee. It fires when the turn
ends, whatever the turn achieved - success, refusal, or abandonment.

## The no-TTY law

The reason to prefer a live peer over any headless or in-process transport,
stated as a rule because it has a recognizable failure signature:

> **An agent with no terminal cannot show you a prompt. It will wedge silently
> instead of failing.**

Symptoms are identical across every transport that violates this: the first
tool call never returns, there is no result, no error, no timeout, and **no
permission dialog or pending indicator anywhere in the UI**. It reads as "the
model is thinking" forever.

Transports that hit it:

- `claude -p` (print / headless mode). Non-interactive permission handling
  covers the ordinary cases, but a trust prompt, an auth re-prompt, or anything
  the non-interactive path does not model has nowhere to render.
- In-process teammates (a teammate mode that resolves to in-process gives the
  agent no pane and therefore no TTY).
- Any agent spawned into a detached surface nobody is attached to.

Diagnosis, in order:

1. Does the target appear in `ListAgents` as `interactive`? If yes, it has a
   TTY and this is not your bug - check `busy` vs `idle` before assuming a hang.
2. If you spawned it, whatever your host offers for inspecting task type is the
   decisive check - an in-process task type means no pane exists, so no prompt
   can ever appear.
3. If the transport is a shim or wrapper, check **its own dependencies**, not
   just its own resolution. A shim that wins its place on `PATH` but whose
   interpreter or backing binary is *off* `PATH` fails in a way that reads as a
   bug in whatever subsystem the shim impersonates. Test every hop in one shot
   from a clean login shell (`env -i HOME=$HOME /bin/bash -lc '...'`), not just
   the first one.
4. Read the **live process environment**, not the shell's. A pane's shell will
   happily report a `PATH` the long-running agent inside it never saw:
   `ps -Eww -o command= -p <pid> | tr ' ' '\n' | grep -E '^(TMUX|PATH)='`
5. Distinguish *wedged* from *never launched* before blaming the environment.
   If the process the transport would have spawned never appears in `ps` at
   all, the spawn never reached the transport, so the transport is not your
   bug. A queued or manually-gated agent and a broken transport look identical
   from outside and are told apart only by that check.
6. **Do not reach for a bypass-permissions flag.** Control test: issue the same
   blocked operation from the session that *does* have a TTY. If it returns
   instantly, the parent is already permissive, the call never reached the
   permission layer at all, and bypassing that layer fixes nothing while
   costing real safety.

## Permission laundering - the hard boundary

Permission boundaries are **per-session**. Never ask a peer to perform an
action that was denied or blocked in your session, or that you expect your own
permission settings would block. A peer doing it for you bypasses a decision
the user actually made.

Route blocked work back to your user instead. This is not a style preference -
delegating around a denial is the failure mode the boundary exists to prevent.

## Never fabricate a peer's reply

A peer that is `busy`, that never answers, or that declines the request has not
given you an answer. Say the reply is still outstanding. Do not synthesize what
it "would have" said, and do not present your own reasoning as its response.
The same applies to an expired idle subscription: report unknown, not done.

## When the native path is genuinely not enough

Honest dividing line, so this skill does not oversell itself. Native
`ListAgents` + `SendMessage` covers **targets that are already running**. It
does not:

- launch a session that is not currently open,
- place a new session side-by-side with yours for watching,
- prove delivery of a specific payload (there is no per-message receipt beyond
  the peer's own reply),
- fork someone else's session so your request does not land in their transcript.

If you need those - most commonly because your working style is short-lived
sessions, so the target is usually *closed* when you want it - a
launch-a-callee tool is the right answer and the native path becomes its fast
path rather than its replacement. Evaluate one on two questions before
installing:

1. **Does it degrade to headless when a dependency is missing?** Many such
   tools require a companion plugin for pane placement and silently fall back
   to `claude -p` without it - which reintroduces the no-TTY law and, on most
   plans, spends programmatic-usage credit that interactive sessions do not.
2. **Does your multiplexer actually expose the control verb it needs?** A paste
   or inject RPC absent from your build means every call degrades to the
   fallback, and you have installed a large dependency to obtain the exact
   transport you were trying to avoid.

Answer both *before* installing, not after.

## Quick reference

```jsonc
// discover
ListAgents                                        // names are addresses

// quick question
{"to": "<peer>", "message": "which port is the dev server on?"}

// work order + wait, no polling
{"to": "<peer>", "message": "rebase onto main and report conflicts",
 "notify_when_idle": true}

// pure subscription, costs the peer nothing
{"to": "<peer>", "notify_when_idle": true}

// reply to an inbound <cross-session-message from="X">
{"to": "X", "message": "..."}
```

## Related

- `agent-team-orchestration` - spawning a *team* of agents over a backlog,
  where watchability per agent is the design constraint. This skill is the
  point-to-point case between sessions that already exist.
- `cmux-agent-tabs` - making spawned agents land on watchable surfaces, i.e.
  giving them the TTY the no-TTY law demands. Also the home of the multi-hop
  `PATH` failures that break a shim-based transport.
- Worked example of the multi-hop trap in a real long-lived setup:
  https://blog.debedb.com/2026/08/10/cmux-eight-weeks-later-the-two-hop-path-trap/

The recurring theme across all three: with long-lived agent sessions nothing
breaks outright, things merely get **reordered underneath you** - `PATH`
positions, workspace identity, which transport a mode resolves to. Verify the
environment before trusting a conclusion drawn from behavior.
