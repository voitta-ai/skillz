---
name: followups
description: |
  Keep a per-machine list of dated follow-ups ("when the silence ends on the
  22nd, confirm the alert recovered", "after the 7-day bake, do the cutover",
  "once the sprint rolls over, stop using its id") and have exactly one live
  Claude Code session check it every 3 hours with a recurring CronCreate job.
  Use when: (1) a finding comes with a date after which someone must look
  again, and the only record of it is prose in a handoff, a memory file or a PR
  comment; (2) a ticket or plan says "after <date>" or "until <date>"; (3) a
  SessionStart line says "followups: N open item(s) on this machine, and the
  loop is not running"; (4) a "[followups tick]" prompt arrives, or a tick
  prints NOT OWNER, REARM or DUE; (5) you want to know which follow-ups are
  pending on this machine. Covers the item format (check time, expiry,
  self-contained check text), the lock that keeps one loop owner per machine
  (pid plus process start time, heartbeat, takeover), arming and re-arming the
  cron job before CronCreate's 7-day expiry, handling due items read-only, and
  the optional SessionStart hook.
author: Claude Code
version: 1.0.0
date: 2026-10-09
source: https://github.com/voitta-ai/skillz
source_file: skills/followups/SKILL.md
---

# followups: dated checks, one loop per machine

## Problem

Findings often come with a date: a silence that ends, a bake period, a sprint
rollover, a link that expires. The date is written into a handoff, a memory
file or a PR comment, and nothing looks at it again when the day comes.

Claude Code can schedule prompts, but only inside one session. `CronCreate`
jobs live in memory and die with the session, they fire only while that
session's REPL is idle, and recurring jobs are deleted after 7 days
(`durable` has no effect). A follow-up two weeks out outlives any one job, and
several sessions each arming their own job would check everything several
times.

## Context / Trigger Conditions

- You just wrote "re-check after <date>" or "until <date>" into a handoff,
  memory, PR comment or ticket. Add an item as well.
- A session starts with: `followups: N open item(s) on this machine, and the
  loop is not running (...)`. That is the SessionStart hook: run Start.
- A prompt beginning `[followups tick]` arrives. That is the loop: run Tick.
- The user asks what is pending, or when something will be checked:
  `~/.followups/bin/followups list`.

## Solution

Everything lives in `~/.followups/` (override with `FOLLOWUPS_DIR`):

| Path | What |
|---|---|
| `open/<id>.json` | items still to check |
| `done/`, `expired/` | closed items; `done/` ones carry `result` and `done_at` |
| `loop.lock` | the loop owner: pid, process start time, session name, `armed_at`, `last_tick` |
| `bin/followups` | stable copy of this skill's `scripts/followups` |

The cron prompt and the SessionStart hook call `~/.followups/bin/followups`,
not the copy under the plugin, because a plugin's install path changes with
every version.

### Add an item (any session)

```bash
~/.followups/bin/followups add <<'EOF'
{
  "id": "2026-10-22-latency-alert-after-silence",
  "title": "Latency alert after its silence ends",
  "check_at": "2026-10-22T16:30:00Z",
  "expires_at": "2026-10-25T00:00:00Z",
  "check": "The silence on alertname=\"API latency p99\" ended 2026-10-22 16:00Z. Read the rule's state from the Grafana API (/api/prometheus/grafana/api/v1/rules). Normal: done. Firing: the projected recovery did not happen; report the current value and the 28-day median, and leave the item open. Context: memory file api-latency-level-shift.",
  "source": "session ops-2, PR #123 comment"
}
EOF
```

- Write `check` for a reader with no context. It runs in whichever session
  owns the loop, possibly days later. Name the exact query, command or API,
  what "fine" looks like, what to do otherwise, and where the background
  lives (memory file, PR, ticket).
- `check_at` and `expires_at` are UTC, exactly `YYYY-MM-DDTHH:MM:SSZ`.
  `expires_at` is when the item stops mattering: an item still unchecked by
  then moves to `expired/`, and the tick reports it.
- Several dates to look at? Add the item for the first one and have its
  check end with `snooze` to the next date.
- `add` refuses an existing id and prints a note when no live loop owns the
  machine: then run Start.

