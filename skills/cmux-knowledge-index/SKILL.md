---
name: cmux-knowledge-index
description: |
  Start here for any cmux question, then follow the pointer. Routes by symptom
  to the right cmux skill, blog post or issue: tabs missing or restored wrong
  after a quit, relaunch or reboot; two tabs resuming one Claude session; a
  tab resuming another tab's conversation; a second cmux window full of
  duplicate tabs ("two instances"); a session that cannot tell which tab it is
  in; agents not showing as tabs; config entries that silently do nothing;
  NODE_OPTIONS/$TMPDIR shims vanishing; tmux tools under cmux; agent-to-agent
  messaging in cmux. Also states in one place how cmux decides which session
  each tab resumes (per-tab resumeBinding replay, no one-tab-per-session rule)
  and which claims in older notes no longer hold on cmux 0.64.25.
author: Claude Code
version: 1.0.0
date: 2026-09-29
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-knowledge-index/SKILL.md
---

# cmux knowledge index

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/cmux-knowledge-index/SKILL.md`).

## Problem

What is known about cmux is spread over thirteen skills, six blog posts and an
open issue. Each one answers a single symptom, so a session starting from a
symptom has to guess which note applies. None of them said how cmux decides
which session a tab resumes, which is the root of most restore surprises.

## Context / Trigger Conditions

- Any cmux restore, tab, window, hook or environment question.
- Before writing a new cmux note: check whether one of these already covers it.

## Route by symptom

| Symptom | Go to |
|---|---|
| Tabs missing after a quit, relaunch or reboot | `cmux-session-restore-forensics` |
| Two tabs on one session, a tab resuming another tab's conversation, a duplicate window, "two instances" | `cmux-session-restore-forensics`, section "Crossed or duplicated bindings" |
| Tabs came back but as fresh agents, or cmux did not relaunch at login | `cmux-autoresume-after-reboot` |
| A session must find the tab it runs in | `cmux-session-self-identity` |
| Tab title, peer name and Remote Control name disagree | `claude-session-three-names` |
| Spawned agents do not appear as tabs | `cmux-agent-tabs` |
| Something was seen "in some pane" | `cmux-search` |
| Agent-to-agent traffic is invisible to the human | `cmux-cross-session-visibility` |
| A Claude agent and a Codex agent must message each other | `cmux-claude-codex-cross-runtime-messaging` |
| A `cmux.json` entry passes `cmux config doctor` but never shows | `cmux-config-silent-drop-triage` |
| Every `node`/`claude` call fails on a missing `--require` file | `cmux-node-options-tmpdir-guard` |
| A tmux-driving tool must work under cmux | `cmux-tmux-compat-gap-probe` |
| A runbook should run step by step beside the agent | `cmux-runbook-in-sibling-tab` |
| `CMUX_*` or other session variables leaked into launchd | `launchd-env-sync-session-leak` |

## How cmux picks the session a tab resumes

Traced in the 0.64.20 source and checked against 0.64.25 behaviour.

1. **Save.** The live file
   `~/Library/Application Support/cmux/session-com.cmuxterm.app.json` is
   autosaved about every 8 s when something changed, and on quit. A SIGTERM
   skips the final save.
2. **Rotate.** At launch the live file is copied to
   `session-com.cmuxterm.app-previous.json`, before the single-instance check.
   Identical bytes are not rewritten.
3. **Restore.** Launch reads the live file and falls back to `-previous` only
   when the live file is missing or unusable.
4. **Replay.** Each tab replays its own `terminal.resumeBinding.command`:
   `cd -- '<cwd>' && <claude wrapper> --resume <uuid>`. The binding's
   `checkpointId` is that session UUID. Nothing is looked up by tab title or
   folder.
5. **Gates.** A tab comes back as a plain shell unless `wasAgentRunning` is
   true or absent, and `autoResume` is true for `source: agent-hook` bindings.
6. **Rebind.** cmux's `claude` wrapper (active when `CMUX_SURFACE_ID` is set)
   injects hooks through `--settings`. A hook finds its tab by the process's
   controlling terminal, falling back to `CMUX_*` variables. The binding is
   written on UserPromptSubmit or Stop (and on SessionStart in 0.64.25) and
   cleared on SessionEnd. A fresh session that never gets a prompt never gets a
   binding.

**Nothing enforces one tab per session.** Reopening a saved snapshot into a
running cmux copies its bindings onto new tabs, and every copy launches.
Typing `claude --resume <uuid>` in a second tab binds it there while the first
tab keeps it. On 0.64.25 a launch-time guard (`cmux_restore_suppressed_live_owner`
in the agent journal) lets the first tab to start win; the twin comes back
empty. The tab title is stored on the tab and is never tied to the session.

## Claims that no longer hold

| Claim | Where | What holds on 0.64.25 |
|---|---|---|
| Workspace and tab ids are re-minted on restore | `cmux-session-restore-forensics` 1.2.0; the 2026-08-10 post | Ids stayed the same across five relaunches; still join on the session UUID |
| Restore launches `claude --session-id <uuid>` | `claude-session-three-names` | Restore uses `--resume <uuid>`; `--session-id` marks a fresh launch |
| Teams panes carry no binding | voitta-lab#2 title | Launcher panes carry one since 0.64.16; teammate panes untested |
| Bindings call an absolute path to claude | the 2026-06-17 post; `cmux-autoresume-after-reboot` | Bindings call `$CMUX_CLAUDE_WRAPPER_SHIM` since 0.64.16 |

## Blog posts

- [cmux setup](https://blog.debedb.com/2026/06/17/cmux-setup/) (2026-06-17):
  reboot-resume recipe on 0.64.15, the `wasAgentRunning` gate, a replay script.
- [herdr and cmux: two shapes of the same agent multiplexer](https://blog.debedb.com/2026/07/26/herdr-and-cmux-two-shapes-of-the-same-agent-multiplexer/)
  (2026-07-26): hooks store each agent's resume command.
- [cmux, eight weeks later: the two-hop PATH trap](https://blog.debedb.com/2026/08/10/cmux-eight-weeks-later-the-two-hop-path-trap/)
  (2026-08-10): a reboot on 0.64.16 restored 7 of 7 tabs.
- [Two agents picked the same job. One said so.](https://blog.debedb.com/2026/08/27/two-agents-picked-the-same-job-one-said-so-part-1-of-2/)
  (2026-08-27): two sessions resuming one handoff document.
- [Pinger, ponger, and the tab that could not say its name](https://blog.debedb.com/2026/08/27/pinger-ponger-and-the-tab-that-could-not-say-its-name-part-2-of-2/)
  (2026-08-27): sessions naming their own tab; stale `CMUX_*` variables.
- [The metric that graded my orchestration a C](https://blog.debedb.com/2026/07/23/the-metric-that-graded-my-orchestration-a-c-and-what-it-was-actually-measuring/)
  (2026-07-23): tagged cmux, nothing on restore.
- All posts: https://blog.debedb.com/tag/cmux/

## Verification

Every skill named in the routing table exists in `skills/` of this repo.
When a new cmux skill lands, add its row here.

## Notes

- Restore behaviour changed between 0.64.15, 0.64.16 and 0.64.25. Quote the
  cmux version with any claim you add.
- The local source trace behind "How cmux picks the session" is 0.64.20; the
  0.64.25 differences listed are observed behaviour, not code.

## Related

- Open issue: https://github.com/voitta-ai/voitta-lab/issues/2 (restore drops,
  teams panes, a 0.64.16 binding sample).
