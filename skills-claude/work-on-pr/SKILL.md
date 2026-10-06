---
name: work-on-pr
description: |
  Iteratively work on a GitHub pull request as the author. Watch for new review comments, issue comments, and inline threads; if nothing new exists yet, wait and re-check instead of exiting. For each actionable item, implement the fix in the PR worktree, run relevant tests, commit and push, then reply with a summary and commit SHA. Continue until the PR is approved, merged or closed, or the user stops the loop. Also accepts an issue reference instead of a PR: in that case the skill creates the PR (if absent), guarantees the PR body contains `Closes #<issue>`, and then enters the watch loop. A bare problem statement works too — the skill opens the issue first, then takes the issue path. Optionally drives its own reviewer by running `codex-adversarial-pr-review` on the PR each round, so the loop closes without a second human. Use when you want the agent to own the start-PR or address-test-push-reply-wait cycle across multiple review rounds rather than handling a single review comment.
author: Claude Code
version: 1.13.0
date: 2026-06-22
source: https://github.com/voitta-ai/skillz
source_file: skills/work-on-pr/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/work-on-pr/SKILL.md`).
> Updates go through the repo's worktree + PR workflow — open an issue,
> branch, PR. The repo replaced gist 5f606018eb36a75dc292016268f08e7c,
> which is preserved as a redirect.

# work-on-pr

## Problem

A non-trivial PR usually goes through several review rounds. The
mechanical loop — fetch the latest review, understand it, implement
the fix, run tests, commit + push, post a reply with the commit SHA,
wait, repeat — is well-defined and tedious. If the agent owns the
loop, the human only needs to step in for scope decisions and the
final merge. Without a structured loop the agent forgets to:

- check for *new* reviews vs ones already addressed,
- run tests before pushing,
- include the commit SHA in the reply,
- reuse the existing worktree instead of creating a new one,
- pace polling against the prompt-cache TTL,
- keep waiting when the PR is quiet and no comments have landed yet,
- avoid ad hoc sub-minute polling that burns turns without reaching a
  stop condition,
- detect the approval / merge exit conditions.

This skill codifies that loop.

## Context / Trigger Conditions

Invoke when:

- User says "address this comment", "address the next comment",
  "iterate on PR #N", "work on PR #N", "watch PR #N for feedback".
- A PR is open and either feedback already exists or is expected
  soon, and the user wants the agent to drive the iteration.
- After an initial PR has been opened (e.g. by the feature-dev or
  rapid-prototyper flow) and review feedback is starting to arrive.
- The user supplies an **issue** reference (URL or `#N`) and asks
  the agent to start a PR. The skill creates the PR (if not yet
  open) and then enters the watch loop. The created PR body MUST
  contain `Closes #<issue>` so merging the PR auto-closes the
  issue.
- The user supplies a **short problem statement** with no issue and
  no PR ("work on X"). The skill opens the issue first, then takes
  the issue path above, so the work stays anchored to a tracked
  issue rather than a bare branch.

Do NOT use when:

- Just reviewing someone else's PR — see `review-pr-loop` instead.
- The PR is already approved or merged — nothing to drive.

## Solution

One invocation owns the watch loop until a termination condition is
reached or the user interrupts it. If there is no actionable
reviewer activity yet, that is an idle wait state, not success: keep
waiting and re-checking. Prefer `ScheduleWakeup` when the host
supports it and the wake-up survives turn end; otherwise sleep and
poll again in the same invocation. Do not return just because a
quiet poll or one sleep interval completed. A loop round only ends
early if it actually scheduled a durable continuation elsewhere, or
if a real stop condition fired.

At the first idle/reschedule pass, surface which watch mode is
active:

- `watch-mode=durable`: a real wake-up was scheduled (a host
  scheduler such as `ScheduleWakeup`, or a cron / scheduled-task
  primitive) and survives turn end.
- `watch-mode=in-process-only`: no durable scheduler, but this
  invocation can stay alive across the wait, so it sleeps and
  re-polls within the same turn. **Codex (CLI/exec) is in this
  class:** it executes shell commands, and a blocking shell
  `sleep <interval>` holds the session open between polls, so the
  loop keeps polling in-process — it does not need to suspend.
- `watch-mode=suspend-resumable`: the host has no durable scheduler
  AND cannot keep the invocation alive even with a blocking shell
  `sleep` — the host kills long-running commands, or ends the turn
  while a command is still running, so an in-process `sleep` cannot
  carry the loop to the next poll. This is the only case where the
  loop physically cannot poll itself; handle it with the
  resumable-suspend protocol in "Hosts that cannot self-schedule"
  below, never with a silent stop. Do not assume a host is in this
  class until a blocking `sleep` has actually been killed — codex is
  not.

While the loop is active, do not send a terminal/final handoff just
to summarize status. Use progress/status updates only. Idle passes,
approval prompts, and empty polls are never completion. Only end the
invocation when a real stop condition fired, when a durable wake-up
was actually scheduled and control is being handed off to it, or —
on a host that can neither schedule a wake-up nor stay alive
in-process — when a resumable suspend hands back an exact resume
command (see "Hosts that cannot self-schedule").

### Single-iteration flow

1. **Resolve invocation target.**
   - Parse the skill args. Two valid shapes:
     - **PR ref**: number, PR URL, or branch name. Skip to 1a.
     - **Issue ref**: issue URL (`https://github.com/<owner>/<repo>/issues/<N>`)
       or `#<N>` plus repo context. Go through 1b first.
     - **Problem statement**: free text carrying neither `#<N>` nor a
       URL. Go through 1d first.
   - **1a. Existing PR:** `gh pr view <N> --json
     number,state,headRefName,headRefOid,baseRefName,mergeable,reviewDecision,url,body`.
     If `state != OPEN` → report and stop (no reschedule). Then run
     step 1c (issue-linkage repair).
   - **1b. Issue → PR (create if absent):** check whether a PR
     already exists for the issue:
     - `gh pr list --repo <owner>/<repo> --search "Closes #<N> in:body" --state open --json number,url`,
       or grep the user-author's open PRs for a branch matching the
       issue.
     - If no PR exists, create the worktree (step 3) and the feature
       branch, scaffold the work needed by the issue, push, then run
       `gh pr create` with a body that includes `Closes #<N>` (use a
       `--body-file` heredoc so quoting survives). The PR's first
       commit on the branch is fine even if it is just a scaffolding
       commit; subsequent rounds add real fixes. After creation,
       continue with step 2 on the just-created PR.
     - If a PR exists, hand off to step 1a.
   - **1c. Issue-linkage repair (existing PR + known issue):**
     when the invocation arg is an issue ref AND an open PR was
     found, check whether the PR's body contains a closing keyword
     for that issue:
     ```
     /\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#<N>\b/i
     ```
     (also accept `<owner>/<repo>#<N>` form). If absent, edit the
     PR body to append `Closes #<N>`:
     ```
     body=$(gh pr view <PR> --json body --jq .body)
     printf '%s\n\nCloses #%s\n' "$body" <N> > /tmp/pr-body.md
     gh pr edit <PR> --body-file /tmp/pr-body.md
     ```
     Use `--body-file` so multiline bodies and backticks survive.
     This step is idempotent; running it on a PR that already has
     `Closes #<N>` is a no-op.
   - **1d. Problem statement → issue:** when the arg is free text
     with no issue and no PR reference, open the issue first:
     ```
     gh issue create --title "<one line>" --body-file /tmp/issue-body.md
     ```
     then re-enter at 1b with the new issue number. Do not branch
     straight off a problem statement: the issue is what `Closes #<N>`
     binds to, and without one the PR has nothing to close and the
     work has no tracked home. If the statement is too vague to title,
     that is a step-8 escalation, not a guess.

