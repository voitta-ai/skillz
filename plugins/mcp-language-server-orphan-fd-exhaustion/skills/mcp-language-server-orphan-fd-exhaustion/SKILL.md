---
name: mcp-language-server-orphan-fd-exhaustion
description: |
  Diagnose and clear a system-wide file-descriptor exhaustion on a macOS
  workstation caused by orphaned `mcp-language-server` (LSP-to-MCP bridge)
  processes leaking file descriptors until the kernel file table is full.
  The symptom masquerades as whatever tool happens to open a file next -
  "ENFILE: file table overflow" from a CLI, terraform failing, DNS lookups
  timing out - so it reads as that tool's bug, not the machine's. Use when:
  (1) any process on a dev machine dies with `ENFILE: file table overflow`
  or errno 23, (2) unrelated tools start failing at once with open/socket
  errors while the machine otherwise seems fine, (3) `sysctl kern.num_files`
  is within a few percent of `kern.maxfiles`, (4) `ps` shows many
  `mcp-language-server` (or other per-session MCP bridge) processes with
  PPID 1. Verified 2026-08-19: 20 orphaned bridge processes held 255,298
  fds (kern.num_files 275,146 of kern.maxfiles 276,480 - 99.5%); killing
  them dropped usage to 19,885 and the failing tool ran clean.
author: Claude Code
version: 1.0.0
date: 2026-08-27
source: https://github.com/voitta-ai/skillz
source_file: skills/mcp-language-server-orphan-fd-exhaustion/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/mcp-language-server-orphan-fd-exhaustion/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

# Orphaned mcp-language-server processes exhaust the macOS file table

## Problem

Mid-session, a CLI invocation (a Codex review run, in the observed case)
died with:

```
ENFILE: file table overflow
```

Nothing about the failing tool was wrong. `ENFILE` is errno 23 - the
**system-wide** kernel file table is full (unlike `EMFILE`, the per-process
limit, which `ulimit` governs). Once the table is nearly full, *every*
process that next opens a file, socket, or pipe fails: terraform, DNS
resolution, editors, shells. The error surfaces in whichever tool loses the
race first, so it masquerades as that tool's bug and gets debugged in the
wrong place.

The actual cause: `mcp-language-server` - the generic Go LSP-to-MCP bridge
(github.com/isaacphi/mcp-language-server) that agent sessions register
per-project to get LSP for languages their curated LSP set lacks - is
spawned per session, and sessions that end abruptly leave their bridge
running. The orphans reparent to PID 1 and keep accumulating open fds.
Twenty of them were alive on the observed machine, holding a quarter of a
million descriptors between them.

## Diagnosis (three commands)

1. **Is the file table actually full?**

   ```bash
   sysctl kern.num_files kern.maxfiles
   ```

   Observed at failure: `kern.num_files: 275146` / `kern.maxfiles: 276480`
   - 99.5% full. Anything above ~90% explains random `ENFILE`s.

2. **Who holds the descriptors?**

   ```bash
   lsof 2>/dev/null | awk '{print $1}' | sort | uniq -c | sort -rn | head
   ```

   Observed: `mcp-language-server` held **255,298** fds. (`lsof` over a
   full table is slow - minutes, not seconds. Let it run.)

3. **Are they orphans?**

   ```bash
   ps -axo pid,ppid,etime,command | grep -E 'mcp-language-server|terraform-ls' | grep -v grep
   ```

   PPID 1 means the parent (the agent session that spawned the bridge)
   exited without reaping it. Observed: 20 processes, all PPID 1.

Capture the three outputs to a file before killing anything - the evidence
is gone the moment the fix runs.

## Fix

```bash
pkill -9 -f mcp-language-server
pkill -9 -f terraform-ls
```

Both are disposable and respawn on demand the next time a session needs
them (`terraform-ls` is the language server the bridge commonly fronts, and
leaks alongside it). Preconditions worth a five-second check:

- No terraform apply/destroy in flight (killing `terraform-ls` is safe for
  state, but do not yank tooling mid-operation on principle).
- This does not touch editors' own state - IDE-embedded language servers
  are separate processes.

Verify:

```bash
sysctl kern.num_files kern.maxfiles
pgrep -fl mcp-language-server || echo "none left"
```

Observed after the kill: `kern.num_files` dropped from **275,146 to
19,885**. The tool that had died with `ENFILE` ran clean on retry.

## Notes

- **ENFILE vs EMFILE decides the whole diagnosis.** `EMFILE` (per-process)
  points at the failing tool and `ulimit`; `ENFILE` (system-wide) means the
  failing tool is a bystander - go find the hoarder. Raising `ulimit` does
  nothing for `ENFILE`.
- Recurrence is expected as long as sessions keep ending abruptly while a
  per-session bridge is registered. Re-run the diagnosis when random tools
  start failing again; consider a periodic sweep
  (`pgrep -f mcp-language-server` count) if it bites often.
- The same shape applies to any per-session stdio MCP server that opens
  many files (workspace watchers especially) - substitute its process name
  in the commands.

## References

- https://github.com/isaacphi/mcp-language-server - the bridge this was
  observed with.
