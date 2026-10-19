---
name: pre-open-source-credential-audit
description: |
  Audit a git repo BEFORE flipping it public / open-sourcing it. Use when:
  (1) about to run `gh repo edit --visibility public` or otherwise publish a
  previously-private repo; (2) asked to "make sure there are no credentials"
  before release; (3) reviewing whether a config/secret file or an editor backup
  got committed; (4) the tip is clean and you need to know whether the history
  behind it is; (5) deciding whether a non-secret leak (internal names, channel
  and workspace names, env-var names, topology) is worth rewriting history for.
  Covers what actually publishes (tracked files + FULL history + commit
  messages, not just the working tree), the `git grep -E` `\b` false-negative
  that makes a dirty repo look clean, tracked editor-backup files (`*~`, `.bak`,
  `.orig`) that shadow a gitignored secret file, telling real tokens from
  `REPLACE`/`CHANGE_ME` placeholders, the separate non-credential term pass, and
  pricing a history rewrite in dangling SHA citations before recommending one.
author: Claude Code
version: 1.1.0
date: 2026-10-19
source: https://github.com/voitta-ai/skillz
source_file: skills/pre-open-source-credential-audit/SKILL.md
---

# Pre-open-source credential audit

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/pre-open-source-credential-audit/SKILL.md`).

## Problem

Making a private repo public exposes **all of git history**, not just the current
tree. A secret committed once and "removed" in a later commit is still public
forever once the repo is public (and may be cloned/indexed within seconds). A
working-tree-only scan therefore gives false confidence. Two more traps turn a
"looks clean" into a leak: a buggy scan regex that silently matches nothing, and
editor/backup junk files that got tracked alongside the real (gitignored) secret.

## Context / trigger conditions

- Preparing to `gh repo edit <repo> --visibility public` (or GitHub UI "make
  public"), publish, or accept an external clone.
- "Double-check we have no credentials before we open-source this."
- A `*-config.json`, `.env`, `*.pem`, or `*~` backup may have been committed.

## Solution

Run all of these; publishing is gated on every one being clean.

**1. Confirm the real secret files are gitignored AND untracked.** `gitignored`
does not imply `untracked` — a file added before it was ignored stays tracked.
```bash
git ls-files | grep -E '(^|/)(\.env|.*secret.*|.*config\.json|.*\.pem|.*\.key)$' \
  || echo "OK: no secret-looking files tracked"
```

**2. Look for tracked editor/backup junk** — these shadow a gitignored secret and
are the most common real leak. An `x.json~` backup of a gitignored `x.json` is
itself tracked and usually holds the same content:
```bash
git ls-files | grep -E '~$|\.(bak|orig|swp|tmp)$|\.DS_Store$'
```
Remove any hit: `git rm --cached <file>` and add the glob (`*~`) to `.gitignore`.

**3. Scan the working tree for real secret patterns** (token prefixes, private
keys, cloud keys):
```bash
git grep -nE '(xox[bpasd]-|xapp-|sk-ant-|sk-or-|nvapi-|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY)' \
  -- . || echo "OK: none in tree"
```

**4. Scan the ENTIRE history — every blob in every commit, not just HEAD:**
```bash
git rev-list --all --objects | awk '{print $1}' | sort -u \
  | git cat-file --batch 2>/dev/null \
  | grep -aoiE '(xox[bpasd]-[0-9A-Za-z-]+|xapp-[0-9A-Za-z-]+|sk-ant-[0-9A-Za-z-]+|sk-or-[0-9A-Za-z-]+|nvapi-[0-9A-Za-z_-]+|AKIA[0-9A-Z]{16})' \
  | sort -u | grep -viE 'REPLACE|CHANGE_ME|EXAMPLE|PLACEHOLDER|xxxx|0000' \
  || echo "OK: no real-looking tokens in any historical blob"
```
The trailing `grep -vi` drops placeholders so real tokens stand out. Also useful
for one file's history: `git log -p --all -- <path>`.

**5. Scan for non-credential private terms — tree, history, AND commit
messages.** Steps 1-4 are credential-shaped: they match token prefixes. A repo
can pass all four with nothing to rotate and still publish internal names,
workspace and channel names, the env-var names of internal apps, partner or
employer names, and enough of the above to read as topology. Those never match a
token pattern, and they live in commit messages as well as blobs — which none of
the earlier steps read.

Build a term list in a scratch directory, one term per line: workspace names,
channel names, scheduler/job labels, internal app names, partner and employer
and client names, internal hostnames, specific env-var names. Then:

```bash
# every blob in every commit
git grep -i -F -f /path/to/terms.txt $(git rev-list --all) 2>/dev/null
# commit messages, which the blob scan above cannot see
git --no-pager log --all --format='%H%n%B' | grep -i -F -f /path/to/terms.txt
# authors, in case a commit carries an address that should not be public
git --no-pager log --all --format='%an <%ae>' | sort -u
# and what only ever existed in history: paths that are not at the tip
comm -13 <(git ls-files | sort) \
  <(git log --all --pretty=format: --name-only --diff-filter=A | sort -u | grep -v '^$')
