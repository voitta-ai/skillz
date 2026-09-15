---
name: permission-gate-inherits-operator-allow-list
description: |
  Audit what a service actually auto-runs when it reuses a permission gate
  built for an interactive terminal. Use when: (1) an agent, bot or daemon
  classifies shell commands through a tool whose "allowed" set comes from a
  human's editor settings (voitta-yolt's `grammar_classifier.py` reading
  `~/.claude/settings.json` and `<cwd>/.claude/settings*.json`; any hook,
  linter or policy engine with the same discovery), (2) a command you expect
  to need approval runs without one, or a reason string says "matches user
  allow pattern", (3) you are wiring such a gate into a service and need to
  decide whose permissions it should read, (4) a test suite's verdicts change
  depending on whose machine it runs on. The failure is a confused deputy: the
  service acts with the union of one human's personal permissions while being
  driven by other people's input, and nothing in the logs says so. Covers
  measuring the inherited set, proving the exposure with the gate's own
  verdicts, cutting the inheritance off, and asserting at boot that it stayed
  cut.
author: Claude Code
version: 1.0.0
date: 2026-09-14
---

# A permission gate reused by a service inherits the operator's allow-list

## Problem

Permission gates are written for one human at one terminal: the tool reads that
person's settings files to learn what they have already agreed to run without
being asked. Embed the same gate in a service -- a chat agent, a bot, a CI
runner, anything driven by input from other people -- and the settings files do
not change meaning by themselves. The service inherits the human's personal
permissions and applies them to requests the human never saw.

Textbook confused deputy: the deputy holds one principal's authority and takes
orders from another. It is invisible in normal operation, because every such
command is *supposed* to run without a prompt; that is what the allow-list
means. Only the reason string gives it away, and only if someone reads it.

Measured on one deployment (a Slack agent gating shell commands through
voitta-yolt): **123 `Bash(...)` patterns** inherited -- 106 from the operator's
`~/.claude/settings.json`, 17 from the *repository's own*
`.claude/settings.local.json`, because the gate was subprocessed with the
service's working directory. Among them `gh pr merge*`, `gh api*` (so
`gh api -X DELETE`), `git push origin feature/*` and `codex exec *`: every one
mutating, every one auto-running with no approval card, all authorized by a
file written for a human typing in a terminal.

Note what does *not* help. A filesystem sandbox does not: these are network
effects. A redactor does not: nothing is being leaked, a command is being run.
Reviewing the service's own code does not: the authority is in a file the
service never mentions.

## Context / trigger conditions

- A service, agent or daemon classifies commands with a tool that also ships as
  an editor/CLI hook.
- A gate verdict carries a reason like `matches user allow pattern '<pattern>'`.
- A command that should have parked for approval ran instead -- especially
  `push`, `merge`, `create`, `delete`, or anything that spawns another agent.
- The gate's own test suite passes on CI and fails locally, or vice versa, with
  no code difference. Same cause: the tests read the developer's settings.
- You are about to embed such a gate and are choosing what "allowed" means.

## Solution

### 1. Find what the gate reads, and from where

Read the entry point, not the docs -- the discovery list is usually hardcoded
near the CLI's `main`:

```bash
grep -n "settings.json\|settings.local\|allow" <gate>/grammar_classifier.py
# .../grammar_classifier.py:517:  Path.home() / ".claude" / "settings.json",
# .../grammar_classifier.py:518:  cwd / ".claude" / "settings.json",
# .../grammar_classifier.py:519:  cwd / ".claude" / "settings.local.json",
```

`cwd` is the second trap: it is the *service's* working directory, so a
project-local settings file in the deployment tree counts too, and an untracked
`settings.local.json` makes the surface differ per checkout.

### 2. Measure it, do not estimate it

```bash
python3 - <<'PY'
import json, os
total = 0
for p in [os.path.expanduser("~/.claude/settings.json"),
          ".claude/settings.json", ".claude/settings.local.json"]:
    try:
        d = json.load(open(p))
    except Exception:
        continue
    a = [e for e in (d.get("permissions") or {}).get("allow") or [] if e.startswith("Bash(")]
    total += len(a)
    print(p, "->", len(a), "patterns;",
          [e for e in a if any(k in e for k in ("push", "merge", "delete", "create"))][:6])
print("total", total)
PY
```

### 3. Prove the exposure with the gate's own verdicts

