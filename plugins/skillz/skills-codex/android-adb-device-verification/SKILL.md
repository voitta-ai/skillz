---
name: android-adb-device-verification
description: |
  Verify an Android change on a device or emulator when the project has no test
  suite, and avoid reading a blind check as a passing one. Use when: (1) you
  changed Android code and want evidence it works beyond "it compiled",
  (2) a UI assertion driven by `uiautomator dump` reports text is missing,
  (3) `adb shell run-as` fails with "not debuggable", (4) a release build
  misbehaves while debug is fine, (5) you are about to conclude a feature is
  broken because a grep over a dump, a dex file, or logcat came back empty.
  Covers the build-install-drive-read loop, tapping by label instead of
  coordinates, mocking location, and the calibration discipline that keeps an
  unplugged cable or a stale dump from reading as a green assertion.
author: Claude Code
version: 1.0.0
date: 2026-09-13
---

# Verifying Android changes on a device, without tests

## Problem

A project with no test suite still needs evidence that a change works. The
obvious loop - build, install, look at it - is fine until it is automated, and
then it acquires a failure mode worse than no check at all: **a check that
cannot observe anything reports the same thing as a check that observed
nothing.** An unplugged cable, a stale screen dump, or a grep whose pattern can
never match all produce a confident "not present".

That is not a hypothetical. Each of the traps below cost real debugging time in
one session, and two of them produced a false bug report before being caught.

## Context / Trigger conditions

- You changed Android code and "it compiled" is not evidence.
- A UI assertion says a string is missing, and you are about to go fix a
  feature that in fact works.
- `adb shell run-as <pkg>` fails: `run-as: package not debuggable`.
- The release build behaves differently from debug - blank output, a crash, a
  serialization error - and nothing in the source explains it.
- You need to exercise location-dependent behavior from a desk.

## Solution

### 1. Verify the release build, not only debug

R8 shrinking and obfuscation break reflection-driven code - JSON serializers,
anything resolved by class name - and debug builds have R8 off, so debug will
happily pass while release is broken.

```bash
./gradlew assembleRelease
adb install -r app/build/outputs/apk/release/app-release.apk
```

Sign the release variant with the debug keystore during development so the
same artifact you shrink is the one you install:

```kotlin
buildTypes {
    release {
        isMinifyEnabled = true
        signingConfig = signingConfigs.getByName("debug")
    }
}
```

Build **bare first** - R8 on, zero keep rules - then add the narrowest rule
that fixes the actual observed failure. A broad `-keep class * extends Foo`
rule can drag an unreachable dependency back in and break a build that was
working.

### 2. Drive the UI by label, not by coordinate

`uiautomator dump` gives the screen as XML. Derive the tap point from the
element's own `bounds`, so the script survives a layout change:

```bash
adb shell uiautomator dump /sdcard/ui.xml
adb shell cat /sdcard/ui.xml | tr '<' '\n' | grep -F "Save" \
  | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1
# then tap the centre of those bounds
```

`scripts/adb-ui.sh` in this skill wraps that: `text`, `has`, `tap`, `tap-nth`,
`type`.

### 3. Read state back from the app

`run-as` reads app-private files, and works **only on a debuggable build**:

```bash
adb shell run-as com.example.app cat files/output.jsonl
```

If you need this against a release build, install the debug build over it -
same signing key, so app data survives.

### 4. Mock location

```bash
adb emu geo fix <longitude> <latitude>     # longitude FIRST
```

Reversing the arguments silently puts you somewhere else on earth rather than
erroring. Send it two or three times; the first can land before the app
subscribes.

### 5. Permissions: grant to skip the flow, withhold to test it

```bash
adb shell pm grant com.example.app android.permission.ACCESS_FINE_LOCATION
adb shell pm revoke com.example.app android.permission.POST_NOTIFICATIONS
```

Pre-granting is right when the permission is incidental to what you are
checking. Withhold it when the permission flow *is* what you are checking -
then drive the real system dialog, which is a separate window in the dump.

### 6. Calibrate every check before believing a negative

**This is the part that matters.** Before concluding "the string is absent",
prove the check can see a string you know is present:

```bash
./scripts/adb-ui.sh has "<something certainly on screen>"   # must exit 0
./scripts/adb-ui.sh has "<the thing you doubt>"             # now meaningful
```

The four ways a check goes blind, all observed:

| Trap | Looks like | Reality |
|---|---|---|
| No device attached | every assertion "absent" | the cable, not the code |
| Stale dump | feature "missing" after reinstall | the app restarted to its initial state; the dump predates the action |
| Wrong quoting | error text "never rendered" | `uiautomator` switches to `text='...'` when the value contains a double quote, so a `text="..."` pattern misses exactly the JSON-bearing errors worth reading |
| Pattern can never match | zero hits, confidently reported | e.g. grepping a `.dex` for plain strings; control strings return zero too |

The generalisation: **a negative from an uncalibrated check is not evidence.**
Run the positive control in the same breath as the assertion.

## Verification

The loop is working when:

- The positive control exits 0 on the same dump that the assertion runs against.
- `adb devices` shows exactly one line ending in `device`. Anything `offline`
  or `unauthorized` must fail loudly, not quietly return nothing.
- A deliberate failure is detectable: point the app at a bad key or a bad
  endpoint and confirm the error reaches the screen or the log. A verification
  path that has only ever seen success has not been verified.

## Example

Proving an API integration works end to end without spending a credential: set
a deliberately invalid key and require the resulting **401 to round-trip** -
through the client, the error state, the UI, and the log.

That single assertion covers class loading, TLS, request serialization,
response deserialization, and error mapping. A valid key proves nothing further
about the wiring, and a 401 that parses is stronger evidence than a 200 you
cannot distinguish from a stub.

## Notes

- `adb` is not on `PATH` by default; it lives in `<sdk>/platform-tools`. Any
  instructions you write for others should say so - "command not found" is the
  first thing a new collaborator hits.
- Reinstalling resets the app to its launch state. Re-drive the app to the
  state under test before dumping, or you are reading the wrong screen.
- Emulator system images lag real devices by years. An API 31 emulator will not
  catch behavior introduced in API 33+ (notification permission) or the package
  visibility rules from API 30+. Confirm on real hardware before claiming a
  feature works.
- Pass secrets to the device on **stdin**, never in `argv`:
  `printf '%s' "$KEY" | adb shell 'IFS= read -r k; input text "$k"'`.
  An `adb shell input text "$KEY"` puts the value in `ps` and in history.
- Clear app data (`adb shell pm clear <pkg>`) when you are done testing with a
  real credential on a shared or borrowed device.
