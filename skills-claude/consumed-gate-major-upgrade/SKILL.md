---
name: consumed-gate-major-upgrade
description: |
  Decide whether a new major of a security gate you consume is safe to adopt,
  when your product depends on a distinction the gate's own host does not.
  Use when: (1) you embed a classifier, policy engine, linter or permission
  hook that another product also ships (voitta-yolt, OPA, semgrep, a CI policy
  bundle), (2) the vendor reports an improvement -- fewer prompts, fewer rules,
  a smaller ask rate -- and you need to know what it costs *you*, (3) a
  dependency's release notes say "no behavior change" and you cannot tell
  whether that was measured in your semantics or theirs, (4) you are writing
  the startup check that decides whether a dependency is usable at all. The
  failure this prevents: a vendor's honest "zero drift" measurement being true
  for their host and catastrophic for yours, because you consume a distinction
  they collapsed. Covers verifying in your own semantics, the delegated-versus-
  unreadable collapse, choosing a startup probe that can actually fail, and
  asking the vendor to report what the verdict depended on.
author: Claude Code
version: 1.0.0
date: 2026-09-15
---

# Adopting a new major of a gate you consume

## Problem

A gate you embed serves its own host first. When it changes, the vendor
measures the change in that host's terms, honestly, and publishes a number. The
number can be true and still be the wrong number for you -- not because anyone
was careless, but because the two of you consume different distinctions.

The worked case: an exec classifier emits `safe | unsafe | unknown`. Its own
host is an interactive tool where `safe` and `unknown` are both *silent* -- the
difference is invisible to a human at a terminal. A downstream service used the
same classifier as its **only** gate, where `safe` meant run-without-asking and
`unknown` meant park-for-approval. The major release deleted 108 of 136 rules,
keeping "only what we refuse to delegate". Measured in the vendor's terms: the
ask rate fell 15.8% to 4.9%, a real improvement. Measured in the consumer's
terms: `cat`, `ls`, `grep`, `head`, `git status`, `git diff` and `curl` all
moved from `safe` to `unknown`, so every ordinary read now required a human.
Three commands still classified `safe`.

The vendor had even measured drift and reported **zero commands changed**.
True -- of the commit measured, which predated the deletion phase.

## Context / trigger conditions

- A dependency you gate on ships a major, a "simplification", or a rule-set cut.
- Release notes quantify an improvement in prompts, alerts, findings or rules.
- The vendor's host has a layer after the gate (a human, an approval flow, a
  second policy) and yours does not.
- You are about to copy a version number out of a changelog into your own docs.

## Solution

### 1. Ask what the gate decides *after* it answers you

One question sorts consumers: **does anything decide after this gate?** If a
human or a second policy sees the verdict, `safe` and `unknown` can be the same
exit and nobody notices. If the gate is terminal -- its verdict *is* the action
-- every distinction it collapses is a decision you now make wrongly.

Write this down where the dependency is declared, not in a design doc. It is
the thing that makes the next upgrade's risk obvious to someone who was not
there.

### 2. Replay in your own semantics, not the vendor's

Do not ask "did verdicts change". Ask "did anything cross **my** boundary". For
a two-tier consumer that boundary is usually one predicate:

```python
for cmd in corpus:
    before = classify_with(old_version, cmd)
    after  = classify_with(new_version, cmd)
    if (before == "safe") != (after == "safe"):     # YOUR boundary, not theirs
        print(cmd, before, "->", after)
```

Check **both directions**, and check the boring one first. The instinct is to
ask what became more permissive; the damage here was everything that stopped
being permissive, and asking only the first question is how it was missed until
someone ran the second.

### 3. Trust the tag, not the branch, and check what you measured

Any drift number is a property of the tree it ran on. Before believing one --
the vendor's or your own -- confirm the tree contained the change in question:

```bash
git show <measured-ref>:rules/shell.json | jq '.commands | length'   # 136
git show v2.0.0:rules/shell.json         | jq '.commands | length'   # 28
```

