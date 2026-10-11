---
name: git-default-branch-detection
description: |
  Determine a repository's actual default branch (main vs master) in a
  script or tool, without getting it wrong. Use when: (1) writing code that
  needs "the default branch" to diff, log, or compare against
  (`<default>..HEAD`, `origin/<default>`), (2) a tool works on `main` repos
  but silently fails or returns empty on `master` repos (or vice versa),
  (3) you are about to read `git config init.defaultBranch` as the answer,
  (4) a branch-comparison feature behaves correctly in a fresh test repo but
  wrong on real ones. Root cause: `init.defaultBranch` is a preference for
  repos that do not exist yet, not a fact about any existing repo, and
  `origin/HEAD` is often absent on a shallow or never-fetched clone.
author: Claude Code
version: 1.0.0
date: 2026-08-14
source: Building YOLT's policy layer, which compares a branch against its repo's default; init.defaultBranch=main made every master repo look like it had no default branch.
source_file: skills/git-default-branch-detection/SKILL.md
---

# Detecting a repo's default branch (and why `init.defaultBranch` lies)

Canonical source: this file in `voitta-ai/skillz`.

## Problem

Tooling that reasons about "is this a feature branch?" or "what changed
versus the mainline?" needs the repo's default branch. The obvious
fallback chain looks right and is wrong:

```bash
# WRONG
default=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|^origin/||')
default=${default:-$(git config --get init.defaultBranch)}
default=${default:-main}
```

`init.defaultBranch` is the branch name git will use **when it creates a
new repository**. It is a global preference, and it says nothing about any
repo that already exists.

It breaks in both directions, so neither value is the safe one:

- set to `main`, every existing `master` repo reports `main`;
- set to `master`, every `main` repo reports `master`.

Either way the reported name resolves to no ref at all. (The instance that
produced this skill was the second one: a machine configured
`init.defaultBranch=master`, against a repo on `main`.)

The failure is quiet. Downstream you get an empty `main..HEAD` range, a
`rev-parse` that returns nothing, or a comparison that silently succeeds
against a branch that does not exist. In the case that produced this
skill, a policy predicate that should have passed returned "cannot
determine the default branch" for every repo on `master`, and it was
invisible until a synthetic repo was built to reproduce it.

The second trap: `refs/remotes/origin/HEAD` is only populated by `git
clone` (and `git remote set-head`). A repo created with `git init`, one
whose remote was added by hand, or one worked on before the first fetch,
has no `origin/HEAD` at all — so the fallback chain runs more often than
you would expect.

## Solution: treat every source as a *candidate*, and verify it resolves

The fix is one rule: nothing is the answer until a ref for it actually
exists in this repo.

```bash
default_branch() {
  local dir="$1" head c ref

  # 1. The remote's HEAD is authoritative when it is present.
  head=$(git -C "$dir" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null)
  case "$head" in
    origin/*) printf '%s\n' "${head#origin/}"; return 0 ;;
  esac

  # 2. Otherwise: candidates, each verified against a real ref.
  for c in "$(git -C "$dir" config --get init.defaultBranch)" main master; do
    [ -n "$c" ] || continue
    for ref in "refs/remotes/origin/$c" "refs/heads/$c"; do
      if git -C "$dir" rev-parse --verify --quiet "$ref" >/dev/null; then
        printf '%s\n' "$c"
        return 0
      fi
    done
  done

  return 1   # genuinely unknown -- do NOT guess
}
```

Points that matter:

- **`init.defaultBranch` is demoted to a candidate**, tried first because
  it reflects what the user tends to create, but discarded when no such
  ref exists here.
- **Check the remote-tracking ref before the local branch** for each
  candidate. A worktree may not have a local `master` even though
  `origin/master` is the mainline.
- **Use full refnames** (`refs/heads/main`, not `main`) with
  `rev-parse --verify --quiet`. A bare name also matches tags and other
  refs, so `main` as a tag name would produce a false positive.
- **Return failure, not a guess.** For a security- or permission-adjacent
  decision, "I could not determine it" must be distinguishable from
  "it is `main`". Guessing turns an unknown into a confident wrong answer.

## Testing it

A fresh `git init` repo is the worst possible test case: it gets whatever
`init.defaultBranch` says, so the buggy version passes. You have to create
the **mismatch** — a repo whose branch is not the configured default:

```bash
git config --get init.defaultBranch          # whatever yours is, call it $X
git init -b "$OTHER" /tmp/probe              # $OTHER = the one it is NOT
cd /tmp/probe && git commit -q --allow-empty -m init
# buggy version -> "$X" (no such ref); correct version -> "$OTHER"
```

Verified cases for the function above:

| Repo | Result |
| ---- | ------ |
| `-b master`, `init.defaultBranch=master` | `master` |
| `-b main`, `init.defaultBranch=master` (the mismatch) | `main` |
| clone with `origin/HEAD` present | fast path, correct |
| `-b odd`, no main/master anywhere | empty output, exit 1 |

## Related

- `git-worktree-convention` — the sibling-worktree layout, whose
  "is this branch work?" check depends on knowing the default branch.
