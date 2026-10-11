---
name: cmux-autoresume-after-reboot
description: |
  Diagnose why cmux (com.cmuxterm.app) does not resume agent sessions after a
  macOS reboot even though terminal.autoResumeAgentSessions is true. Use when:
  (1) cmux config / Settings has autoResumeAgentSessions enabled but Claude/Codex
  panels come back EMPTY or as FRESH agents after a restart, (2) panes are
  restored and agents are even running, but they are NEW sessions (lost prior
  conversation), (3) you need to confirm whether cmux relaunched at login AND
  whether it resumed vs started fresh. TWO independent failures: (A) cmux not
  relaunched at login (not a Login Item) -> nothing to resume; (B) cmux relaunches
  fine but the per-pane wasAgentRunning==false gate (manaflow-ai/cmux#4269)
  suppresses auto-resume, so every pane starts a fresh agent. Covers the
  login-time-vs-boottime trap, the decisive snapshot/argv checks, restore gating
  rules, and the manual-resume-script workaround.
author: Claude Code
version: 1.5.0
date: 2026-06-19
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-autoresume-after-reboot/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/cmux-autoresume-after-reboot/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.
# cmux autoResumeAgentSessions not resuming after macOS reboot

## Problem
`terminal.autoResumeAgentSessions` is true, but after a macOS **reboot** the
Claude/Codex panels are empty, or (more subtly) the panes come back with **fresh**
agents that have lost their prior conversation. User concludes the setting is broken.

## There are TWO independent failures. Diagnose which one.

### Cause A: cmux did not relaunch at login
`autoResumeAgentSessions` only runs resume commands **when cmux reopens** (schema:
*"...when cmux reopens after quit."*). It is NOT a boot daemon. If cmux is not a
Login Item (and not in the macOS reopen-at-login list / no LaunchAgent), it stays
closed across the reboot, so nothing resumes. Fix = make it relaunch (Login Item).

### Cause B: cmux relaunched, but auto-resume is gated off (the subtle one)
Even with cmux relaunching correctly, every pane can come back as a **fresh** agent
(`claude --chrome`, new `--session-id`) instead of `claude --resume <id>`. Root cause
is the `wasAgentRunning == false` gate added in cmux #4269:

> At restore time, skip auto-resume when `wasAgentRunning == false`.

`wasAgentRunning` is computed at snapshot time as `shellActivityState == .commandRunning`.
For a long-running interactive agent that is **idle at its own prompt** (the normal
state when you walk away / shut down), `shellActivityState` is not `.commandRunning`,
so `wasAgentRunning` is persisted `false` — and #4269 then treats the live-but-idle
agent the same as a user-exited one and does NOT resume it. The conversation id is
preserved for *manual* resume only. Net: auto-resume is effectively a no-op for the
"shut laptop with agents idle, reboot, reopen" flow. (Upstream: #5802 reports this;
related #4187 focus-gating, #2923 feature request. The setting value is NOT the gate.)

## Diagnosis (read-only)

1. Confirm the setting is actually on where the app reads it (UserDefaults, NOT just
   cmux.json — Swift reads `AgentSessionAutoResumeSettings.isEnabled(defaults:.standard)`):
   ```bash
   defaults read com.cmuxterm.app terminal.autoResumeAgentSessions   # want 1
   ```
   If this is 1 (or unset -> defaults true) the setting is fine; the gate is elsewhere.

2. Did cmux relaunch AT LOGIN? Do NOT trust `kern.boottime` vs process etime — the
   Mac can sit at the password screen for hours after kernel boot, so a process that
   started "long after boot" may still have started right at login. Compare against
   the **login** time instead:
   ```bash
   for p in loginwindow Finder Dock; do pid=$(pgrep -x "$p"|head -1); \
     [ -n "$pid" ] && echo "$p: $(ps -o lstart= -p $pid)"; done
   ps -o lstart= -p "$(pgrep -x cmux|head -1)"     # cmux start time
   ```
   cmux lstart ~= Finder/Dock/loginwindow lstart  => it DID relaunch at login (Cause A
   is fixed; look at Cause B). cmux much later than login => Cause A (manual open).

3. DECISIVE for Cause B — did agents resume or start fresh?
   ```bash
   # a) no process should be fresh if resume worked:
   ps -axo pid,command | grep -E '/(claude|codex)' | grep -v grep \
     | grep -oE -- '--resume [0-9a-f-]+|--session-id [0-9a-f-]+' | sort | uniq -c
   #    many `--session-id` and zero `--resume`  => launched FRESH, not resumed.
   ```
   ```bash
   # b) the gate itself — every agent pane shows wasAgentRunning=false => #4269 suppressed resume:
   python3 - <<'PY'
   import json, os
   p=os.path.expanduser('~/Library/Application Support/cmux/session-com.cmuxterm.app.json')
   d=json.load(open(p))
   for w in d.get('windows',[]):
     for ws in w.get('tabManager',{}).get('workspaces',[]):
       for pn in ws.get('panels',[]):
         t=pn.get('terminal') or {}
         if t.get('resumeBinding'):
           print(pn.get('customTitle'),'wasAgentRunning=',t.get('wasAgentRunning'),
                 'cmd=',(t['resumeBinding'].get('command') or '')[:60])
   PY
   ```
   wasAgentRunning=false on every pane (even in a snapshot written while agents run)
   confirms Cause B. The `resumeBinding.command` is the exact `claude --resume <id>`
   you can run by hand.

4. Rule out the hard-disable:
   ```bash
   launchctl getenv CMUX_DISABLE_SESSION_RESTORE   # must be empty
   ```

## Solution / workaround

- **Cause A:** add `/Applications/cmux.app` to System Settings > General > Login Items
  & Extensions ("Open at Login"). Confirm with
  `osascript -e 'tell application "System Events" to get the name of every login item'`.
  There is NO in-app open-at-login key in cmux.

- **Cause B — what actually resumes (CONFIRMED 2026-06-17, cmux 0.64.15):** the resume
  is done by **cmux's own restore in 0.64.15 after the Login Item relaunches it** — NOT
  by macOS "Reopen windows when logging back in". (An earlier guess crediting reopen-
  windows was WRONG — do not repeat it.) How it was isolated: on a reboot with "Reopen
  windows when logging back in" OFF, no ordinary app restored its windows — ONLY
  auto-launch items (cmux + other Login Items such as Slack/Texty) came back — yet 14/14
  agent panes still resumed. So macOS window-reopen is not involved.
  - **Mechanistic key:** the per-pane `wasAgentRunning` flag is `null`/absent on 0.64.15
    but was written `false` on 0.64.10. The #4269 gate skips auto-resume on `false` and
    treats `null` (legacy/absent) as resumable — very likely WHY 0.64.10 came back fresh
    and 0.64.15 resumes. A snapshot with `wasAgentRunning` null everywhere is the GOOD
    state, not a problem.
  Working recipe: Login Item (Cause A) + cmux >= 0.64.15 + `autoResumeAgentSessions:true`
  + arg-free launch. You do NOT need "Reopen windows when logging back in" (and that box
  being off is also how you can tell, post-reboot, that any window restoration came from
  Login Items, not macOS state restoration).
  Verify resume after a reboot (handles 0.64.15's quoted `'--resume' '<id>'` bindings —
  the unquoted-only regex silently reports 0):
  ```bash
  python3 - <<'PY'
  import json,os,subprocess,re
  d=json.load(open(os.path.expanduser('~/Library/Application Support/cmux/session-com.cmuxterm.app.json')))
  saved=set()
  for w in d.get('windows',[]):
   for ws in w.get('tabManager',{}).get('workspaces',[]):
    for pn in ws.get('panels',[]):
     rb=(pn.get('terminal') or {}).get('resumeBinding')
     if rb: saved|=set(re.findall(r"resume['\"\s]+([0-9a-f-]{36})", rb.get('command') or ''))
  out=subprocess.run("ps -axo command",shell=True,capture_output=True,text=True).stdout
  running=set(re.findall(r"resume['\"\s]+([0-9a-f-]{36})",out))|set(re.findall(r'--session-id ([0-9a-f-]{36})',out))
  print(f"resumed {len(saved&running)} / {len(saved)}")
  PY
  ```
  Quick cross-check: `ps -axo command | grep -E '/(claude|codex)' | grep -c -- 'resume '`
  should roughly equal your agent-pane count.

- **Fallback when auto-resume does NOT happen** (older cmux < 0.64.15, or a relaunch
  that came back fresh): conversations are NOT lost. Every pane's
  `resumeBinding.command` is in the snapshot and transcripts are on disk. Re-open them
  with a generated picker script (reads the snapshot live; `all` mode opens each via
  `cmux new-workspace --command`, pinning `--window "$(cmux current-window)"` when run
  outside a cmux pane). Optionally wrap in a `.app` for Spotlight. Track upstream
  #5802 / #4269 / #4187 / #2923.

## Keep restore working (gotchas)
From `Sources/SessionPersistence.swift` `SessionRestorePolicy.shouldAttemptRestore`:
- Restore fires only on a **no-argument** launch; only `-psn_*` args are tolerated.
  Launching cmux from a script / `open -a cmux <path>` / any explicit arg makes
  `shouldAttemptRestore` return false and restore is skipped. A Login Item launch is
  arg-free, so it is fine.
- Env `CMUX_DISABLE_SESSION_RESTORE=1` disables restore entirely. Beware if you sync
  env vars into `launchctl` (osx-env-sync style) — a stray value kills restore for
  Spotlight/Dock/login launches too.
- Automatic startup restore loads the **active** `session.json`; the **manual** reopen
  path (`loadReopenSessionSnapshot`) loads `-previous.json`. Both honor the #4269 gate.

Second relaunch-failure mode — **stale hardcoded agent path** (a pane fails with
`bash: /Users/.../claude: No such file or directory`): cmux saves each pane's resume
command with the **absolute** path to the agent binary as it was at pane creation
(e.g. `/Users/<you>/.nvm/versions/node/vXX/bin/claude`). If that binary moves or is
removed, resume execs a dead path even though `claude` still works on PATH (cmux injects
a CLI shim under `$TMPDIR/cmux-cli-shims/...`). Two common triggers:
- **Claude Code migrating off npm/nvm to the native installer** (current as of 2026-06):
  the binary moves to `~/.local/bin/claude` -> `~/.local/share/claude/versions/<v>` and
  the old nvm copy is deleted, so every pre-migration binding is stale.
- a node version upgrade/removal that drops the nvm `claude`.

Find stale bindings:
```bash
python3 - <<'PY'
import json, os, re
d=json.load(open(os.path.expanduser('~/Library/Application Support/cmux/session-com.cmuxterm.app.json')))
for w in d.get('windows',[]):
  for ws in w.get('tabManager',{}).get('workspaces',[]):
    for pn in ws.get('panels',[]):
      rb=(pn.get('terminal') or {}).get('resumeBinding')
      if rb:
        m=re.search(r'(/\S+/(?:claude|codex))', rb.get('command') or '')
        if m and not os.path.exists(m.group(1)):
          print('STALE:', pn.get('customTitle'), '->', m.group(1))
PY
```
Fix: reinstall so the agent is back on PATH (`curl -fsSL https://claude.ai/install.sh | bash`
for Claude Code's native installer), then **relaunch each affected pane's agent once** so
cmux re-records the binding with the current path. Until a pane relaunches, its saved
binding keeps the dead path and fails again on the next reboot. (The fallback resume
script does NOT help here — it runs the same stale `resumeBinding.command`.)
FIXED UPSTREAM in manaflow-ai/cmux#6582 (canonicalizes PATH-managed absolute
`claude`/`codex` tokens back to the bare executable name at snapshot decode/restore,
which also repairs already-stale snapshots; custom absolute execs like
`/opt/company/bin/codex` are preserved). Merged to main 2026-06-22; ships in the first
release after 0.64.16. On a build that includes #6582 the manual relaunch is unnecessary —
the stale bindings self-repair on restore. Until then, use the reinstall + relaunch above.

## Verification
- Cause A fixed: after reboot, cmux auto-opens (cmux lstart ~= login time).
- Cause B present: panes open but `--resume` count is 0 and every pane has
  `wasAgentRunning=false`. Until upstream fixes it, use the manual resume script.

## Notes
- The `--session-id` of a freshly launched agent will NOT match the saved
  `checkpointId`; that mismatch is the fingerprint of a fresh (non-resumed) launch.
- Related upstream: #5802 (this gate), #4269 (gate origin), #4187 (focus-gating),
  #2923 (reopen-after-laptop-off feature).

## Related

- `cmux-session-restore-forensics` — **the reference for the state files this
  skill parses.** Both read `session-com.cmuxterm.app.json` with the same
  `windows[] -> tabManager.workspaces[] -> panels[]` shape; that skill owns the
  description, plus three traps not covered here: `-previous.json` as the
  recovery source, `closed-item-history-com.cmuxterm.app.json`'s Core Data epoch (seconds from
  2001-01-01, so a close from last night reads as 1995), and `workspaceId` being
  re-minted on restore, which makes any set-difference on it useless. The
  shell-quoting trap in `resumeBinding.command` is the one thing both cover, and
  they agree — match the UUID after `--resume`, never on plain spacing.
- The two skills answer adjacent questions: reach for this one when panes come
  back **fresh** or not at all after a reboot; reach for that one when panes came
  back but you need to know **what the relaunch dropped** and get it back.
- `cmux-agent-tabs` — why an agent has a pane to resume in the first place.
