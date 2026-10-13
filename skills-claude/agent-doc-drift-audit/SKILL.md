---
name: agent-doc-drift-audit
description: |
  Audit agent-facing repo docs (CLAUDE.md, AGENTS.md, .claude/, REPO_MAP,
  README, runbooks) across one or many repos for claims that contradict the
  code, then land the fixes as per-repo PRs. Use when: (1) asked to evaluate
  or clean up CLAUDE.md / AGENTS.md across repos, or to design an org-level
  convention doc, (2) an agent acted on a doc claim that turned out false (a
  folded module, a retired fleet, a renamed test), (3) a migration finished
  and its status text was never re-derived. Ships scripts/check-doc-paths.py,
  a stdlib checker for stale paths, broken links and committed plugin stubs.
author: Claude Code
version: 1.0.0
date: 2026-10-13
source: https://github.com/voitta-ai/skillz
source_file: skills/agent-doc-drift-audit/SKILL.md
---

# Agent-doc drift audit

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/agent-doc-drift-audit/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

## Problem

Agent docs are loaded into every session and acted on, but nothing
re-derives them. They rot fastest where they were written as status logs,
during a migration, and where they restate a rule that lives somewhere else.

Measured on an eight-repo audit (2026-10-13): every repo's agent doc
contradicted its code somewhere, and in most the wrong claim was one an agent
would act on:

- a compute module the doc named had been folded into another two months
  earlier;
- a "migration in flight" section still said restoring the retired fleet's
  dashboards was allowed;
- a rule copied from a skill was later corrected in the skill but not in the
  doc, and the stale copy now caused a NullPointerException;
- a CI section described one deny rule where the role carried eight, so some
  dev applies fail for a reason the doc hid;
- the org-wide conventions doc described one repo's shape, and five of six
  services contradicted it.

## Context / trigger conditions

- "Evaluate / clean up the CLAUDE.md (AGENTS.md) in these repos."
- "Do we have something generic for the org?" A pattern doc is about to be
  written from several repos that "slightly differ".
- A session followed a doc instruction and did the wrong thing.
- A migration (platform, framework, observability stack) just finished.

## Solution

### 1. Audit the remote default branch, not the local checkout

Local default branches lag; in the audit above all eight were 1 to 29
commits behind. Snapshot each repo's remote default branch without touching
any working tree:

```bash
git -C <repo> fetch origin
mkdir -p snap/<repo> && git -C <repo> archive origin/<default> | tar -x -C snap/<repo>
git -C <repo> --no-pager log -1 --format='%h %cs' origin/<default>   # record it
```

Inventory per repo: every `CLAUDE.md` (root, `.claude/`, nested), `AGENTS.md`,
`REPO_MAP.md`, README and runbooks, plus `.gitignore` rules that hide
`.claude/`. Look for plugin artifacts too. Memory plugins can commit nested
`CLAUDE.md` stubs, and they load for every contributor. Local checkouts can
also hold untracked stubs in phantom directories that mirror another repo's
paths. Run `scripts/check-doc-paths.py --repo snap/<repo> --owner <org>` for a
first cut.

### 2. Build the implementation fact matrix before judging any doc

Per repo, read from config rather than from the docs:

- framework and version
- runtime/JDK version
- formatter: the actual flags, not the doc's words
- coverage gate and test stack
- metrics library and endpoint
- deploy target
- IaC layout: module dir naming, script names and argument signatures
- CI on the default branch: what it auto-applies and how it authenticates
- where dashboards and alerts live

This matrix is the ground truth that any org-level doc must not contradict.
It also exposes "patterns" that are really one repo's shape.

### 3. Verify claims, in parallel, a repo or two per verifier

Each verifier enumerates every checkable claim, then verifies it against the
snapshot and marks it CONFIRMED or UNSURE. Checkable claims are:

- paths and module or resource names
- env vars, ports, probes
- commands and make targets
- versions
- CI behavior
- counts
- "X lives in Y"

It also lists what it checked that matched; a negative result is a result.

Report sections:

- **Contradictions**: doc:line, then evidence path:line.
- **Stale history**: dated narratives whose fix landed, closed-issue lists, rollout logs.
- **Personal content**:
  - per-user model settings ("always use maximum thinking effort");
  - one person's workflow ("DM me the announcement");
  - `$HOME` or machine-local skill paths;
  - references to personal memories;
  - personal IAM ARNs.
- **Missing essentials**:
  - what the service is;
  - build, test and format commands;
  - deploy model, including "main is not prod";
  - where metrics, dashboards and alerts live.
- **Duplicated boilerplate**: sections copy-pasted across repos. Diff the copies; they diverge.

High-yield places to look:

- Migration-era "current state" sections.
- Rules restated from a skill or runbook. Diff the doc's copy against the
  source; the source gets fixed and the copy does not.
- Cross-repo references ("mirror repo X's file", "run repo Y's script on branch Z").
- Claims that fight the repo's own enforcement. For example, "no tests unless
  asked" next to a 90% coverage gate.