```

That last one matters because a file deleted three commits in is invisible to
every tip-based check, and a deleted `config.yaml-example` is exactly the kind of
file that held real names before someone genericized it.

Expect false positives and write down the ones that recur, or the next person
re-investigates them: a short org name is often a substring of an unrelated
identifier (`CommandAction` contains one), and a vendor's own API hostname looks
like an internal host.

**6. Rotate; then price a history rewrite before recommending one.** For any
**real** credential found in tree or history:
  - **Rotate/revoke it first** — assume it is already compromised. Removal is not
    containment.
  - Then **rewrite history** (`git filter-repo --invert-paths --path <f>`, or BFG)
    before publishing, or start a fresh repo with a clean root. Removing it in a
    new commit is NOT enough — it stays in history.
  For an **inert identifier** that is not a credential (e.g. a bare Slack channel
  ID, an internal hostname with no auth value): note it and let the owner decide.
  Rewriting shared history is disruptive; a non-secret usually is not worth it.

"Disruptive" is measurable, and measuring it is what turns the recommendation from
a shrug into a decision. Both rewrite routes — `filter-repo`, or squashing to a
single root commit at flip time — change **every** SHA, so every existing citation
of a commit dangles afterwards. Count them first:

```bash
gh api --paginate 'repos/<owner>/<repo>/issues?state=all&per_page=100' \
  --jq '.[] | select((.body // "") | test("\\b[0-9a-f]{7,8}\\b|/commit/")) | .number'
```

Issue and PR *comments* are not in that count, so it is a floor. Add: every open
PR has to be recreated, and a squash throws away the commit bodies, which in a
repo that writes real PR descriptions into them is most of the written rationale
for the design. Weigh that against what is actually exposed. If the exposure is
names and topology rather than secrets, accepting it is usually right — but say
which specific item would flip the judgement, because there is often exactly one
(a third party's name, read in context, saying something about them rather than
about you), and if that one item is the whole case then squash-at-flip is the
cheap answer and `filter-repo` is not worth its extra steps.

## Verification

- Steps 1-4 all print their `OK:` line (or only placeholder hits).
- Step 5's four scans return nothing but the recurring false positives you
  wrote down, and step 6's count is recorded alongside the recommendation, so
  the owner is choosing against a number rather than against an adjective.
- Run the whole sweep on a fresh `git clone --branch <branch>` in a scratch
  directory, not in the live checkout: the live one has untracked and ignored
  files that are not what publishes, which both hides real hits and invents
  fake ones.
- `git ls-files` shows no secret/backup files.
- Only then: `gh repo edit <owner>/<repo> --visibility public --accept-visibility-change-consequences`
  and confirm with `gh repo view <owner>/<repo> --json visibility -q .visibility`.

## Example

A repo about to be open-sourced had `shmobster-config.json` correctly gitignored
and untracked — but `git ls-files` showed a tracked `shmobster-config.json~`
editor backup (step 2). Its HEAD and full history held only `*-REPLACE`
placeholders (steps 3–4), so no rotation/rewrite was needed; the fix was
`git rm --cached shmobster-config.json~` + `*~` in `.gitignore`. The all-blobs
history scan (step 4) confirmed clean before the public flip.

A second repo, 64 commits, about to be flipped: steps 1-4 came back completely
clean — no token prefix of any kind in any blob in any commit, one author, two
vanished paths and both of them `config.yaml-example` files. Step 5 is the one
that found anything. Across history and commit messages it turned up the env-var
names of two internal apps, a private channel and its webhook variable, a partner
organization named as a data source, a third party's name sitting in a test
fixture that the tip had since genericized, and four commit messages naming an
internal workspace. Nothing to rotate, nothing a scanner would ever flag. Step 6
priced the rewrite at 17 dangling issue and PR citations plus both open PRs
recreated, which is what made "accept it" the recommendation instead of a guess,
and the finding went to a private repo because writing it down anywhere else
would have published the list.

## Notes

- **The `\b` false-negative (most dangerous trap).** `git grep -E` uses POSIX ERE,
  which does **not** support `\b`. A scan like `git grep -E '\b[CU]0[A-Z0-9]{8,}'`
  matches **nothing** and prints clean — a silent false negative that can pass a
  dirty repo. Use `git grep -P` (PCRE) for `\b`, or drop `\b` and widen the
  pattern. Always sanity-check a scan regex against a value you KNOW is present.
- **Placeholders vs. real:** treat `REPLACE`, `CHANGE_ME`, `YOUR_*`, `xxxx`,
  all-zeros as non-secrets; everything else matching a token prefix is real until
  proven otherwise.
- **The finding cannot be filed in the repo being published.** A step-5 write-up is
  a list of the strings being removed, so an issue holding it goes public with the
  repo, which is the leak the audit exists to prevent. File it in a private repo and
  leave a pointer — "there is one further pre-flip decision that cannot be described
  here" — in the public one. Same for the term list itself: it never lands in that
  repo in any form, including a commit message.
- **Check what is neither tracked nor ignored, not just what is tracked.** Step 1
  asks whether secret files are ignored and untracked; the inverse also bites. A
  directory that is untracked **and** unignored (an agent's `.claude/`, a `build/`)
  is one `git add -A` away from being committed, and if it holds session handoffs it
  holds exactly the names step 5 looks for. Add it to `.gitignore` before the flip,
  and prove it: `git check-ignore -v <a real path under it>`.
- **A missing license is a pre-flip item too.** A public repo with no `LICENSE` is
  all-rights-reserved: nobody may use or contribute to it. Pick it before the flip,
  because relicensing stops being unilateral the moment an outside contribution
  lands, and copy the text verbatim from a sibling repo so the wording and the
  copyright line match rather than drifting.
- **GitHub secret scanning / push protection** catches many provider tokens but
  not everything (custom secrets, private-channel IDs, internal hostnames) — it is
  a backstop, not a substitute for this audit.
- Prefer `--data`-free, read-only commands here; none of the scan steps mutate the
  repo, so they are safe to run before deciding anything.
- **Once this audit passes, stop the next one at the source:**
  `prevent-committing-secrets` installs a pre-commit scanner (and a git template
  so new repos get it), which is the gate that makes this audit boring instead of
  urgent.