2. **Check exit conditions.** There are two, they are reached
   differently, and they are not interchangeable.

   - **Human exit — an external approval.**
     - `reviewDecision == "APPROVED"` → stop, report success.
     - Or fetch latest review: `gh api repos/:owner/:repo/pulls/<N>/reviews`,
       last entry `state == "APPROVED"` → stop.
     - Or an issue comment whose body matches
       `/\b(lgtm|ship it|approved|approve)\b/i` from a maintainer →
       stop.
   - **Codex exit — a clean adversarial review.** When this loop
     drives its own review via step 7, the codex side can never
     produce a GitHub approval: if the posting identity is the PR
     author — the norm when the agent opened the PR — GitHub rejects
     `APPROVE` and `REQUEST_CHANGES`, which is why
     `codex-adversarial-pr-review` posts `event: COMMENT`. So the
     codex-side exit is **zero blocking findings returned by the
     script against the current head**, never a review state. A round
     that addressed findings and then re-reviewed clean satisfies it.
     A round that never ran the review does not, and neither does a
     single zero-finding result — see step 7d.
   - **The codex exit does not merge the PR.** It says the
     self-review is out of objections. Merging still needs the human
     exit or an explicit user instruction, because an agent reviewing
     its own diff is not independent review (see Notes).

3. **Reuse or create the worktree.**
   - Location: `<repo>.worktrees/<branch-name>/`, the sibling
     directory the `git-worktree-convention` skill defines. Pass
     it as an **absolute** path — `git worktree add` resolves a
     relative one against the cwd, which nests the worktree inside
     the repo when you run it from there.
   - `git worktree list` to check; if absent, create one at
     `<repo>.worktrees/<headRefName>/` tracking
     `origin/<headRefName>`.
   - Run subsequent git operations in single-shot form via
     `git -C <worktree-path> <subcommand> ...`. Do NOT chain a
     `cd <worktree>` with `&&` in front of `git`. The compound
     does not match any single `Bash(git ...)` allow pattern, so
     it forces a permission prompt every time even when the
     standalone git command would have been auto-allowed. See the
     "Auto-approved operations" section below for the matching
     allow entries.
   - For ad-hoc reads (`git status`, `git --no-pager diff`, etc.)
     the same rule applies: use `git -C <worktree> --no-pager
     <subcommand>` rather than `cd <worktree> && git ...`.
   - If the host uses sandbox approvals, preflight the operations
     this loop is likely to need: `git -C <worktree> add` /
     `git -C <worktree> commit`, `git -C <worktree> push origin
     <branch>`, `gh pr comment`, and inline `gh api .../replies`.
   - Reuse already-approved command prefixes when possible.
   - If approvals are likely to recur, request scoped prefix
     approvals up front rather than waiting until after tests pass.
   - An approval request is not a stop condition; once granted,
     continue the loop.

4. **Determine what's new since last addressed.**
   - "Last addressed" anchor = max(committed_at of head commit,
     created_at of last issue comment posted by the authenticated
     user). Compute via:
     - `gh api repos/:owner/:repo/commits/<headRefOid> --jq .commit.committer.date`
     - `gh api repos/:owner/:repo/issues/<N>/comments
        --jq '[.[] | select(.user.login == "<me>")] | last | .created_at'`
   - Note: the response from `GET /repos/{owner}/{repo}/commits/{ref}` nests
     commit metadata under `.commit.*`. The top-level `.committer` is the
     GitHub user object (login/id), not the commit timestamp —
     `.committer.date` is empty. Prefer `.commit.committer.date` over
     `.commit.author.date`: committer date moves on rebase, author date does
     not, so committer date better reflects "when did this commit hit the
     branch".
   - Take the MAX. Call it `anchor_ts`.
   - Fetch all three comment surfaces:
     - reviews: `gh api repos/:owner/:repo/pulls/<N>/reviews`
     - issue comments: `gh api repos/:owner/:repo/issues/<N>/comments`
     - inline review comments: `gh api repos/:owner/:repo/pulls/<N>/comments`
   - Filter to items with `submitted_at > anchor_ts` (reviews) or
     `created_at > anchor_ts` (comments) AND author != self.
   - **Shared-identity caveat (do not filter `author != self` by
     login alone).** The `author != self` test is only reliable when
     the reviewer and you post under *distinct* GitHub identities.
     When one operator drives both this loop and the paired
     `review-pr-loop` under the **same** GitHub login (e.g. the author
     side tags `[claude]` and the reviewer side tags `[codex]`, both
     posting as the same user), a `select(.user.login != "<me>")`
     filter hides the reviewer's reviews/comments and the loop never
     sees the feedback. Under shared identity, discriminate by
     `timestamp > anchor_ts` **plus** the model tag (`[codex]` vs
     `[claude]`) in the body, not by login: anything newer than your
     anchor that you did not just post is actionable, regardless of
     login. (Detect shared identity by checking whether the reviewer's
     posts carry the *other* tag under your own login.) Reserve the
     login-based `author != self` filter for genuinely separate
     identities. See `review-pr-loop` and the
     `docs/pr-review-workflow.md` "GitHub identity caveat".
   - Approval-only reviews (no body, state=APPROVED) → handled in
     step 2; otherwise treat the body as actionable.
   - **Timeline fallback (cache-stale list endpoints).** If all three
     list endpoints above return `[]` AND `anchor_ts` is more than
     ~2 minutes ago (i.e. enough time has passed that real activity
     could have landed), do not trust the empty result. The
     `api.github.com` list endpoints are edge-cached more
     aggressively than single-resource lookups; right after a fresh
     PR opens, the cache can serve `[]` for many minutes while
     newer comments / reviews already exist at the origin. Hit the
     PR timeline endpoint instead:
     ```
     gh api "repos/:owner/:repo/issues/<N>/timeline?per_page=100" \
       -H "Accept: application/vnd.github.mockingbird-preview+json"
     ```
     The timeline returns `commented`, `reviewed`, `line-commented`,
     `merged`, and `closed` events with `created_at` / `submitted_at`
     timestamps. For each event whose timestamp is newer than
     `anchor_ts` and whose actor is not self, hydrate the referenced
     comment / review by ID via single-resource fetch (which does
     not exhibit the same staleness):
     - issue comment: `gh api repos/:owner/:repo/issues/comments/<id>`
     - review: `gh api repos/:owner/:repo/pulls/<N>/reviews/<id>`
     - inline review comment: `gh api repos/:owner/:repo/pulls/comments/<id>`
     Treat the hydrated bodies as the actionable set for this round.
     If the timeline ALSO returns no relevant events, the PR really
     is quiet — proceed to step 5.
   - **Cache-suspicious empty polls.** Track per-PR whether the most
     recent list-endpoint poll returned `[]`. If the next poll also
     returns `[]` within ~5 minutes (well under typical edge-cache
     TTL), log it as cache-suspicious and use the timeline fallback
     above on this iteration too, instead of treating the back-to-back
     `[]` as definitively quiet. Two adjacent empty polls on a fresh
     PR are exactly the failure mode that hid the LGTM in #33.
   - **Manual comment-URL handoff.** If the user pastes a specific
     comment URL into the loop, parse the comment ID out of the URL
     and fetch the comment directly via the single-resource endpoint
     rather than relying on the list view to surface it. The list
     view may still be returning `[]` even though the comment is
     reachable by ID.

