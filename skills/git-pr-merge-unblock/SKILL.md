---
name: git-pr-merge-unblock
description: |
  Work out why a pull request will not merge and who can actually unblock it, on
  github.com or a self-hosted GitHub Enterprise. Use when: (1) the PR shows "Code
  owner review required" and you need to find a human who can approve it, (2) the
  PR reports APPROVED reviews but `reviewDecision` is still REVIEW_REQUIRED,
  (3) a PR has sat for days with no human review because only *teams* were
  requested and no individual was ever notified, (4) you need to know who holds
  admin/write on a repo, or who maintains a code-owner team, (5) a merge or push
  is rejected by commit-message enforcement (commitlint or a custom hook).
  Encodes the non-obvious parts: bot approvals satisfy nothing CODEOWNERS checks,
  CODEOWNERS is matched per-path so a repo-wide "who owns this" answer is usually
  wrong, and the highest-yield reviewer is the changed file's recent author rather
  than whoever the team picker offers first. Also (6) `gh pr merge` fails with
  `the base branch policy prohibits the merge` while every check is green - the
  REST protection endpoint is 404 for non-admins, so read the effective rules via
  GraphQL `refUpdateRule` and look for an unresolved review thread. Covers the
  inverse too: `refUpdateRule` is viewer-scoped, so after you are added to a
  bypass list its zeros mean "does not apply to me", never "the rule is gone".
author: Claude Code
version: 1.4.0
date: 2026-08-29
source: https://github.com/voitta-ai/skillz
---

# Git PR merge unblock

## Problem

A PR can be blocked by code-owner requirements, branch protection, commit-message
enforcement, or CI — and the UI rarely names the person who can clear it. Worse, a PR
can look *approved and green* and still be unmergeable, so the blocker is invisible
until someone goes looking.

Throughout: on GitHub Enterprise, `gh` needs `GH_HOST=your-ghe.example.com` as an **env
var**, not a `--hostname` flag. On github.com, drop the prefix. Examples below show the
env-var form; it is harmless on github.com if you set it correctly.

## Pre-flight: check commit conventions BEFORE you create the PR

Cheaper than discovering it at merge time. Inspect:

- `.github/workflows/` — CI running commitlint or a custom enforcement script
- `.husky/`, `.git/hooks/` — client-side hooks
- `package.json` — `commitlint` config, `lint-staged`
- `.commitlintrc.*`
- `scripts/` — repos often keep a bespoke `enforce-commit-msg*.sh` here

Default to conventional commits (`type(scope): description`) when nothing says otherwise.
Valid types: `fix`, `feat`, `chore`, `docs`, `style`, `refactor`, `perf`, `test`, `build`,
`ci`, `revert`.

## Step 1: Read the actual blocker

```bash
GH_HOST=your-ghe.example.com gh pr view {PR} --repo {org}/{repo} \
  --json mergeStateStatus,reviewDecision,statusCheckRollup
```

Look for code-owner requirements, failing required checks, and commit-message validation.

## Step 2: `reviewDecision` is REVIEW_REQUIRED but `reviews` shows APPROVED

Both are true at once, and it is the single most confusing state a PR reaches. Two causes,
and one query shows both:

```bash
GH_HOST=your-ghe.example.com gh pr view {PR} --repo {org}/{repo} \
  --json reviewDecision,reviews,reviewRequests \
  --jq '{decision: .reviewDecision,
         reviews: [.reviews[] | "\(.author.login):\(.state)"],
         requested: [.reviewRequests[] | .login // .name]}'
```

**Cause 1 — every approval came from a bot.** Most orgs run review bots (a CI account, a
lint bot, an automated reviewer). Their APPROVED shows up in `reviews` and counts toward
nothing CODEOWNERS checks. The PR reads "2 approvals, all checks green" and is still
unmergeable.

**Cause 2 — only *teams* were requested.** If `requested` contains team names and no
individual logins, nobody's personal review queue ever received it. Team requests are
easy to ignore and PRs sit on them for weeks. Requesting named individuals is what gets
a human to look — Steps 3 and 5.

Neither cause produces an error message anywhere. You have to go read `reviews[].author`
and notice they are all bots.

## Step 3: Resolve the code owners **for the changed path**, then pick a human

