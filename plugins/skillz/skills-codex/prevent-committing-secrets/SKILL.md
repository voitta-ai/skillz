---
name: prevent-committing-secrets
description: |
  Block a credential at commit time with a pre-commit secret scanner, and make
  new repos get one without anyone remembering to ask. Use when: (1) running
  `git init` or cloning a repo you will commit to; (2) about to commit in a repo
  that has no scanner installed; (3) asked to "make sure we never commit a key";
  (4) a commit was just blocked and someone reaches for `--no-verify`. Covers
  gitleaks via the pre-commit framework and as a raw hook, `init.templateDir` so
  new and cloned repos are covered automatically, the six paths that skip the hook
  (`--no-verify`, clean merges, replayed commits, `core.hooksPath`, in-repo config
  files, a missing exec bit), where the default ruleset is blind, why a
  staged-diff scan says nothing about history, GitHub push protection and CI as
  the halves that cannot be bypassed locally, and what to do when it fires.
author: Claude Code
version: 1.0.0
date: 2026-08-15
---

# Prevent committing secrets

## Problem

A repo starts with no secret scanning and stays that way. `.git/hooks/` ships
only `*.sample` files, hooks are never cloned and never versioned, so every repo
and every fresh clone is unguarded until someone acts per-repo.

Commit time is the last cheap moment. After a push, deleting the line is not
containment — the blob is in history, in every clone, and possibly already
indexed; the only real fix is rotation. Keys have sat in private repos for a year
this way, not because a review missed them, but because nothing was checking.

## Check before you commit

A hook file is not the question — a hook that *scans* is. Most repos with a
`pre-commit` hook have a formatter, a husky shim, or pre-commit's own
skip-on-missing-config stub, all of which are executable and exit 0:

```bash
hooks="$(git rev-parse --git-path hooks)"       # honors core.hooksPath
grep -qsE 'gitleaks|trufflehog|detect-secrets|git-secrets' \
     "$hooks/pre-commit" .pre-commit-config.yaml \
  || echo "no secret scanning here, whatever else that hook does"
```

Either way, scan what is about to be committed — this needs no hook and no
config:

```bash
command -v gitleaks >/dev/null || echo "no scanner: install it or do not commit"
gitleaks git --pre-commit --redact --staged --verbose
```

`--redact` matters: without it the finding prints the secret, which puts it in
the terminal, the CI log, and the agent transcript. See
`secrets-in-agent-sessions`.

`--staged` also means untracked files are not looked at, so a `credentials.json`
you were never going to commit anyway stays invisible. If anything env-shaped is
sitting in the tree, check it and your `.gitignore` before it gets staged by a
future `git add -A`:

```bash
git status --porcelain --untracked-files=all \
  | grep -iE '\.(env|pem|p12|key)|id_rsa|kubeconfig|credentials'
```

## Install: repo-local

