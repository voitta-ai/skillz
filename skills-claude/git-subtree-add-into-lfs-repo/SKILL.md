---
name: git-subtree-add-into-lfs-repo
description: |
  Bring a repo into a monorepo with `git subtree add` when the destination
  routes some pattern through Git LFS and the source stored those files as
  plain blobs. Use when: (1) immediately after a subtree add, `git status`
  shows a binary file as modified that nobody touched; (2) `git diff --stat`
  shows that file shrinking to about 130 bytes (`Bin 8879291 -> 132 bytes`),
  which is a pointer, not a truncation; (3) `git lfs ls-files` says
  "Encountered 1 file that should have been a pointer, but wasn't";
  (4) you are about to commit a "renormalize" to make the dirty tree go away;
  (5) you need the fix to keep author, date and message rather than flattening
  the imported history. Root cause: the subtree copies the source tree
  verbatim, raw blob included, while the destination's inherited LFS clean
  filter pointer-izes the working copy - so index and working file can never
  agree. Covers migrating the source before the add, why a renormalize commit
  is the wrong fix, and the one case where you must stop and ask.
author: Claude Code
version: 1.0.0
date: 2026-10-05
source: https://github.com/voitta-ai/skillz
source_file: skills/git-subtree-add-into-lfs-repo/SKILL.md
---

# git subtree add into an LFS-tracked monorepo

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/git-subtree-add-into-lfs-repo/SKILL.md`).

## Problem

The destination monorepo's root `.gitattributes` routes a pattern through Git
LFS:

```
*.mp4 filter=lfs diff=lfs merge=lfs -text
```

The source repo predates that policy and stored those files as ordinary blobs.
`git subtree add` copies the source commit's tree in **verbatim**, raw blob and
all. The destination's LFS clean filter then applies to the *working copy*, so
the file in the index (the raw blob) and the file on disk (a pointer) disagree,
permanently:

```
$ git status
	modified:   <dir>/<file>.mp4        # nobody touched it

$ git diff --stat
 <dir>/<file>.mp4 | Bin 8879291 -> 132 bytes

$ git lfs ls-files
Encountered 1 file that should have been a pointer, but wasn't
```

The 132 bytes is not a corrupted file. That is the size of an LFS pointer.

**The obvious fix is the wrong one.** Committing the difference — a
"renormalize" — makes `git status` clean and leaves the full raw blob in the
destination's history forever, which is the thing the LFS policy existed to
prevent. The tip looks right and the repository is permanently heavier.

## Context / Trigger Conditions

- A `git subtree add` or subtree merge into a repo whose root
  `.gitattributes` has `filter=lfs` for a pattern the incoming files match.
- A binary file shows as modified straight after the add, with no edit.
- `git diff --stat` reports it shrinking to ~130 bytes.
- `git lfs ls-files` reports a file that should have been a pointer.
- You are weighing a renormalize commit, or `--squash`, to clear the dirt.

## Solution

Fix the **source** before it enters the destination, so the imported commits
carry pointers rather than blobs. This preserves history semantically — same
author, same date, same message — while changing SHAs.

1. **Clone the source into a scratch directory.** Work on a throwaway copy; the
   next step rewrites it.

   ```bash
   git clone <source> /tmp/src-migrate && cd /tmp/src-migrate
   ```

2. **Migrate its history to LFS, matching the destination's patterns.**

   ```bash
   git lfs migrate import --include="*.mp4" --everything --yes
   ```

   `--everything` covers all refs, not just the current branch. The `--include`
   patterns must match what the destination's `.gitattributes` routes, or the
   same mismatch arrives in a different file. This also writes a
   `.gitattributes` into the source.

3. **Reset the bad subtree commits out of the destination — only if unpushed.**

   ```bash
   git -C <destination> reset --hard origin/<branch>
   ```

4. **Redo the add from the local migrated clone.** Use the filesystem path, not
   the remote URL: the LFS objects exist only in the scratch clone, and a URL
   would fetch the unmigrated originals.

   ```bash
   git subtree add --prefix=<dir> /tmp/src-migrate <branch>
   ```

5. **Verify before pushing** (see below).

### If the bad subtree was already pushed

Stop and ask. Steps 3-4 rewrite commits that other people may have fetched, and
that decision is not yours to make quietly. Note also that removing the blob
from your branch does not unpublish it — the original objects remain reachable
on the remote until it prunes them, so treat the blob as disclosed if that
mattered. See `git-rewrite-does-not-unpublish-orphaned-commits`.

## Verification

```bash
git status                 # clean - no phantom modification
git lfs ls-files           # lists the file with a '*' => object present locally
```

The `*` is the part worth checking: it means the object is present, not merely
referenced. On push you should see `Uploading LFS objects: 100% (1/1)`. A push
that uploads zero LFS objects while `git lfs ls-files` lists the file means the
pointer landed without its object.

## Example

An 8.9 MB `.mp4` subtree'd into a monorepo whose root `.gitattributes` carried
`*.mp4 filter=lfs`. The add left the file permanently "modified",
`Bin 8879291 -> 132 bytes`. After migrating the source clone with
`git lfs migrate import --include="*.mp4" --everything --yes` and redoing the
add from that clone's local path, the tree was clean and the push reported one
LFS object uploaded.

## Notes

- **The migrate adds a nested `.gitattributes`** under the subtree prefix. It is
  redundant once the root file already routes the pattern, and harmless; leaving
  it costs nothing and keeps the subtree self-describing if it is ever split
  back out.
- **The subtree commit references the migrated SHAs, not the originals.** If
  lineage matters to anyone, say so in the commit message — the content and
  authorship are the same, the identifiers are not.
- **`--squash` does not solve this.** It changes how much history arrives, not
  whether the blob is a blob.
- **Match the patterns, not just the one file that complained.** A source
  carrying several LFS-destined types needs every matching `--include`, or you
  will repeat this for the next extension.
- **A renormalize commit is a one-way door.** Once the raw blob is in the
  destination's history, getting it out is a history rewrite of the
  destination, which is a much larger operation than redoing an unpushed
  subtree add.

## References

- [`git lfs migrate`](https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-migrate.adoc)
  — `import`, `--include`, `--everything`.
- [`git subtree`](https://git-scm.com/docs/git-subtree) — `add --prefix`.
- [Git LFS clean/smudge filters](https://github.com/git-lfs/git-lfs/blob/main/docs/man/git-lfs-clean.adoc)
  — why the working copy and a verbatim-copied index entry diverge.
- `git-rewrite-does-not-unpublish-orphaned-commits` — what a rewrite does and
  does not remove from a remote.
