---
name: macos-memory-attribution
description: |
  Find what holds macOS swap, compressed and wired memory, then stop it safely. Use when:
  (1) `sysctl vm.swapusage` is near full, `/System/Volumes/VM` holds many 1 GiB swapfileN files, or free disk shrinks in 1 GiB steps;
  (2) top shows several GiB wired or a huge compressor, yet Activity Monitor's biggest entries do not add up;
  (3) hundreds of small helper processes (npm, node, python, MCP servers, language servers) may be piling up;
  (4) you must stop a process tree without ever signalling a reused PID.
author: Claude Code
version: 1.0.0
date: 2026-11-12
source: https://github.com/voitta-ai/skillz
source_file: skills/macos-memory-attribution/SKILL.md
---

# macOS memory attribution

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/macos-memory-attribution/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

## Problem
Swap files, a big compressor and 10 GiB of wired memory are symptoms. `ps -o rss`, Activity Monitor and
top-N lists show the largest processes and miss a herd of small ones, because swapped and compressed pages
are not in RSS. On one 36 GiB Apple Silicon Mac, about 2,000 helper processes of 5 to 50 MiB each held
two thirds of the compressed pool (95 GiB logical) and 59% of the wired memory.

## Trigger conditions
- `vm.swapusage` total is N x 1 GiB and nearly all used; free disk falls in 1 GiB steps.
- `top` header: wired 5+ GiB with no VM or GPU load that explains it, compressor 10+ GiB.
- `ps -ax | wc -l` is over about 1,500.

## Solution
1. **Confirm it is swap and size it.** `sysctl vm.swapusage`; `ls /System/Volumes/VM | wc -l`;
   `diskutil apfs list` (the VM volume's "Capacity Consumed" equals the swap files). Reconcile the free-space
   drop: baseline minus now = swap files + data growth. Check `tmutil listlocalsnapshots /` too: local
   snapshots are the other phantom disk loss. `vm_stat -c 5 2` is count then interval; swapouts 0 means
   swap is static right now.
2. **Attribute compressed memory by family:** `scripts/mem_by_family.sh`. top's CMPRS is the LOGICAL
   (uncompressed) size of a process's compressed plus swapped pages. Its sum should tie to `vm_stat`
   "Pages stored in compressor" x page size (16 KiB on Apple Silicon). Observed: 3% apart on a steady
   system, 15% right after killing many processes. top's G and M are binary: convert before comparing.
   A family with hundreds of members is the answer even when each member is small.
3. **Find the real owner.** Classify by ancestor chain, not `ppid == 1`: children of a daemonised broker are
   not launchd orphans. Print the owner's arguments (`--cwd`, `--endpoint`, workspace) and match them with
   the owner's own records (job counts per workspace matched process sets per broker, 19/18/12/10/8/8
   against 18/18/10/9/8/8).
4. **Wired memory.** `zprint` works without root; its "wired memory" table is by VM tag and
   `VM_KERN_MEMORY_PTE` is page tables. `footprint --sysFootprint <own pid> --noCategories` prints
   `sys_wired`. `scripts/pagetables_by_family.sh` sums the per-process "page table" rows and ties to the
   PTE tag (98% with 2,422 of 2,644 processes readable). Page tables cost about 0.3 MiB for small Go or
   Python processes and 5 to 7 MiB for Node processes (sparse V8 heap), so a few hundred Node helpers
   pin GiB of RAM that can never be swapped. Without root, zone sizes read 0K (the wired remainder is
   zones) and `footprint -a` refuses. A VM's guest RAM is not wired (no large HV or MLOCK tag); kexts
   report 0 wired on Apple Silicon.
5. **Stop it safely.**
   - Idle check: no ESTABLISHED TCP for the workers (`lsof -nP -a -iTCP -sTCP:ESTABLISHED -p <pids>`);
     the owner's job records can be stale (a crashed job stays "running": check its pid and log mtime).
   - If the processes belong to a peer session or person, tell them first; kill only what the user authorizes.
   - `scripts/reap_tree.sh capture '<root ERE>' <file>` BEFORE any shutdown: it records
     pid | root | start time | command for the roots and every descendant.
   - Shut down through the owner's own protocol if it has one, wait about 6 s, `alive`, then
     `signal TERM` (children of a daemon often survive: 30% in one case, 1.4% in another), wait about 8 s,
     `alive`, then `signal KILL <file> 'docker run'` for the rest. `signal` only touches a process whose
     pid, start time and command still match the capture, so a reused PID is never hit.
   - Verify: process count, `vm.swapusage`, swap file count, `df`. Swap files are released without a
     reboot, over minutes (33 files to 10 in about 10 minutes, then 10 to 8 in one more).
6. **VM runtimes (Rancher, Docker Desktop, Lima).** The VM process's footprint equals its configured RAM.
   Before lowering it, check `rdctl shell free -m` (or `docker run --rm alpine free -m`): "available" must stay
   above about 1 GiB at the new size. Containers started by MCP clients (`docker run -i --rm`) pile up
   with the sessions (44 containers used 5 GiB of an 8 GiB guest).

## Verification
- Σ CMPRS per family is within a few percent of the vm_stat figure.
- Σ per-process page tables is within a few percent of the PTE tag.
- After the stop: fewer processes, lower `used` in `vm.swapusage`, fewer swap files, more free disk.

## Example
Before: swap 32.3 of 33.0 GiB in 33 files, free disk 128 GiB, 2,644 processes, load 14.8, wired 9.8 GiB.
After stopping the helper trees of 16 idle workers: swap 7.1 of 8.0 GiB in 8 files, free disk 153 GiB,
1,157 processes, load 5.3, wired 4.9 GiB.

## Notes
- top CMPRS for a hypervisor VM process can exceed its `footprint` (13 GiB against 8.2 GiB seen once): unexplained,
  trust `footprint` for the VM's own total.
- `top` run without root still shows root processes' memory; `footprint` and `vmmap` need the same uid or root.
- `ps -o rss` hides swapped and compressed pages; never use it to size this problem.
- Unreadable (root) processes are missing from `pagetables_by_family.sh`; the script says so in its total line.
- Compression ratio on that machine was about 2 to 1 (95 GiB logical in 14 GiB RAM plus 32 GiB swap).

## References
- Local man pages: footprint(1), zprint(1), vm_stat(1), top(1). Verified on macOS 26 (Darwin 25.6), 2026-11-12.

## Related
- `mcp-language-server-orphan-fd-exhaustion` — the same pile-up of orphaned MCP helper processes on a workstation, when the exhausted resource is file descriptors instead of memory
