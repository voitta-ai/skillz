---
name: obsidian-vault-scripted-setup
description: |
  Turn an existing directory (e.g. a whole code/work tree) into an Obsidian
  vault on macOS by script - register it, pre-seed exclusions so build junk
  never shows up, and fold older nested vaults into it. Use when: (1) the user
  used "Create new vault" on a folder and got an EMPTY vault in a new
  subfolder, expecting it to show the parent's contents; (2) you want a
  directory full of git repos as one vault without node_modules, dist,
  build, venv, __pycache__ or *.worktrees noise; (3) an "Excluded files"
  entry like "node_modules/" only hides the top-level folder and nested
  ones still show; (4) you need to add, remove or replace vaults without
  clicking through the vault switcher; (5) an older vault lives inside the
  new one and its link/daily-note settings must carry over. Covers the
  obsidian.json registry, quitting Obsidian before editing it, regex
  userIgnoreFilters, obsidian://open, and merging nested vaults.
author: Claude Code
version: 1.0.0
date: 2026-09-30
---

# Obsidian vault: scripted setup

## Problem

Obsidian's UI makes a common intent awkward: "make this existing directory
my vault, minus the junk". Three things go wrong:

- **"Create new vault" always creates a NEW subfolder** named after the vault
  inside the location you pick. Pointing it at `~/work` with the name
  `work-vault` yields `~/work/work-vault/`, which is empty. Users then ask
  why the vault doesn't show what's in `~/work`. The right action is **"Open
  folder as vault"**.
- **Plain "Excluded files" entries match from the vault root.**
  `node_modules/` hides `./node_modules` but not `repo/web/node_modules`. In
  a tree of repos the nested ones are the ones that matter.
- Exclusions added in the UI after the first open apply only after
  Obsidian has already walked the tree once.

## Context / Trigger Conditions

- An empty vault whose folder sits inside the directory the user meant.
- A tree of many repos (`.git`, `node_modules`, `dist`, `.venv`, worktree
  checkouts) that the user wants as a single vault.
- One or more vaults already registered at sub-paths of the new root.

## Solution

`scripts/obsidian-vault-setup.sh` does steps 2-6. Read it and pass the vault
root, and optionally extra folder names to exclude.

1. **Survey before choosing exclusions.** Count which junk folder names
   actually occur, pruning as you go so it stays fast:

   ```bash
   find "$ROOT" \( -name node_modules -o -name dist -o -name build \
     -o -name target -o -name vendor -o -name bin -o -name venv \
     -o -name __pycache__ -o -name site-packages -o -name coverage \
     -o -name '*.worktrees' -o -name .git \) -type d -prune -print \
     | awk -F/ '{print $NF}' | sort | uniq -c | sort -rn
   ```

   Obsidian already skips dot-folders (`.git`, `.venv`, `.next`, `.idea`,
   `.gradle`, `.terraform`), so they need no rule. Ask the user about
   generated-but-maybe-wanted output, such as a folder of generated
   Markdown, rather than guessing.

2. **Quit Obsidian and back up the registry.** The registry is
   `~/Library/Application Support/obsidian/obsidian.json`:

   ```json
   {"vaults": {"<16 hex chars>": {"path": "/abs/path", "ts": 1790000000000, "open": true}}}
   ```

   Obsidian rewrites this file when it exits, so an edit made while it runs
   can be lost. Quit with `osascript -e 'quit app "Obsidian"'` and wait on
   `pgrep -x Obsidian` before editing.

3. **Re-read the registry right before you edit it**, and print it after.
   The user may have clicked around in the meantime. In the source session
   a stray `<root>/<root-name>` vault from an earlier "Create new vault"
   attempt showed up that hadn't been there a few minutes earlier.

4. **Register the root.** Add an entry with a random 16-hex id
   (`secrets.token_hex(8)`), `ts` in epoch milliseconds, and `"open": true`.
   Remove entries for vaults being replaced. Edit by path, never by id.

5. **Pre-seed `<root>/.obsidian/app.json` before the first open.** Use the
   regex form: an entry wrapped in slashes is a regex tested against the
   vault-relative path. Anchor it to path segments so it matches at any
   depth without hitting substrings:

   ```json
   {
     "userIgnoreFilters": [
       "/(^|\\/)node_modules(\\/|$)/",
       "/(^|\\/)(dist|build|target|out|bin|obj|vendor|coverage)(\\/|$)/",
       "/(^|\\/)(venv|site-packages|__pycache__)(\\/|$)/",
       "/\\.worktrees(\\/|$)/"
     ]
   }
   ```

   Exclude `*.worktrees` folders: they are duplicate checkouts of repos
   already in the vault, so every note would show up twice.

6. **Reopen** with `open "obsidian://open?path=<abs root>"`.

### Folding a nested vault into the new root

If a vault was registered at `<root>/sub`:

1. Back up `<root>/sub/.obsidian` first, then read its `app.json` and
   plugin configs.
2. Copy the link settings into the root's `app.json`: `newLinkFormat`,
   `useMarkdownLinks`, `alwaysUpdateLinks` and `attachmentFolderPath`. The
   existing notes were written under those settings, and keeping them
   means Obsidian won't rewrite links in a different style.
3. **Rebase vault-relative paths.** For example, `daily-notes.json`
   `"folder": "journal"` becomes `"sub/journal"`. The same applies to any
   template or attachment folder that isn't `./`-relative.
4. Remove `<root>/sub` from the registry and delete `<root>/sub/.obsidian`.
   Being a dot-folder, it's invisible to the root vault anyway, but a
   leftover nested vault confuses the next person to open `sub`.
5. Check `.obsidian/plugins/` too. Community plugins don't migrate on
   their own and need to be reinstalled in the root vault.

## Verification

- Print `obsidian.json` after the edit: exactly the intended vaults, each
  path absolute.
- `pgrep -x Obsidian` succeeds after the reopen, and Obsidian has written
  new files such as `core-plugins.json` into `<root>/.obsidian/`. That
  shows it loaded the pre-seeded config and didn't make a fresh vault.
- In the app, the quick switcher (Cmd-O) returns nothing for
  `node_modules` or `package.json` paths under nested repos.

## Notes

- **Exclusions hide; they do not stop indexing.** Excluded files are left
  out of search, the graph and the quick switcher, but Obsidian still
  scans and watches the whole tree. A very large root will still open
  slowly. If that matters, make the vault a narrower folder or symlink in
  only the note-bearing subtrees.
- Always back up the registry. Removing an entry deletes nothing on disk,
  but losing the list means re-adding vaults by hand.
- Nested vaults (a vault inside a vault) do work, but each keeps its own
  `.obsidian` settings. Opening a note from the inner vault inside the
  outer one uses the outer vault's settings and plugins, not the inner
  vault's. Fold them in unless the user wants both.
- macOS-specific paths. On Linux the registry is
  `~/.config/obsidian/obsidian.json`; on Windows it's
  `%APPDATA%\obsidian\obsidian.json`. The quit step differs on each.

## References

- Obsidian forum, "Ignore/exclude completely files or a folder from all
  obsidian indexers and parsers" - the `/node_modules/` regex form, and
  confirmation that excluded files are still indexed internally:
  https://forum.obsidian.md/t/ignore-exclude-completely-files-or-a-folder-from-all-obsidian-indexers-and-parsers/52025
