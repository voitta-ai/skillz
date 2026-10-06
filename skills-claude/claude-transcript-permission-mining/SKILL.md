---
name: claude-transcript-permission-mining
description: |
  Count permission outcomes -- auto-mode refusals, operator rejections --
  from `~/.claude/projects/**/*.jsonl` without the traps that silently
  corrupt the number while leaving the output plausible. Use when: (1) you
  are measuring permission friction or building a gate whose criterion is a
  rejection rate; (2) you are comparing before and after a hook, plugin, or
  `settings.json` change; (3) two measurement scripts disagree about "the
  same" count and you need to know which is wrong, often neither; (4) a
  denial count rose and you need to rule out self-contamination before
  reporting it; (5) you want to know which command was refused, not just how
  many. Covers the unanchored-marker trap where the search matches the very
  session that wrote the marker so the count climbs as you iterate on the
  extractor, UTC day-bucketing that splits a working evening across two days,
  the two distinct populations that both get called "rejections", per-1k
  normalization against work volume that varies a hundredfold day to day,
  the single forward pass that recovers the refused command, and the standing
  limit that approved prompts are byte-identical to ungated calls so prompt
  volume is unrecoverable.
author: Claude Code
version: 1.0.0
date: 2026-08-28
source: https://github.com/voitta-ai/skillz
source_file: skills/claude-transcript-permission-mining/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/claude-transcript-permission-mining/SKILL.md`). Updates go through
> the repo's worktree + PR workflow — open an issue, branch, PR.

## Problem

Claude Code's transcript store is the only local record of what the
permission layer actually did. Mining it looks like a ten-line `grep`, and
the ten-line version produces numbers that are wrong in ways that do not
announce themselves -- the output is plausible, monotonic, and off.

Three distinct failures, all observed on one measurement:

1. **The marker matches your own analysis.** Searching transcripts for
   `"Permission for this action was denied..."` hits the session where you
   *wrote that string* -- your prompt, your script, your summary are all
   transcript records too. The count inflates as you iterate on the script,
   which reads exactly like a real upward trend.
2. **UTC bucketing splits the working day.** `datetime.fromisoformat(ts).date()`
   buckets by UTC. West-coast evening work lands on the next day, halving
   both days.
3. **Two scripts, two populations, one name.** "Rejections" means either the
   operator was prompted and said no, or the host's classifier refused and
   the operator was never asked. These are different populations. Comparing
   a number from one against a number from the other produces a trend that
   does not exist.

## Context / Trigger Conditions

Invoke when:

- Counting permission prompts, denials, or rejections from local transcripts.
- Building or auditing a gate whose criterion is a rejection rate.
- Comparing permission friction before and after a hook, plugin, or
  `settings.json` change.
- Two measurement scripts disagree about "the same" count and you need to
  know which is wrong (often: neither).
- A denial count rose and you need to rule out self-contamination before
  reporting it.

## Solution

### 1. Anchor the marker, do not substring it

The refusal text is the *beginning* of a `tool_result` block. Match it there,
allowing the optional `Error: ` prefix the host adds on some paths:

```python
MARKER = "Permission for this action was denied by the Claude Code auto mode"
ANCHORS = tuple(p + MARKER for p in ("", "Error: "))

if not text.startswith(ANCHORS):
    continue
```

`startswith` on the flattened `tool_result` body cannot match a prompt, an
assistant message, or a script body, because none of those are a tool result
that *opens* with the refusal.

Flatten first -- the body is a string on some paths and a block list on
others:

```python
body = block.get("content")
if isinstance(body, list):
    body = "".join(p.get("text", "") for p in body if isinstance(p, dict))
```

### 2. Bucket by local day

```python
datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
```

`.astimezone()` with no argument converts to the local zone. Without it the
day boundary is UTC.

### 3. Name the population in the script, not in your head

State at the top of the file which of these it counts:

| population | marker | operator saw a prompt? |
|---|---|---|
| operator rejection | `Permission denied by user`, `the user doesn't want to proceed with this tool use` | yes, and said no |
| auto-mode refusal | `Permission for this action was denied by the Claude Code auto mode` | no |

If a prior measurement reports a different number, check which population it
counted before assuming either is broken. On one store the two instruments
reported 10 and 20 -- both correct.

### 4. Normalize before comparing periods

Daily transcript volume varies by more than an order of magnitude (153 to
15,031 records/day on a real store). Raw daily counts track workload, not
policy. Report **denials per 1,000 transcript records** and compare those.

### 5. Recover the command that was refused

The `tool_use` block precedes its `tool_result` in the same file, so one
forward pass resolves it:

```python
pending = {}                       # tool_use_id -> (name, input)
# ... on a tool_use block:
pending[block["id"]] = (block.get("name"), block.get("input") or {})
# ... on a matched tool_result:
tool, args = pending.get(block.get("tool_use_id"), ("?", {}))
target = args.get("command") or args.get("file_path") or ""
```

Without this the count has no interpretation -- knowing *what* was refused is
what separates "the gate is working" from "the classifier is wrong about
read-only commands".

## Verification

Run the extractor twice, with an edit to the script in between that mentions
the marker text in a comment. A correct extractor returns the identical
count. An unanchored one returns a higher count the second time -- it just
found its own diff.

Cross-check day bucketing by confirming the busiest day matches the operator's
recollection of when they worked, not the day after.

## Notes

- Transcripts under `~/.claude/projects/` may be pruned, which biases older
  periods downward. State it rather than discovering it in review.
- Approved prompts are **not** recoverable: an approved prompt is byte-identical
  in the transcript to a call that was never gated. Only refusals persist. Any
  gate built on "how often was I interrupted" is unbuildable from this store;
  the refusal tail is the available proxy.

## References

- voitta-yolt #98: https://github.com/voitta-ai/voitta-yolt/issues/98

## Related

- `session-transcript-mining` — the same store, the opposite question. That
  one sweeps transcripts for *knowledge* worth turning into skills; this one
  *counts outcomes* in them. If you are harvesting, go there; if you are
  measuring, stay here.
- `agent-session-credential-audit` — the same store again, hunting leaked
  secrets rather than permission outcomes. Worth reading alongside this for
  its false-positive taxonomy and its insistence on verifying by fingerprint
  rather than by pattern count, which is the same discipline as anchoring the
  marker here.
- `secrets-in-agent-sessions` — how to stop the transcript accumulating
  secrets in the first place, rather than measuring what it already holds.
- `agent-credential-leak-surfaces` — where agent state piles up on local
  disk, including the permission allowlist that determines which calls ever
  reach the classifier this skill measures.
