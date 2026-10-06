---
name: credential-audit-rerun
description: |
  Re-run a credential audit weeks after the sweep that produced it, when the
  manifest has gone stale. Use when: (1) `classify.py` or an equivalent crashes
  with FileNotFoundError on a path the sweep recorded, (2) you are resuming a
  half-finished audit and need to know which verdicts still hold, (3) a
  fingerprint's recorded file exists but no longer contains it and you must
  decide what that means, (4) a scrub has run and you are deciding what is
  actually finished. Covers why versioned plugin caches expire recorded paths
  on a schedule nobody controls, the three different things an unreadable span
  means and why two of them look identical, the rule that "I could not read it"
  must never become "safe to delete", why a tool that re-walks the filesystem
  survives staleness and one that trusts the manifest does not, and the two
  credential-bearing surfaces the audit itself creates while running.
author: Claude Code
version: 1.0.0
date: 2026-09-17
source: https://github.com/voitta-ai/skillz
source_file: skills/credential-audit-rerun/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/credential-audit-rerun/SKILL.md`). Updates go through the repo's
> worktree + PR workflow - open an issue, branch, PR.

# Re-running a credential audit that has gone stale

## Problem

`agent-session-credential-audit` covers the first pass: sweep, analyse,
classify, probe, scrub. This is the second pass, days or weeks later, and it
fails differently. The sweep wrote down **paths**, and paths move. By the time
anyone resumes, some of the evidence has relocated, some has been remediated,
and some has been rotated into a file the manifest never names - and all three
look the same to code that opens `files[0]` and reads.

Measured on one machine, 2026-09-17, twenty days after the sweep: of 1224
fingerprints with recorded files, **16 had a vanished first path and 1 had no
surviving file at all.** That is enough to crash a classifier sixteen times in
a row, one fingerprint per run.

## Context / Trigger conditions

- `FileNotFoundError` from a classify/report step, on a path under
  `~/.claude/plugins/cache/...`, `~/.claude/file-history/...`, or any other
  versioned or pruned directory.
- Resuming an audit whose `probe.json` / `pending.json` are older than its
  `probe.out`, so the last probe run was never folded back in.
- A private key or token classified from a span that could not be read.
- Deciding whether a scrub is "done".

## Solution

### 1. The manifest is a snapshot; re-derive before you trust it

A sweep records `{fingerprint: {kind, classes, files: [...]}}`. Nothing keeps
those paths valid. The reliable movers:

- **Versioned plugin caches.** `~/.claude/plugins/cache/<plugin>/<n>/1.0.0/...`
  becomes `.../1.1.0/...` on the next update. Every recorded path under a cache
  expires on somebody else's release schedule. This is the single most common
  cause.
- **Pruned history.** `~/.claude/file-history/<session>/<hash>@v2` entries are
  garbage-collected.
- **Rotation.** `x.log` becomes `x.log.old` and a fresh `x.log` appears. The
  recorded path still exists and is now a different file.

Before re-classifying, measure the damage rather than discovering it one crash
at a time:

```python
import json, os
sw = json.load(open("sweep.json"))["fingerprints"]
gone_first = sum(1 for r in sw.values()
                 if r.get("files") and not os.path.exists(sorted(r["files"])[0]))
gone_all = sum(1 for r in sw.values()
               if r.get("files") and not any(os.path.exists(f) for f in r["files"]))
print(gone_first, "crash the naive reader;", gone_all, "are unresolvable")
```

### 2. Read every recorded file, not the first

A fingerprint usually appears in several files, and the survivors often still
hold it. The naive form is one line and wrong:

```python
def first_span(fp, r):
    p = sorted(r["files"])[0]          # crashes the moment this one moves
    data = open(p, "rb").read()