**With the pre-commit framework** (reproducible, versioned, reviewable):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - id: gitleaks
```

```bash
pre-commit install
pre-commit install --hook-type pre-merge-commit     # see "does not cover", 2
```

Committing the config protects nobody until each clone runs `pre-commit install`
— it is inert on its own. A repo can carry a beautiful config with zero
contributors scanning anything, which is why the CI job below is the copy that
actually enforces.

The three hook ids differ in where the scanner comes from, which decides whether
`rev` means anything:

- `gitleaks` — `language: golang`, builds the pinned revision from source, so
  the pin is real. Needs Go (pre-commit can fetch a toolchain itself). Default
  choice.
- `gitleaks-system` — runs whatever `gitleaks` is on `PATH`
  (`brew install gitleaks`). `rev` then pins only the hook definition, not the
  scanner: two machines can share a config and run different rulesets. It also
  ships **without** `pass_filenames: false` (the other two set it), so
  pre-commit appends staged filenames to a subcommand that takes at most one
  positional argument. Add the override yourself if you use this id:
  ```yaml
      - id: gitleaks-system
        pass_filenames: false
  ```
- `gitleaks-docker` — needs neither, but does need a running Docker daemon,
  which is the usual reason this id fails in CI.

**Raw hook**, for a repo not using the framework:

```bash
hooks="$(git rev-parse --git-path hooks)"
cat > "$hooks/pre-commit" <<'SH'
#!/bin/sh
exec gitleaks git --pre-commit --redact --staged --verbose
SH
chmod +x "$hooks/pre-commit"
```

The older spelling `gitleaks protect --staged` still runs but the subcommand is
hidden and deprecated; `gitleaks git --staged` replaced it. Check
`gitleaks version` before copying a snippet found online.

That hook **fails closed** on a missing binary: `exec` exits 127 and git aborts
the commit. Correct, but the message a colleague sees is `gitleaks: not found`
and the tempting fix is to delete the hook. Install gitleaks instead.

It **fails open** on a missing mode bit. A `pre-commit` file without `+x` is
skipped and the commit succeeds — verified: exit 0, commit created, no error
anyone reads. Checkouts onto a mode-dropping filesystem, an editor rewriting the
file, a tight umask all produce it, so assert `[ -x ]` rather than assuming the
file's presence means anything.

## Install: every future repo, automatically

Hooks are per-repo, so the leverage is in the template git copies into each new
`.git/`. With the framework, one command does it:

```bash
pre-commit init-templatedir ~/.git-template -t pre-commit -t pre-merge-commit
git config --global init.templateDir ~/.git-template
```

Pass both hook types. `init-templatedir` defaults to `pre-commit` only, so
without `-t` every repo you ever create carries exactly the merge-commit gap
described below. It installs with skip-on-missing-config, so repos cloned without
a `.pre-commit-config.yaml` are not broken by the template hook, and it warns if
`init.templateDir` does not point at the directory you just populated. Without
the framework, write the hooks in yourself:

```bash
mkdir -p ~/.git-template/hooks
for h in pre-commit pre-merge-commit; do
  cat > ~/.git-template/hooks/$h <<'SH'
#!/bin/sh
exec gitleaks git --pre-commit --redact --staged --verbose
SH
  chmod +x ~/.git-template/hooks/$h
done
[ -x ~/.git-template/hooks/pre-commit ] \
  && git config --global init.templateDir ~/.git-template
```

Gate the `git config` on the hook actually being there. Setting
`init.templateDir` at a directory that has no hooks is worse than not setting it:
every future repo gets an empty `.git/hooks/` (the template replaces git's
defaults), no scanner, and nothing says so.

Write the hook, do not copy one out of an existing repo: if that repo uses the
framework, `.git/hooks/pre-commit` is pre-commit's shim, which exits 1 when no
`.pre-commit-config.yaml` is present — as a template that blocks every commit in
every new repo.

The raw version also has no skip-on-missing tolerance of its own: every repo
created afterwards blocks every commit on a machine where gitleaks is missing.
Right default for a secret gate, but decide it deliberately.

`git init` **and** `git clone` copy the template's hooks into the new repo, so
this is the answer to "install a scanner whenever a repo is created". Existing
repos are not retro-fitted automatically, but re-running init in one is safe and
does the job — verified: it copies template files that are absent and leaves an
existing `pre-commit` untouched.

```bash
git init .          # in an existing repo: adds the hook, overwrites nothing
```

## What the hook does not cover

1. **`--no-verify`** — bypass by design, for `git commit` and `git merge` alike.
   A local hook is advisory. This is the reason for push protection below.
2. **Merge commits git completes on its own.** Those fire `pre-merge-commit`,
   not `pre-commit`, and a default `pre-commit install` covers only the latter.
   A merge that hits a conflict is fine — you resolve and run `git commit`, which
   does fire `pre-commit` (githooks(5) says so, and `merge --squash` behaves the
   same way). So the gap is exactly the clean automatic merges, which is most of
   them.
3. **Commits git creates by replay** — rebase, cherry-pick, `git commit-tree`,
   and anything writing objects directly. Only `git commit` runs `pre-commit`.
4. **`core.hooksPath` is set.** Then `.git/hooks/` is ignored entirely and a hook
   written there never runs; the framework refuses outright —
   `Cowardly refusing to install hooks with core.hooksPath set` (fix:
   `git config --unset-all core.hooksPath`, or put the hook in the configured
   directory). `git rev-parse --git-path hooks` (used above) resolves to the real
   directory, so use it rather than hardcoding `.git/hooks` — note it answers
   relative to your current directory, so re-derive it after a `cd`.
5. **Files in the repo that turn the scanner off**, no `--no-verify` needed: a
   trailing `# gitleaks:allow` comment (honored by default —
   `--ignore-gitleaks-allow` is opt-in), a `.gitleaksignore` listing
   fingerprints, and a `.gitleaks.toml` (see below — one that forgets
   `[extend] useDefault = true` disables every rule). Each is a normal file, so
   one merged PR silently disables scanning on every developer's machine. Treat
   changes to those three as security review, or pin the hook with
   `--config <trusted-path> --ignore-gitleaks-allow`.
