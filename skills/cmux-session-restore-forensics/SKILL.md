---
name: cmux-session-restore-forensics
description: |
  Work out what cmux actually restored after a quit/relaunch, and bring back
  workspaces and panes it dropped. Use when: (1) cmux reopened "some but not
  all" tabs and the result looks haphazard, (2) an agent-teams session did not
  come back at all, (3) tabs reappeared that you had already closed, (4) you
  need to tell "cmux silently lost this pane" apart from "I closed it myself",
  (5) you want to resurrect a Claude Code session whose tab is gone but whose
  session id still exists, (6) a tab resumed another tab's conversation, or two
  tabs (two ListAgents rows with one name) run the same session, (7) a second
  cmux window full of duplicate tabs appeared and it looks like "two instances".
  Covers the on-disk session/closed-history JSON, the Core Data epoch gotcha in
  their timestamps, diffing two snapshots by session UUID, the agent journal,
  ~/.cmuxterm/events.jsonl and the runningboardd log as evidence, replaying a
  pane's stored resumeBinding through `cmux new-workspace`, and rewriting
  crossed bindings offline with cmux quit.
author: Claude Code
version: 1.3.0
date: 2026-09-29
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-session-restore-forensics/SKILL.md
---

# cmux Session Restore Forensics

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/cmux-session-restore-forensics/SKILL.md`).

## Problem

cmux restores workspaces and panes after a relaunch on a best-effort basis. When
it only partly succeeds you get a window that looks roughly right but is missing
work, and cmux surfaces no error saying so. On builds before 0.64.25 the restore
path also *recreated* workspaces with new ids, so matching workspaces by id
before and after reported total churn and told you nothing.

Agent panes are the expensive case: a lost pane means a Claude Code session you
can no longer reach from the UI, even though the session itself still exists on
disk and is resumable.

A quieter failure is a pane that comes back *wrong*. Every pane replays the
session named in its own saved binding, and nothing stops two panes naming the
same session. Once a binding is crossed, every later restore reproduces it
faithfully, so it looks like restore is broken when the saved state is.

## Context / Trigger Conditions

- After a cmux quit/relaunch, noticeably fewer tabs than you had.
- A Claude Teams / agent-teams workspace did not reopen, or reopened as an empty
  shell that does nothing.
- Tabs you had closed earlier are back.
- You need to prove whether a given pane was dropped by cmux or closed by you.
- A tab opens another tab's conversation, or one tab of a pair comes back empty
  on every relaunch.
- `ListAgents` shows two rows with one session name, or `ps` shows two
  `claude --resume <same-uuid>` processes.
- A second cmux window with the same workspaces appeared, and "two cmux
  instances" is the working theory.

## The state files

Under `~/Library/Application Support/cmux/` on macOS:

| File | What it is |
|---|---|
| `session-com.cmuxterm.app.json` | live state, autosaved as you work and on quit |
| `session-com.cmuxterm.app-previous.json` | **the snapshot from before the last relaunch — your recovery source** |
| `closed-item-history-com.cmuxterm.app.json` | full snapshots of individually closed workspaces/panels/windows |
| `agent-journal-com.cmuxterm.app.sqlite3` | append-only log of agent hook events per pane (0.64.25): which pane started which session, and restore suppressions |

And under `~/.cmuxterm/`:

| File | What it is |
|---|---|
| `events.jsonl` (older part in `events.jsonl.1`) | timestamped `window.created`, `workspace.created`, `surface.created` / `.closed` events and `agent.hook.*` events |
| `claude-hook-sessions.json` | the hook store: session to pane, cwd, restorable flag; records expire after 7 days |

Shape of the session files:

```
windows[] -> tabManager.workspaces[] -> panels[]
```

A workspace carries `workspaceId`, `customTitle`, `currentDirectory`, `layout`.
A panel carries `id`, `customTitle`, `directory`, and `terminal`, and
`terminal.resumeBinding.command` is the command cmux replays to bring that pane
back. For Claude, `resumeBinding.checkpointId` is the session UUID in that
command. **A panel with no `resumeBinding.command` cannot be restored by
anything.** A single-pane workspace lists its tabs in
`layout.pane.panelIds`.

`closed-item-history` is a dict with a `records` list; each record is
`{closedAt, id, entry}` where `entry` is a single-key dict — `workspace`,
`panel`, or `window` — whose `_0.snapshot` holds the same structure as above.

## Three gotchas that will mislead you

**1. `closedAt` uses the Core Data reference date, not the Unix epoch.**
It counts seconds from 2001-01-01, so `datetime.fromtimestamp()` reports dates
31 years too early — a close from last night shows up as 1995. Convert with
`datetime(2001,1,1) + timedelta(seconds=closedAt)`. Getting this wrong makes
every closed item look ancient and irrelevant.

**2. Join on the session UUID, not on `workspaceId`.** Builds before 0.64.25
minted new workspace and panel ids on restore, so a set-difference on
`workspaceId` reported "everything lost, everything new". On 0.64.25 the ids
stayed the same across five relaunches, but a reopened snapshot or a rescued
pane still gets ids of its own. The session UUID in the binding is the same
session before and after, so it is the reliable join key.

**3. Extracting that UUID from the command is fiddly.** The stored command is
heavily shell-quoted, e.g. `'\''--resume'\'' '\''<uuid>'\''`. A regex expecting
`--resume <uuid>` with plain spacing silently matches nothing and you conclude
no pane had a binding. Read `resumeBinding.checkpointId`, or search for the
first UUID *after* the index of the literal `--resume`.

## Solution

### Step 1 — classify every pane

For each panel in `-previous.json`, extract `(workspace title, panel title, cwd,
resume command, session uuid)`. Do the same for the current session file, and
read the closed-item history for anything closed since the relaunch. Then bucket:

- **has a binding, present now** — restored fine.
- **has a binding, absent now, present in closed-history after the relaunch** —
  you closed it. Leave it.
- **has a binding, absent now, not in closed-history** — **silently dropped by
  cmux. This is what you recover.**
- **no binding at all** — unrecoverable; nothing was ever stored to replay.
- **session UUID shared with another pane** — a crossed binding; see
  "Crossed or duplicated bindings" below.

### Step 2 — recover the dropped panes

Replay each stored command as a new workspace:

```bash
CMUX="${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}"
"$CMUX" new-workspace --name "<panel title>" --cwd "<cwd>" --command "<resumeBinding.command>" --focus false
```

Use `--focus false` so a batch of restores does not yank your focus around.

`closed-item-history` is a second recovery source with the same shape, for tabs
closed further back than the last relaunch.

### Step 3 — expect a trust prompt on each rescued tab

The pane comes back in a *new* workspace, and Claude Code's folder trust is
scoped to the original one. Every rescued agent tab therefore stops at
"Quick safety check: is this a project you created or one you trust?" and waits
for a keypress. That is expected, not a failure — walk the tabs and confirm each.

## Crossed or duplicated bindings

Nothing in cmux enforces one pane per session. Reopening a saved snapshot into a
running cmux copies its bindings onto new panes and every copy launches;
`claude --resume <uuid>` typed in a second pane binds it there while the first
pane keeps it. On 0.64.25 a launch-time guard logs
`cmux_restore_suppressed_live_owner` and lets the first pane to start win, so
the twin comes back as an empty shell.

**1. List bindings and flag shared sessions.** Copy the state files aside first.

```bash
python3 - <<'PY'
import collections, json, os
path = os.path.expanduser('~/Library/Application Support/cmux/session-com.cmuxterm.app.json')
owners = collections.defaultdict(list)
for w in json.load(open(path))['windows']:
    for ws in w['tabManager']['workspaces']:
        for p in ws['panels']:
            rb = (p.get('terminal') or {}).get('resumeBinding') or {}
            name = '%s/%s' % (ws.get('customTitle'), p.get('customTitle'))
            print('%-32s %s  %s' % (name, rb.get('checkpointId', '-'), rb.get('cwd', '')))
            if rb.get('checkpointId'):
                owners[rb['checkpointId']].append(name)