```

Try each, skip what will not open, and **return empty rather than guessing**.

### 3. An unreadable span means three different things

This is the part that is easy to get wrong, and getting it wrong is how a
remediated credential ends up on a re-sweep list for ever - or worse, how a
credential that merely **moved** gets called fixed.

| What you observe | What it means | What to do |
|---|---|---|
| No recorded file exists | Evidence lost | Pending, re-sweep |
| Files exist, none contains it | **Ambiguous** | Pending, and go look |
| Files exist, one contains it | You have the span | Classify normally |

The middle row is the trap. A value leaves a file two ways: it was **redacted**,
or the file was **rotated** and the value went with the old content. On the
machine above, two private keys read as "no longer in any recorded file" from
`~/.claude/yolt.log` - and were sitting in `~/.claude/yolt.log.old`, five
megabytes of it, one directory listing away. Checking only that the value had
*left* was not the same as checking where it had *gone*.

So the pending reason should say `check rotations/backups (.old, .1, .bak,
.N.gz) before believing it is gone`, not `already remediated`.

Include the compressed forms. No `.gz` rotation existed on the machine above,
so this is the shape rather than an observation - but it is `logrotate`'s
default, and it defeats the same check twice: the value is absent from the
live file *and* invisible to a plain grep of the archive that holds it. A
rotation you cannot read is the first row of the table, not the second.

### 4. "I could not read it" must never become "safe to delete"

The rule the whole pass turns on. A kill-list drives a destructive step, so
every path into it has to be positive evidence. Absence of evidence goes to
pending.

A tool that gets this right can still crash rather than mis-classify - and that
is the correct failure. `pk_structural(b"")` raising `IndexError` is a tool
refusing to answer a question it cannot answer. Fix the crash by routing the
empty span to pending, not by making the classifier tolerate emptiness.

The same rule recurs everywhere once you look for it: an unpriced API call is
not `$0`, a scanner with no wordlist is not `clean`, a request whose target
cannot be resolved is not `allowed`.

### 5. Re-walk beats re-read, and check which one your scrub does

Two scripts in the same audit, same data, opposite robustness:

- `classify.py` read the manifest -> crashed on staleness.
- `scrub.py` called `sweep.iter_files()` -> re-walked the filesystem, never saw
  a vanished path, and found the rotated `.old` files the manifest never named
  for those fingerprints.

The tool that **mutates files** was the one built to tolerate a moving world.
That is the right way round, but it happened by design in one script and not the
other, and nothing in the toolchain made the difference visible. Check yours
before assuming the destructive step is as tolerant as the reporting step.

### 6. Verdict conservatism survives the gap, and should

A probe that answers `HTTP 200 ok=False err=invalid_auth` for a Slack token is
telling you it is dead. Kill-list it only if your rule says DEAD, not
"not-LIVE": a rate-limited GitHub token answers 403 and is very much alive. On
the run above, 97 probed gave **91 DEAD, 6 INCONCLUSIVE, 0 LIVE**, and 5 slack
tokens stayed pending on exactly this rule. They are almost certainly dead.
Leaving them pending costs nothing; the opposite mistake costs a live secret.

Separately: a token that appeared in a **transcript** is worth rotating on
exposure grounds whatever its liveness verdict says. Dead is not the same as
never-read.

### 7. The audit creates two credential-bearing surfaces while it runs

Both are easy to leave behind because neither is the thing you were hunting.

**The backup directory.** A scrub that is safe to run writes the originals
somewhere first. That directory now holds verbatim copies of every value the
pass removed, in the clear - 54 MB of it on the run above, mode 0700. Worth
having until the result is verified; a fresh instance of the original problem
the moment it is not. Delete it deliberately, as a step, not when you remember.

**The transcript of the audit itself.** Session files grow while you work in
them. On the run above, the auditing session's own transcript was deferred with
**4 kill-listed spans at the dry run and 9 at the apply** - it had gained five
while the audit was being discussed.

That is why positive controls belong on stdin, never in a command:

```bash
# wrong: the shape is now in the transcript for ever
python3 -c "import credlib; print(credlib.find_all(b'ghp_...'))"

# right: generate at runtime, or feed it in
python3 - <<'PY'
import os, credlib
probe = b"ghp_" + os.urandom(20).hex().encode()[:36]
print([k for k, *_ in credlib.find_all(probe)])
PY
```

Denying the command afterwards does not unwrite the transcript entry.

### 8. Live writers, and why the last pass needs everything quit

A scrub must refuse to rewrite a file a running process holds open: the process
may rewrite it back from its own buffer, undoing the scrub while the tool
reports success. That is the same silent failure the audit exists to catch.

Expect the deferred set to include `history.jsonl`, the `file-history` of live
sessions, and **each live session's own transcript**. The final pass is a
scheduling problem, not a command - on the run above there were 52 agent
sessions alive on one machine.

Write down everything the next session needs **before** that pass, in a repo, an
issue or a memory file. The transcript you would otherwise read it back out of
is one of the files being rewritten.

## Verification

- Re-run the classifier: it completes, and any unresolvable fingerprint appears
  in `pending` with a reason naming rotations rather than claiming remediation.
- The scrub's last line reports residual by **fingerprint**, not by pattern
  count: `verified: residual kill-listed spans in scrubbed files = 0`. Counting
  patterns would call a file clean because the redaction changed its shape.
- Independently re-scan a surface the audit did not sweep - an application's own
  log, say - with the same patterns, and **exercise the scanner on a known shape
  first**. A zero from an unexercised scanner is not a measurement.

## Notes

- The sweep's roots are usually agent homes (`~/.claude`, `~/.codex`, ...) plus
  shell profiles. Applications that write their own logs elsewhere are outside
  it. On the run above, an agent's 225 MB error log had never been swept; it
  scanned clean, but nothing had checked.
- Do not re-sweep to "refresh" the manifest without deciding what to do with the
  old verdicts. A re-sweep renumbers nothing but does re-date everything, and a
  probe run whose output was never folded back in (`probe.out` newer than
  `probe.json`) will silently keep the older answer.

## References

- `agent-session-credential-audit` - the first pass this one resumes.
- `pre-open-source-credential-audit` - the same discipline before publishing.
- `secrets-in-agent-sessions` - the redaction hook that stops the next one.
- "The call was coming from inside the house",
  https://blog.debedb.com/2026/08/20/the-call-was-coming-from-inside-the-house/
  - the leak class, and the warning that verification systems fail silently:
  "You only find these by checking the thing itself instead of the report."
