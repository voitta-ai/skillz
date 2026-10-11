---
name: continuous-learning
description: |
  Run the end-of-task retrospective that Codex's `Stop` and `UserPromptSubmit` hooks demand, and decide what the session actually produced. Most turns end with `No reusable learning.` Of the rest, most are **memory** — a single cause->fix, an API gotcha, a config detail — and must NOT become a `SKILL.md`; only a repeatable procedure does. Use when a `Stop` hook fires at end-of-task, when a debugging-heavy session ends, or when the user asks "what did we learn?". Covers the four gates (discovery cost, recurrence, verifiable trigger, verified result), the skill-vs-memory classification, the install-location choice, and the `No reusable learning.` escape hatch. For an explicitly invoked retrospective, and for the wiring that promotes a skill into the `voitta-ai/skillz` catalog, see `claudeception` — this skill defers to it rather than restating it.
author: Codex
version: 0.3.0
date: 2026-10-09
source: https://github.com/voitta-ai/skillz
source_file: skills/continuous-learning/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/continuous-learning/SKILL.md`). Updates go through the
> repo's worktree + PR workflow — open an issue, branch, PR.

# continuous-learning

## Problem

Codex sessions routinely uncover non-obvious facts: a workaround for
a flaky API, an undocumented config flag, a regex that took five
tries to get right, a sequence of commands that fixed a recurring
class of failure. By default that knowledge dies with the session.
The next time the same wall is hit, the next agent starts from
zero.

Capturing every learning is the wrong fix. A noisy retrospective
trains users to mash through the prompt and ignore it. The useful
loop is narrow:

1. work on a real task,
2. detect that something non-obvious was learned,
3. force a brief retrospective,
4. save the reusable result as a future capability — *or* explicitly
   conclude there is nothing reusable.

This skill defines step 4. The Codex hooks in the
`codex-continuous-learning` plugin bundle drive steps 2–3.

## Context / Trigger Conditions

Invoke when:

- A `Stop` hook fires at end-of-task and the agent must decide
  whether to extract a skill before exiting.
- The user asks "what did we learn?", "save this as a skill",
  "extract a skill from this", or similar.
- A debugging-heavy session ends and reusable diagnostic / fix
  patterns emerged.
- A `PostToolUse` signal flagged the current task as
  likely-discovery work (long shell sessions, repeated failed
  commands, multiple file edits across unrelated areas).

Do NOT invoke when:

- The task was a routine code edit with no surprises.
- The "learning" is a public documentation fact already in the
  upstream README.
- The pattern is so narrow it only applies to one commit in one
  repo (no recurrence value).

## Solution

Run a structured retrospective. The default outcome is
`No reusable learning.` — promotion to a skill is the exception, not
the rule.

### 1. Retrospective questions

Answer each in one short line. If any answer is "no" or "unclear",
default to `No reusable learning.` and stop.

1. **Discovery cost?** Did finding the answer require real
   investigation — multiple failing attempts, reading source, asking
   a teammate, instrumenting a system? A direct documentation lookup
   does not count.
2. **Recurrence likelihood?** Is the same situation likely to come
   up again — for this user, this team, or this class of problem?
   One-shot historical facts do not count.
3. **Verifiable trigger?** Can the situation that benefits from this
   learning be described concretely (error string, command shape,
   file pattern, symptom)? "Sometimes things go wrong with X" does
   not count.
4. **Verified result?** Was the fix or workaround actually confirmed
   to work in this session? Speculative ideas do not count.

### 2. Classify: skill, or memory?

A learning that passes the four questions above is worth
**keeping**. It is not automatically worth a `SKILL.md`. Ask once:

- **Repeatable procedure** — a multi-step method with judgment
  calls, that an agent *does* the same way next time (a review
  loop, a migration, a publish flow). This is a **skill**.
  Continue below.
- **Specific recollection** — a single cause->fix, an API gotcha,
  a config detail, a project quirk, that an agent *recalls*. This
  is **memory, not a skill.** Do not write a `SKILL.md`. Save it
  as a memory file using the host's memory conventions (one fact
  per file, `name` / `description` frontmatter) and stop.
  On Codex with native memories on (`[features] memories = true`,
  off by default), Codex keeps its own memories under
  `~/.codex/memories/`. The docs call those files generated state
  and say not to edit them by hand, so do not write the fact
  there; keep it wherever your other memory files live.

**Most session learnings are memory.** A catalog that admits every
verified gotcha as a skill stops being searchable, which is the
same rot the conservative bias in section 1 exists to prevent -
the questions decide whether to keep, this decides where.

The classification is shared with `claudeception`, which is the
same procedure for Claude Code. Both must give the same answer for
the same learning; if they ever diverge, that is a bug in one of
them, not a host difference.

### 3. Prefer updating an existing skill

Before creating a new skill:

- List installed skills (e.g. inspect `~/.agents/skills/`,
  `~/.codex/skills/` and any repo-local `.agents/skills/`
  directories).
- If a related skill already exists, append a short section or a
  worked example rather than spawning a sibling skill.
- Only create a new skill if no existing one fits and the new
  trigger conditions are genuinely distinct.

A proliferation of near-duplicate skills makes the catalog harder to
search and waters down each skill's trigger criteria. Updating wins.

### 4. Choose the install location

- **Cross-project learnings** (tooling quirks, language-level
  patterns, host-level behavior): user-global.
  - Codex: `$HOME/.agents/skills/<name>/SKILL.md` (the documented
    user scope). `$CODEX_HOME/skills/` (`~/.codex/skills/`) is no
    longer in the docs' scope table, but Codex 0.160.1 still uses
    it: its bundled skill installer writes there.
  - Claude Code: `~/.claude/skills/<name>/SKILL.md`
- **Repo-specific learnings** (build system quirks, internal
  conventions, project-only workflow): repo-local skill directory.
- **Org-wide learnings**: contribute back to the team's shared
  catalog (`voitta-ai/skillz`) via the normal worktree + PR
  workflow. That catalog is not a directory of files - a skill
  that is only copied in installs for nobody, because
  `catalog.json`, the bundle's per-host symlinks and the version
  bumps are what actually ship it, and `validate-catalog.sh`
  rejects the tree without them. **Follow `claudeception`'s
  "Wiring procedure"**, which is that checklist and is kept in
  step with the repo's CI.

When in doubt, prefer user-global over repo-local — repo-local
learnings tend to leak into other repos eventually.

### 5. Skill shape

A captured skill is a single `SKILL.md` with YAML frontmatter and
a tight body. Required sections:

- Frontmatter: `name`, `description`, `author`, `version`, `date`,
  `source`, `source_file`. Description must be specific enough that
  an LLM picking from a long catalog can decide if this skill
  applies. Avoid generic phrasings like "helps with X".
- `## Problem` — one paragraph, what hurts and why.
- `## Context / Trigger Conditions` — the *exact* situations where
  this skill applies. Use bullet points starting with verbs:
  "Invoked when...", "Used when...". Include the failure mode or
  symptom that should make a future agent reach for this skill.
