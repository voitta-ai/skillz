---
name: cmux-session-self-identity
description: |
  Determine which cmux workspace, tab and surface an agent session is actually
  running in, and map other live sessions to theirs. Use when: (1) a session
  needs to tell a human or a peer where it is ("which tab am I?"), (2) you are
  about to address a message to another session and need its real tab, (3) a
  human sent instructions to the wrong tab and you are reconstructing who should
  have received them, (4) you are tempted to read `CMUX_*` environment variables
  to answer any of the above, (5) several sessions disagree about which is which, (6) `cmux identify` fails with a broken-pipe or access-denied error, which is the normal case for a spawned subagent rather than a fault.
  Root cause of the confusion: the tab and workspace environment variables can
  carry the SAME id, so tab identity is not in the environment at all -- and on a
  resumed session those variables are a stale launch-time snapshot that can name
  a workspace the session is no longer in. The bundled cmux CLI answers all of it
  authoritatively.
author: Claude Code
version: 1.2.0
date: 2026-08-24
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-session-self-identity/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/cmux-session-self-identity/SKILL.md`). Updates go through the repo's
> worktree + PR workflow.

# cmux-session-self-identity

## Problem

Agent sessions running in cmux are routinely wrong about where they are. In one
observed window, **three of four sessions could not correctly name their own
tab** — each had inferred it from the phrasing of the task it was given rather
than from the runtime.

That is not a cosmetic problem. It has a direct failure downstream: a session
that cannot name its own tab cannot tell a human which tab to address, so the
human has no reliable source either. In the same window a human typed
instructions into the wrong tab; they landed in a session with no ability to act
on them. The identity gap is *upstream* of the addressing error, not parallel to
it.

## Why the environment lies

Two separate defects, and they compound:

1. **Tab identity is not in the environment.** The tab and workspace variables
   can hold the *same* id, so there is nothing there that distinguishes the tab
   from the workspace. Reading the "tab" variable and reporting it as a tab is
   reporting the workspace.
2. **A resumed session's variables are a launch-time snapshot.** They are not
   refreshed when the session is restored elsewhere. An observed session reported
   one workspace id from its environment while actually running in a different
   workspace entirely.

So: never answer an identity question from `CMUX_*`. Ask the runtime.

## The three commands

The CLI ships inside the app bundle, at
`/Applications/cmux.app/Contents/Resources/bin/cmux` on macOS. Use the bundled
path rather than relying on it being on `PATH`.

**Who am I** — returns the *caller's* own refs:

```bash
/Applications/cmux.app/Contents/Resources/bin/cmux identify
```

The `caller` object is the answer; a separate `focused` object describes whatever
the user is currently looking at, which is usually a **different** session. Read
`caller`, not `focused` — confusing the two is the most likely way to get a
confident wrong answer out of this command.

```json
{
  "caller": {
    "workspace_ref": "workspace:2",
    "tab_ref": "tab:4",
    "surface_ref": "surface:4",
    "pane_ref": "pane:2",
    "window_ref": "window:1",
    "surface_type": "terminal"
  },
  "focused": { "workspace_ref": "workspace:4", "...": "..." }
}
```

**Refs to names** — `identify` returns refs, not names. Resolve them:

```bash
/Applications/cmux.app/Contents/Resources/bin/cmux tree --all --id-format both
```

```
window window:1 <uuid> [current] ◀ active
├── workspace workspace:1 <uuid> "alpha"
│   └── pane pane:1 <uuid> [focused]
│       └── surface surface:3 <uuid> [terminal] "worker-1" [selected]
├── workspace workspace:2 <uuid> "beta"
│   └── pane pane:2 <uuid> [focused]
│       └── surface surface:4 <uuid> [terminal] "worker-2" [selected]
```

(Names above are invented for illustration.) Match your `caller.workspace_ref`
and `caller.surface_ref` against this tree to get your workspace and tab names.
`--id-format both` prints refs *and* UUIDs, which is what lets you join the two
commands.

**Sessions to surfaces** — map running processes onto the tree:

```bash
/Applications/cmux.app/Contents/Resources/bin/cmux top --all --processes --format tsv
```

This is how you answer "which tab is that *other* session in", given its pid.

## When the CLI refuses you

**The commands above only work if your process is a descendant of the cmux app.**
A subagent running in a detached multiplexer pane usually is not, and the CLI
fails in a way that does not say so:

```
Failed to write to socket (Broken pipe)
```

Probing the control socket directly gives the real reason:

```
Access denied — only processes started inside cmux can connect
```

Check your ancestry to confirm — a chain that reaches a daemonized multiplexer
server (parent pid 1) rather than the cmux app is the tell:

```bash
cur=$$; for i in $(seq 8); do
  read -r pid ppid comm <<<"$(ps -o pid=,ppid=,comm= -p $cur)"
  echo "$pid $comm"; [ "$ppid" -le 1 ] && break; cur=$ppid