- Code comments near the docs (tfvars, CI files). Agents read them too.
  Report them separately.

Spot-check the most consequential findings yourself, one command each, before
stating them.

### 4. Land fixes as one PR per repo

1. **Check open PRs first.** Run `gh pr list --state open --json number,title,files`
   and read the diff of every PR that touches a doc you will edit. Leave what
   it fixes to it and say "complements #N" in your PR. In the audit above,
   approved doc-fix PRs had sat unmerged for two months and covered a share
   of the findings.
2. **Ask the owner once, up front**, about:
   - the overlap policy;
   - a layout change. `AGENTS.md` as the canonical file plus a root
     `CLAUDE.md` holding `@AGENTS.md` lets Codex read it natively; use the
     import, not a symlink;
   - whether style rules are team conventions or one person's;
   - whether an org-level doc is in scope.
3. **Branch:** one worktree and branch per repo, from the fresh remote default branch.
4. **If the doc moves,** commit the pure move first, with only path-reference
   updates. Put the content fixes in a second commit, so reviewers can read
   the content diff and open PRs can rebase onto the rename.
   - **Only a true rename carries open PRs along.** Moving `.claude/CLAUDE.md`
     to a root `AGENTS.md` deletes the old path. When open PRs that edit it
     rebase, git's rename detection carries their hunks to the new file, with
     conflicts only on adjacent lines. Moving a root `CLAUDE.md` is different:
     the path survives as the `@AGENTS.md` import stub. Rename detection only
     pairs a deleted path with an added one, so git sees a rewritten
     `CLAUDE.md` plus a new `AGENTS.md`. Every open PR that edits `CLAUDE.md`
     must then re-apply its hunks to `AGENTS.md` by hand. Say so in the PR body
     and name those PRs.
   - **Doc-contract tests can whitelist their inputs by file name.** In one
     audited repo, a test required every tracked root `.md` to be a declared
     test input in the build file. The move needed a one-line build change,
     and a filtered run of the doc-contract tests stayed green while the full
     suite failed. Run the full suite once after a move.
5. **Docs only.** Report stale code comments, security findings and CI
   defects separately instead of fixing them in the doc PR.
6. **Repos another team owns:** fix contradictions only, keep their structure
   and voice, and run their doc ratchets and contract tests before pushing.

### 5. Make the drift mechanical

Prose rules such as "keep CLAUDE.md current" fail; checks hold. Cheapest first:

- **`scripts/check-doc-paths.py`** fails when an agent doc names a missing
  repo path or a relative link breaks. It suffix-matches against tracked
  files, so `module/x/main.tf` passes when `terraform/module/x/main.tf`
  exists and fails once the module is gone. It also flags committed plugin
  stubs. Run it in CI.
- **Claim markers.** Put `<!-- claim: name = N -->` next to a number in a doc,
  and have a script re-derive N from the repo.
- **Doc-contract tests.** Unit tests read a doc and assert it matches config.
  For example, "no doc may name a CI workflow that does not exist", or "the
  documented local check command is not weaker than CI's".

For an org-level conventions doc, give each pattern two parts: a "canonical
(target)" section, and a per-repo deviation table dated when it was read.
Aspiration goes in the first, reality in the second, so the doc can be
ambitious without contradicting any repo.

## Verification

- Every reported contradiction carries `doc:line` plus evidence `path:line`,
  read from the snapshot at a recorded SHA.
- `python3 scripts/check-doc-paths.py --self-test` prints `self-test OK`.
- After the fix PRs: `check-doc-paths.py --repo <worktree>` reports nothing
  for the edited docs, and each PR body lists the open PRs it complements and
  what it left alone.

## Example

```bash
# first cut over a snapshot (plain dir: pass the org so its other repos' paths are skipped)
python3 scripts/check-doc-paths.py --repo snap/service-a --owner my-org
# .claude/CLAUDE.md:23: missing path: terraform/module/service-a-eks/
# REPO_MAP.md:30: missing path: module/dashboard/
# terraform/env/CLAUDE.md:1: plugin-generated stub: <claude-mem-context>

# in a checkout (owner from the git remote; .gitignore'd generated files skipped)
python3 scripts/check-doc-paths.py --repo . --ignore '^vendor/'
```

## Notes

- **False positives** come mostly from paths into another repo, on lines that
  don't name that repo. Link the file by URL (the link text is then
  skipped), name the repo on the line, or pass `--ignore`.
- **A doc that names a deleted file in order to say it was deleted** will be
  flagged. Rephrase it, or ignore that token.
- **Run the checker in git mode for CI.** In snapshot mode `.gitignore` is not
  applied, so generated files such as `env/secrets.env` show up as missing.
- **Fix the source, not just the copy.** When a skill or runbook is
  corrected, sweep the repos that restated it. The fix is a one-line pointer
  to the source, never a second copy.