### Start the loop (any session; the hook asks for this)

1. Refresh the stable copy:
   `install -d ~/.followups/bin && { cmp -s <this skill's dir>/scripts/followups ~/.followups/bin/followups || install -m 755 <this skill's dir>/scripts/followups ~/.followups/bin/followups; }`
2. `~/.followups/bin/followups claim "<this session's ListAgents name>"`.
   Exit 1 means a live session already owns the loop: stop here.
3. Call `CronCreate` with the `cron` and `prompt` that `claim` printed,
   `recurring: true`.
4. Run Tick once now.

`claim` takes the lock only if it is absent, or its holder has exited, or its
holder has not ticked for 7 hours. "Exited" compares the pid and the process
start time, so a reused pid does not keep a dead owner alive. The lock is
created with `ln`, so two sessions starting at once cannot both win; the loser
gets exit 1.

### Tick (the owner session, every 3 hours)

`followups tick` refreshes `last_tick`, moves expired items and prints:

- `NOT OWNER` — another session took the loop while this one was not
  ticking. `CronList`, `CronDelete` the `[followups tick]` job, and stop.
- `REARM` — the job is over 6 days old and `CronCreate` deletes it at 7:
  `CronDelete` it, `CronCreate` the same cron and prompt, then
  `followups claim` to reset `armed_at`. A session that adopts an orphaned
  loop during a tick gets `REARM` at once, because its job's age is unknown.
- `DUE:` and the item's JSON, once per item — handle each one (below).
- A last line, `followups: N due` or `followups: nothing due; next: <id> at
  <time>`, plus any items that expired unchecked. When nothing is due, that
  line is the whole reply.

### Handle a due item

1. Do what `check` says, read-only. Do not post, apply, merge, resolve,
   delete or silence anything from a tick: nobody is watching this session
   for approvals. If the check calls for such an action, say so and leave
   the item open.
2. Close it with `followups done <id> "<one-line result>"`, which also
   raises a macOS notification. To look again later, use
   `followups snooze <id> <next check_at>` instead.
3. Report the result in one or two lines in the session.

### SessionStart hook (once per machine, with the user's OK)

`followups hook` is silent unless open items exist and no live session owns
the loop; then it prints the one line shown above. Merge this into the
existing `hooks` object of `~/.claude/settings.json` rather than replacing
it:

```json
{"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "$HOME/.followups/bin/followups hook"}]}]}}
```

## Verification

- `followups list` prints `loop: owner <name> (pid N), last tick Nh ago`,
  then the open items in check order.
- `CronList` in the owner session shows exactly one `[followups tick]` job.
- After a tick, `jq .last_tick ~/.followups/loop.lock` is fresh.

## Example

A latency alert was silenced for two weeks while a metric's 28-day median
caught up with a deliberate level shift. The session that set the silence
added the item above and ran Start. On the 22nd at 16:30Z the owner session's
tick printed the item as DUE, read the rule state (Normal), and ran
`followups done 2026-10-22-latency-alert-after-silence "rule Normal since
00:40Z; silence expired cleanly"`. Had the rule been firing, the tick would
have reported the value and left the item open for a human.

## Notes

- Per machine. The lock means nothing across machines; give each machine its
  own items.
- Ticks land in the owner's conversation, about 8 a day. A dedicated, mostly
  idle session makes the cleanest owner, but any session works. A busy owner
  ticks late, since cron fires only when its REPL is idle; after 7 hours
  without a tick, another session may take over, and the old owner stands
  down at its next tick.
- `claim` and `tick` need `CLAUDE_PID`, which Claude Code sets in its Bash
  tool environment, and `jq`. Notifications need `osascript`; elsewhere
  `done` only prints.
- The interval (3 hours), the staleness limit (7 hours) and the re-arm age
  (6 days) are constants at the top of the script.

## Related

- `claude-session-three-names` — give the owner a meaningful ListAgents name, since `claim` records it and `list` shows it to everyone.
- `claude-code-cross-session-messaging` — to ask the owner session about a check it ran, or hand it one.
- `parallel-agent-session-collisions` — general duplicate-work hazards between sessions; this skill's lock covers only the loop.