Ask the classifier; do not run anything. A verdict is data, and this is the
evidence an issue or a PR needs:

```bash
python3 <gate>/grammar_classifier.py 'gh pr merge 1 --squash'
# {"decision": "safe", "reason": "matches user allow pattern 'gh pr merge*'"}
```

Pick commands that are unambiguously mutating and that a reader will recognize
as alarming in the service's context. "It would auto-run `gh pr merge`" ends an
argument that "123 patterns" does not.

### 4. Cut the inheritance at the gate, not around it

Three shapes, in order of preference:

1. **A flag on the gate** (`--no-user-allow` in voitta-yolt >= 1.2.0) that
   skips discovery for one invocation, default unchanged so the interactive
   hook keeps working. Every other consumer gets the same control, and the fix
   cannot be undone by a future refactor of the caller.
2. **Explicit settings paths** passed by the caller, if the gate supports them.
3. **A sanitized environment** (`HOME` pointed at an empty dir, run from a
   directory with no `.claude/`) only as a stopgap: it is a workaround a future
   change to the gate's discovery silently defeats.

Do not rebuild the matcher in the service to "filter" the inherited patterns.
That leaves the surface intact and adds a second thing to keep correct.

### 5. Make the service prove it at boot

Cutting the inheritance is silent, and so is its failure. Ask the gate to
report how many patterns were in play, and assert zero at startup:

```python
def preflight():
    """A gate too old to understand the flag classifies the flag itself, so
    every verdict becomes a verdict about the string -- fail-closed, unusable,
    and silent. A gate that accepts the flag and inherits anyway is worse: the
    old surface with nothing to show for it."""
    retval = []
    data, err = _classify_raw("echo preflight")       # a known read-only command
    if err:
        retval.append(err)
    elif data.get("decision") != "safe":
        retval.append("gate does not understand the flag; every command will park")
    elif "allow_patterns" not in data:
        retval.append("gate does not report the count; the opt-out cannot be confirmed")
    elif data["allow_patterns"]:
        retval.append(f"gate loaded {data['allow_patterns']} pattern(s) despite the flag")
    return retval
```

Warn, do not exit. Every failure above is already fail-closed in behavior --
the service asks a human instead of running -- so dying at boot under a
supervisor turns a cautious service into a restart loop.

## Verification

Same command, before and after:

```
before:  gh pr merge 1 --squash  -> safe,    "matches user allow pattern 'gh pr merge*'"
after:   gh pr merge 1 --squash  -> unsafe,  "gh pr merge: mutating"          (parks)
after:   cat README.md           -> safe,    "cat: read-only"                 (still runs)
```

And at startup: one line reporting zero inherited patterns. If the log instead
names a version to upgrade to, the dependency was not pulled -- in that state
every command parks, which is safe and completely unusable, so it must be loud.

## Notes

- **Expect a behavior change at rollout.** Commands the service used to run
  silently now ask. That is the fix working; say so in the upgrade note before
  someone reports it as a regression.
- **Do not add a service-side allow-list "for parity" while you are here.**
  Nothing needs one until a specific command does, and then it belongs in the
  service's own reviewable config -- not inherited from a file written for
  another purpose. Inheriting was the bug; re-creating it under a new name is
  the same bug.
- **The gate's own test suite has this disease too.** If verdicts depend on the
  developer's settings, the suite is not hermetic: it passed on CI (no settings
  files) and failed locally, differing again between a clone and a worktree
  because an untracked project settings file only exists in one. Run it with a
  scratch `HOME` to confirm the cause: `CLEAN=$(mktemp -d); HOME="$CLEAN" <test
  command>`. Fix it at the gate, and use "no test fails on my branch that
  passes on master" as the control while it is unfixed.
- **Upstream over local.** Both halves of the fix -- the flag and the reported
  count -- belong in the gate, where every consumer benefits and where the next
  refactor cannot quietly undo them. Expect to open two PRs, upstream first.
- **A later rewrite may delete the machinery entirely.** If the gate stops
  emitting allow decisions at all, ask that the flag be kept as an accepted
  no-op: consumers pass it unconditionally, and a removal turns into "every
  command parks" on somebody's box. One line upstream against a version gate in
  every consumer.

## References

- voitta-ai/voitta-yolt#125 and #126 -- the flag, the reported count, and the
  measured 123-pattern surface.
- voitta-ai/shmobster#148 -- the consumer side: passing the flag, and the boot
  preflight above.
