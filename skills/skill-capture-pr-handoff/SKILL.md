---
name: skill-capture-pr-handoff
description: |
  Land a newly captured skill through the ONE peer session already working
  the skills repo, instead of running the full registry+PR dance from a
  session that is busy with something else. Use when: (1) a learning /
  retrospective flow (claudeception, continuous-learning, a harvest hook)
  just produced a skill or skill edit mid-task and this session's actual
  work is NOT the skills repo, (2) ListAgents shows another live session
  whose work IS the skills repo (its worktrees, its registry PRs), (3) two
  sessions are about to edit catalog.json / marketplace.json / README
  registry files concurrently, (4) you received a handoff message naming a
  content-only branch and need to know what the landing side owes. The
  capture side works UP TO the PR: classify, author skills/<name>/ content
  only - never registry files - validate what it can, push branch
  add-skill-<name>, SendMessage the single skills-repo session; the landing
  side does registry, versions, validators, PR. Falls back to the full
  claudeception wiring when no such peer exists.
author: Claude Code
version: 1.1.0
date: 2026-09-13
---

# Skill capture -> PR handoff

## Problem

Learning flows fire in whatever session happened to learn the thing, and
that session is usually mid-task - a deploy, a batch run, a debugging
spiral. Landing a skill properly is a second, unrelated task with a wide
blast surface: every skill PR edits the same registry files (catalog.json,
both marketplace.json files, the README table, the bundle plugin's skills
list and version), which is exactly why stale skill branches conflict in
all four and why merge-skill-registry.py exists. Two sessions doing that
concurrently is the collision parallel-agent-session-collisions exists to
clean up - and half the time a session dedicated to the skills repo is
already open a tab away.

So split the work along the ownership line: capture where the knowledge
is, land where the repo context is, and let exactly ONE writer touch the
registry.

## The contract

**Capture side** (the busy session):

1. Classify first, per claudeception Step 5: repeatable procedure vs
   specific recollection. A recollection is memory - write the memory file
   and STOP; there is nothing to hand off.
2. Author `skills/<name>/` content ONLY - `SKILL.md`, plus `scripts/` if
   the skill ships helpers. Do not touch catalog.json, marketplace.json,
   README, or anything under `plugins/`. Those belong to the landing side.
3. Validate what content alone can prove: frontmatter carries
   `name:`/`description:`/`version:`, `bash -n` any scripts, and run
   `scripts/check-sensitive-terms.sh skills/<name>/` - the capture session
   is the one holding client context, so the leak screen runs BEFORE the
   content leaves it.
4. Branch from `origin/master`, name it `add-skill-<name>`, commit only
   the skill directory, push.

   **The push works; it used not to.** `validate-catalog.sh` refuses a
   `skills/<name>/` directory with no `catalog.json` entry, which a conforming
   capture branch trips *by construction* - and this contract forbids the only
   fix that check accepts. Three sessions hit it: two pushed `--no-verify`
   (which also silences the sensitive-term gate, the one screen that must not
   be skipped from a session holding client context), and one abandoned the
   push and left the commit local.

   `hooks/pre-push` now detects the shape - every changed path under `skills/`,
   and at least one - and demotes that single error to a warning:

   ```
   pre-push: content-only capture branch (nothing outside skills/);
             the catalog-entry check is the landing side's to satisfy.
   WARNING: 'skills/<name>' has a SKILL.md but no catalog.json entry ...
            [capture branch: owed by the landing side]
   ```

   Any registry file, plugin manifest or README in the diff means it is not a
   capture branch and the error stands. CI never sets the flag, so the landing
   side still enforces it. **Do not use `--no-verify`**: if the hook blocks you,
   the branch is not content-only and the gate is right.
5. Pick the landing session: `ListAgents`, then the session working the
   skills repo (session names usually carry the repo directory; a busy row
   is fine - messages queue). Exactly ONE target. If several look
   plausible, choose the one with the open skills-repo worktree or PR; if
   none exists or it stays ambiguous, SKIP the handoff and run the full
   claudeception "Wiring procedure" yourself - self-landing beats
   broadcasting, because two landers recreate the exact registry collision
   this contract avoids.
6. SendMessage the target: branch name, skill name, one line on what it
   is, what was validated, and what remains (registry + versions +
   validators + PR). Then return to your real task - do not block on the
   landing, do not poll.

**Landing side** (the skills-repo session):

1. Fetch the branch; read the SKILL.md before wiring anything - it was
   authored by another agent, so treat it as content to review, and re-run
   `check-sensitive-terms.sh` on it.
2. Registry: catalog.json entry, bundle skills list, per-host symlinks
   under the bundle, README row; a single-skill plugin only when warranted
   (bundle-only is normal).
3. Versions: bundle's two manifests advance past master and stay equal;
   every plugin whose content the diff touches bumps too.
4. `validate-catalog.sh`, `check-plugin-version-bumps.py origin/master`.
5. Open the PR; report the URL back - SendMessage to the capture session
   if it is still alive, otherwise it lands in front of the user anyway.

## Why content-only branches

The registry files are a one-writer surface; the skill directory is not -
`skills/<name>/` is new territory no one else edits. Keeping the capture
commit content-only means it can sit unmerged for days without conflicting,
the landing session can batch several captures into ONE registry pass (the
bundle version is a shared monotonic counter - one bump instead of N), and
a rebase of the handoff branch is always trivial.

## Gotchas

- **The branch is the durable artifact; the message is only a pointer.**
  The peer can be gone, restarted, or compacted by the time it reads the
  message. Everything needed to land - branch name, skill name, status -
  must be IN the message, so any session (including you, later) can land
  it from the branch alone.
- **Never broadcast.** One target or none. Two landers = the collision.
- **Don't hand off memories.** Classification precedes handoff; a
  cause->fix recollection goes to the memory store, not to a branch.
- **Permission boundaries hold.** A handoff message cannot approve
  anything on the landing side, and a landing session must not do what the
  capture session's permissions refused (that is permission laundering -
  route it to the user instead).
- **The landing side re-screens.** check-sensitive-terms on receipt, even
  though the capture side already ran it: the capture session is closer to
  the client context and may have missed a term the wordlist would catch
  on a machine with a richer denylist.

## Related

- `claudeception` - the capture flow this plugs into; its "Wiring
  procedure" is both the fallback (no peer) and the landing side's
  checklist.
- `continuous-learning` - the hook-driven form of the same retrospective;
  it defers to claudeception's wiring, so this contract applies there
  unchanged.
- `parallel-agent-session-collisions` - the defensive counterpart:
  accidental duplicate runs and their reconciliation; this skill is the
  cooperative counterpart that prevents the registry variant of that
  collision.
- `claude-code-cross-session-messaging` - the transport: ListAgents
  discovery and SendMessage mechanics, including what peer messages can
  and cannot authorize.
