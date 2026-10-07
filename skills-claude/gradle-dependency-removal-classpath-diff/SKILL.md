---
name: gradle-dependency-removal-classpath-diff
description: |
  Prove that removing a Gradle dependency did not silently DOWNGRADE transitive
  modules, by diffing the resolved runtime classpath before and after. Use when:
  (1) you are deleting the last direct dependency on a library family and the
  `platform(...)` / BOM line looks newly unused, (2) a dependency-removal PR is
  green and you are about to merge it on that basis, (3) a library you did not
  touch is suddenly resolving to an older version, (4) you need to know WHICH
  dependency pulls a transitive you thought you had removed, (5) you removed a
  provider or client and want to know whether its classes left the classpath at
  all. The failure this prevents is silent: no compile step, test or build gate
  notices that about twenty modules resolved down a minor version, because a
  downgrade is a successful resolution. Ships a normalizer that handles the
  `requested -> resolved` conflict form, which is the step a hand-rolled diff
  gets wrong.
author: Claude Code
version: 1.0.0
date: 2026-10-06
hosts: [claude, codex]
---

# Diffing the resolved classpath across a dependency removal

## Problem

A service dropped its last direct dependencies on one SDK family, and with them
the `platform('...:bom:2.30.x')` line, which now looked unused. **The build
stayed green.**

But an internal HTTP utility library pulled a module of that same family in
transitively, at `2.17.x`. Without the BOM to pin it, **about twenty modules
resolved down** from `2.30.11` to `2.17.109`, and two unrelated libraries went
with them — `commons-codec` 1.17.1 to 1.15, `httpcore` 4.4.16 to 4.4.13 — plus a
set of reactive-streams modules that appeared from nowhere.

Nothing failed. **A downgrade is a successful resolution**, so no compile step,
test or build gate has anything to report. The BOM was not unused; it was
pinning a transitive nobody had looked for.

## Context / Trigger conditions

- Removing the last direct dependency on a library family, where the BOM or
  `platform(...)` line then looks unused.
- A dependency-removal PR is green and that is the whole argument for merging.
- A library you did not touch is resolving to an older version.
- You need to know which dependency pulls a transitive you meant to remove.
- You removed a client or provider and want to know whether its classes are off
  the classpath at all.

## Solution

### 1. Take the resolved set on both sides

`scripts/classpath-set.sh` emits a sorted set of
`group:artifact:resolvedVersion`:

```bash
git checkout main   && ./scripts/classpath-set.sh runtimeClasspath > /tmp/main.txt
git checkout branch && ./scripts/classpath-set.sh runtimeClasspath > /tmp/branch.txt
```

**The normalization is the part that goes wrong by hand.** The tree prints
conflict resolution as `1.2.3 -> 4.5.6`, and the version that matters is the one
on the **right**. A diff of the raw tree compares requested versions and
misreports in both directions.

### 2. Diff both ways, and read them together

```bash
comm -23 /tmp/main.txt /tmp/branch.txt   # gone from the branch
comm -13 /tmp/main.txt /tmp/branch.txt   # new on the branch
```

**A version change shows up on BOTH sides** — as a removal at the old version
and an addition at the new one. That is the signature to look for, and it is why
reading only the removal side hides every downgrade.

Worked example, from the fixture in this skill's own check. Intent was to remove
two artifacts; the diff shows six gone and four new:

```
gone:  commons-codec:commons-codec:1.17.1        <- NOT intended
       org.apache.httpcomponents:httpcore:4.4.16 <- NOT intended
       software.amazon.awssdk:bom:2.30.11            intended
       software.amazon.awssdk:cloudwatch:2.30.11     intended
       software.amazon.awssdk:dynamodb:2.30.11   <- NOT intended
       software.amazon.awssdk:sdk-core:2.30.11   <- NOT intended
new:   commons-codec:commons-codec:1.15          <- the downgrade
       org.apache.httpcomponents:httpcore:4.4.13 <- the downgrade
       software.amazon.awssdk:dynamodb:2.17.109  <- the downgrade
       software.amazon.awssdk:sdk-core:2.17.109  <- the downgrade
```

**Anything beyond the artifacts you meant to remove is a finding.** No version
may change.

### 3. Attribute the transitive

```bash
./gradlew dependencyInsight --dependency <group:artifact> --configuration runtimeClasspath
```

That names who pulls it, which is what tells you the BOM was load-bearing.

### 4. Fix by keeping the pin, with its reason

Keep the `platform(...)` line and **comment it with the transitive it pins**:

```kotlin
// Pins <group>:<artifact>, pulled transitively by <library>. No direct
// dependency on this family remains; removing this line downgrades ~20 modules.
implementation(platform("<group>:bom:<version>"))
```

A `platform(...)` with no direct dependency beside it looks like dead config to
the next reader, and to every automated cleanup. The comment is the only thing
standing between it and deletion.

Then re-diff: only the intended artifacts may disappear, and no version may
change.

## Verification

Run step 1 and 2 again on the fixed branch. Both `comm` outputs must contain
only the artifacts you intended to remove, and nothing on the `new` side.

The skill's own check:

```bash
./scripts/classpath-set.sh --from-file <(printf '%s\n' '+--- g:a:1.0 -> 2.0')
# must print g:a:2.0
```

## Notes

- **Removing the direct dependency does not remove the family.** The core and
  auth modules of that SDK stayed on the classpath through the transitive. What
  the removal took away was the injectable provider, not every class — so "is it
  still on the classpath" and "is it still wired" are different questions with
  different answers.
- Do this for `runtimeClasspath`. A `compileClasspath` diff can be clean while
  runtime resolution changes, because they are resolved separately.
- The same method covers a dependency *addition*: the finding is any version
  that moves other than the one you added.

## Related

- `secretsmanager-prove-no-consumer-before-destroy` — the same discipline on a
  different surface: before removing a thing, produce evidence rather than the
  absence of a complaint. A green build is the absence of a complaint.
