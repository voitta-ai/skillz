---
name: git-rewrite-does-not-unpublish-orphaned-commits
description: |
  Reach a genuinely clean public repo after sensitive content was already
  pushed, given that rewriting history and force-pushing does NOT remove the
  old commits from the hosting provider. Use when: (1) you rewrote history
  (orphan branch, filter-repo, rebase, amend) and force-pushed, and are about
  to make the repo public or consider the data gone; (2) splitting a repo into
  a public generic half and a private company half after both halves were
  already committed together; (3) a secret, customer name, or internal metric
  was pushed and "removed" in a later commit or by a force-push; (4) `gh repo
  delete` fails with "needs the delete_repo scope" and you need another path.
  Covers the verification call that proves the old blob is still served, why a
  clean `git log` and a clean remote tree are not evidence, rename-plus-recreate
  as a no-extra-scope substitute for deletion, and why a fresh repo id is the
  property that actually matters. Complements pre-open-source-credential-audit,
  which covers the audit BEFORE the first push.
author: Claude Code
version: 1.0.0
date: 2026-09-12
---

# Git rewrite does not unpublish orphaned commits

## Problem

You rewrote history to remove something that should not be public. `git log`
shows one clean commit. The remote's file tree shows only the files you want.
Both are true, and neither means the old content is gone.

A force-push moves a ref. It does not delete objects. The hosting provider
keeps the orphaned commits, and on GitHub they stay retrievable **by SHA**
through the web UI and the API, with no authentication beyond whatever the repo
already requires. Flip that repo public and every orphaned commit becomes
world-readable, including the content you rewrote history to remove.

The SHAs are not secret either. They appear in your own shell history, in CI
logs, in any transcript of the session, and in the force-push's own output.

## The check that settles it

After any rewrite, before concluding anything, ask the provider for the old
commit directly:

```bash
# The SHA is in your reflog, the force-push output, or the session transcript.
gh api repos/OWNER/REPO/commits/<old-sha> --jq '.commit.message'

# And the specific blob:
gh api repos/OWNER/REPO/contents/<path>?ref=<old-sha> --jq '.size'
```

A size back means the content is still served. Observed exactly this after a
force-push that replaced three commits with one orphan commit: the removed file
came back at 6063 bytes, in full, from the rewritten repo.

`git fsck`, `git log --all`, and `git ls-files` all run against your **local**
object store, which the rewrite really did clean. That is why they agree with
you and why they are useless as evidence here. Only a call to the provider
answers the question.

## What actually works

Ranked by how reliably the data ends up gone.

1. **Delete the repo and recreate it.** Destroys the object store, so orphaned
   commits go with it. Needs the `delete_repo` OAuth scope:

   ```bash
   gh auth refresh -h github.com -s delete_repo
   gh repo delete OWNER/REPO --yes
   ```

2. **Rename the dirty repo, create a clean one in its place.** The substitute
   when you cannot or should not delete, and it needs no extra scope:

   ```bash
   gh api -X PATCH repos/OWNER/REPO -f name=REPO-predecessor-private
   cd /path/to/clean/local/repo
   git remote remove origin
   gh repo create OWNER/REPO --public --source=. --remote=origin --push
   ```

   The new repo has a **different repository id**, which is the property that
   matters: a separate object store, so the old SHAs cannot resolve in it.
   Verify that, do not assume it:

   ```bash
   gh api repos/OWNER/REPO --jq .id          # new id
   gh api repos/OWNER/REPO/commits/<old-sha> # expect HTTP 422
   ```

   The renamed repo still holds the data, so it stays private and gets deleted
   by someone with the scope. Leaving it renamed-but-alive is not done.

3. **Contact provider support.** Required if the repo was ever public, was
   forked, or the content is a live credential. Rewriting does not touch forks,
   and cached views can persist. A credential that was ever exposed gets
   rotated regardless of what you do to the repo.

## Order of operations

Do the rewrite locally, verify locally, and only then touch the remote. On the
clean side:

```bash
git checkout --orphan clean
git add -A && git commit -m "..."
git branch -D master && git branch -m master
git bundle create /tmp/backup.bundle --all   # insurance before destroying anything
git bundle verify /tmp/backup.bundle         # "records a complete history"
```

Take the bundle before deleting or renaming the remote. The local repo is the
only copy of the clean history at that moment, and a recreate that goes wrong
with no bundle is unrecoverable.

## Non-obvious specifics

- **A repo rename does not redirect for a repo you then recreate at the old
  name.** Normally GitHub redirects the old name to the new one; creating a
  fresh repo at the vacated name takes precedence, which is what makes the
  substitute work.
- **Collaborators come back on recreate** if they were inherited from the org,
  so the access cost of recreating is usually zero. Check forks, watchers, and
  open issues first, since those do not survive.
- **An unauthenticated 404 is not proof of absence.** A private repo returns
  404 to everyone without access, which looks identical to gone. Check with an
  authenticated call.
- **Splitting a repo is the common trigger.** Generic code goes public, company
  specifics go private, and the split is usually decided after both halves were
  already committed together. At that point the public half needs a new object
  store, not a rewrite.

## Verification

A clean split is done when all four hold:

```bash
gh api repos/OWNER/REPO --jq '"private=\(.private) id=\(.id)"'
gh api repos/OWNER/REPO/commits/<old-sha>                 # HTTP 422
gh api repos/OWNER/REPO/contents/<removed-path>            # HTTP 404
gh api repos/OWNER/REPO/git/trees/master?recursive=1 --jq '.tree[].path'
```

The 422 is the one that matters. A 404 on the path alone would also be
satisfied by a repo that still serves the old commit.
