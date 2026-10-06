---
name: agent-eval-replay-history-leak
description: |
  Stop a "replay a merged PR from its parent commit" agent eval from leaking the
  answer through git history, and audit transcripts for runs that already read
  it. Use when: (1) you benchmark coding agents, configs or prompts by checking
  out a real PR's parent and asking the agent to redo the change; (2) results
  look too good, or an arm "fails" by reverting work it calls already merged;
  (3) the workspace is a `git worktree`, or a clone with remotes or other
  branches; (4) a task removes a file from the working tree and asks the agent
  to rewrite it; (5) you need to decide whether past replay results are valid.
  Covers why a worktree shares the future (object store, refs, `origin/*`,
  landing branches), why `git show HEAD:path` defeats deleting a file, a
  single-branch clone truncated at the parent as the fix, a transcript audit
  that flags non-ancestor SHAs, task framing that does not invite
  reconstruction, and the headless `claude -p` error shape that looks like an
  answer.
author: Claude Code
version: 1.0.0
date: 2026-10-03
source: https://github.com/voitta-ai/skillz
source_file: skills/agent-eval-replay-history-leak/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/agent-eval-replay-history-leak/SKILL.md`). Updates go through the
> repo's worktree + PR workflow - open an issue, branch, PR.

# Replay evals leak the answer through git history

## Problem

A cheap way to build a coding-agent eval is to replay real work: take a merged
PR, check out its parent commit, hand the agent the PR's task text, and score
the agent's diff against the merged one. It is realistic, the reference answer
already exists, and the repo's own CI gives you a scorer.

It is also leaky by default. The agent works in a git repository, and **checking
history is normal diligence**: `git log --all -- path`, `git show <sha>`,
`git diff origin/master`, a look at a `land/…` branch. If the workspace can
reach any commit after the parent, the agent can and will read the answer. It
is not cheating; it is doing what a careful engineer does.

Measured in one config-ablation study (three agent configurations, replays of
merged PRs, 2-5 repetitions per cell):

- **8 of 12** replay cells read a commit after their parent, across **all three**
  configurations, including one that read the landing branch holding the exact
  answer.
- In a second task that deleted a file and asked the agent to rewrite it,
  **4 of 6** cells either copied the post-review version from a later commit or
  restored the pre-review version with `git show HEAD:path`. The variant
  comparison measured which copy each run found, not the variable under test.
- A headline verdict, "the full configuration hurts correctness" (2/4 vs 4/4
  exact matches), came **entirely** from the leak: one failing run had read the
  merged commit, concluded the work was already done, and reverted itself.
  Re-run in isolated clones, the configurations tied.

## Context / Trigger Conditions

- The eval workspace is a `git worktree` of a working clone. A worktree shares
  the source repository's object store **and** refs, so every branch, tag,
  remote-tracking ref and reflog entry is one command away.
- The workspace is a full clone, or a clone with `origin` still configured, or
  one created with tags: later commits are reachable through `origin/*`, tags,
  or a fetch.
- The task deletes a file "so the agent writes it": the file is still in `HEAD`.
- Replay scores are suspiciously high, or nearly identical across arms that
  should differ.
- A run's final message mentions the upstream being ahead, the change being
  already merged, or the base being stale.

## Solution

### 1. Give each cell a clone truncated at the parent

Only the parent and its ancestors, no remote, one ref. Learning conventions from
*earlier* commits stays possible and is legitimate; the future is gone.

```python
import shutil
import subprocess
from pathlib import Path


def git(cwd, *args, check=True):
    retval = subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True, text=True, check=check,
    )
    return retval


def isolated_checkout(repo, parent, dest):
    """A clone holding only `parent` and its ancestors: no remote, no later refs."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    branch = "isolate-{0}".format(dest.name)
    git(repo, "branch", "-f", branch, parent)          # temp ref in the source
    try:
        subprocess.run(
            ["git", "clone", "-q", "--no-local", "--single-branch", "--no-tags",
             "--branch", branch, str(repo), str(dest)],
            check=True, capture_output=True, text=True,
        )
    finally:
        git(repo, "branch", "-D", branch, check=False)  # never leave it behind
    git(dest, "remote", "remove", "origin")
    git(dest, "branch", "-m", branch, "master")
    git(dest, "reflog", "expire", "--expire=now", "--all")
    retval = dest
    return retval
```

`--no-local` matters: a local-path clone otherwise hardlinks the source's object
directory, and `--single-branch` alone does not stop objects from being present.

### 2. Verify the isolation before running anything

```bash
git -C "$DEST" cat-file -e "$MERGE_SHA^{commit}" && echo "LEAK: merge reachable"
git -C "$DEST" for-each-ref --format='%(refname)'   # expect only refs/heads/master
git -C "$DEST" remote                               # expect nothing
git -C "$DEST" log --all -1 --format=%H             # expect the parent
```

Anything that compares against the merged reference (seed files, expected
versions) must now read from the **source** repo, because the clone no longer
contains the merge commit.

### 3. Frame the task against the real prior state

Do not delete a file and ask for it back: history still holds it, and you are
measuring reconstruction. Replay what actually happened. If review found bugs in
an existing file, the task is "make this file trustworthy before it ships",
with the file present at its pre-review state.

### 4. Audit transcripts, including runs you already scored

For each cell, flag Bash commands that name a SHA which is not an ancestor of
the parent, or that reference `origin/`, `--all`, `--remotes`, or a landing
branch:

```python
import re, subprocess

def future_reads(commands, repo, parent):
    hits = []
    for c in commands:
        if re.search(r"--all\b|--remotes|origin/|land/", c):
            hits.append(c)
        for sha in set(re.findall(r"\b[0-9a-f]{7,40}\b", c)):
            known = subprocess.run(["git", "-C", repo, "cat-file", "-e", sha + "^{commit}"],
                                   capture_output=True).returncode == 0
            if known and subprocess.run(["git", "-C", repo, "merge-base",
                                         "--is-ancestor", sha, parent]).returncode != 0:
                hits.append(c)
    retval = hits
    return retval
```

Run it against the **source** repo, which still knows the future SHAs. Reading
*older* commits is fine and expected; only non-ancestors count. Void and re-run
any cell that hits, and say so wherever the old numbers were reported.

## Verification

- `cat-file -e <merge>` fails in every cell workspace.
- The audit reports zero future reads on the re-run.
- Cells whose behaviour changed after isolation (an arm that "lost" now ties)
  are the ones the leak was driving; report the before/after rather than only
  the new number.

## Notes

- **Headless `claude -p` errors look like answers.** On an API failure (credit
  exhausted, usage cap) the result event can carry `subtype: "success"`,
  `is_error: true`, and the error sentence as `result`, with exit code 0. A
  harness that only checks for a non-empty answer will score the error text.
  Gate every cell on `is_error`.
- A harness that writes its results inside a tracked directory of a repo it also
  watches for side effects will flag itself; exclude its own output paths.
- Tags are a leak too: a release tag on a later commit is reachable unless the
  clone uses `--no-tags`.

## Related

- `git-worktree-convention` — the everyday reason worktrees are the default; this
  skill is the case where a worktree is the wrong tool.
- `metrics-zero-provenance-audit` — the same instinct applied to metrics: audit
  where a number came from before trusting it.
