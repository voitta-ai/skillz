---
name: jacoco-class-id-mismatch-warns-then-succeeds
description: |
  Read a JaCoCo coverage report correctly when the execution data and the class
  files come from different builds, given that the mismatch is a WARNING and the
  build still succeeds while the affected classes silently report zero coverage.
  Use when: (1) generating a report from a `.exec` file that is older than the
  current build, or from dumps taken across a deploy; (2) accumulating coverage
  over a long window (production coverage, long-running processes, merged dumps)
  where releases land mid-window; (3) a class you know is heavily tested reports
  zero coverage; (4) about to conclude code is dead or untested from a zero in a
  coverage report; (5) wiring coverage into CI or a pipeline that must fail
  rather than warn. Covers the exact warning text, why the build exit code is
  useless as a signal, the class-id keying that causes it, the
  enclosing-scope control that makes a zero inadmissible rather than damning,
  and what JaCoCo's own merge can and cannot do across releases.
author: Claude Code
version: 1.0.0
date: 2026-09-12
---

# JaCoCo class-id mismatch warns, then succeeds

## Problem

JaCoCo keys execution data by a **hash of the class bytes**, not by class name.
If the class files handed to `report` differ from those loaded when the data was
recorded, the entries do not reconcile and the affected classes report **zero
coverage**.

It does not fail. It prints a warning and exits successfully:

```
[ant:jacocoReport] Classes in bundle 'myproject' do not match with execution data.
For report generation the same class files must be used as at runtime.
[ant:jacocoReport] Execution data for class com/example/service/SomeFactory does not match.
BUILD SUCCESSFUL
```

The report is not empty, which is what makes this dangerous. Most classes look
fine and a subset reads zero, so nothing about the output announces itself as
broken. Any consumer that treats zero coverage as "untested" or "dead" now has
a confident false positive, aimed preferentially at the classes that change
most, which are usually the most important ones.

## Observed

Running `jacocoTestReport` against execution data eight months old, on a
codebase whose test suite thoroughly exercises its controller and service:

| class | commits since the exec was recorded | coverage reported |
|---|---|---|
| the HTTP controller | 25 | **zero** |
| the service it delegates to | 24 | **zero** |
| a config class beside them | 4 | present |

Overall the report showed 46 of 77 classes with coverage and 146 of 324 methods,
which looks like a plausible mediocre-coverage codebase. The two classes reading
zero were the two most heavily tested in the repository, exercised by four test
classes across roughly eighteen call sites.

Note the correlation with churn: classes that changed report zero, classes that
did not report fine. That is the signature.

## Detection

**Do not rely on the exit code.** Capture the output and grep it:

```bash
./gradlew jacocoTestReport 2>&1 | tee /tmp/jacoco.log
grep -q "do not match with execution data" /tmp/jacoco.log && {
  echo "FATAL: class-id mismatch; coverage zeros are not trustworthy" >&2
  exit 1
}
```

In a pipeline, make it fatal. A warning nobody reads is the whole failure mode.

## The control that makes zeros safe to read

Before believing any zero, check two things.

**A known-live control.** Pick a method that certainly executes, and confirm it
reads non-zero. If it does not, the report is broken rather than the code.

**The enclosing scope.** A zero on a method whose **class** also reads zero
carries no information: the class never executed in this window, so nothing
inside it could have. Treat those rows as inadmissible, not as findings. Only a
zero method inside a live class is evidence.

```python
admissible   = [m for m in methods if m.class_covered > 0]
inadmissible = [m for m in methods if m.class_covered == 0]   # report separately
```

This single rule is what turns the failure above from a false positive into a
correctly-labelled unknown, with no extra data required.

## Merging across releases

`jacococli merge` folds multiple `.exec` files, and within one release it is
exact and free. Across a deploy where a class changed, the entries for that
class cannot reconcile, and merge does not fix it.

So for any accumulation whose window spans releases:

- Report using the **exact class files from the build that produced the dumps**,
  never a fresh local build. On containers, that means the jars from that image.
- Key accumulated results by something stable across releases. Fully-qualified
  method names survive; line numbers do not, which is one reason to accumulate
  at method granularity rather than branch.
- Treat each release as its own bundle, and combine at the symbol level
  afterwards rather than at the `.exec` level.

This is the specific reason a long-window coverage pipeline needs its own
accumulation layer instead of calling JaCoCo's merge: accumulating across
releases is exactly the job JaCoCo cannot do, and it does not refuse when
asked.

## Related

- **`dump --reset` changes the measurement.** Resetting zeroes the counters, so
  each subsequent dump covers only the interval since the last one. Omit it and
  every dump is cumulative since process start.
- **JaCoCo is binary, not counting.** It reports "executed at least once", never
  how many times. A single report supports no rate or frequency bound, so a
  denominator for statistical claims has to be the number of accumulated
  observation windows.
- **A stale `.exec` on disk survives a lot.** `build/jacoco/test.exec` persists
  across branch switches and partial builds, so `jacocoTestReport -x test`
  cheerfully reports against whatever is there.
