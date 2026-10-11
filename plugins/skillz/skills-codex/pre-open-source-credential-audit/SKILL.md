---
name: pre-open-source-credential-audit
description: |
  Audit a git repo for leaked secrets BEFORE flipping it public / open-sourcing
  it. Use when: (1) about to run `gh repo edit --visibility public` or otherwise
  publish a previously-private repo; (2) asked to "make sure there are no
  credentials" before release; (3) reviewing whether a config/secret file or an
  editor backup got committed. Covers what actually publishes (tracked files +
  FULL history, not just the working tree), the `git grep -E` `\b` false-negative
  that makes a dirty repo look clean, tracked editor-backup files (`*~`, `.bak`,
  `.orig`) that shadow a gitignored secret file, telling real tokens from
  `REPLACE`/`CHANGE_ME` placeholders, and the decision to rewrite history +
  rotate vs. accept an inert identifier.
---

# Pre-open-source credential audit

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

**5. Rotate, then decide on history.** For any **real** credential found in tree
or history:
  - **Rotate/revoke it first** — assume it is already compromised. Removal is not
    containment.
  - Then **rewrite history** (`git filter-repo --invert-paths --path <f>`, or BFG)
    before publishing, or start a fresh repo with a clean root. Removing it in a
    new commit is NOT enough — it stays in history.
  For an **inert identifier** that is not a credential (e.g. a bare Slack channel
  ID, an internal hostname with no auth value): note it and let the owner decide.
  Rewriting shared history is disruptive; a non-secret usually is not worth it.

## Verification

- Steps 1–4 all print their `OK:` line (or only placeholder hits).
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

## Notes

- **The `\b` false-negative (most dangerous trap).** `git grep -E` uses POSIX ERE,
  which does **not** support `\b`. A scan like `git grep -E '\b[CU]0[A-Z0-9]{8,}'`
  matches **nothing** and prints clean — a silent false negative that can pass a
  dirty repo. Use `git grep -P` (PCRE) for `\b`, or drop `\b` and widen the
  pattern. Always sanity-check a scan regex against a value you KNOW is present.
- **Placeholders vs. real:** treat `REPLACE`, `CHANGE_ME`, `YOUR_*`, `xxxx`,
  all-zeros as non-secrets; everything else matching a token prefix is real until
  proven otherwise.
- **GitHub secret scanning / push protection** catches many provider tokens but
  not everything (custom secrets, private-channel IDs, internal hostnames) — it is
  a backstop, not a substitute for this audit.
- Prefer `--data`-free, read-only commands here; none of the scan steps mutate the
  repo, so they are safe to run before deciding anything.
- **Once this audit passes, stop the next one at the source:**
  `prevent-committing-secrets` installs a pre-commit scanner (and a git template
  so new repos get it), which is the gate that makes this audit boring instead of
  urgent.
