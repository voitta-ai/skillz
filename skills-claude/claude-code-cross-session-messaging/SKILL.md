---
name: claude-code-cross-session-messaging
description: |
  What the host docs for Claude Code cross-session messaging (`ListAgents` +
  `SendMessage`) do not tell you. Use when: (1) you sent a peer a question and
  are unsure whether to wait for its reply or for its idle notice; (2) a reply
  arrives in a session that was `/clear`ed and refers to a request you have no
  memory of; (3) a peer is busy, silent, or declined, and you must not
  fabricate its reply; (4) a delegated agent has gone silent with no output, no
  error and no timeout, and you need to know whether it is wedged, waiting on a
  permission prompt, or was never launched; (5) you are deciding between the
  native transport and a launch-a-callee tool and want the actual dividing
  line. Addressing, delivery, `notify_when_idle` limits and the per-session
  permission boundary are in the docs and are not repeated here.
author: Claude Code
version: 1.3.0
date: 2026-10-09
source: https://github.com/voitta-ai/skillz
source_file: skills/claude-code-cross-session-messaging/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/claude-code-cross-session-messaging/SKILL.md`). Updates go through the
> repo's worktree + PR workflow - open an issue, branch, PR.

## Start with the docs

The transport itself is documented:
https://code.claude.com/docs/en/cross-session-messaging - discovery and
addressing, delivery and refusal, `notify_when_idle` (one-shot, main
conversation only, this machine only, dropped after 12 hours), inbound controls
(`crossSessionInbound`), the inbox socket, and the rule that a session never
asks a peer to do what its own permissions denied. Requires Claude Code
2.1.224+; `/list-agents` not being recognized means the session does not have
it.

This skill covers what that page leaves out.

## Reply vs idle notice

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

Two corollaries:

- **Your plain text is not a reply.** A peer reads only what you send with
  `SendMessage`. If you did not call it, you did not answer.
- **Never poll `ListAgents` in a loop, and never send "are you done?"
  messages.** The reply arrives on its own; for "tell me when it is quiet",
  `notify_when_idle` with no `message` costs the peer nothing.

## Silent agent: wedged, waiting, or never launched

An agent with no terminal does not wedge on a permission prompt any more. What
the host does instead:

- **`claude -p` with no permission host denies** any call that would prompt
  and continues; it does not wait. Only a run with a host (an Agent SDK
  `canUseTool` callback, `--permission-prompt-tool`) waits on that host, and
  `--permission-prompts none` stops that wait too. See
  https://code.claude.com/docs/en/headless.
- **Teammate permission prompts appear in the lead session**, whatever the
  teammate mode, including in-process
  (https://code.claude.com/docs/en/agent-teams).
- **Background subagent prompts surface in your main session**, naming the
  subagent (https://code.claude.com/docs/en/sub-agents).

So a silent agent is first a question of *where* its prompt went: look in the
lead or main session before calling it wedged. If nothing is pending there:

1. Check the target's state in `ListAgents`: `busy` vs `idle` vs `waiting`
   before assuming a hang.
2. If the transport is a shim or wrapper, check **its own dependencies**, not
   just its own resolution. A shim that wins its place on `PATH` but whose
   interpreter or backing binary is *off* `PATH` fails in a way that reads as a
   bug in whatever subsystem the shim impersonates. Test every hop in one shot
   from a clean login shell (`env -i HOME=$HOME /bin/bash -lc '...'`), not just
   the first one.
3. Read the **live process environment**, not the shell's. A pane's shell will
   happily report a `PATH` the long-running agent inside it never saw:
   `ps -Eww -o command= -p <pid> | tr ' ' '\n' | grep -E '^(TMUX|PATH)='`
4. Distinguish *wedged* from *never launched* before blaming the environment.
   If the process the transport would have spawned never appears in `ps` at
   all, the spawn never reached the transport, so the transport is not your
   bug. A queued or manually-gated agent and a broken transport look identical
   from outside and are told apart only by that check.
5. **Do not reach for a bypass-permissions flag.** Control test: issue the same
   blocked operation from the lead or main session. If it returns instantly, the parent is already permissive, the call never reached the
   permission layer at all, and bypassing that layer fixes nothing while
   costing real safety.

## A reply arrives after this session was `/clear`ed

The reply refers to a request you have no memory of making.

**First, let the host give the old conversation back.** `/clear` keeps it:

- In the same Claude Code process, the rewind menu (`/rewind`, or `Esc` twice
  on an empty prompt) lists `/resume <session-id> (previous session)` at the
  top. That id names the exact transcript,
  `~/.claude/projects/<cwd-slug>/<session-id>.jsonl`.
- After a restart, `/resume <name>` or the `/resume` picker.

Both are user commands; the model cannot run them. Ask the user for the id from
the rewind menu, or to resume, rather than guessing a file.

**Fallback, when neither is available** (a different process, an unnamed
session, nobody at the keyboard): find the transcript yourself. Three traps,
all measured 2026-10-06, and they compound: the first makes you answer for the
wrong session, and the second sends you to the wrong transcript to check.

### 1. Do not infer your identity from `cwd`

A coordinator asked its peers for reports, then was `/clear`ed. A peer replied
with "I sent both to `<skills session>`". The cleared session's `cwd` **was** the
skills repo, so it read the reply as addressed to itself. It was not.

**The authoritative identity is the first line of `ListAgents`** - `This session
is <name> [ref]` - and that line survives a `/clear`. Read it before deciding a
message is yours.

`cwd` is not identity and is not close to it: one project directory here holds
**52 transcripts**, every session ever started in it.

### 2. `mtime` does not identify the right transcript

The pre-clear conversation is a *different* `.jsonl` in
`~/.claude/projects/<cwd-slug>/`. Every session started in that cwd writes
there, so picking the newest is a guess.

Measured in one such directory: **34 of 52 files share a single mtime minute.**
Sorting by time cannot separate them.

**Grep for THIS session's own name** - the first line of `ListAgents` - and not
for the peer that replied. A peer that many sessions talk to, such as a skills
or coordinator session, appears across many transcripts, so its count does not
separate them.

```bash
D=~/.claude/projects/<cwd-slug>
for f in "$D"/*.jsonl; do
  printf '%6s  %s\n' "$(grep -c '<this-session-name>' "$f")" "$f"
done | sort -rn | head -5
```

Measured in a 28-file directory: **1033 and 44** matching lines in this session's
two earlier transcripts, at most **12** in any other. The replying peer's name
gave 65, 51, 18, 11 - and **the right file came fourth**, at 11. Second place
went to a transcript with zero mentions of this session's name.

**After more than one `/clear`, every earlier transcript of this session
matches**, so the ranking alone is not the answer. The highest count is the
longest-lived transcript, not the one that sent the request: in the measured case
the 1033-line file held 7 `SendMessage`s to that peer but not the request being
answered, which was in the 44-line file. Among the matches, take the one with the
**latest `SendMessage` to the replying peer** (step 3).

A path you already know the old session wrote also works, if you have one.

**Validate the discriminator where it can fail:** in a directory where this
session has more than one transcript, *and* where other sessions talk to the same
peer. The first condition exposes the every-transcript-matches trap; the second
exposes the hub-peer trap. They are independent, and each needs its own witness.

Where neither holds, both readings can split 1-vs-0, so a clean split proves
nothing - which is how the wrong name shipped here first. Measured in such a
directory: own name 426 against 0, peer name 51 against 0, both apparently
perfect, because the session had one transcript there and no other session in it
mentioned that peer.

Where the second condition does hold, the peer reading fails on its own, whatever
the transcript count: other sessions in the measured 28-file directory scored 18,
10 and 5 on the peer's name, and a transcript with zero mentions of this session
took second place at 51.

### 3. Read the request, not just the reply

In that transcript, the `SendMessage` `tool_use` inputs hold **the exact request
each peer is answering** - which is the context the reply assumes and you lack.
The last assistant text shows what was still outstanding ("X is the only session
that has not replied"), so you can tell a complete set from a partial one.

### 4. Fold it into what the old session produced, and correct contradictions

The late reply is evidence that arrived after the conclusion was written, so the
conclusion may now be wrong. In the measured case the old session's next-day
plan required an approval naming an "istiod roll"; the reply's dev evidence
showed istiod does not restart. The plan needed changing, not annotating.

Treat a late reply as a reason to re-check the artifact, not merely to append to
it.

## Never fabricate a peer's reply

A peer that is `busy`, that never answers, or that declines the request has not
given you an answer. Say the reply is still outstanding. Do not synthesize what
it "would have" said, and do not present your own reasoning as its response.
The same applies to an expired idle subscription or a message the peer held or
refused: report unknown, not done.

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
   to `claude -p` without it - where every call that would prompt is denied
   rather than shown to you, and, on most plans, programmatic-usage credit is
   spent that interactive sessions do not.
2. **Does your multiplexer actually expose the control verb it needs?** A paste
   or inject RPC absent from your build means every call degrades to the
   fallback, and you have installed a large dependency to obtain the exact
   transport you were trying to avoid.

Answer both *before* installing, not after.

## Quick reference

| Situation | Do |
|---|---|
| Asked a question | wait for the `SendMessage` reply; no subscription needed |
| Delegated work, result lands in the repo | attach `notify_when_idle`, read the repo after the notice |
| Late reply after `/clear` | rewind menu's previous-session entry or `/resume`; grep only as fallback |
| Peer silent | check the lead/main session for its pending prompt, then `ListAgents` state |
| No reply, expired, held or refused | say "outstanding / unknown"; never write its answer |
| Target is not running | launch-a-callee, after the two questions above |

## Related

- `agent-team-orchestration` - spawning a *team* of agents over a backlog,
  where watchability per agent is the design constraint. This skill is the
  point-to-point case between sessions that already exist.
- `cmux-agent-tabs` - making spawned agents land on watchable surfaces. Also
  the home of the multi-hop `PATH` failures that break a shim-based transport.
- Worked example of the multi-hop trap in a real long-lived setup:
  https://blog.debedb.com/2026/08/10/cmux-eight-weeks-later-the-two-hop-path-trap/

The recurring theme across all three: with long-lived agent sessions nothing
breaks outright, things merely get **reordered underneath you** - `PATH`
positions, workspace identity, which transport a mode resolves to. Verify the
environment before trusting a conclusion drawn from behavior.
