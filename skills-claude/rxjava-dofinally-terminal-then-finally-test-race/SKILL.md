---
name: rxjava-dofinally-terminal-then-finally-test-race
description: |
  An RxJava test that asserts a side effect of `doFinally` (a released
  semaphore permit, a decremented in-flight gauge, a closed resource)
  immediately after `TestObserver.await()` / `blockingGet()` is racy BY
  CONSTRUCTION: the operator delivers the terminal event to the downstream
  observer FIRST and runs the finally action AFTER, so the awaiting thread can
  observe the pre-release state. Use when: (1) CI fails with something like
  "permits should be returned once the held requests complete ==>
  expected: <0.0> but was: <1.0>" while the same test passes locally and in
  other parameterizations, (2) deciding whether such a failure is a REAL
  resource leak or a test-harness race, (3) writing tests around
  `doFinally`-based cleanup and choosing between asserting immediately and
  polling, (4) tempted to claim "fixed locally, 5/5 green" for a race your
  machine never reproduced. Covers the RxJava source proof, the
  leak-vs-race differentiation signals, the polling-assert fix, and the
  control experiment that tells you whether local runs mean anything.
author: Claude Code
version: 1.0.0
date: 2026-08-27
source: https://github.com/voitta-ai/skillz
source_file: skills/rxjava-dofinally-terminal-then-finally-test-race/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/rxjava-dofinally-terminal-then-finally-test-race/SKILL.md`).
> Updates go through the repo's worktree + PR workflow.

# RxJava `doFinally` runs AFTER the terminal event reaches your test

## Problem

A service client bounded its in-flight calls with a semaphore, released via
`doFinally`:

```java
return Maybe.defer(() -> {
    if (!inFlight.tryAcquire()) { shedCounter.increment(); return Maybe.empty(); }
    return call.get().doFinally(inFlight::release);
});
```

Its test drove N concurrent calls, awaited them, and asserted the in-flight
gauge returned to zero. CI failed — once, in one parameterization:

```
permits should be returned once the held requests complete ==> expected: <0.0> but was: <1.0>
```

The immediate question, and the one the PR review asked too: **real permit
leak, or harness race?**

## The root cause, from RxJava source

RxJava 3.x, `MaybeDoFinally` (`MaybeDoFinally.java:70-85`; pull the sources
jar from the Gradle cache:
`find ~/.gradle/caches -name "rxjava-3*-sources.jar"`):

```java
public void onSuccess(T t) {
    downstream.onSuccess(t);   // observer (and any await() on it) wakes HERE
    runFinally();              // the permit is released HERE
}
```

The terminal event reaches the downstream observer **before** `runFinally()`
executes the finally action. `TestObserver.await()` and `blockingGet()` both
return inside that window, so an assertion on the side effect immediately
after them races the releasing thread. Same ordering for `onError` and
`onComplete`, and the `Observable`/`Flowable`/`Single`/`Completable`
`doFinally` operators follow the same terminal-then-finally shape — verify
the one you use from its source rather than assuming, it is a two-minute
read.

This is not a bug in RxJava: `doFinally` guarantees the action runs exactly
once after termination or disposal; it does not guarantee it runs before
anyone who was awaiting the terminal event resumes.

## Real leak vs harness race — the differentiation signals

All three of these came from the SAME failing CI run and each independently
says "race, not leak":

1. **The sibling parameterization of the same test passed.** A genuine leak
   in the success path is deterministic — it leaks for every input shape, not
   for one of two parameter values.
2. **A test driving four sequential calls through a SINGLE permit passed.**
   If success/error/not-found leaked the permit, call two of four could never
   acquire. That test passing is a stronger no-leak proof than the failing
   test is a leak proof.
3. **The one test that POLLED (the dispose-path test) passed.** The only
   assertion style immune to the window is the one that did not fail.

If instead the failure reproduced across parameterizations and the
sequential-reuse test failed too, you would be looking at a real leak.

## The fix: poll the side effect, do not reorder the code

Do not "fix" this by moving the release earlier (e.g. `doAfterTerminate` vs
`doFinally` games) — the operator ordering is not yours to change, and the
production behavior is correct. Fix the assertion: add a polling helper as a
sibling of whatever awaiting asserts the test harness already has:

```java
// MeterAssertions: awaitCounter / awaitTimerCount already existed on a shared
// awaitCondition(deadline 5s, poll 5ms); awaitGauge is the missing sibling.
public static void awaitGauge(MeterRegistry registry, String name, double expected) {
    awaitCondition(() -> gaugeValue(registry, name) == expected,
        () -> String.format("gauge %s expected %s", name, expected));
}
```

Then replace every bare gauge/side-effect assert that follows a terminal
event with the polling form — including the ones that pass today. In the
same file, a `Thread.sleep(20)` retry loop and two more immediate asserts
were the same race latent; the class ended up sleep-free with three call
sites converted.

## The control experiment: does your machine even reproduce it?

After the fix, 5/5 local runs were green. **That proved nothing**, and the
way to know is a control: restore the PRE-fix test file and run it
repeatedly on the same machine.

- Control fails at least once: the machine reproduces the window; your green
  runs after the fix are real evidence.
- Control passes every time (here: **8/8 passed**): the machine never hits
  the window, local green is vacuous either way, and the claim on the PR
  must rest on the source ordering plus the CI signals — say exactly that
  rather than "verified locally".

This race was observed exactly once, in CI, and never locally. "Green after
fix" without a failing control is the classic way to ship an unverified
timing fix with false confidence.

## One real leak lives next door

While the gauge assert was a false alarm, the same gate had a genuine leak
on a path no test exercised: if the deferred supplier (`call.get()`) throws
**synchronously**, the permit acquired just above it is never released —
`doFinally` never attaches. The fix is a try/catch around the supplier call
that releases before rethrowing. When you touch a `tryAcquire` +
`doFinally(release)` gate, check the synchronous-throw path explicitly; the
race investigation is what surfaced it.

## Notes

- Applies to any `doFinally`-observed side effect, not just semaphores: gauge
  decrements, connection returns, MDC/context cleanup.
- Disposal is different: on `dispose()` the finally action runs on the
  disposing thread's call, so dispose-path tests naturally tend to poll —
  which is why they do not exhibit this failure.
- If the failure message names a count off by exactly one permit/unit in a
  concurrency test that "cannot fail", read the operator source before the
  application code. The application code was correct here.
