---
name: macos-menubar-app-hidden-behind-notch
description: |
  Diagnose and fix a macOS menu bar app (LSUIElement, status item only, no
  Dock icon) that runs fine but whose icon the user cannot see on a notched
  MacBook with a busy menu bar. Use when: (1) the user says "I don't see the
  icon in the menu bar" while the process is up, its ports listen and its log
  is clean, (2) the Mac has a notch and the menu bar is full of third-party
  icons, (3) you need to prove which status items macOS is not drawing
  (CGWindowListCopyWindowInfo, layer 25, kCGWindowIsOnscreen = false; on
  macOS 26 every status item is owned by "Control Center"), (4) osascript
  System Events fails with "osascript is not allowed assistive access
  (-1719)", (5) you are adding entry points that do not depend on menu bar
  space: a window on first launch and applicationShouldHandleReopen:
  hasVisibleWindows: (including adding it to a rumps app's delegate with
  objc.classAddMethods), (6) you need to test a reopen handler next to an
  already-installed copy of the same app.
author: Claude Code
version: 1.0.0
date: 2026-09-30
---

# macOS menu bar app hidden behind the notch

## Problem

macOS does not draw status items that do not fit between the notch and the
right edge of the menu bar. There is no overflow menu, no error and no
callback: the item exists and the app runs, but the icon is not there. A
menu bar-only app (`LSUIElement = true`, no Dock icon, no window at launch)
is then unreachable. The user cannot open its menu, its settings or its
Quit item. The newest status item is usually the one pushed off, because
new items are inserted to the left of the existing third-party ones.

## Context / Trigger Conditions

- The process is up (`pgrep`), its ports listen (`lsof -iTCP -sTCP:LISTEN`)
  and its log shows a clean start, but the user sees no icon.
- A notched MacBook. `system_profiler SPDisplaysDataType` shows a built-in
  Liquid Retina XDR display; a 14" Pro at 3024 x 1964 is 1512 pt wide.
- A crowded menu bar.
- `osascript -e 'tell application "System Events" to tell process "X" to get
  menu bar items of menu bar 2'` fails with
  `osascript is not allowed assistive access. (-1719)`, so the AX route is
  closed unless Accessibility is granted to the terminal.

## Solution

### 1. Prove it (no TCC grant needed)

Window bounds and the on-screen flag are readable without Screen Recording
or Accessibility. Status items are layer-25 windows:

```swift
// status25.swift - run with: swift status25.swift
import CoreGraphics
let list = CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as! [[String: Any]]
var rows: [(Double, Double, Bool, String)] = []
for w in list where (w["kCGWindowLayer"] as? Int) == 25 {
    let b = w["kCGWindowBounds"] as! [String: Any]
    rows.append((b["X"] as! Double, b["Width"] as! Double,
                 (w["kCGWindowIsOnscreen"] as? Bool) ?? false,
                 w["kCGWindowOwnerName"] as? String ?? "?"))
}
for r in rows.sorted(by: { $0.0 < $1.0 }) {
    print(String(format: "x=%5.0f w=%3.0f on=%@  %@", r.0, r.1, r.2 ? "Y" : "N", r.3))
}
```

The items macOS skipped are the ones with `on=N` and an x left of the first
`on=Y` item. Observed on a 14" MacBook Pro running macOS 26.7: visible items
started at x=877, and five items between x=697 and x=843 had `on=N`.

On macOS 26 **every** status item is owned by "Control Center", which hosts
the extras. The owner column therefore cannot tell you which item is yours,
and your own process owns no layer-25 window at all. Attribute by
elimination:
- by width: a title plus an icon is wider than a 32-38 pt plain icon;
- or by counting the `on=N` rows before and after launching the app.

### 2. Unblock the user now

Make room in the menu bar. On macOS 26, open System Settings > Menu Bar >
"Allow in the Menu Bar" and switch off a few apps. Alternatively, quit some
menu bar apps. The hidden items slide into view.

### 3. Fix the app: entry points that do not need menu bar space

- **The first launch opens the main or Settings window.** Detect "first
  launch" from state the app writes on its first run (for example, the config
  file is absent). Check it BEFORE the config is loaded, because loading may
  create the file. Schedule the window to open after the run loop starts.
- **Launching the app again while it runs opens the window.** Finder,
  Spotlight and `open -a` send a reopen Apple event to the running instance.
  AppKit turns that event into `applicationShouldHandleReopen:hasVisibleWindows:`
  on the app delegate. Show the window, then return NO.

rumps' delegate class (`rumps.rumps.NSApp`) does not implement that method.
Add it to the class before `App.run()` creates the delegate and calls
`setDelegate_`, since AppKit may cache which optional delegate methods exist
at that point:

```python
import objc
import rumps.rumps as rumps_impl
from PyObjCTools import AppHelper


def install_entry_points(app, first_run):
    def reopen(_delegate, _sender, _has_visible_windows):
        app.show_settings(None)
        let_appkit_handle = False
        return let_appkit_handle

    objc.classAddMethods(rumps_impl.NSApp, [objc.selector(
        reopen,
        selector=b"applicationShouldHandleReopen:hasVisibleWindows:",
        signature=b"Z@:@Z",
    )])
    if first_run:
        AppHelper.callAfter(app.show_settings, None)  # runs once the loop is up
```

Call it from the `__init__` of your `rumps.App` subclass. A plain PyObjC
app can implement the method directly on its own delegate class.

## Verification

You can test next to an already-installed copy of the app without
touching it.

1. Build the app. Ad-hoc signing is enough for a local launch.
2. Start a **second, isolated instance** with its own state directory and
   its own ports, so it cannot collide with the installed copy:

   ```bash
   open -n --env MYAPP_HOME=/tmp/fresh-home --env MYAPP_PORT=28900 "/path/to/build/My App.app"
   ```

   `open --env` passes environment variables to the launched app.
3. Check the first launch. List the windows of that pid using the same
   CGWindowList call, filtered on `kCGWindowOwnerPID`, layer 0, `on=Y`. You
   should see the settings window.
4. Check the reopen:
   1. Kill the instance and start it again on the same state, which now
      exists.
   2. Confirm there is no on-screen window.
   3. Run `open "/path/to/build/My App.app"` without `-n`. LaunchServices
      routes the reopen to the running instance **at that path**; the
      installed copy in /Applications gets nothing.
   4. You should see the window on the test pid.

**A missing log line proves nothing.** In the worked case, the module's
logger inherited a WARNING root level: `logging.basicConfig(level=WARNING)`,
with only selected child loggers raised to INFO. The new `logger.info` lines
were dropped while the code ran fine. Check the side effect (the window), not
the log.

## Example

Worked case: a Python/rumps menu bar app, installed from a notarized DMG on a
14" MacBook Pro running macOS 26.7. Its ports were up and its log was clean,
but there was no icon. The scan above showed five `on=N` items left of x=877.

Fix: Settings opens on first launch, plus the reopen hook above.

Verified with an isolated `open -n --env` instance:
- The first launch put a 540x682 window on screen.
- A later launch on existing state showed no window until `open <bundle>`,
  which brought Settings up.
- The installed copy next to it got no window.

## Notes

- **Known gap.** Suppose the icon is still hidden and the app is cold-started,
  but it is not the first launch. Nothing appears until the user launches
  the app a second time. On macOS 26, Control Center hosts the item, and it
  is unverified whether the app can detect from inside that its own item is
  not drawn.
- `osascript` with System Events needs Accessibility for the calling
  terminal. CGWindowListCopyWindowInfo does not.
- Users can Cmd-drag visible items to reorder them, but cannot grab a hidden
  one.