6. **A hook without the executable bit** — silently skipped, commit succeeds.

And the one that gives false confidence: **the hook only sees the staged diff.**
It says nothing about what is already in the repo. Installing it is not evidence
the repo is clean, so scan the history once, at install time:

```bash
gitleaks git --redact .          # full history
gitleaks dir  --redact .         # working tree, including untracked
```

A clean scan is also not proof, and it is worth knowing exactly how much it is
not. gitleaks v8.30.1 ships 222 rules: 221 match a provider's shape, and the
lone general one, `generic-api-key`, needs a keyword (`key`, `token`, `secret`,
`password`, …) within ~29 characters *before* the value **and** entropy strictly
above 3.5. No rule fires on entropy alone. So a credential in a field named
`"k"`, or an internal token format with no recognizable prefix, passes the hook
and GitHub's push protection both.

Two more default blind spots, from the config's global allowlist and flag
defaults:

- **Paths that are never scanned**: `node_modules/`, `vendor/…`, and the lock
  files (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `Pipfile.lock`),
  plus binaries and documents (`*.pdf`, `*.docx`, `*.exe`, `*.dll`). An npm
  registry token in a lockfile is invisible by design.
- **Archives are not opened**: `--max-archive-depth` defaults to 0, so a secret
  inside a committed `.jar` or `.zip` is not scanned.

Treat the scanners as catching known shapes in ordinary text files, not as an
oracle.

For the deeper version of that audit — history rewrites, placeholders vs. real
values, the `git grep -E` `\b` false negative — see
`pre-open-source-credential-audit`.

## The half that cannot be bypassed locally: push protection

```bash
gh api repos/$ORG/$REPO --jq .security_and_analysis
```

Do not assume it is on because the repo is public; check. `null` means your token
cannot see the setting (it is admin-visible only), which is not the same as
disabled. Enable per repo — set both, since push protection without scanning
protects nothing:

```bash
gh api -X PATCH repos/$ORG/$REPO --input - <<'JSON'
{"security_and_analysis":{"secret_scanning":{"status":"enabled"},
 "secret_scanning_push_protection":{"status":"enabled"},
 "secret_scanning_non_provider_patterns":{"status":"enabled"}}}
JSON
```

`secret_scanning_non_provider_patterns` defaults to disabled and is the one that
looks for the shapeless things — the exact gap named above. Turn it on.

Org-wide, GitHub now does this with a code security configuration rather than
per-repo toggles. Listing configurations tells you nothing on its own: a
configuration can say `enabled` while being attached to zero repositories, so
check the attachment, not the definition:

```bash
id=$(gh api orgs/$ORG/code-security/configurations \
       --jq '.[] | select(.secret_scanning_push_protection=="enabled") | .id' | head -1)
gh api "orgs/$ORG/code-security/configurations/$id/repositories" \
  --jq '.[] | [.status, .repository.name] | @tsv'      # empty = protecting nothing
```

That is not hypothetical: on the org holding this skill, the "GitHub recommended"
configuration reads `enabled` and is attached to no repositories at all, while
the repo itself reports secret scanning `disabled`. An agent that stops at the
listing reports the org protected.

Push protection blocks the push server-side; a bypass takes an explicit reason
and is recorded. Local hook = fast feedback for the person committing; server
side = the actual gate. Ship both.

**Check that you can have it before you plan around it.** Secret scanning and
push protection are free on public repositories; on private or internal ones they
are part of paid GitHub Secret Protection. If the org does not have it — which is
the case for exactly the private repos where keys sit unnoticed — the PATCH above
enables nothing, and CI becomes the enforcing copy: a required status check that
runs `gitleaks git --redact` over the pushed range. Unlike the local hook, a
required check cannot be skipped with `--no-verify`.

## When it fires

1. **Stop and report `file:line` and the rule id — never the value.** With
   `--redact` on (it is, everywhere here) you cannot see the value, so you are in
   no position to rule it a placeholder. If you are an agent, this is where you
   hand back to a human: a blocked commit is a stop, not an obstacle.
