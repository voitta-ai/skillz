---
name: gist-to-repo-migration
description: |
  Migrate a multi-file GitHub gist into a regular GitHub repo while
  preserving the full gist revision history as commits on the repo's
  default branch, then convert the gist into a redirect. Use when:
  (1) a gist has outgrown gist tooling (no branches, no issues, no
  PRs, no review threads, no fine-grained permissions),
  (2) you want each gist revision to land as its own commit on the
  repo's history, (3) you need a single canonical source going
  forward and want the gist to stay as a discoverable redirect,
  (4) the target repo already has a placeholder/asdf commit you
  want to preserve as the root. Covers: gist-is-git, fetching gist
  history as a remote, rebase --root --onto master with -X theirs
  for the "asdf vs gist root" conflict, gh gist edit --remove for
  file pruning, frontmatter `source:` field rewrite, and the
  redirect-README pattern that points users at the new repo.
author: Claude Code
version: 1.2.0
date: 2026-05-14
---

# Gist → repo migration preserving full revision history

## Problem

A gist that started as a quick share has accumulated meaningful
revisions and now needs the things gists do not have: issues, PRs,
review threads, branches, fork discovery. The naive migration
(copy the latest file content into a repo) throws away the entire
revision graph. The right migration imports every gist revision as
its own commit on the repo's default branch and converts the gist
into a redirect that points discoverers at the new home.

Two subtleties make this non-trivial:

1. A gist is already a git repository — you can `git clone` it —
   but the user almost never knows that. Every "revision" in the
   gist UI is already a commit, with author, date, and tree state,
   waiting to be reused.
2. The destination repo usually has either nothing (default
   branch = unborn) or a placeholder commit (e.g. `asdf`). The
   first gist commit creates files including `README.md`; the
   placeholder commit also has a `README.md`. Naive cherry-pick or
   merge conflicts on `README.md`. The fix is `git rebase --root
   --onto <placeholder> -X theirs` which resolves every same-path
   conflict in favor of the incoming gist commit.

## Context / Trigger Conditions

- User asks to "move this gist to a repo" / "convert gist to repo"
  / "this gist is getting unwieldy".
- Gist has more than ~5 meaningful revisions worth keeping.
- Destination repo already exists (empty or has placeholder).
- The migration must preserve per-revision authorship and dates.
- The gist will continue to receive traffic; it must redirect to
  the new repo so old install one-liners do not silently break.

## Solution

### 1. Clone the gist as git

```bash
git clone https://gist.github.com/<owner>/<gist-id>.git /tmp/gist-clone
cd /tmp/gist-clone
git --no-pager log --pretty=format:'%h %ai %s' | head -20
```

This shows the full revision graph. Commit subjects from the gist
web UI are typically empty — that is faithful, do not synthesize.

### 2. Add gist as remote to destination repo

```bash
cd <destination-repo>
git remote add gist /tmp/gist-clone
git fetch gist
git branch gist-history gist/master
```

### 3. Rebase gist history onto the placeholder commit

```bash
git rebase --root --onto master -X theirs gist-history
```

- `--root` rebases starting from the very first commit on
  `gist-history` (no upstream).
- `--onto master` reparents that root commit onto the current
  `master` HEAD (the placeholder).
- `-X theirs` auto-resolves any file conflict in favor of the
  commit being applied (the incoming gist commit). This is what
  handles the `README.md` collision between the placeholder and
  the first gist commit.

If you would rather drop the placeholder entirely, do
`git rebase --root gist-history` (no `--onto`) instead, and later
reset master to `gist-history`.

### 4. Fast-forward master and force-push

```bash
git checkout master
git merge --ff-only gist-history
git push -u origin master --force-with-lease
```

`--force-with-lease` is safer than `--force` when the remote may
have moved.

### 5. Reorganize layout in a follow-up PR

The gist-flat layout (`SKILL_<name>.md` at root) usually mirrors
gist conventions, but the destination repo wants per-folder layout
(e.g. `skills/<name>/SKILL.md`). Do this in a feature branch +
PR, not on master, so the migration commit graph stays clean.

```bash
# Absolute path: a relative one resolves against the cwd and would nest
# the worktree inside the repo. See `git-worktree-convention`.
git worktree add -b feature/reorg-per-folder \
  /path/to/repo.worktrees/feature/reorg-per-folder origin/master
cd /path/to/repo.worktrees/feature/reorg-per-folder
git mv SKILL_work-on-pr.md skills/work-on-pr/SKILL.md
git mv SKILL_review-pr-loop.md skills/review-pr-loop/SKILL.md
# update install.sh paths, README, frontmatter `source:` fields
```

Each SKILL.md's frontmatter `source:` field must be rewritten from
the gist URL to the repo URL, and the canonical-source banner inside
the file must be updated. Bump `version:` so installed copies can
detect drift.

### 6. Convert the gist to a redirect

```bash
cat > /tmp/redirect.md <<'EOF'
# Moved to https://github.com/<owner>/<repo>

These files now live in a regular repo:
- <repo-url>

## Install

bash <(curl -sL https://raw.githubusercontent.com/<owner>/<repo>/master/install.sh)
EOF

gh gist edit <gist-id> -f README.md /tmp/redirect.md
gh gist edit <gist-id> --remove SKILL_work-on-pr.md
gh gist edit <gist-id> --remove SKILL_review-pr-loop.md
gh gist edit <gist-id> --remove install.sh
```