5. **No new actionable items yet → keep waiting.**
   - No comments yet is not completion; the reviewer may simply not
     have responded yet.
   - Recent activity (anchor < 10 min old) → short delay
     (`270s` to stay inside the 5-minute prompt-cache TTL).
   - Quiet (anchor > 30 min) → long delay (`1800s` or `3600s`).
   - Emit one short status line for the pass. Use
     `watch-mode=durable` only when a real wake-up was scheduled;
     use `watch-mode=in-process-only` when this invocation stays
     alive to re-poll; use `watch-mode=suspend-resumable` on a host
     that can do neither (see "Hosts that cannot self-schedule").
   - If the environment exposes `ScheduleWakeup` and the wake-up
     survives turn end, schedule the next check with the same
     `/work-on-pr <N>` prompt and end the current iteration.
   - Otherwise, if this invocation can stay alive, send a brief
     user-facing wait update, keep the current invocation alive,
     sleep for the chosen delay, and jump back to step 1. An
     in-process sleep does not survive a terminal/final handoff.
   - If the host has no durable scheduler AND cannot keep this
     invocation alive even with a blocking `sleep` (the host kills the
     sleep or ends the turn while it runs — codex does neither),
     do not claim polling will continue and do not silently stop.
     Follow the resumable-suspend protocol in "Hosts that cannot
     self-schedule" below: rule out a host-native trigger first, then
     hand back `action=watch suspended:host cannot self-schedule;
     resume with /work-on-pr <N>`.
   - Do not substitute ad hoc `30s` sleeps unless the user explicitly
     asked for aggressive polling.
   - Only terminate on approval / merge / user stop / hard-cap
     escalation.