- `## Solution` — the steps, in order. Keep it short. Inline a
  worked command example.
- `## Verification` — how to know the fix worked. Specific output,
  exit code, or observable system change.
- `## Notes` (optional) — only what does not fit above and is still
  load-bearing.
- `## References` (optional) — direct links only; no synthesis.

What does NOT belong:

- Background tutorials. Skills are reference, not pedagogy.
- Multiple problems bundled together — split into separate skills.
- Aspirations or todos.

### 6. Stop-hook escape hatch

If the four retrospective questions all answer "no", emit exactly:

```
No reusable learning.
```

…and exit. Do not pad with apologies, justifications, or
"interesting observations". The escape hatch is the point: it makes
the hook cheap enough to leave on by default.

### 7. When the user disagrees

If the user says "save this anyway" after the agent concluded
`No reusable learning.`, save it as requested. The user has context
the retrospective questions cannot capture. Do not argue.

If the user says "skip the retrospective today", honor that for the
session. Do not silently re-enter the loop on the next stop.

## Verification

A successful retrospective run produces exactly one of:

- A new `SKILL.md` written to the chosen install path, with all
  required frontmatter and section headings. Path printed in the
  reply.
- An edit to an existing skill. Diff (or path + section name)
  printed in the reply.
- The literal line `No reusable learning.` and nothing else.

If the output is anything else (waffly summary, "here's what we
might do later", recap of the task), the retrospective was not
followed.

## Notes

- **Conservative bias is intentional.** The retrospective is the
  user's last line of defense against skill-catalog rot. Erring
  toward `No reusable learning.` is the correct default.
- **Stop hook vs prompt hook.** The `UserPromptSubmit` hook in the
  bundle injects a one-line reminder so the agent keeps an eye out
  for learnings as it works. The `Stop` hook forces the
  retrospective at end-of-task. Together they are cheap; alone the
  prompt hook tends to be ignored and the stop hook tends to feel
  abrupt.
- **PostToolUse refinement.** A future v2 may gate the stop hook on
  a `PostToolUse` signal (e.g. only require the retrospective after
  ≥N tool calls, or after a shell session with ≥M failed commands).
  v1 keeps the stop hook unconditional and relies on the
  `No reusable learning.` escape for cheap exits.
- **Updating beats creating.** If the learning belongs in an
  existing skill, append. The catalog should grow in depth, not
  surface area.
- **Codex-native, not faux cross-host.** The hook layer in the
  plugin bundle is Codex-specific; that is the only part that is.
  The *rules* - what counts as a learning, and whether it is a
  skill or a memory - are host-agnostic and are shared with
  `claudeception`. Divergence there is a defect, not a host
  difference. Claude Code drives the same rules from its own
  hooks.

## Related

- `claudeception` - the same decision procedure, and the home of
  the catalog **Wiring procedure** this skill defers to in
  section 4. Read it before promoting anything to `voitta-ai/skillz`.
  The classification in section 2 is shared with it verbatim.

## References

- Claudeception (the Claude Code reference implementation):
  https://github.com/blader/Claudeception
- skillz catalog: https://github.com/voitta-ai/skillz
- Multi-skill catalog refactor that this bundle depends on: #16
  (closed in this repo).