Two separate stale-tree artifacts appeared in one day on one project: a review
reasoning over a two-dot diff range, and a drift measurement taken nine commits
before the phase that changed verdicts. Both were produced by careful people.
**Measure the rig before you believe the result.**

### 4. Beware the collapse: "delegated" versus "unreadable"

The sharpest form of this failure is a value that used to mean one thing and
now means two. When a gate stops classifying something *on purpose*, its
"no opinion" verdict becomes indistinguishable from "could not parse":

| population | example | separable after the change? |
|---|---|---|
| delegated by policy | `cat x` | no |
| unrecognized | `somecommand_xyz` | no -- identical state |
| unreadable (parse failure) | `((` | yes, by reason string |

A consumer that must fail closed on the third has no choice but to fail closed
on the first. State it to the vendor in exactly those terms -- it is a concrete,
fixable interface defect, not a preference.

And when the vendor offers to split the bucket the cheap way ("no-opinion"
versus "unreadable"), price it before accepting: that turns an **allow-list**
(run what is known read-only) into a **deny-list** (run what has not been
objected to). If your tier exists so that nobody has to watch, the deny-list
version is the bucket inverting, not a smaller version of the same thing.

### 5. Make the startup probe out of something that can fail

A gate you cannot use must say so at boot, once, loudly -- not a command at a
time. But the probe is itself a measurement, and it is easy to draw it from the
population that cannot move:

```python
_PROBE = "echo preflight"    # WRONG: echo is one of three survivors
_PROBE = "cat /dev/null"     # right: a command the change delegated
```

The first probe passes cleanly on a release that breaks every read. **A canary
drawn from the set that never changes cannot detect change.** Pick the probe
from the population the change affected, assert in the test suite that the
probe is not in the surviving set, and prefer a behavioral check to a version
comparison -- a gate that cannot call `cat` read-only is unusable whatever its
version string says.

### 6. Ask the vendor to report what the verdict depended on

You can only verify what the payload reports. If a flag, a working directory or
a rule file changed the answer, the answer should say so:

```json
{"decision": "unsafe", "reason": "...", "allow_patterns": 0, "cwd_used": "/srv/app"}
```

`allow_patterns: 0` is what lets a consumer *assert* at startup that an opt-out
took effect instead of hoping. Every default that is correct for the vendor's
host and wrong for yours -- `os.getcwd()`, a home-directory config path, a
default profile -- is invisible until it produces a wrong verdict. Reported, it
becomes one assertion.

Related: prefer **a pointer over a profile** when asking for configurability. A
new flag with a default has a default that is wrong for someone; `--rules-file
PATH` with no default has nothing to be wrong about.

## Verification

Before the pin changes:

- the replay in your semantics is empty, or every entry is understood;
- the startup probe fails against the new version if the new version is
  unusable, and you have run it both ways to see it fail;
- the floor in your docs is the version that fixes what mattered **to you**,
  not the version that added the feature you noticed. Check the intervening
  releases for anything that was *granted* rather than merely *asked*: a grant
  in a terminal consumer is an uncarded action.

## Notes

- **A version number copied from a changelog is a claim you did not check.**
  The floor in these docs was for a while the release that added the flag,
  while four write-target fixes sat above it -- one of which had classified a
  write to `~/.ssh/authorized_keys` as safe.
- **Pinning below the newest is a normal outcome, not a failure.** "1.6.0
  answers the question we need answered" is a complete argument, and it beats
  adopting a major on schedule.
- **Say the cost in the vendor's own frame.** The exchange that produced this
  went well because both sides checked claims against source before agreeing --
  including retracting a "three lines on your side" that one `grep` refuted.

## References

- voitta-ai/voitta-yolt#143, #144 -- the CLI/hook verdict divergence, and the
  `unknown` collapse.
- voitta-ai/shmobster#177, #178 -- the consumer side: the adoption hold, and the
  probe drawn from the affected population.