for sid, names in owners.items():
    if len(names) > 1:
        print('SHARED', sid, names)
PY
```

**2. Settle "two instances" with the process log.** Single-instance is enforced
by bundle id, so a second *window* is far likelier than a second *process*.
RunningBoard records every launch and exit:

```bash
log show --start '<YYYY-MM-DD HH:MM:SS>' --style compact \
  --predicate 'process == "runningboardd" AND eventMessage CONTAINS "application.com.cmuxterm.app"' \
  | grep -E 'Now tracking process: \[app|termination reported'
```

Two instances means one PID's `Now tracking` before another's `termination
reported`. `(0, 0, 0)` is a clean exit; `(2, 15, 15)` is SIGTERM, which skips
cmux's final save.

**3. Find when the duplicates appeared.** `~/.cmuxterm/events.jsonl` has
`window.created` and `surface.created` with timestamps; the burst of
`agent.hook.SessionStart` right after it (payload `session_id`, plus the
`workspace_id`) shows every session the new window launched. The agent journal
gives the pane:

```bash
mkdir -p /tmp/j && cp ~/Library/Application\ Support/cmux/agent-journal-com.cmuxterm.app.sqlite3* /tmp/j/   # WAL: copy all three
sqlite3 -readonly 'file:/tmp/j/agent-journal-com.cmuxterm.app.sqlite3?mode=ro' \
  "select datetime(occurred_at_ms/1000,'unixepoch','localtime'), native_event, session_id, surface_id
   from agent_journal order by sequence"
