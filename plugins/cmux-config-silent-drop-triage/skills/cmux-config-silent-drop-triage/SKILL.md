---
name: cmux-config-silent-drop-triage
description: |
  Find out why a cmux.json entry that passes `cmux config doctor` never shows
  up: a Command Palette action, plus-button item, surface-tab-bar button or
  custom command that is defined, syntactically valid, and simply absent. Use
  when: (1) an `actions` entry vanished from the palette after an edit and
  `cmux config doctor` says OK; (2) `cmux reload-config` and a full restart
  change nothing; (3) the schema validates the file because the section is
  `additionalProperties: true`; (4) the unified log shows nothing from
  `CmuxConfig`; (5) you need the real allowed values of an enum-like key
  (`restart`, action `type`, ...) and the docs page is ahead of or behind the
  installed build. Encodes the order of checks that works: doctor is
  syntax-only, the binary's own `[CmuxConfig]` diagnostics and enum triads are
  in `strings`, and a backup-diff bisect names the edit. Worked example: a
  `workspaceCommand` action hidden by `"restart": "restart"` (valid values are
  `ignore`/`confirm`/`recreate`, or omit).
author: Claude Code
version: 1.1.0
date: 2026-08-26
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-config-silent-drop-triage/SKILL.md
---

# cmux-config-silent-drop-triage

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/cmux-config-silent-drop-triage/SKILL.md`).

## Problem

`~/.config/cmux/cmux.json` has an entry - an `actions` item, a `commands[]`
definition, a tab-bar button - and the UI does not show it. Nothing errors.
`cmux config doctor` prints `OK`. `cmux reload-config` returns `OK Reloaded
config`. Restarting the app changes nothing. The entry worked last week.

The reason this eats an evening: every checker you would normally reach for
answers a different question than the one you are asking.

## Context / trigger conditions

- A Command Palette action, plus-button menu item, or `ui.surfaceTabBar`
  button defined in `actions` is missing.
- `cmux config doctor` / `check` / `validate` (all three are the same command)
  report `JSONC syntax is valid` plus a byte count and the top-level keys.
- Validating against the published schema passes, because `actions` and
  `commands` are `"additionalProperties": true` - the schema rejects nothing
  inside them.
- `log show --predicate 'subsystem == "ai.manaflow.cmux"'` has no
  `CmuxConfig` lines. (It may have unrelated noise, e.g.
  `VaultAgentRegistry: Failed to decode config` every few seconds - that is a
  different subsystem's decoder and does not mean your entry is broken.)

## Solution

Work from cheapest oracle to most expensive. Stop as soon as one names the
edit.

**1. Know what `doctor` is.** It is a JSONC parser, not a validator. It will
approve an action whose `type` is misspelled, a `commandName` that matches no
command, and an enum value that does not exist. Its `OK` rules out one thing
only: a syntax error. Do not spend time re-running it.

**2. Diff the backups, newest to oldest.** If you keep `cmux.json.bak-*` files
(do), diff each consecutive pair. You are looking for the *first* pair whose
diff touches anything other than a string's contents. In the worked example
the only non-string change across five backups was one line:

```diff
-      "restart": "ignore",
+      "restart": "restart",
```

**3. Ask the binary, not the docs.** The rules live in the app, and the docs
URL that `cmux docs settings` prints points at `main`, which need not match
the installed build. Dump strings once and grep:

```bash
strings -a /Applications/cmux.app/Contents/MacOS/cmux > /tmp/cmux.strings
grep -n '\[CmuxConfig\]' /tmp/cmux.strings           # the real diagnostics
```

You will find lines such as:

```
[CmuxConfig] workspaceCommand actions require commandName
[CmuxConfig] %@ '%@' does not match any loaded command
[CmuxConfig] action '%@' ignored because it does not define a runnable action
[CmuxConfig] surfaceTabBarButtons action '%@' hidden because workspace command '%@' is unavailable
```

Each one is a way an entry can be dropped *without* a syntax error. "Does not
match any loaded command" and "workspace command unavailable" are the ones
that bite when the `commands[]` entry itself failed to load.

**4. Read enum values off the binary too.** Swift `Codable` enums land in the
strings table as adjacent short lines. Find one value you know and look at its
neighbours:

```bash
grep -n -B3 -A3 '^recreate' /tmp/cmux.strings
#   ignore
#   confirm
#   recreate
```

That triad is the full set for `restart`. `"restart"` is not in it, so a
command carrying it fails to decode, the `workspaceCommand` action pointing at
it has no loaded command, and the palette entry is hidden - three hops from
the typo, none of them logged.

The web docs, once fetched, agree - but they are JSON-escaped inside the page,
so grep with escaped quotes or you will conclude the page says nothing:

```bash
curl -sL https://cmux.com/docs/configuration \
  | grep -o '\\"restart[A-Za-z]*\\":\\"[^\\]*' | sed 's/\\"//g' | sort -u
# restartConfirm:Ask the user before recreating
# restartIgnore:Switch to the existing workspace
# restartNew:Create a new workspace (default)
# restartRecreate:Close and recreate without asking
```

**5. Fix and reload.** Correct the value (or delete the key for the default),
then `cmux reload-config`. No restart is needed; the entry is back on the next
palette open.

## Verification

- The entry appears in the palette / menu it belongs to.
- If the config has a second entry of the same shape that never broke (a
  second `workspaceCommand`), it is the control: same type, same wiring, one
  field different. Compare against it before anything else.
- The backups diff clean against the last known-good file except for the one
  intended change.

## Example

Symptom: "Open Claude Teams" gone from the palette; "Open OMX" (same action
type) still there. Doctor OK, log silent, restart useless. Backup diff: the
"Claude Teams" command gained `"restart": "restart"` at 18:44. Binary strings:
`ignore`/`confirm`/`recreate`. Deleting the line and reloading restored the
entry; the second invocation now opens a second workspace, which was the
intent behind the edit (omit `restart` = always create a new workspace).

## Notes

- `restart` is about **name collisions**, not process restarts: it controls
  what happens when a workspace with that `name` already exists. Omit it to
  run several instances of the same command at once.
- `additionalProperties: true` in the schema is a statement about the
  schema's coverage, not about what the app accepts. Treat the schema as a
  hint and the binary as the contract.
- The same `strings` dump answers "does this build support key X at all?" -
  grep the key name. If it is absent, the docs are ahead of your build.
- Keep dated backups on every config edit; the bisect in step 2 is the
  fastest oracle you have and it only exists if you made them.

## References

- cmux configuration docs: https://cmux.com/docs/configuration
- cmux schema (tracks `main`):
  https://raw.githubusercontent.com/manaflow-ai/cmux/main/web/data/cmux.schema.json

## Related

- `cmux-agent-tabs` — what the actions and surface buttons in this config are
  *for*: getting an agent onto a tab. A palette entry that silently drops is
  one reason the tab never appears, and doctor will call the file fine.
- `cmux-autoresume-after-reboot` — the other place `restart` reads as a process
  word and is not one. Here it governs workspace-name collisions
  (`ignore`/`confirm`/`recreate`); there the question is which panes come back
  as live agents.
- `cmux-session-restore-forensics` — when the config is right and the workspace
  still is not what you expect, the next question is what happened to the
  session rather than what the file says.
