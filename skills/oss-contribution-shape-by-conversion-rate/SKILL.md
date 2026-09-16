---
name: oss-contribution-shape-by-conversion-rate
description: |
  Decide whether to contribute to an open-source repo as a pull request or as
  an issue by measuring the repo's conversion rate first: what share of merged
  PRs come from the maintainers, how many outside PRs sit open, how far main
  is ahead of the last release, and what reviews an outside PR actually gets
  (bots only, or a human). Use when: (1) you are about to write a patch for a
  fast-moving repo (thousands of merged PRs a quarter, one to three
  maintainers, agent-generated PRs) and want to know if it will be read,
  (2) your PR has sat for weeks with green bot checks and no human review,
  (3) required checks never ran on your fork branch so the PR shows BLOCKED
  with nothing to fix, (4) a maintainer opened their own PR for the thing you
  filed, with or without crediting the issue, (5) several competing fix PRs
  for one bug are rotting while a duplicate issue gets the fix, (6) you are
  writing an issue and want it to convert. Covers the four numbers, the
  decision rule (issue with field data + kill condition, not PR), what makes
  an issue convert, cross-linking duplicates so the fix closes the canonical
  issue, and closing your own superseded PR with a pointer.
author: Claude Code
version: 1.1.0
date: 2026-09-14
source: cmux contribution record Jul-Sep 2026 (hq#145); aiqrank/plugin Aug 2026
source_file: skills/oss-contribution-shape-by-conversion-rate/SKILL.md
---

# Contribution shape by conversion rate

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/oss-contribution-shape-by-conversion-rate/SKILL.md`).

## Problem

The internet says "send a patch". On a repo where three people merge 95% of
everything and land thousands of commits between releases, an outside patch is
a liability with a diff attached: somebody has to hold it against a `main`
that moved thousands of times, and nobody has the time. The same repo will
take a well-argued issue and reimplement it as a maintainer PR within weeks.
Sending the wrong shape costs you the work and costs the maintainer triage.

Measured on one such repo over two months: the two features asked for in
issues shipped together in one maintainer PR; the patch sent for one of those
features sat 32 days with seven green bot checks, zero workflow runs (the
required checks do not run on fork branches), and no human review, then was
superseded. A bug with nine competing fix PRs, four by the maintainer, got
its fix attached to a duplicate issue filed four months after the original.

## Context / Trigger Conditions

- Before writing a patch for a repo you do not maintain.
- A PR of yours shows `BLOCKED` with green bot checks and no runs of the
  required checks; or `mergeStateStatus` stays `UNKNOWN`/`UNSTABLE` with
  nobody assigned.
- The review log on a maintainer PR reads "automated pre-merge suggestion
  triage", CodeRabbit, Cursor, greptile ("too many files"), Bugbot ("spend
  limit reached"): the repo reviews by robot.
- A maintainer PR "Fixes #<duplicate>" and never mentions the original.

## Solution

### 1. Measure four numbers (five minutes, read-only)

Use the search API's `total_count` for counts, with the date window pinned
at **both** ends. Two traps, both verified:

- `gh pr list --search ...` rides on the GitHub Search API, which refuses
  anything past result 1000 (`422 Only the first 1000 search results are
  available` on page 11). `--limit 3000` silently returns 1000. A count built
  from that listing was off by 5x.
- `total_count` is not capped, but an open-ended window (`merged:>=DATE`) is a
  live number: 1,889 one day, 2,112 six days later, same query. Pin the upper
  bound and record the date next to the number.

```bash
R=owner/repo; WIN=2026-07-10..2026-09-09
q() { gh api -X GET search/issues -f q="repo:$R $1" --jq .total_count; }
q "is:pr is:merged merged:$WIN"                           # all merged
q "is:pr is:merged merged:$WIN author:<maintainer>"       # per maintainer
q "is:pr is:merged merged:$WIN -author:<m1> -author:<m2>" # everyone else
q "is:pr is:open -author:<m1> -author:<m2>"               # outside PRs waiting
gh api "repos/$R/releases?per_page=1" --jq '.[0].tag_name'
gh api "repos/$R/compare/<last-tag>...main" --jq .total_commits # unreleased
```

Batch these; the search endpoint secondary-rate-limits (HTTP 403) after
roughly ten rapid calls. For an exact count above 1000, paginate REST
`/repos/$R/pulls?state=closed&sort=updated&direction=desc` or GraphQL
`repository.pullRequests(states: MERGED)` with cursors and filter on
`mergedAt` client-side; neither is capped.

Then look at one recent outside PR and one maintainer PR: who reviewed
(`gh pr view N --json reviews --jq '[.reviews[].author.login]'`) and whether
the required checks ran (`--json statusCheckRollup`; compare against the
ruleset's required names). A fork branch where required checks never run is
a structural block, not something to fix in your PR.

### 2. Read the numbers

| Signal | Shape to send |
|---|---|
| Maintainers merge >90% and outside-open is in the hundreds | issue |
| Unreleased commits in the thousands | issue; a patch cannot stay rebased |
| Outside PRs get bot reviews only | issue |
| Maintainer reimplemented a recent issue as their own PR | issue; that is the intake path |
| Outside PRs merge within days with a human review | PR is fine |

### 3. Write the issue so it converts

An issue converts when it is a spec an agent-generated PR can be checked
against. Four parts, in this order:

1. **Reproduction** on a named version, with the exact command and output.
2. **Mechanism**, verified, not guessed. The paragraph that rules out a family
   of fixes is worth more than any one fix (on the nine-PR bug, one
   observation that APFS does not update `atime` on read, so a daily-required
   file still looks idle to the temp cleaner, ruled out every
   recreate-at-launch patch).
3. **The ask, sized to one PR**, naming the verb or event and its contract.
4. **A kill condition** for your own claim: "if X was deliberate, this issue
   is wrong and I would rather know". It is the cheapest way to signal you did
   the work, and it is what distinguishes good faith from politeness.

Do not attach a patch unless step 2 said PRs merge. If you must, expect it to
be superseded and say so in the body.

### 4. When a maintainer PR lands for your issue

- Read the diff before asking scope questions; on the measured repo the
  question "is `send --wait-until` in this PR?" went unanswered for weeks
  while `grep -c wait-until` on the diff answered it in one second.
- If your own PR is superseded, **close it yourself with a pointer** to the
  maintainer PR, credit what they did better, and state the block you hit
  (required checks never ran) as a fact for the next contributor, not as a
  grievance.
- Offer the review the bots cannot give: build the branch and run it against
  your real workload. On a repo that reviews by robot, that is the one thing
  only an outside user can contribute.

### 5. Cross-link duplicates

When the fix PR says "Fixes #<duplicate>", comment on the PR, the duplicate
and the canonical issue, linking all three, so the merge closes the issue
people actually find by search. One comment each, no reopening.

## Verification

- The four numbers are in your notes with the date and the query used.
- Your issue has all four parts; a stranger could implement it and check
  their work against it.
- Your superseded PR is closed by you, not by a stale bot.

## Example

cmux, measured 2026-09-09 (window July 10 to that day): 1,889 PRs merged, 1,790 by three
maintainers, 99 by everyone else; 3,007 open, 773 from outside; 4,665
commits since the last release five weeks earlier. Two issues filed in July
(a `wait` verb and an `agent.state.changed` event) shipped together in a
maintainer PR of 111 files; the outside PR for the event sat 32 days at
BLOCKED with zero workflow runs and was closed by its author with a pointer.
Decision recorded: issues with field data and a kill condition, not PRs, for
that repo from then on.

## Notes

- This is a statement about a repo's intake path, not about its quality. A
  team landing 4,665 commits in five weeks cannot review 773 outside PRs; the
  robot reviewers are what they have, not what they chose.
- The rule inverts on small repos with responsive maintainers, where a patch
  with tests is the fastest way to be understood. Measure; do not assume.
- Related: `codex-adversarial-pr-review` (how to review a PR you cannot
  merge), `parallel-agent-session-collisions` (checking for an existing PR
  before opening one), `git-pr-merge-unblock` (when the block is yours to
  fix).

## References

- GitHub search syntax for issues and PRs: https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests
- GitHub secondary rate limits: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#about-secondary-rate-limits