CODEOWNERS is matched per-path, longest prefix wins. A repo-wide "who owns this repo"
answer is usually wrong — a large monorepo can carry dozens of distinct per-path owners
and no global one. Start from what you actually changed:

```bash
git diff --name-only origin/main...HEAD          # the files under review
grep -nE 'libs/the-lib-you-touched' .github/CODEOWNERS
```

Expand the owning team(s) to members:

```bash
GH_HOST=your-ghe.example.com gh api orgs/{org}/teams/{team}/members --jq '.[].login'

# Who can add members to the team (maintainers only)
GH_HOST=your-ghe.example.com gh api orgs/{org}/teams/{team}/memberships/{username}
```

Then pick the member who actually knows the file — its most frequent recent author:

```bash
git --no-pager log -20 --format='%an|%ae' -- path/to/changed/file | sort | uniq -c | sort -rn
```

Cross-reference that name against the team roster. **The person whose name tops that list
and sits on the owning team is the highest-yield reviewer**; a team mention is not, and
the alphabetical first member of the team is not either.

## Step 4: Check a candidate's repo permission

```bash
# Returns: admin, write, read, or none
GH_HOST=your-ghe.example.com gh api repos/{org}/{repo}/collaborators/{username}/permission
```

- **admin** — can bypass branch protection and merge without reviews
- **write** — can approve, cannot bypass branch protection
- **read** — view only

Key insight: `write` **without** membership of the code-owner team does **not** satisfy a
code-owner requirement. The approval has to come from a team member.

Caveat: this endpoint is gated on **the caller's** push access, and it denies you
differently depending on the repo. On a **public** repo you get an honest `403 "Must have
push access to view collaborator permission."` On a **private** repo that diagnostic is
withheld and you get a bare `404` — indistinguishable from the `404` for "that user is not
a collaborator". So a permission sweep over private repos can exit 0, print a clean table,
and be wrong on every row. Guard it:

```bash
# false or 404 => the permission answer above is meaningless; record UNKNOWN, not "none"
gh api repos/{org}/{repo} --jq '.permissions.push'

# read-only fallback, asymmetric: non-zero PROVES they can push; zero proves nothing
gh api "search/issues?q=repo:{org}/{repo}+type:pr+author:{username}&per_page=1" --jq '.total_count'
```

## Step 5: Add reviewers from the CLI

```bash
GH_HOST=your-ghe.example.com gh pr edit {PR} --repo {org}/{repo} \
  --add-reviewer user1,user2,user3
```

Much faster than the browser picker for multiple additions.

**Before you push anything else:** many repos dismiss stale reviews on every push. If a PR
has hard-won approvals, an incidental push costs you all of them. Check
`Settings > Branches` (or just ask) before pushing a cosmetic change to an approved PR.

## Step 6: Fix commit-message rejection

The PR **title** becomes the squash-merge commit message, so that is usually what a
commit-lint gate is rejecting:

```bash
GH_HOST=your-ghe.example.com gh pr edit {PR} --repo {org}/{repo} \
  --title "fix(TICKET-123): description here"
```

## Step 7: Find who can bypass (org owners / repo admins)

```bash
GH_HOST=your-ghe.example.com gh api orgs/{org}/memberships/{username}

# Or browse the org people page and look for the Owner badge:
# https://your-ghe.example.com/orgs/{org}/people?query={username}
```

## Step 8: "the base branch policy prohibits the merge", every check green

`gh pr merge` says only that; `mergeStateStatus` says only `BLOCKED`. The REST
protection endpoint (`repos/{o}/{r}/branches/{b}/protection`) returns **404 to
anyone who is not a repo admin** - indistinguishable from "not protected" - and
`rules/branches/{b}` lists rulesets but not classic protection. The one view a
write-only user gets is GraphQL:

```bash
gh api graphql -f query='query { repository(owner:"{org}", name:"{repo}") {
  pullRequest(number:{PR}) { mergeStateStatus reviewDecision viewerCanMergeAsAdmin
    reviewThreads(first:50) { nodes { id isResolved } }
    baseRef { refUpdateRule { requiredApprovingReviewCount
      requiresConversationResolution requiredStatusCheckContexts requiresLinearHistory } } } } }'
```

Read it in this order:

