---
name: permission-gate-allow-list-not-decisive
description: |
  Work out WHICH permission gate refused a command when more than one is
  active, and why a standing allow rule did not prevent it. Use when: (1) a
  rule you already added to `permissions.allow` fires a prompt or a denial
  anyway; (2) a denial's remediation advice is to add a permission rule you
  can see is already there; (3) the same command is allowed in one session
  and gated in the next with no config change between them; (4) you are about
  to loosen a config to get past a gate and want to know first whether that
  config is even being read; (5) a refusal might be masking a second,
  server-side gate. Records the opt-in setting `autoMode.classifyAllShell`
  (Claude Code, **default false**), which when enabled suspends EVERY
  `Bash(...)` and PowerShell allow rule while auto mode is active - and the
  fact that outside auto mode those same rules apply and bypass `PreToolUse`
  hooks entirely. Also records the diagnostic order to use when a rule is not
  taking effect and that setting is off, which is the usual case.
author: Claude Code
version: 1.1.0
date: 2026-09-16
source: https://github.com/voitta-ai/skillz
source_file: skills/permission-gate-allow-list-not-decisive/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/permission-gate-allow-list-not-decisive/SKILL.md`). Updates go
> through the repo's worktree + PR workflow - open an issue, branch, PR.

## Problem

An allow-list looks like a single authority. It is not. When two gates sit in
front of the same command - a host's own classifier and a `PreToolUse` hook,
or either of those and a server-side rule - the allow-list can be
*authoritative* to one and *ignored* by the other, in the same session, with
no surface naming which one refused.

The user-visible symptom is a rule that provably exists and provably does not
work. The expensive part is the response: with nothing identifying the gate,
the natural move is to loosen the config further, which changes nothing and
ratchets the permission surface looser on every attempt.

One setting makes an allow-list stop counting, and it is off by default.
From Claude Code's settings schema in the 2.1.273 binary:

```
classifyAllShell: ...describe("When true, every Bash/PowerShell allow rule is
suspended while auto mode is active so all shell commands are routed through
the classifier (higher safety, more classifier calls). Default: false.")
```

So `Bash(gh pr merge*)` in `~/.claude/settings.json` is:

| mode | effect of the rule |
|---|---|
| normal | auto-approves, and **bypasses `PreToolUse` hooks entirely** |
| auto, `classifyAllShell` unset (**default**) | applies, as in normal mode |
| auto, `classifyAllShell: true` | **suspended** - the classifier decides as if it were absent |

All three are deliberate. None is announced at the prompt, which is the whole
problem: the same rule has three behaviours and the refusal names none of them.

**Check the setting before you believe it is the cause.** `classifyAllShell`
is opt-in, so on most machines it is off and is *not* why your rule failed.

> **How this skill got that wrong once, which is the trap worth naming.**
> The binary also carries the sentence *"classifyAllShell is active, so at
> runtime auto mode ignores every Bash/PowerShell allow rule..."*. That is not
> a statement about auto mode - it is the consequent of a ternary (its else
> branch is `""`), emitted by the setup recon only when the setting is already
> on. Extracted alone it reads as an unconditional rule. When pulling a fact
> out of a binary, **find the guard before you quote the branch.**

## Context / Trigger Conditions

Invoke when:

- A command is gated despite a matching entry in `permissions.allow`.
- A denial tells you to add a permission rule that is already present.
- The same command behaves differently across sessions with no config change.
- A hook you installed appears not to fire (in normal mode, an allow rule
  that matches is why - the hook never sees the command).
- You are about to widen a config to get past a refusal.

Do NOT invoke when:

- There is only one gate and it refused on its stated grounds. Read the
  reason and fix the named property instead.

## Solution

### 1. Establish the mode before touching any config

Auto mode and normal mode give opposite answers about whether a Bash allow
rule counts. Determine which you are in first; everything else depends on it.
A hook that receives the payload can read `permission_mode` directly - it is
always present.

### 2. Check the rule's shape, not just its presence

Under auto mode the ignore is categorical for shell: every `Bash(...)` and
PowerShell rule, not a subset. A non-shell rule is unaffected. So "my rule is
there" and "my rule applies" are different claims, and only the second
matters.

Auto-mode setup also rejects and auto-strips certain rules at runtime
regardless of mode - a bare or wildcard `Bash`, an interpreter or wrapper
prefix (`Bash(python:*)`, `Bash(sudo:*)`), and any `Agent` rule.

### 3. Ask whether the hook fired at all

In normal mode a matching allow rule short-circuits `PreToolUse`, so a hook
that "did nothing" may have been correctly bypassed rather than broken. In
auto mode the same rule is ignored, so the hook *does* run - meaning turning
auto mode on can make a hook start firing on commands it never saw before.
This inversion is the single most confusing consequence, and it is worth
checking the hook's own log rather than reasoning about it.

### 4. Look for a second gate before believing the first

A client-side refusal can mask a server-side one. In the observed case a
`gh pr merge` denial was reported as the blocker while a repository ruleset
requiring one approval was also refusing; fixing the client gate would have
revealed the second, not completed the merge. **A gate that names itself as
the blocker when it is one of two is worse than either alone** - it produces
a confident, wrong diagnosis.

Check the server side directly (`gh api repos/{owner}/{repo}/rulesets`,
branch protection, org policy) before concluding the local gate is the
obstacle.

### 5. If the docs do not say, read the binary

None of the above is in the published settings schema. See
`claude-code-settings-spec-from-binary` for the extraction procedure.

## Verification

You have identified the right gate when you can state what would make the
request acceptable to *that specific gate*, and the change works on the first
try. If your next step is "widen the config and retry", you have not
identified it yet.

## Notes

- **A denial that names a fixable property of the request gets fixed; one
  that names only a category gets argued with or routed around.** Offered as
  a design heuristic from field observation, not as a measured finding: an
  agent routing around a gate is evidence about the agent as much as the
  gate. It is still the sharpest available test of whether a refusal is
  actionable. A refusal saying "the output was hidden" was fixed in one move;
  refusals naming a category produced config edits that made nothing safer.
- **A gate shaped like an instrument filters technique, not risk.** A block
  on a Bash heredoc write that the `Edit` tool then performs byte-for-byte is
  not a safety boundary. Check whether a refusal survives changing the tool.
- **False positives spend the credibility the true positives need.** After a
  run of wrong refusals, a later correct one was nearly dismissed with them.
  This is a real cost of an over-broad gate, and it is paid by the correct
  refusals, not the wrong ones.
- A profile captured in one repository and applied globally is strictest
  exactly where it knows least: an unseen repository is foreign by
  construction. If refusals cluster in a repo the profile was not captured
  in, suspect scope before suspecting the rules.

## References

- Claude Code settings schema (which omits all of the above):
  https://json.schemastore.org/claude-code-settings.json

## Related

- `permission-gate-inherits-operator-allow-list` - **the other end of this
  same design gap, and the one to read alongside this.** There, a gate reads
  an operator's allow-list and it is *too* decisive: a service inherits one
  human's personal permissions and acts on them for other people's input -
  the confused-deputy direction. Here, the allow-list is read and is *not*
  decisive. Same root cause, opposite symptom: an allow-list that is
  authoritative in one direction and advisory in the other, with no
  indication to the caller which mode is in force. Read as a pair; read
  singly they look like contradictions.
- `claude-code-settings-spec-from-binary` - how the `classifyAllShell` fact
  above was recovered, and the procedure for the next undocumented one.

The normal-mode half is worth stating on its own, because it surprises hook
authors in the opposite direction: outside auto mode a matching static allow
rule means your `PreToolUse` hook is never invoked at all. A hook that "does
nothing" on exactly the commands you allow-listed is working correctly. Do
not add wildcard entries such as `Bash(gh:*)` or `Bash(python3:*)` to get
past prompts - they silently retire your hook for everything underneath them.