6. **For each new actionable item:**

   a. Read the full body.

   b. **Plan + implement** in the worktree. Edit files, follow
      the project's conventions (read CLAUDE.md / README).

   c. **Run the project's test suite.** No commits / pushes if tests
      fail. Diagnose, fix, re-run. If a test failure surfaces an
      ambiguity in the reviewer's ask, fall back to step 8 (escalate).

   d. **Commit** in the worktree with a real message describing the
      fix and which review/comment ID it addresses. Use HEREDOC via a
      `/tmp` file for the commit body to avoid shell-quoting traps
      when the body contains quotes or backticks (see
      `gh-git-heredoc-body-file` skill). Invoke the commit as
      `git -C <worktree> commit -F /tmp/...` so the call matches a
      single allow entry; chained `cd <worktree> && git commit ...`
      will prompt every time.
      **Heredoc file path is always under `/tmp/`** (e.g.
      `/tmp/pr-<N>-commit.txt`, `/tmp/issue-<N>-commit.txt`).
      Never write the heredoc body file inside the worktree, cwd,
      or any other tracked location: that creates an untracked file
      the next `git add` may stage by accident, AND it falls outside
      the `Write(/tmp/**)` allow entry below so the Write tool will
      prompt. The basename alone (`issue-<N>-commit.txt`) without the
      `/tmp/` prefix is the most common form of this mistake.

   e. **Push** the feature branch via
      `git -C <worktree> push origin <branch>`. The allow block
      below pairs `Bash(git push origin feature/*)` with the
      `Bash(git -C * push origin feature/*)` form so either cwd
      shape works without a prompt.

   f. **Post a reply.** Body explains what was done and references
      the commit SHA. Use `gh pr comment <N> --body-file /tmp/...` —
      `--body-file`, not `-b`, to dodge shell quoting.
      For inline review-thread replies, use
      `gh api repos/:owner/:repo/pulls/<N>/comments/<comment_id>/replies
       -F body=@/tmp/reply.md` or the `--in-reply-to` form of `gh
      api`. **Use `-F` (uppercase), not `-f`**: `-f`/`--raw-field`
      sends the value as a literal string, so
      `-f body=@/tmp/reply.md` posts the literal text `@/tmp/reply.md`
      as the comment body and the actual file contents never get
      uploaded. `-F`/`--field` honors the `@file` prefix and reads
      the file. The bug is silent — the POST succeeds and returns
      `201`, just with garbage content. Same caveat applies to
      `gh api ... /reviews` (top-level review bodies) and any other
      `gh api -F body=@<file>` write. (Editing afterward is
      `gh api -X PATCH /repos/:owner/:repo/pulls/comments/<id>
       -F body=@/tmp/reply.md`.) When host/model identity is known,
      prefix the body with a short tag (e.g. `[claude]`, `[codex]`)
      — see "Reply convention" below. This mirrors the reviewer-side
      rule in `review-pr-loop` so the reader can tell who/what
      generated each post in a multi-round thread.

   g. **Resolve the thread you just addressed.** A reply is not a
      resolution. Under a branch rule that requires conversation
      resolution (classic protection "Require conversation resolution
      before merging", or the ruleset equivalent) every unresolved
      review thread blocks the merge: `gh pr merge` fails with the
      unhelpful `the base branch policy prohibits the merge`, and the
      web UI says `All comments must be resolved`. That includes the
      threads this loop opened itself in step 7 — a codex round with
      one inline finding leaves the PR unmergeable until someone clicks
      Resolve. There is no REST endpoint for it; it is GraphQL only.
      Map the inline comment's REST id (`databaseId`) to its thread id,
      then resolve:
      ```
      gh api graphql -f query='query { repository(owner:"<owner>", name:"<repo>") {
        pullRequest(number:<N>) { reviewThreads(first:50) { nodes {
          id isResolved comments(first:1) { nodes { databaseId } } } } } } }'
      gh api graphql -f query='mutation {
        resolveReviewThread(input:{threadId:"<PRRT_...>"}) { thread { isResolved } } }'
      ```
      Resolve only the threads you addressed in this round, after the
      SHA reply is posted, so the thread's last word says what changed.
      A human reviewer's thread that asked a question you could not
      answer stays open — that is step 8, not a click. Before reporting
      the human exit in step 9, confirm `reviewThreads` has no
      `isResolved: false` left; `mergeStateStatus == BLOCKED` with every
      check green is the signature of a forgotten thread.

7. **Adversarial self-review (codex side).** Optional. Run it once
   per round *after* the round's fixes are pushed — once per round,
   not once per addressed item.

   a. **Dry-run first.** Against the current head:
      ```
      node <skills-dir>/codex-adversarial-pr-review/scripts/codex-adversarial-pr-review.mjs \
        --pr <N> --repo-dir <worktree> --fetch --dry-run \
        > /tmp/pr-<N>-review.json
      ```
      The dry-run output **is** the POST body, verbatim. Never re-run
      without `--dry-run` in order to post: that spends a second Codex
      pass and can come back with different findings than the ones you
      just judged.

   b. **Judge the findings before posting.** Adversarial framing
      produces confident, well-written, wrong findings, and the
      confidence score does not separate them. Drop the ones you
      verified are wrong by editing the saved payload with `jq`, keep
      the rest. See `codex-adversarial-pr-review` for the pattern.

   c. **Post the judged payload:**
      ```
      gh api repos/:owner/:repo/pulls/<N>/reviews --method POST \
        --input /tmp/pr-<N>-review.json
      ```
      The findings land as ordinary PR review comments, so step 4
      picks them up on the next round with no extra machinery. Tag the
      body `[codex]` per "Reply convention" below — under a shared
      GitHub identity that tag, not the login, is what step 4's filter
      discriminates on. Each inline finding is also a review thread,
      and under a conversation-resolution rule each one blocks the
      merge until resolved — so every finding the next round addresses
      ends with step 6g, and a finding you decide not to act on gets a
      reply saying why and then the same resolve.

   d. **Zero findings is suspicious, not a pass.** An empty result is
      indistinguishable on the wire from a clean review, and this has
      already fired: a flaky parse of the companion's output discarded
      four real findings, two of them `high`, while the wrapper
      reported `Codex review returned no findings` (skillz#212, fixed
      by `salvageResult()`). So on a zero-finding result:
      - check stderr for a `note: recovered N finding(s)` line, which
        marks a salvaged run rather than a clean one;
      - re-run once. Only when a second run also comes back empty does
        the result satisfy the codex-side exit in step 2.
      - If the script errors, or returns no result at all, that is a
        **failed round, not a clean one**. Escalate per step 8; do not
        let it stand in for the codex exit.

   e. **Skip this step when an external human reviewer is already
      driving the PR.** Running both produces two rounds of feedback
      on the same diff and the author side cannot tell which one it is
      waiting on.

8. **Escalate to the user** when:
   - A reviewer asked for a scope change you cannot interpret without
     guidance.
   - Tests fail in a way that suggests the fix would have to touch
     unrelated code.
   - Conflicting requests across reviewers.
   - Merge conflicts with base branch.
   - Stop the loop, summarize, ask the user how to proceed.

9. **Re-check exit conditions** (step 2) after each address cycle. A
   reviewer that approved AND left a final comment is still
   approved.

10. **After each addressed cycle, return to waiting.** Adaptive delay:
   - Just pushed a fix → 270s (cache-warm, expect quick reviewer
     turn).
   - Quiet period → 1800s.
   - User instructed "check daily" → 3600s.
   - If `ScheduleWakeup` exists and the wake-up survives turn end,
     use it; otherwise sleep and loop in-process.
   - `watch-mode=in-process-only` only remains true while the current
     invocation stays alive. An in-process sleep does not survive a
     terminal/final handoff.
   - On a host that can neither schedule a wake-up nor stay alive even
     with a blocking `sleep` (not codex), suspend with a resume handle
     per "Hosts that cannot self-schedule" instead of looping or
     stopping.
   - Keep the same delay policy in-process; do not collapse to short
     ad hoc sleeps just because the loop is already running.
   - Skip further waiting if the loop has terminated.

### Status line

Every iteration emits a single status line to the user, even when
nothing changed. Format suggestion:

```
PR #<N> r<round> | state=<OPEN/MERGED/CLOSED> head=<sha7>
watch-mode=<durable|in-process-only|suspend-resumable> anchor=<iso>
new-since-anchor=<n reviews, m issue comments, k inline comments>
action=<addressing:<id> | idle wait | exit:<reason> | watch stopped:<reason> | watch suspended:<reason>>
next=<delaySeconds>s
```

`next=<delaySeconds>s` is optional. Omit it unless a wake-up was
actually scheduled or the current invocation is about to sleep and
re-poll in-process. If the watch loop is no longer running in this
invocation, say so with the right token:

- `action=watch stopped:<reason>` — a terminal stop: approved, the
  PR merged or closed, or the user stopped the loop.
- `action=watch suspended:host cannot self-schedule; resume with
  /work-on-pr <N>` — the host has no durable scheduler and cannot
  keep the invocation alive even with a blocking `sleep` (not codex —
  see below). A resumable host limitation, not a terminal stop. See
  "Hosts that cannot self-schedule".

Never emit either token on an idle pass while the invocation is still
alive and able to re-poll.

### Pre-handoff guardrail

Before any terminal/final handoff, force this checklist:

1. Did a real stop condition fire (approval / merge / close / user
   stop)?
2. Was a durable wake-up actually scheduled?
3. Can this invocation stay alive in-process to sleep and re-poll
   (codex can — a blocking shell `sleep` holds the session open)? If
   so, do that instead of ending.
4. Is the host one that can neither schedule a wake-up nor stay alive
   even with a blocking `sleep` (not codex)? Then suspend with a resume
   handle per "Hosts that cannot self-schedule" — rule out a
   host-native trigger first, then hand back `watch suspended:host
   cannot self-schedule; resume with /work-on-pr <N>`. Never silently
   stop.
5. If none of 1, 2, or 4 applies, do not end the invocation; keep
   polling in-process.

### Auto-approved operations (self-PR workflow)

When the agent is iterating on its own PR (author side, not
reviewing someone else's), the following operations should be on
the user's `permissions.allow` list so the loop does not stall on
permission prompts every iteration. Add these patterns to
`~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(gh pr create:*)",
      "Bash(gh pr edit:*)",
      "Bash(gh pr comment:*)",
      "Bash(gh pr merge:*)",
      "Bash(gh pr ready:*)",
      "Bash(gh issue create:*)",
      "Bash(gh issue comment:*)",
      "Bash(gh issue edit:*)",
      "Bash(gh api repos/*/pulls/*/comments)",
      "Bash(gh api repos/*/pulls/*/comments/*)",
      "Bash(gh api repos/*/pulls/*/comments/*/replies)",
      "Bash(gh api repos/*/issues/*/comments)",
      "Bash(git push origin feature/*)",
      "Bash(git push -u origin feature/*)",
      "Bash(git -C * push origin feature/*)",
      "Bash(git -C * push -u origin feature/*)",
      "Bash(git -C * add:*)",
      "Bash(git -C * commit:*)",
      "Bash(git -C * status)",
      "Bash(git -C * --no-pager log:*)",
      "Bash(git -C * --no-pager diff:*)",
      "Bash(git -C * --no-pager show:*)",
      "Write(/tmp/**)",
      "Edit",
      "Write",
      "MultiEdit"
    ]
  }
}
```

**Why the `-u` push variants.** The first push of a new branch is
typically `git push -u origin feature/<name>` to set upstream
tracking. CC's allow matcher matches the full command verbatim and
does not strip flags, so `Bash(git -C * push origin feature/*)`
does NOT match a `-u` push. Both shapes are listed so the first
push and subsequent follow-up pushes are both auto-allowed.

**Why `Write(/tmp/**)`.** The skill writes commit-body, reply-body,
and PR-body heredocs to `/tmp/<file>` and passes them via
`--body-file` / `git commit -F`. The `Write` tool prompts on every
new file without this entry. `/tmp` is process-local scratch — no
risk of overwriting persistent data.

**The `Edit` / `Write` / `MultiEdit` tradeoff.** Listing the tools
without a path scope allows edits to ANY file from ANY cwd, not
just the worktree. This is the simplest way to silence per-edit
prompts because CC's allow matcher does not accept a path glob for
`Edit` / `Write` (e.g. `Edit(/path/to/repo.worktrees/**)` is not
honored). If you'd rather keep `Edit` prompting outside the loop
and only auto-allow inside the worktree, omit those three entries
and accept one prompt per file edit per iteration.

Rationale: every entry is a *write* the loop does on the agent's
own work — opening the PR, replying to its reviews, pushing
follow-up commits to its feature branch. None of them touch shared
infrastructure or master directly. Static `Bash(...)` entries in
`permissions.allow` short-circuit CC's native permission layer and
its PreToolUse hooks (see
`claude-code-static-allow-bypasses-hook`), so once these are in
place the loop runs without prompts **from CC's own permission
matcher**. A separately-installed PreToolUse hook may still
intercept — see "YOLT-specific gotcha" below for the one case we
know of in practice.

**Why the `git -C *` patterns matter.** Claude Code matches each
`Bash(...)` allow entry against the *full* command string. A
compound like `cd <worktree> && git push origin <branch>` starts
with `cd`, so `Bash(git push origin feature/*)` never fires on it
even though the second segment would match on its own. The
host's Bash-tool description is explicit:

> never prepend `cd <current-directory>` to a `git` command —
> the compound triggers a permission prompt

The loop avoids that trap by running every git operation in
single-shot form via `git -C <worktree-path>` instead of
`cd <worktree> && git ...`. The `git -C * <subcommand>` allow
entries above cover that form; the original `Bash(git push origin
feature/*)` is kept for the (rarer) case where the agent really is
in the worktree's cwd.

The same compound-matching rule applies to multi-step chains like
`git -C X commit ... && git -C X push ...`. Issue separate Bash
tool calls instead of chaining with `&&`. CC's allow matcher does
not split compounds for you.

For commands that an allowlist cannot reasonably cover — the most
common one being a quick `cat <file> | python3 -c "<inline>"`
introspection — expect a prompt. The YOLT hook (when installed)
classifies `python3 -c "<inline>"` as `unknown` rather than `safe`
because it cannot statically analyze a single-string script
without parsing it as Python, and the matcher conservatively asks.
Pulling the snippet into a real `.py` file and invoking
`python3 path/to/file.py` makes it analyzable.

What is intentionally NOT on the auto-approve list:

- `git push origin master` / `git push --force` — never auto-allow
  pushing to a default branch.
- `gh pr merge` of someone else's PR — the pattern above covers
  `gh pr merge <N>` of any PR, so use scoped prefixes
  (e.g. `Bash(gh pr merge:*)`) only when you trust the agent to
  judge merge readiness. If not, drop that one entry.
- `gh release create` — release artifacts deserve a human gate.
- `gh repo delete` / `gh repo archive` — irreversible.

### YOLT interaction (post voitta-yolt#36)

The `permissions.allow` block above composes correctly with the
`voitta-yolt` hook on builds that include
voitta-ai/voitta-yolt#36 (merged 2026-05-17, commit `e610f3e8`).
That change does two things:

1. `_maybe_allow` (in `hooks/grammar_classifier.py`) now applies
   user allow patterns to UNSAFE decisions, not just UNKNOWN. The
   classifier still labels `git add` / `git commit` / `git push`
   and `gh pr <create|comment|edit|merge|ready>` /
   `gh issue <create|comment|edit>` as UNSAFE in
   `rules/shell.json`, but a matching `Bash(...)` entry in
   `~/.claude/settings.json#permissions.allow` short-circuits the
   ask. So the patterns documented above are now sufficient on
   their own — no `~/.claude/yolt/shell.json` override needed.
2. When the hook does ask (no allow pattern matches the UNSAFE
   command), the ask body now appends a paste-ready
   `Bash(...)` hint derived from the command shape. Copy that line
   into `permissions.allow` to silence future prompts of the same
   shape.

The yolt-side enumeration is not exhaustive yet — see
voitta-ai/voitta-yolt#37 for the residual gaps (`gh pr review`
hint generation, mapped-push hint generation, friendlier
`python3 -c` SyntaxError reason). Until those land, the affected
commands will still ask without a copy-paste hint, but the allow
pattern (if you compose it by hand) still works.

If your installed yolt predates `e610f3e8`, fall back to one of:

1. Override the classification per command in
   `~/.claude/yolt/shell.json` so YOLT sees the loop's writes as
   `safe`. YOLT merges this with the bundled `rules/shell.json`
   at load:

   ```json
   {
     "commands": {
       "gh": {
         "safe_subcommands": ["pr create", "pr edit", "pr comment",
                              "pr ready", "pr merge",
                              "issue create", "issue comment",
                              "issue edit"]
       },
       "git": {
         "safe_subcommands": ["add", "commit", "push"]
       }
     }
   }
   ```

   Caveat: promoting `git push` to safe here also auto-allows
   `git push origin master` / `git push --force` from YOLT's
   perspective; the `permissions.allow` block above still does NOT
   allow those (no matching pattern), so CC's native matcher
   continues to prompt on them. The two layers compose
   restrictively — both must allow for a command to run silent.

2. Disable the YOLT plugin (`/plugin disable yolt`) for the
   duration of the loop and rely on `permissions.allow` alone.

3. Upgrade to a yolt build containing `e610f3e8` or later and
   delete any per-command override that's no longer needed.

### Codex CLI / sandbox approval flow

Codex CLI prompts differently from Claude Code: instead of a
static `permissions.allow` matched at tool-call time, it asks at
each unknown command with three options — accept once,
`Yes, and don't ask again for commands that start with <prefix>`
(option **p**), or cancel. Choose the prefix-remember option
deliberately so the loop stops re-prompting on the same shape
for the rest of the session.

Useful prefixes the loop will hit if you let Codex drive it:

- `gh api repos/<owner>/<repo>/pulls/<N>/comments/` — covers ALL
  inline review-thread replies in PR <N>, regardless of comment
  ID. Pick this when Codex asks about the FIRST
  `comments/<id>/replies` write of the round; subsequent replies
  silently match.
- `gh pr comment <N> --repo <owner>/<repo>` — covers all
  top-level reply comments on PR <N>. The `--repo` form is what
  Codex emits when the cwd is a different repo (e.g. driving a
  yolt PR from the skillz worktree).
- `git -C <worktree-path> add` — covers all per-round staging.
- `git -C <worktree-path> commit` — covers all per-round commits.
- `git -C <worktree-path> push origin` — covers feature-branch
  pushes from that worktree. Includes the `-u` first-push form.

What NOT to prefix-remember at session scope:

- `git push origin master` / `git push --force` shapes — always
  let those re-prompt.
- `gh pr merge` of someone else's PR.
- `rm -rf /` and friends.

### Merge-conflict resolution path

If the watch loop hits a merge conflict against base (step 8
escalation), and the user delegates conflict resolution back to
the loop instead of taking over, the resolution will additionally
need approvals or allow patterns for:

- `git -C <worktree> merge --no-edit origin/master` — merge base
  into PR branch.
- `git -C <worktree> rebase --continue` — alternative path if
  rebasing instead of merging.
- `git -C <worktree> push origin <branch>` (and possibly the
  mapped form `<local>:<remote>` if the worktree was created on
  a differently-named branch).
- `kill <pid>` if `git rebase --continue` spawned an interactive
  editor that hangs the loop.

These are intentionally NOT on the default `permissions.allow`
block above — conflict resolution is a structural change that
deserves its own approval per PR. On Codex CLI, expect a fresh
ask for each shape and apply the prefix-remember option
sparingly. If you intend to do many conflict resolutions in one
session, add `Bash(git -C * merge --no-edit origin/master)` to
`permissions.allow` temporarily, then remove it.

### Skill-activation prompt

The first time the host invokes this skill in a given working
directory, Claude Code shows a one-time confirmation:

```
Use skill "work-on-pr"?
 1. Yes
 2. Yes, and don't ask again for work-on-pr in <cwd>
```

Pick **option 2** so the loop doesn't pause on every restart in
the same project. This is separate from `permissions.allow` —
skill activation is gated independently.

### Pacing rules

- Anthropic prompt cache TTL is 5 min. Stay under 270s when
  expecting quick turn; jump to ≥1200s when genuinely idle. Don't
  pick 300s — worst-of-both.
- "No new comments yet" is an idle state, not a success condition.
- Sub-minute sleeps are only for explicit user overrides, not the
  default watch loop.
- One iteration = one poll / action cycle.
- Hard cap suggested: 20 idle polls without progress → stop and
  escalate to the user with the current status.

### Hosts that cannot self-schedule

Some hosts have neither a durable wake-up scheduler nor the ability to
keep one invocation alive across the wait — not even with a blocking
shell `sleep`, because the host kills long-running commands or ends the
turn while a command is still running. On such a host the loop cannot
poll itself. Do not resolve that by silently stopping — that drops
every later reviewer update on the floor.

**Codex is not such a host.** Codex executes shell commands, and a
blocking `sleep <interval>` holds the session open across polls, so
codex is `watch-mode=in-process-only`: keep polling in-process, never
suspend. Reach the resumable-suspend protocol below only on a host
where a blocking `sleep` has actually been killed.

When a host genuinely cannot self-schedule, handle it with the
**resumable-suspend protocol**:

1. **First, rule out a host-native durable trigger.** Before
   concluding the host cannot self-schedule, check for any scheduling
   primitive it does expose — a cron / scheduled-task / reminder tool
   (for example Claude Code's `ScheduleWakeup` or `CronCreate`, or a
   Codex scheduled-task entry if one exists in that session). If one
   exists, the host is actually `watch-mode=durable`: use it and stop
   here.

2. **If there is genuinely none, suspend with a resume handle.** Emit
   one explicit status line that:
   - declares `watch-mode=suspend-resumable` and
     `action=watch suspended:host cannot self-schedule; resume with
     /work-on-pr <N>`,
   - states plainly that this is a host limitation, **not** loop
     completion, approval, merge, or close,
   - records the current anchor (`anchor_ts`) so the operator can see
     where the loop paused. The resumed run re-derives all state from
     GitHub, so no local state file is needed — the anchor is
     informational.

3. **Offer the unattended option.** If the operator wants the loop to
   continue without re-typing the command, note in the suspend handle
   that any external re-trigger works: a shell `cron` entry, a CI
   schedule, or a `watch`-style wrapper that re-invokes
   `/work-on-pr <N>` on an interval. That converts a
   `suspend-resumable` host into an externally-driven `durable` one.

A resumable suspend is distinct from a voluntary idle stop. Stopping
the watch just because a few polls were idle is still forbidden;
suspending because the host physically cannot carry the loop forward,
while handing back an exact resume command, is the honest behavior for
this host class. This mirrors the reviewer-side protocol in
`review-pr-loop`.

### Reply convention

- Always reference the commit SHA: `Addressed in 6f23a45.`
- Summarize the fix in ≤4 sentences, then a short code block when
  useful.
- Don't restate the reviewer's text.
- Don't promise future work in the same PR scope — open a new issue
  if needed.
- When the host/model identity is known, prefix the reply body with
  a short tag such as `[codex]` or `[claude]` (e.g.
  `[claude] Addressed in 6f23a45.`). If the identity cannot be
  determined, omit the tag rather than guessing. This mirrors the
  reviewer-side rule in `review-pr-loop` — once a PR has several
  rounds the tag is the fastest way to scan who-said-what without
  opening every comment.

### Worktree + branch hygiene

- Branch name: `feature/<kebab-name>` (matches PRs #8-#13 lineage in
  voitta-yolt; carry-over from the user's worktree-PR memory).
- Never amend or force-push unless the user explicitly requests it.
  Add new commits per round so the review history is intact.
- Don't skip hooks (no `--no-verify`).
- Use `--body-file` everywhere (`gh pr create`, `gh pr comment`,
  `gh issue comment`) to avoid quoting traps. See
  `gh-git-heredoc-body-file`.

## Verification

After invoking, expect to see (per iteration):

- A single short user-facing update: "Iteration N on PR #X. Found M
  new comment(s). Addressing comment <id>." OR "No new comments yet
  as of <timestamp>; waiting <delay>s before the next check." The
  status line should include
  `watch-mode=<durable|in-process-only|suspend-resumable>`. If no
  durable wake-up exists but the invocation can stay alive, it polls
  in-process (codex is here — a blocking `sleep` holds the session
  open). Only on a host that can neither schedule nor stay alive even
  with a blocking `sleep` expect a `watch suspended:host cannot
  self-schedule; resume with /work-on-pr <N>` handoff instead — a
  resumable host limitation, never a silent stop.
- One commit pushed per round (only when there were actionable
  comments).
- One reply posted per addressed comment.
- When the optional step-7 self-review is enabled: one review posted
  per round, tagged `[codex]`, with a saved `/tmp/pr-<N>-review.json`
  payload that matches what was posted.
- Either a `ScheduleWakeup` call or an in-process sleep / poll loop
  unless the loop exited.
- No `final` / terminal handoff while the watch loop is still active.

When invoked with an issue reference, additionally expect:

- A new PR whose body contains `Closes #<issue>` (idempotent — the
  agent must not add a duplicate `Closes` line if one already
  exists).
- OR, if a PR for that issue already exists, the PR body edited
  exactly once to append `Closes #<issue>` if it was missing.

Exit signals:

- `reviewDecision == APPROVED` → summary + stop.
- PR merged/closed → summary + stop.
- User says "stop" / interrupts → summary + stop.
- Step-7 self-review returns zero blocking findings on two
  consecutive runs against the same head → the codex-side exit is
  satisfied. Report it and stop *reviewing*; do not merge on it alone.

Not exit signals:

- A single zero-finding self-review (step 7d).
- A self-review that errored or returned no result — that is a failed
  round, and reading it as clean is the exact shape of skillz#212.
- Any `event: COMMENT` review posted by the author identity. GitHub
  will not let that identity `APPROVE`, so its absence carries no
  information.

## Example

User: "/work-on-pr 20"

Iteration 1:
- `gh pr view 20` → state=OPEN, headRefName=`feature/foo`,
  reviewDecision=`CHANGES_REQUESTED`.
- Worktree at `<repo>.worktrees/feature/foo` doesn't exist → create.
- Anchor = head commit committed_at = `2026-05-12T18:00:00Z`.
- No review activity yet. Wait 270s via `ScheduleWakeup` (or sleep
  270s and re-poll if no scheduler exists).

Iteration 2:
- `gh pr view 20` → state=OPEN, headRefName=`feature/foo`,
  reviewDecision=`CHANGES_REQUESTED`.
- Reviews since anchor → one new review (id 999, state COMMENTED).
- Read body: "Annotation calls flagged as destructive — that's
  wrong under PEP 563."
- Implement fix in worktree, run `python3 -m unittest discover
  tests`, commit, push.
- Post reply via `gh pr comment 20 --body-file /tmp/reply.md`
  starting with "Addressed in <sha>."
- `ScheduleWakeup(delaySeconds=270, prompt="/work-on-pr 20",
  reason="just pushed reply to review 999; expect fast turnaround")`

Iteration 3 (270s later):
- Anchor = new head commit committed_at.
- No new reviews/comments. Bump to `ScheduleWakeup(delaySeconds=1800,
  ...)`

Iteration 8:
- Latest review state == APPROVED → exit. Final summary:
  "PR #20 approved by @reviewer in 7 rounds. Ready to merge."

### Example: issue-mode invocation

User: "/work-on-pr Issue https://github.com/voitta-ai/voitta-yolt/issues/18, start a PR"

Iteration 1:
- Parse arg → issue ref: owner=`voitta-ai`, repo=`voitta-yolt`, N=18.
- Search for an open PR linking issue 18 → none.
- Read issue body. Implement the scoped work in a fresh worktree
  on `feature/issue-18-<slug>` tracking `origin/master`.
- `gh pr create --body-file /tmp/pr.md` where the body contains
  a `## Summary` section and the line `Closes #18`.
- Confirm in the PR's `body` field that `Closes #18` is present
  (idempotency guard: do not add a second `Closes #18` if one is
  already there).
- Enter the watch loop on the just-created PR.

Iteration 2+: identical to the PR-mode flow above.

### Example: existing PR + missing `Closes`

User: "/work-on-pr Issue https://github.com/foo/bar/issues/42"

- Parse arg → issue ref. PR search finds open PR #99 on a branch
  whose name contains `issue-42`.
- `gh pr view 99 --json body` → body lacks any `Closes #42` /
  `Fixes #42` / `Resolves #42`.
- `gh pr edit 99 --body-file /tmp/pr-body.md` with the original
  body + `\n\nCloses #42\n` appended.
- Continue with normal watch loop on PR 99.

## Notes

- **State derivation, not persistence**: each invocation re-derives
  what's new from GitHub timestamps and the bot's own posted
  comments. No local state file is needed.
- **Invoking before comments exist is expected.** The skill's job is
  to watch the PR until feedback arrives, not to treat an empty poll
  as completion.
- **Approval phrase detection** is heuristic. A maintainer comment
  with the literal words "I approve" without using the GitHub
  approve button counts here; if false-positive risk is high in a
  given project, restrict to the `reviewDecision` field only.
- **Inline review comments** (`pulls/N/comments`) are threaded;
  replying requires `--in-reply-to` or the dedicated `/replies`
  endpoint. Issue comments use `gh pr comment` / `gh issue comment`.
- **An unresolved thread is a merge blocker, and the loop's own review
  creates threads.** Seen on a PR whose only review was the step-7 codex
  round: one inline finding, addressed and replied to, still left the
  merge button reading `All comments must be resolved`, because the
  repo's branch protection requires conversation resolution and a reply
  does not resolve. Step 6g exists for that. The rule is invisible to
  non-admins through REST (`branches/<b>/protection` returns 404); read
  it through GraphQL `ref.refUpdateRule.requiresConversationResolution`.
- **Worktree cleanup**: don't remove the worktree until the PR
  merges. After merge, `git worktree remove <path> && git branch -D
  <branch>`.
- **gh CLI vs API**: prefer `gh pr view --json` for top-level state;
  drop to `gh api` for the per-thread surfaces and for fields the
  high-level commands don't expose (committed_at, individual review
  bodies by ID).
- **Issue closing keywords**: GitHub honors `close[sd]?`, `fix(es|ed)?`,
  `resolve[sd]?` (case-insensitive) followed by `#N` or
  `owner/repo#N`. The detection regex must accept all of these so
  the skill does not append a second `Closes #N` when the user
  already wrote `Fixes #N`. Default to `Closes #N` when adding one,
  since "closes" is the most generic verb.
- **Idempotency**: every issue-linkage step must be safe to re-run.
  The repair appends exactly one `Closes #N` line, only when none
  of the recognized keywords match `#N` in the existing body. The
  same holds for PR-create when an issue ref is supplied — never
  emit a second `Closes #N`.
- **Self-review is not independent review.** One agent acting as both
  author and adversarial reviewer of its own diff shares the author's
  blind spots, and the author side still chooses which findings to
  accept. A separate model and process (step 7) narrows that, it does
  not remove it. This is why the codex exit in step 2 stops the review
  loop but never merges, and why a zero-finding round is treated as
  suspicious rather than as a pass: a loop that grades its own
  homework fails silently and reads as success.
- **Bumping the version**: when editing this skill, increment
  `version:` in the frontmatter so installed copies can be compared
  against the canonical source.
- **Scheduler fallback**: if `ScheduleWakeup` is unavailable in the
  host agent, keep the current turn alive with `sleep` + re-poll
  instead of returning "nothing to do". On codex this is the normal
  mode: a blocking shell `sleep <interval>` holds the session open
  between polls. `watch-mode=in-process-only` only remains valid while
  that invocation stays alive; a `final` handoff ends it. Only if the
  host can do neither — no durable scheduler and a blocking `sleep` is
  killed or the turn ends while it runs — use the resumable-suspend
  protocol in "Hosts that cannot self-schedule": rule out a
  host-native trigger, then hand back an exact `resume with
  /work-on-pr <N>` command rather than dropping the loop.
- **Approval-aware execution**: in constrained sandboxes, `git add` /
  `git commit` may need approval for shared git metadata writes, and
  `git push` / `gh pr comment` / inline `gh api` replies may need
  approval for network writes. Anticipate those operations, keep the
  command forms stable so prefix approvals can be reused, and do not
  treat "approval needed" as loop completion.
- **Multiple new comments in one wake-up**: address them in
  submitted_at order; one commit per coherent fix-set is fine, as
  long as each addressed comment gets its own reply with the same
  commit SHA referenced.
- **CI failures** that come in as a check (not a review) can be
  treated like a comment if the user opted into "address CI
  failures too"; default is to surface CI failures to the user
  rather than auto-fix.
- **GitHub list-endpoint cache staleness (the #33 quirk).** The
  list endpoints (`/issues/<N>/comments`, `/pulls/<N>/reviews`,
  `/pulls/<N>/comments`) can return `[]` for many minutes after a
  fresh PR is opened, even when a real comment / review already
  exists at the origin and can be fetched by ID. The PR timeline
  endpoint
  (`/issues/<N>/timeline`) and single-resource lookups
  (`/issues/comments/<id>`, `/pulls/<N>/reviews/<id>`,
  `/pulls/comments/<id>`) appear to be less aggressively cached and
  surface the activity quickly. Watch-style loops MUST use the
  timeline fallback in step 4 instead of trusting an `[]` list
  result on a young PR, or an LGTM / changes-requested signal can
  sit invisible for 10+ minutes per poll. Treat back-to-back `[]`
  list polls within ~5 minutes as cache-suspicious and force the
  fallback. The same caveat likely applies to other GitHub watch
  workflows that poll list endpoints, so consider extracting a
  shared `gh-api-list-cache-staleness` skill if a second use site
  appears.

## References

- [GitHub REST: list reviews on a PR](https://docs.github.com/en/rest/pulls/reviews)
- [GitHub REST: list issue comments](https://docs.github.com/en/rest/issues/comments)
- [GitHub REST: list review comments on a PR](https://docs.github.com/en/rest/pulls/comments)
- [gh pr view / gh pr comment](https://cli.github.com/manual/gh_pr)

## Related

- `review-pr-loop` — the reviewer side of the same loop. Use it when the
  reviewer is a genuinely separate person, or when the review is a
  conversational multi-round exchange rather than a findings dump.
- `codex-adversarial-pr-review` — the step-7 reviewer this skill can drive
  itself. Preferred over `review-pr-loop` when both sides run under one
  operator and one GitHub identity, because a login-based "is this mine?"
  filter cannot tell the two apart.
- `parallel-agent-session-collisions` — before claiming the branch or worktree
  this loop works in, and the shared-counter trap if the repo has one.
- `git-worktree-convention` — the layout this skill's worktrees follow.
- `python-ast-static-analyzer-scoping` — a worked example of an iterative
  review cycle this skill drove.

The body-file pattern for `gh` bodies lives in `gh-git-heredoc-body-file`, in
the sibling `skillz-memory` repo rather than this catalog.