done
```

This is not an edge case. **It is the normal situation for spawned subagents**,
which are exactly the processes that most need to answer "where am I".

### Fallback: the app's live state file

```
~/Library/Application Support/cmux/session-<bundle-id>.json
```

It maps workspace ids to their `customTitle` and panel/surface ids to theirs.
Unlike the environment variables, **it is maintained live** — check its mtime
before trusting it; a file modified seconds ago is current state, not a
launch-time snapshot.

The environment variables are still useful here, but only as *keys*, never as
answers: read `CMUX_WORKSPACE_ID` / `CMUX_SURFACE_ID` and look them **up** in the
live file rather than reporting them directly. That inverts the earlier warning
correctly — the ids are real, it is the *placement they imply* that goes stale.

```bash
python3 - <<'PY'
import json, os, glob
p = glob.glob(os.path.expanduser("~/Library/Application Support/cmux/session-*.json"))[0]
d = json.load(open(p))
ws, surf = os.environ.get("CMUX_WORKSPACE_ID"), os.environ.get("CMUX_SURFACE_ID")
print("workspace id:", ws, "surface id:", surf)
print(json.dumps(d)[:0])  # shape varies by version; walk it for customTitle next to those ids
PY
```

Cross-check the ids across your own environment, the multiplexer server's, and
your parent agent's. Agreement across independent processes is what upgrades the
answer from a guess to a reading.

### Two claims to keep separate

A resumed or subagent session must distinguish:

1. **Which tab am I associated with** — answerable from the live state file.
2. **Which tab is rendering me right now** — often *nothing*. A detached
   multiplexer pane (`attached=0`, zero clients) is displayed nowhere, and the
   tab that "owns" it is showing the parent session instead.

Report the first, and say plainly that it is an association rather than a
rendering, when the pane is detached. Claiming a tab is "showing you" when
nobody is attached to it is the kind of confident-but-wrong answer this skill
exists to prevent.

## Recipe: name yourself

```bash
CMUX=/Applications/cmux.app/Contents/Resources/bin/cmux
WS=$("$CMUX" identify | python3 -c 'import json,sys; print(json.load(sys.stdin)["caller"]["workspace_ref"])')
SF=$("$CMUX" identify | python3 -c 'import json,sys; print(json.load(sys.stdin)["caller"]["surface_ref"])')
"$CMUX" tree --all --id-format both | grep -E "workspace $WS |surface $SF "
```

## Verification

You have the right answer when all three hold:

- The workspace name came from `tree`, matched against `caller.workspace_ref` —
  not from an environment variable, and not from the wording of your task.
- You used `caller`, not `focused`.
- A peer session independently agrees, or you resolved its pid through
  `top --processes` yourself.
- If the CLI refused you, you said so and named the fallback you used, rather
  than presenting a state-file reading as though the runtime confirmed it.

If a peer tells you your own tab name and it contradicts what you believed,
**the peer that ran the CLI is right** and you were guessing. That is the normal
case, not an unusual one.

## Notes

- Session names visible to messaging tools (the names peers address you by) are
  a *different* namespace from cmux workspace and tab names. A session can be
  addressable as one string while sitting in a tab called something else
  entirely. Report both when identifying yourself to a human, since the human
  sees the tab and the peer sees the session name.
- Do not publish a real workspace/tab layout: names, UUIDs and pids together are
  infra topology. The examples here are invented.

## Related

- `cmux-agent-tabs` — why a session may have no cmux surface at all, in which
  case the identity question has no answer rather than a wrong one.
- `claude-code-cross-session-messaging` — the peer-addressing namespace this
  skill's Notes warn is *different* from workspace and tab names. Resolve the
  address there; resolve the surface here.
- `cmux-cross-session-visibility` — the status pill a session maintains for its
  own workspace, which needs the workspace id this skill resolves.
- `cmux-search` — the inverse lookup: find the surface that holds a string,
  rather than the surface you are in.
- `cmux-session-restore-forensics` — why the ids you resolved stop matching
  after a relaunch.