1. `reviewThreads` with any `isResolved: false` **and** `requiresConversationResolution: true`
   is the case the UI reports as `All comments must be resolved`. A reply does not
   resolve a thread, and a review the author's own tooling posted counts. Resolve the
   ones that were addressed - GraphQL only, no REST:
   `mutation { resolveReviewThread(input:{threadId:"PRRT_..."}) { thread { isResolved } } }`
2. `requiredApprovingReviewCount` above the approvals present, with the author unable
   to approve their own PR, is Steps 3-5. `viewerCanMergeAsAdmin: false` rules out
   `gh pr merge --admin` before you try it.
3. `requiredStatusCheckContexts` names checks that must exist on the head commit -
   a renamed workflow job leaves the old name required forever.

**The inverse, once you are put on the bypass list.** `refUpdateRule` is
**viewer-scoped** - it reports the rule *as it applies to you*, not the rule.
After a bypass it reads `requiredApprovingReviewCount: 0`,
`requiresConversationResolution: false`, while `requiredStatusCheckContexts`
and `allowsForcePushes` keep reporting the parts that still bind everyone:

```bash
gh api graphql -f query='{repository(owner:"{org}",name:"{repo}"){
  branchProtectionRules(first:5){nodes{pattern requiredApprovingReviewCount}}
  ref(qualifiedName:"refs/heads/{branch}"){refUpdateRule{
    requiredApprovingReviewCount requiresConversationResolution
    requiredStatusCheckContexts allowsForcePushes viewerCanPush}}}}'
```

Two traps here, and they push in opposite directions:

- A clean `mergeStateStatus` and a `0` from `refUpdateRule` prove **you**
  bypass the rule. They are not evidence it was removed for anyone else. Do
  not write "protection was removed" into a README on that basis.
- `branchProtectionRules` returns an **empty list** to non-admins, the same
  as the REST 404. An empty list is not evidence of no protection - and the
  populated `refUpdateRule` beside it proves the rule exists.

The practical read: `refUpdateRule` answers "what applies to me", which is the
answerable question. "What applies to everyone" still needs admin, so if being
unable to see the rule was the actual complaint, a bypass does not settle it.

**To date a rule you did not see appear**, compare the repo's `updated_at` with
`pushed_at`: `gh api repos/{org}/{repo} --jq '{updated_at,pushed_at}'`. Pushes and
merges move `pushed_at`; a settings edit moves `updated_at` alone, so an `updated_at`
hours after the last push with no PR activity at that time is the moment. Bound it
from the other side with a merge census - every PR merged since a date, with its
approvals and threads:

```bash
gh search prs --owner {org} --merged --merged-at ">{ISO}" --limit 60 --json repository,number \
  --jq '.[] | "\(.repository.name) \(.number)"' | while read -r repo num; do
  gh api graphql -f query="query { repository(owner:\"{org}\", name:\"$repo\") {
    pullRequest(number:$num) { mergedAt mergedBy { login } reviewDecision
      reviews(first:20) { nodes { state author { login } } }
      reviewThreads(first:1) { totalCount } } } }"
done
```

PRs that merged with zero approvals under a `REVIEW_REQUIRED` decision were merged
before the approval rule existed, or by someone on its bypass list; the last such
merge is the lower bound. Naming the actor needs the org audit log (`read:audit_log`
on an owner's token) - `repos/{o}/{r}/events` carries no protection changes.

## Verification

```bash
GH_HOST=your-ghe.example.com gh pr view {PR} --repo {org}/{repo} \
  --json mergeStateStatus,reviewDecision
```

`reviewDecision: APPROVED` **and** a `mergeStateStatus` that is not `BLOCKED` means it is
genuinely clear. `APPROVED` with `BLOCKED` is Step 8 - almost always an unresolved thread. `reviewDecision` alone is the number to trust — not the count of green
ticks in the reviews list, for the reason in Step 2.

## Notes

- GitHub Enterprise needs `GH_HOST=` as an env var; `--hostname` is not a `gh` flag.
- Only team **maintainers** or **org owners** can add members to a team.
- Use whatever chat tooling your org has to check a reviewer's timezone before assuming
  silence means refusal.
- Record per-repo CODEOWNERS findings somewhere durable as you learn them — but record
  the *path-to-team* mapping, not a roster snapshot. Rosters go stale in weeks; the path
  mapping survives, and re-expanding a team to members is one API call.
