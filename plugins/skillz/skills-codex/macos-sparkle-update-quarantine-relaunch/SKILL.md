---
name: macos-sparkle-update-quarantine-relaunch
description: >
  Fix a macOS Sparkle in-app updater that fails with SUSparkleErrorDomain 4005
  "remote port connection was invalidated" + underlying SUSparkleErrorDomain(10)
  "Failed to create installation cache directory", where stripping
  com.apple.quarantine and clearing Sparkle caches alone does NOT help. Use when
  the app is correctly in /Applications and Developer-ID signed, the update DMG
  already downloaded, yet Retry keeps failing. Root cause: the running app
  instance was launched BEFORE quarantine was removed, so its installer XPC
  context is stale. The missing step is a full relaunch of the un-quarantined
  bundle.
author: debedb
version: 1.0
date: 2026-06-17
source: cmux 0.64.10 -> 0.64.16 update on macOS 15 (Apple Silicon)
source_file: ~/.config/cmux/SETUP-NOTES.md
---

## Problem

A macOS app that self-updates via Sparkle refuses to install an update. The UI
shows "Move <app> into Applications and relaunch to enable updates" with:

```
Domain: SUSparkleErrorDomain
Code: 4005
Failure: The remote port connection was invalidated from the updater.
underlying=SUSparkleErrorDomain(10) Error: Failed to create installation cache
directory in ~/Library/Caches/<bundle-id>/org.sparkle-project.Sparkle/...
```

The well-known fix (strip `com.apple.quarantine`, delete the Sparkle
PersistentDownloads/Installation caches, Retry) does NOT clear it on its own. The
"Move into Applications" banner is misleading — the app is already in
`/Applications`.

## Context / Trigger Conditions

Invoke when ALL of these hold:

- Sparkle updater fails with `SUSparkleErrorDomain` code `4005` and/or underlying
  `(10)` "Failed to create installation cache directory".
- The app is genuinely in `/Applications` (not App-Translocated): verify with
  `lsof -p <pid> | awk '$4=="txt"{print $NF}' | grep <app>.app`.
- The app is Developer-ID signed with hardened runtime and ships
  `Installer.xpc`/`Downloader.xpc` (so entitlements/signing are NOT the cause —
  Sparkle's error text lists them as red herrings).
- The update DMG already downloaded fully (the failure is the INSTALL phase).
- You stripped quarantine and/or cleared Sparkle caches but Retry still fails.

Do NOT invoke for: a quarantined app that has never been launched post-strip
(just strip + relaunch normally), or a genuinely translocated app (move it into
/Applications first).

## Solution

The decisive insight: a long-lived app process launched while the bundle was
still quarantined keeps a stale Sparkle installer XPC launch context, so the
privileged install helper connection is invalidated. Stripping quarantine only
affects *future* launches. You must relaunch.

1. Strip quarantine and clear stale Sparkle caches:

   ```
   xattr -dr com.apple.quarantine /Applications/<app>.app
   rm -rf "$HOME/Library/Caches/<bundle-id>/org.sparkle-project.Sparkle/PersistentDownloads/"* \
          "$HOME/Library/Caches/<bundle-id>/org.sparkle-project.Sparkle/Installation/"*
   ```

2. **Fully quit the app (Cmd-Q) and relaunch it from /Applications** (Spotlight /
   Dock / Login Item — arg-free). This is the step the usual recipe omits.
3. Check for Updates -> Retry. The DMG is cached, so install is fast.

Diagnostic that nails the root cause — compare the running process start time to
when quarantine was stripped:

```
ps -o pid,lstart,comm -p "$(pgrep -x <app> | head -1)"
```

If the process started before the strip, that stale instance is why Retry fails.

## Verification

```
/Applications/<app>.app/Contents/Resources/bin/<cli> --version   # new version
xattr /Applications/<app>.app | grep quarantine                  # absent
```

The updater installs without the 4005 dialog; the relaunched app reports the new
version. (Confirmed: cmux 0.64.10 -> 0.64.16 on macOS 15 Apple Silicon.)

## Notes

- `com.apple.macl` and `com.apple.provenance` xattrs remaining after the strip
  are harmless — only `com.apple.quarantine` matters here.
- For cmux specifically, a graceful Cmd-Q + reopen resumes agent panes on their
  real conversations, so quitting to update does not lose sessions.

## References

- Sparkle sandboxing docs: https://sparkle-project.org/documentation/sandboxing/
- Original quarantine-only fix (incomplete without relaunch):
  https://blog.debedb.com/2026/06/17/cmux-setup/
