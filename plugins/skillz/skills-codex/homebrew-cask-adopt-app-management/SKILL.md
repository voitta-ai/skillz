---
name: homebrew-cask-adopt-app-management
description: |
  Update a macOS app that was installed by hand (drag from a DMG) by adopting it
  into a Homebrew cask, and get past the three ways that silently fails. Use when:
  (1) `brew install --cask <app> --adopt` fails with
  `/usr/bin/sudo -E -- chgrp -hR admin /Applications/<App>.app exited with 1`
  and every line says `Operation not permitted` - even after sudo accepted the
  password; (2) `sudo brew ...` is refused with "Running Homebrew as root is
  extremely dangerous and no longer supported"; (3) a retry fails with
  `hdiutil: attach failed - Resource busy` / "Download failed for <cask>";
  (4) an agent's shell fails with `sudo: a terminal is required to read the
  password`; (5) brew output piped through `tail` looks like a clean cleanup run
  but the app version did not change. Root cause of (1) is macOS App Management
  (TCC) protection on the terminal app, not file permissions.
author: Claude Code
version: 1.0.0
date: 2026-09-25
source: session learning
source_file: skills/homebrew-cask-adopt-app-management/SKILL.md
---

# Homebrew cask --adopt vs macOS App Management

> **Canonical source.** https://github.com/voitta-ai/skillz
> (file: `skills/homebrew-cask-adopt-app-management/SKILL.md`).

## Problem

An app in `/Applications` was installed by hand, so Homebrew does not own it and
`brew upgrade` never touches it. `--adopt` is the documented way to take it over
without reinstalling, but the adopt step runs `sudo chgrp -hR admin` over the
existing bundle, and on current macOS that is blocked for any process whose
responsible app lacks **App Management** permission. Root does not help: TCC
attributes the write to the terminal app that launched it, not to the uid.

## Context / Trigger Conditions

- `Error: <cask>: Failure while executing; /usr/bin/sudo -E -- chgrp -hR admin /Applications/<App>.app exited with 1`
  followed by hundreds of `chgrp: ...: Operation not permitted` lines.
- The terminal is a third-party emulator (cmux, Ghostty, iTerm2, an IDE's built-in
  terminal, ...) that was never granted App Management.
- Running from an agent's non-interactive shell fails earlier, at the password
  prompt: `sudo: a terminal is required to read the password`.

## Solution

1. **Check what is installed and who owns it** (read-only):
   ```bash
   defaults read /Applications/<App>.app/Contents/Info.plist CFBundleShortVersionString
   brew list --cask | grep <cask>          # empty = not brew-managed
   brew info --cask <cask> | head -3       # latest version
   ```
2. **Quit the app** first (`osascript -e 'quit app "<App>"'`).
3. **Run the install from a terminal that has App Management.** Apple's
   Terminal.app normally works. An agent can't answer the sudo prompt, so hand the
   user the command:
   ```bash
   brew install --cask <cask> --adopt && open -a <App>
   ```
   If the terminal you want to use lacks it: System Settings > Privacy & Security >
   App Management, enable it, then **quit and relaunch that terminal**. The grant
   does not apply to a running process. If the agent itself runs inside that
   terminal, the relaunch ends the agent session, so prefer another terminal.
4. **Never `sudo brew`.** Homebrew refuses, and root does not bypass TCC anyway.
5. **Alternative without adopt:** drag the old app to the Trash in Finder (Finder
   has the permission), then `brew install --cask <cask>` with no `--adopt`.
   User data under `~/Library/Containers/...` / `~/Library/Application Support/...`
   survives because only the bundle is deleted.

### Retry fails with "Resource busy"

A failed cask run can leave its DMG attached under
`/private/tmp/homebrew-dmg*/`. The next run's `hdiutil attach` of the same cached
DMG then fails with `hdiutil: attach failed - Resource busy`, and brew reports it
as "Download failed". Detach it and retry:
```bash
hdiutil info | grep -E 'image-path|homebrew-dmg'   # find the /dev/diskN
hdiutil detach /dev/diskN || hdiutil detach -force /dev/diskN
```

## Verification

- `CFBundleShortVersionString` shows the new version.
- `brew list --cask` now lists the cask, so future updates go through `brew upgrade`.
- The app starts (for a daemon-style app, poll its CLI until it answers, e.g.
  `docker version --format '{{.Server.Version}}'`).

## Example

Docker Desktop installed by hand at 4.50.0, cask at 4.92.0. From an agent shell:
`sudo: a terminal is required`. From cmux via `! brew ...`: sudo accepted the
password, then every `chgrp` failed `Operation not permitted`. Retried in
Terminal.app: `hdiutil: attach failed - Resource busy` from the first failed run's
leftover mount. After `hdiutil detach` the Terminal.app run adopted cleanly. 4.92.0 is now
brew-managed, and the existing containers restarted on launch.

## Notes

- **Don't pipe brew output through `tail`.** Auto-cleanup (`Removing: ...`) prints
  after the error and can push it out of view. Filter it instead
  (`grep -vE '^Removing|^Pruned'`) or set `HOMEBREW_NO_INSTALL_CLEANUP=1`, and
  always confirm with the version read in step 1.
- `HOMEBREW_NO_AUTO_UPDATE=1` skips the API refresh on retries.
- The tap-trust warning printed on every run is unrelated noise here.

## References

- Homebrew cask `--adopt` option: `brew install --help`
- Apple Platform Security, App Management / TCC:
  https://support.apple.com/guide/security/welcome/web