2. **Assume real: rotate first.** The scanner found it in your staged diff, which
   means it is also in the working tree, the editor's undo history, your shell
   history and probably an agent transcript. Removing this one copy is not
   containment (`agent-credential-leak-surfaces`).
3. Replace the literal with an env var or a secret-store read, re-stage, commit.
4. **Never re-run the commit with `--no-verify`.**
5. **Only a human, having seen the value, declares it a fixture** — and then the
   narrow fix is that one fingerprint in `.gitleaksignore`, not the path in
   `.gitleaks.toml`. A path allowlist blinds the scanner to that file forever,
   and note that `.gitleaksignore` is itself a public index of where the findings
   were, which matters if the repo is ever open-sourced.
   Any `.gitleaks.toml` you add **must** begin with:
   ```toml
   [extend]
   useDefault = true
   ```
   Without it your file replaces the built-in ruleset entirely: 222 rules become
   however many you wrote, the hook keeps passing every commit, and nothing looks
   wrong. Re-run the verification below after any config change.
6. If an **earlier** commit already carries it (hook installed late), local-only
   is not safe either — `git reset` leaves the blob reachable through the reflog
   and as a dangling object until gc. And if it was ever pushed, `git filter-repo`
   plus a force-push does **not** remove it from GitHub: the original commit stays
   reachable by SHA, in every fork in the network, and in `refs/pull/*` for any PR
   that carried it. Clearing that needs GitHub Support. Rotation is the only step
   that actually closes the exposure; the rewrite is cleanup.

## Verification

Prove the hook actually blocks, in a throwaway repo:

```bash
command -v gitleaks >/dev/null || { echo "gitleaks not on PATH"; exit 1; }
d="$(mktemp -d)" && cd "$d" && git init -q .        # picks up init.templateDir
git config user.email t@example.invalid && git config user.name t
h="$(git rev-parse --git-path hooks)"
[ -x "$h/pre-commit" ] || echo "NO HOOK - nothing under test"

echo 'ok' > clean.txt && git add clean.txt          # negative control
git commit -qm clean && echo "clean commit passed"

printf 'aws_key = %s%s\n' 'AKIA' 'ZZ4Q7XWMPUTV3JKR' > leak.txt
git add leak.txt
git commit -m t 2>&1 | tee out
n=$(git log --oneline | wc -l)                      # expect 1: only the control
grep -qE  'leaks found: [1-9]' out && echo "BLOCKED BY THE HOOK"
grep -qi  'not found'          out && echo "HOOK COULD NOT RUN - install gitleaks"
[ "$n" -gt 1 ] && echo "NOT BLOCKED - the leak was committed"
```

Both halves matter. The negative control catches a hook that blocks everything
(the `--no-verify` habit starts there), and checking *why* the second commit
failed separates four outcomes that look alike from outside: no `user.email`
aborts at exit 128, a missing binary exits the hook at 127, a hook that ran and
matched nothing lets the leak through, and only the fourth is a real block.

Match `leaks found: [1-9]`, not `leaks found` — a clean scan prints
`no leaks found`, so the looser pattern reports "BLOCKED BY THE HOOK" for a
commit that went through. A verification step that passes when the thing it
verifies failed is worse than no verification at all.

Two things about that fixture, both learned the hard way:

- It is assembled from two halves at runtime because a document *about* secret
  scanning otherwise trips secret scanners, including this repo's publish gate.
- It is deliberately **not** the canonical `AKIA…EXAMPLE` key from AWS's own
  docs. gitleaks' `aws-access-token` rule carries an allowlist regex `.+EXAMPLE$`,
  and `example` is a stopword for the generic rule — so the obvious test value
  produces zero findings, the commit succeeds, and you conclude your hook is
  broken when it is working. When you write a fixture for a scanner, check the
  scanner's own allowlists and stopwords first.

## Related

- `pre-open-source-credential-audit` — the audit before making a repo public:
  full history, not just the tree. This skill is the gate on every commit; that
  one is the sweep before publishing.
- `secrets-in-agent-sessions` — the other leak vector: the transcript, tool
  output and permission allowlist, none of which are in git.
- `agent-credential-leak-surfaces` — where copies accumulate once a value has
  been exposed, and how to clean them.