`gh gist edit --remove` deletes a file from the gist. It is not
prominent in `gh --help`; you have to know it exists.

### 7. Update any installer / fetcher to point at the repo

If the gist had an `install.sh` with a hard-coded raw gist URL,
change it to `https://raw.githubusercontent.com/<owner>/<repo>/master`.
Keep the old env var name (`GIST_RAW_BASE`) as a deprecated alias
for one release so existing scripts keep working.

### 8. Save institutional memory

- Add a reference memory: "skills come from <repo>, not the gist."
- Update `~/.claude/CLAUDE.md` or equivalent global config to point
  at the new repo.
- The gist URL stays valid as a redirect — do not delete the gist
  unless you also delete every reference to it.

## Verification

- `gh api gists/<gist-id> --jq '.history | length'` matches the
  commit count you imported (placeholder + gist-history commits).
- `git --no-pager log master --oneline | wc -l` =
  1 (placeholder) + N (gist commits) + M (post-migration commits).
- `git --no-pager log --format='%an %ai' master | tail -<N>` shows
  the original gist authors / dates, not the date of the migration
  run.
- `gh gist view <gist-id> --files` shows only the redirect README.
- The install one-liner from the redirect actually fetches files
  from the new repo (verify with `--dry-run` if the installer
  supports it).

## Example

Starting point:
- Gist `5f606018eb36a75dc292016268f08e7c` with 13 revisions and
  four files: `README.md`, `install.sh`, `SKILL_work-on-pr.md`,
  `SKILL_review-pr-loop.md`.
- Repo `debedb/skillz` exists with one placeholder commit
  `asdf` and a 7-byte `README.md`.

Execution:

```bash
# 1-3: import history
git clone https://gist.github.com/5f606018eb36a75dc292016268f08e7c.git /tmp/gist-clone
cd ~/g/git.debedb/skillz
git remote add gist /tmp/gist-clone
git fetch gist
git branch gist-history gist/master
git rebase --root --onto master -X theirs gist-history
git checkout master
git merge --ff-only gist-history
git push -u origin master --force-with-lease

# 5: reorganize via PR (worktree + feature branch + gh pr create)
# ...

# 6: convert gist
gh gist edit 5f606018eb36a75dc292016268f08e7c -f README.md /tmp/redirect.md
gh gist edit 5f606018eb36a75dc292016268f08e7c --remove SKILL_work-on-pr.md
gh gist edit 5f606018eb36a75dc292016268f08e7c --remove SKILL_review-pr-loop.md
gh gist edit 5f606018eb36a75dc292016268f08e7c --remove install.sh
```

Result:
- Repo master = 14 commits (1 placeholder + 13 gist revisions),
  authors and dates preserved.
- Gist = single `README.md` pointing at the repo.

## Notes

- **Gist IS git.** You do not need any GitHub API to read its
  history; `git clone https://gist.github.com/<owner>/<id>.git`
  works exactly like any other clone. The history is the gist's
  revision graph.
- **`-X theirs` direction.** During rebase, "theirs" means the
  commit currently being applied, not the branch you started on.
  This is the opposite of merge semantics where "theirs" is the
  incoming branch. The result is the same: file content from the
  gist wins over the placeholder.
- **Empty commit subjects.** Gist revisions have no commit
  messages. After rebase, `git log --oneline` shows only SHAs.
  Resist the urge to synthesize subjects — that loses the
  one-to-one correspondence with the gist UI revision list. Add
  context in a post-migration commit or in the README instead.
- **`gh gist edit` may split a single edit into multiple gist
  revisions.** Each call increments the revision counter; do not
  panic if a single `gh gist edit -f X file` registers as two
  revisions in the web UI — content is correct.
- **Symlink gotcha.** If you also need to update a CLAUDE.md /
  AGENTS.md to point at the new repo and the file is a symlink
  (common for `~/.claude/CLAUDE.md` → `~/g/svalka/llm/base-prompt.md`),
  Claude Code's Write tool will refuse with:
  `Refusing to write through symlink: ... Resolve the symlink and
  pass the real target path explicitly.` Run `readlink <path>` and
  edit the target instead.
- **Force-push to a default branch.** `--force-with-lease` is
  preferable but still destroys remote history. Confirm the
  destination really has only the placeholder commit before
  running it. If anyone else has cloned the repo, coordinate
  before the migration.
- **Keep the gist alive.** Old `curl https://gist.../raw/install.sh`
  invocations are everywhere — bookmarks, docs, scripts. Leaving
  the gist as a redirect is much friendlier than 404ing.

## References

- [GitHub: how gist URLs and clones work](https://docs.github.com/en/get-started/writing-on-github/editing-and-sharing-content-with-gists)
- [git rebase --onto / --root](https://git-scm.com/docs/git-rebase)
- [git merge strategy options `-X ours` / `-X theirs`](https://git-scm.com/docs/merge-strategies#Documentation/merge-strategies.txt-ours)
- [gh gist subcommands](https://cli.github.com/manual/gh_gist)
- Related, both in the sibling `skillz-memory` repo rather than this
  catalog: `claude-code-static-allow-bypasses-hook` (relevant if the
  migrated artifact triggers shell-permission prompts) and
  `gh-git-heredoc-body-file` (for the redirect-README + PR body
  authoring step).