```

`surface_id` is the panel `id` in the session file.

**4. Find each pane's rightful session.** Claude transcripts
(`~/.claude/projects/<dir>/<uuid>.jsonl`) carry a `custom-title` entry, often
`<workspace>:<tab>`, and a `cwd`. Match the tab name against those titles, then
check the cwd. A window closed during the mess is in `closed-item-history` and
may still hold the correct binding verbatim; prefer copying it over building
one.

**5. Rewrite the bindings offline.** Quit cmux first: it autosaves every few
seconds and on quit, overwriting any edit. Back up the live file, then per
wrong pane:

```python
import json, os, shutil
path = os.path.expanduser('~/Library/Application Support/cmux/session-com.cmuxterm.app.json')
shutil.copy2(path, path + '.pre-patch')
state = json.load(open(path))

def pane(ws_title, tab_title):
    retval = next(p for w in state['windows'] for ws in w['tabManager']['workspaces']
                  if ws.get('customTitle') == ws_title
                  for p in ws['panels'] if p.get('customTitle') == tab_title)
    return retval

def rebind(p, sid, cwd):
    term = p['terminal']
    rb = term['resumeBinding']
    rb['command'] = rb['command'].replace(rb['checkpointId'], sid).replace("'%s'" % rb['cwd'], "'%s'" % cwd)
    rb.update(checkpointId=sid, cwd=cwd, autoResume=True)
    if 'launchCommand' in rb:
        rb['launchCommand']['workingDirectory'] = cwd
    term.update(wasAgentRunning=True, workingDirectory=cwd)
    p['directory'] = cwd

rebind(pane('<workspace>', '<tab>'), '<right-session-uuid>', '<right-cwd>')
json.dump(state, open(path, 'w'), sort_keys=True)
```

A pane with no binding takes a deep copy of a working pane's binding, then
`rebind`. To bring back a closed tab, deep-copy its panel from
`closed-item-history`, append it to the workspace's `panels` and to
`layout.pane.panelIds`, and check its `id` is not already in use. Before
writing, rerun step 1's check on the patched state: no session may appear
twice.

## Verification

After a recovery with `new-workspace`:

```bash
python3 - <<'PY'
import json
d=json.load(open('/Users/<you>/Library/Application Support/cmux/session-com.cmuxterm.app.json'))
n=0
for w in d['windows']:
    for ws in w['tabManager']['workspaces']:
        n+=len(ws['panels'])
        print(' %-16s panels=%d'%(str(ws.get('customTitle'))[:16], len(ws['panels'])))
