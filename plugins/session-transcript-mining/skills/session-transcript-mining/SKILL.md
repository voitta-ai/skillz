---
name: session-transcript-mining
description: |
  Sweep every Claude Code session transcript on a machine for skill-worthy
  knowledge: root-caused bugs, non-obvious gotchas, painfully derived
  procedures - and for HOMELESS artifacts (skills written to ~/.claude/skills
  but never committed, skill edits stranded in worktrees, harvest PRs left
  open). Use when: (1) asked to "mine sessions", "harvest what we learned",
  or "sweep transcripts for skills", (2) daily/per-session harvesting has
  been running and you need the periodic catch-up pass that finds what it
  missed, (3) a skills repo looks behind what you know was learned recently,
  (4) you need to reconstruct what a lost or crashed session discovered.
  Method verified at scale: 50+ sessions condensed and mined by 8 parallel
  subagent miners in one sweep, yielding 22 shipped skill PRs.
author: Claude Code
version: 1.0.0
date: 2026-08-28
source: https://github.com/voitta-ai/skillz
source_file: skills/session-transcript-mining/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/session-transcript-mining/SKILL.md`). Updates go through the
> repo's worktree + PR workflow - open an issue, branch, PR.

# session-transcript-mining

## Problem

Claude Code sessions accumulate hard-won knowledge - root-caused bugs, API
gotchas, procedures that took an hour to derive - and most of it evaporates
when the session ends. Per-session harvesting (a continuous-learning hook,
an end-of-day habit) catches some, but it misses sessions that crashed, were
abandoned mid-harvest, or simply never triggered the hook. Raw transcripts
are too big to read (hundreds of KB to MB of JSONL each), and re-reading N
sessions serially in one context does not scale.

This skill is the periodic sweep: condense everything, fan out miners,
dedupe against the existing skill catalogs, and ship only what clears a high
bar. Its yield is characteristically NOT "new skills from every session" -
in a recently-harvested window most learnings are already covered. The yield
is (a) what daily harvesting missed, and (b) **homeless artifacts**: skills
that were already written but never landed anywhere.

## Step 1 - inventory and window

Transcripts live at:

```
~/.claude/projects/<encoded-cwd>/<uuid>.jsonl
```

`<encoded-cwd>` is the session's working directory with `/` replaced by `-`
(e.g. `-Users-alice-src-myrepo`). One directory per cwd, one file per
session; a home-directory cwd holds mixed-topic sessions, so identify each
session's topic from its early `USER:` lines rather than from the path.

```bash
# newest-first inventory with sizes
for d in ~/.claude/projects/*/; do
  stat -f "%m %z %N" "$d"*.jsonl 2>/dev/null   # macOS; Linux: stat -c "%Y %s %n"
done | sort -rn | head -80
```

Establish the **unharvested window** - do not re-mine what a prior sweep
covered:

- Find the previous sweep session itself (grep the inventory's own
  transcripts for this skill's name or the sweep prompt).
- Cross-check harvest commits in the target skills repo(s):
  `git log --oneline --since=<date>` - daily harvesting leaves a trail of
  `skills(<name>): ...` commits whose dates bound the already-covered range.

Sessions inside the covered range still get a cheap pass (Step 3's homeless
check); only sessions after the watermark get full mining.

## Step 2 - condense before reading (10-40x smaller)

Never Read raw session JSONL. Condense each file first with this extractor
- it emits USER/AI text, one-line tool calls, and tool errors, which is
exactly the signal mining needs:

```python
#!/usr/bin/env python3
"""Condense a Claude Code session .jsonl into a readable transcript.
Usage: python3 extract.py /path/to/session.jsonl [maxchars_per_block]
Prints: USER / ASSISTANT text, tool calls one-line, tool errors."""
import json, sys

path = sys.argv[1]
cap = int(sys.argv[2]) if len(sys.argv) > 2 else 1200

def clip(t, n):
    t = t.strip()
    retval = t if len(t) <= n else t[:n] + " ..."
    return retval

for line in open(path, errors="replace"):
    try:
        d = json.loads(line)
    except Exception:
        continue
    typ = d.get("type")
    if typ == "summary":
        print("== SUMMARY:", clip(d.get("summary", ""), 500))
        continue
    if typ not in ("user", "assistant"):
        continue
    msg = d.get("message", {})
    content = msg.get("content")
    if isinstance(content, str):
        if typ == "user" and content.strip():
            print("USER:", clip(content, cap))
        continue
    if not isinstance(content, list):
        continue
    for c in content:
        if not isinstance(c, dict):
            continue
        ct = c.get("type")
        if ct == "text":
            t = c.get("text", "").strip()
            if not t:
                continue
            if typ == "user" and t.startswith("<system-reminder"):
                continue
            print(("USER:" if typ == "user" else "AI:"), clip(t, cap))
        elif ct == "tool_use":
            name = c.get("name", "?")
            inp = c.get("input", {}) or {}
            brief = inp.get("command") or inp.get("file_path") or inp.get("prompt") or inp.get("query") or ""
            print("  TOOL", name + ":", clip(str(brief), 200))
        elif ct == "tool_result" and c.get("is_error"):
            cc = c.get("content")
            if isinstance(cc, list):
                cc = " ".join(x.get("text", "") for x in cc if isinstance(x, dict))
            print("  ERR:", clip(str(cc), 300))
```

Usage pattern (from a scratchpad directory):

```bash
python3 extract.py ~/.claude/projects/<dir>/<uuid>.jsonl > <shortname>.txt
wc -c *.txt        # typical: 400K-2MB jsonl -> 5-35K condensed
```

Then `Read` the condensed file in chunks, or `Grep` it for `USER:` (topic),
`ERR:` (what went wrong), and error strings. `AI:` lines ending a session
often contain the session's own "what did we learn" summary - the highest
signal per byte in the file.

## Step 3 - fan out miners with a mandatory overlap check

Cluster sessions (by repo, by topic, or just N-per-miner) and launch one
subagent per cluster in parallel. Each miner's brief must include:

1. The condense-then-read procedure above (miners must not read raw JSONL).
2. **A mandatory overlap check before proposing anything**: `ls` the skills
   directory of EVERY target repo (e.g. the private org repo and the public
   one), and for near-matches read that SKILL.md. Verdict per candidate:
   `covered-by <skill>` / `EXTEND <skill>` / `NEW` / `<other-repo>-material`
   / `not-worth`.
3. The bar: keep only what **saves a future agent >30 minutes or prevents a
   wrong action**, and only if it was VERIFIED in-session (skip speculation,
   routine work, and one-off trivia).
4. Placement rule: org-internal systems -> the private skills repo; fully
   generic -> the public repo (flag for scrubbing of internal names either
   way).
5. The homeless-artifact checklist (below) - even for sessions whose
   learnings are all "covered".
6. Report format: per session one "what it was" line; per candidate:
   proposed kebab-case name | verdict | 2-4 sentence gist
   (symptom -> root cause -> fix, with exact errors/commands) | short
   evidence quote from the transcript.

### The homeless-artifact checklist

Sessions that "already harvested their own learnings" often did not finish
the job. For each session that authored or edited a skill, VERIFY the
artifact actually landed - do not trust the transcript's claim:

- **Loose skills never committed**: a skill written to `~/.claude/skills/`
  exists but is absent from every repo's `skills/` listing.
- **Edits that never persisted**: the transcript shows an edit to an
  installed skill copy, but diffing that copy (or a later backup of it)
  against the repo shows zero difference - the learning is lost and must be
  re-drafted from the transcript.
- **Stranded worktrees**: `git -C <skills-repo-worktree> status` shows the
  new skill untracked / uncommitted, `git log origin/<default>..HEAD` shows
  0 commits - the session died mid-commit. Cheapest harvest available:
  finish commit + push + PR from the existing worktree.
- **Stalled harvest PRs**: `gh pr list -R <repo> --state all --search
  <skill-name>` - the PR was opened and never merged, or was never opened
  at all despite the branch existing.

## Step 4 - triage report in tiers

Merge miner reports into one plan, ordered by cost-to-value:

1. **Already-written, just commit** - stranded worktrees and loose files.
   Do these first; the content exists, only shipping remains.
2. **NEW skills** - draft from transcript evidence.
3. **EXTEND / corrections** - additions to existing skills; within this
   tier, put *actively wrong* claims first (a skill asserting something a
   session disproved is worse than a missing skill).
4. **Other-repo material** - candidates that belong in a different catalog
   (e.g. generic material surfaced while mining for the org repo); report
   and route, do not silently drop.
5. **Repo maintenance** - drift between installed copies and the repo,
   stale catalog entries, broken install state discovered along the way.

## Step 5 - ship serially

Drafting can be parallel (each draft to a scratchpad, never directly into a
repo); **shipping is serial per target repo**. Skills repos typically have
CI that gates on catalog regeneration, per-skill version bumps, and a
plugin/bundle manifest version - two parallel PRs both bumping the bundle
version conflict with each other. Convention observed on such repos: bump
the skill's own `version:` (minor for content additions), leave its `date:`
at creation, regenerate the catalog, bump the bundle manifest once per PR,
rebase the next PR after each merge.

## Gotcha - subagent finished but no report arrived

A parallel miner going **idle without having sent its report is not a
crash**: the subagent finished its analysis but ended its turn without
transmitting (plain final text in a teammate/subagent is NOT delivered to
the coordinator). Do NOT respawn it - the mining work is done and sits in
its context. Send it a message asking it to transmit its report; it resumes
from its transcript and replies in seconds. Respawning re-runs the whole
mining pass and doubles the cost for zero new information.

## Verification

- Every miner report names its sessions and gives per-candidate verdicts
  with evidence quotes.
- Every "covered" verdict names the covering skill; every "landed
  in-session" claim was verified against the repo/PR state, not the
  transcript's say-so.
- After shipping: the repo's `skills/` listing contains the new/extended
  skills, CI is green, and the next sweep's watermark (this sweep's date)
  is discoverable from the harvest commits.
