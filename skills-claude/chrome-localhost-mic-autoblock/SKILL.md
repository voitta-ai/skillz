---
name: chrome-localhost-mic-autoblock
description: |
  Fix a web app's microphone failing in Chrome with a `not-allowed`
  permission error (Web Speech `SpeechRecognition` / `getUserMedia`)
  even though the OS has granted Chrome mic access and Chrome was
  restarted. Use when: (1) a page on `http://localhost:<port>` (or any
  insecure/dev origin) reports `mic error: not-allowed` /
  `NotAllowedError` and Start/record never starts, (2) macOS System
  Settings -> Privacy & Security -> Microphone already shows the app
  (Google Chrome / Terminal) enabled yet the site still fails, (3) the
  address-bar shows a struck-through mic pill "Microphone not allowed",
  (4) `chrome://settings/content/microphone` lists the origin under
  "Not allowed to use your microphone" tagged "Automatically blocked".
  Root cause: Chrome AUTO-BLOCKS the mic per-site after a dismissed/
  denied prompt or via abusive-notification/insecure-origin protection;
  this site-scoped block is NOT cleared by the OS Privacy toggle or by
  restarting Chrome. Covers the actual fix (set the site to Allow),
  why the OS layer is a red herring, and how to tell the two apart.
author: Claude Code
version: 1.0.0
date: 2026-06-19
source: https://github.com/voitta-ai/skillz
source_file: skills/chrome-localhost-mic-autoblock/SKILL.md
---

# Chrome auto-blocks the mic per-site on localhost (OS toggle does not fix it)

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/chrome-localhost-mic-autoblock/SKILL.md`). Updates go through the
> repo's worktree + PR workflow - open an issue, branch, PR.

## Problem

A browser page that needs the microphone — `navigator.mediaDevices.getUserMedia`
or the Web Speech `SpeechRecognition` API — fails immediately in Chrome with a
`not-allowed` error (`SpeechRecognitionErrorEvent.error === 'not-allowed'`, or
`getUserMedia` rejecting with `NotAllowedError`). Recording/recognition never
starts.

You "fix" the obvious layer and it still fails:

- macOS System Settings -> Privacy & Security -> Microphone already shows
  **Google Chrome** (and Terminal) toggled ON.
- You fully quit and reopen Chrome.

Still `not-allowed`.

## Trigger conditions

- The origin is `http://localhost:<port>` or another dev/insecure origin.
- The address bar shows a **struck-through mic pill** ("Microphone not allowed").
- `chrome://settings/content/microphone` lists the origin under **"Not allowed
  to use your microphone"** with the subtitle **"Automatically blocked"**.

## Root cause

Chrome maintains a **per-site** microphone permission that is independent of the
OS-level app permission. After a dismissed or denied prompt — or proactively, for
insecure origins / its abusive-prompt protection — Chrome moves the site to an
**auto-blocked** state. That site-scoped block:

- is **not** affected by the macOS Privacy & Security mic toggle (that governs
  whether the Chrome process can touch the mic at all, a different layer), and
- **survives** a Chrome restart.

So you can have OS = allowed, Chrome process = allowed, and the specific site =
blocked, all at once. The site block wins.

## Fix

Clear the **site** permission, not the OS one:

1. Open `chrome://settings/content/microphone`.
2. Under **"Not allowed to use your microphone"**, find the origin
   (e.g. `http://localhost:5173`).
3. Click it and set **Microphone = Allow** (or delete the entry to reset to
   "Ask").
4. Reload the page.

Equivalent path: click the site-controls icon to the left of the URL ->
**Microphone -> Allow** -> reload. The struck-through mic pill turns solid and
the app starts listening.

Only if **no** site entry exists is the OS the culprit: System Settings ->
Privacy & Security -> **Microphone** -> enable **Google Chrome**.

## Verify

- The address-bar pill is a solid mic (not struck through).
- `chrome://settings/content/microphone` lists the origin under **"Allowed"**.
- The app's recognition/recording starts (e.g. status flips to "listening").

## Notes

- This is two distinct layers — keep them straight: **OS app permission**
  (Chrome can use the mic) vs **Chrome per-site permission** (this origin can).
  `not-allowed` despite an enabled OS toggle is almost always the site layer.
- For a demo, always have a **paste/type fallback** for the transcript so a mic
  block never stalls you live.
- Same mechanism affects `getUserMedia` and Web Speech alike, since both consult
  the site mic permission.