print('total panels:', n)
PY
```

The rescued names should appear, and the total should have risen by exactly the
number you replayed. The live file is rewritten within a second or two of the
`new-workspace` call.

After an offline rewrite, relaunch cmux and read the agent journal from the
relaunch on: every pane should log exactly one `SessionStart`, with its own
session, and no `cmux_restore_suppressed_live_owner`.

## Example

A relaunch that looked mostly fine actually broke down as: 26 panels before the
quit, 16 of them carrying a `resumeBinding`, 7 restored, 3 restored and then
closed by hand, and **5 silently dropped**. The remaining 10 had no binding at
all. Replaying those 5 commands brought every one back.

A second case, on 0.64.25: after two reboots, two tabs resumed other tabs'
sessions and a third came back as a shell. The process log showed one cmux at a
time, never two. `events.jsonl` showed a second window created in one step
inside a long-running cmux, which then launched 17 sessions in 15 seconds, many
of them already open in the first window. Its bindings came from an older
snapshot and were already crossed. Later the *original* window was closed, so
the stale window was the one saved, and both reboots replayed it faithfully.
Rewriting three bindings offline, turning on one `autoResume`, and re-adding
four closed tabs from `closed-item-history` brought all 15 tabs back on the
next launch, each session started exactly once.

## Notes

- **Teams panes and `resumeBinding`: check, do not assume.** Older cmux gave
  panes spawned by `cmux claude-teams` no `resumeBinding` at all — neither the
  launcher nor the teammates — so a teams session was unrecoverable by
  construction. **That no longer holds as of cmux 0.64.16.** Measured across a
  real reboot on 2026-08-07: 7/7 panels restored, zero dropped, and the
  agent-teams launcher pane came back carrying a `resumeBinding` with
  `source: "agent-hook"`. Teammate panes spawned through the tmux-compat path
  remain untested — none existed before that reboot. So read the pane's actual
  binding out of `-previous.json` before writing a teams session off. A rescued
  teams pane still returns in a new workspace with its folder trust reset; keep
  durable state in git, issues, or notes regardless.
- Do not diff the two session files by hand. The interesting difference is
  almost never visible at the workspace level; it lives in per-panel bindings.
- `-previous.json` is overwritten by the *next* launch, even one killed seconds
  later. If a restore looks wrong, copy the state files aside before doing
  anything else — including before relaunching again to "see if it fixes
  itself". One 0.64.25 launch from an edited live file left `-previous.json`
  untouched (unexplained), so do not assume it holds the last launch's input.
- The window you keep is the window that restores. Closing the wrong one of two
  duplicate windows keeps the stale bindings.
- The `cmux` CLI is often not on `PATH`; resolve it via
  `${CMUX_BUNDLED_CLI_PATH:-/Applications/cmux.app/Contents/Resources/bin/cmux}`.

## Related

- `cmux-knowledge-index` — the hub: routes any cmux symptom to its skill and
  says how restore picks each tab's session.
- `cmux-autoresume-after-reboot` — the adjacent question of *why* restore
  under-performed: cmux not relaunching at login, or the
  `wasAgentRunning == false` gate bringing panes back as fresh agents. Reach for
  that one when panes return but have lost their conversation; reach for this one
  when panes do not return at all and you want them back. It parses the same
  session file as this skill and defers here for its layout.
- `cmux-agent-tabs` — getting agents to appear as tabs in the first place, which
  is what gives them a `resumeBinding` to recover.
- `cmux-search` — searching across live panes and transcripts, including the
  transcripts of a session whose pane did not come back.
- `cmux-session-self-identity` — mapping a restored pane back to the session
  running in it.
- `claude-session-three-names` — why a tab title and the session's own names
  drift apart.
