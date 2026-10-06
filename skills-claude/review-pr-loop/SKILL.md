---
name: review-pr-loop
description: |
  Iteratively review a GitHub pull request across multiple rounds. Each round, read the linked issue(s), prior review comments, issue comments, and inline threads before reviewing only the new diff or the author's latest response. If no author response exists yet, wait and re-check instead of exiting. Leave structured feedback (REQUEST_CHANGES, COMMENT, or APPROVE) and continue until you approve, the PR is merged or closed, or the user stops the loop. Use when you are the reviewer on a non-trivial PR and want the agent to own the back-and-forth review cycle rather than doing a one-shot review.
author: Claude Code
version: 1.8.0
date: 2026-06-22
source: https://github.com/voitta-ai/skillz
source_file: skills/review-pr-loop/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/review-pr-loop/SKILL.md`).
> Updates go through the repo's worktree + PR workflow. The repo replaced
> gist 5f606018eb36a75dc292016268f08e7c, which is preserved as a redirect.

# review-pr-loop

## Problem

Reviewing a PR across multiple rounds requires more than reading the
newest diff. Each round you need to:

- (Re)read the underlying issue(s) the PR claims to address so you
  can check that the PR actually solves the stated problem (not just
  whatever the author chose to implement).
- Read ALL prior review comments and issue comments — yours and
  others' — so you don't repeat feedback already given, don't miss
  prior context, and don't lose track of items that were promised
  but not yet addressed.
- Diff only the *new* commits since your last review so you don't
  re-review code you already approved.
- Leave structured feedback (REQUEST_CHANGES if anything blocks,
  COMMENT if observations only, APPROVE if done).
- Wait for the author to push and respond, then re-evaluate.

This loop is mechanical and easy to short-cut. The skill codifies it
so each round is consistent.

## Context / Trigger Conditions

Invoke when:

- User says "review PR #N", "watch PR #N for changes and re-review",
  "review this PR loop", "act as reviewer on PR #N".
- You are the assigned or self-appointed reviewer on a PR and the
  author is iterating, or you want the agent to keep waiting for the
  next author response / push.

Do NOT use when:

- You are the PR author — use `work-on-pr` instead.
- You and the "reviewer" are the same operator posting under one
  GitHub identity, and what you actually want is an adversarial pass
  per round — use `codex-adversarial-pr-review`, driven from
  `work-on-pr` step 7. One deterministic script call per round beats a
  second agent roleplaying a reviewer: no pacing or self-scheduling
  machinery to get wrong, no drift between rounds, and it carries the
  salvage path for the companion's flaky parse (skillz#212). Note the
  ceiling: that identity cannot `APPROVE` its own PR, so the loop exits
  on zero findings rather than on a review state. Keep **this** skill
  for a genuinely separate reviewer identity, or when the multi-round
  conversation with a human author is itself the point.
- A one-shot review is enough — use `pr-review-toolkit:review-pr`.
- The PR is already approved or merged.

## Solution

One invocation owns the watch loop. If there is no new author
activity yet, that is an idle wait state, not completion: keep
waiting and re-checking. Prefer `ScheduleWakeup` when the host
supports it and the wake-up survives the current turn; otherwise
sleep and poll again in the same invocation. Do not return just
because one idle poll or sleep completed. An idle pass is never a
terminal condition; it must either schedule a real wake-up or stay
alive for the next in-process poll.

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

If the active mode is `watch-mode=in-process-only`, a final response
stops the watcher. Do not choose to end the turn after a small number
of idle polls just because no durable scheduler exists. In-process-only
means "keep this invocation alive with `sleep` + re-poll" until a real
stop condition fires, the user stops the loop, or the host/runtime
forces termination.

While the loop is active, do not send a terminal/final handoff
message just to summarize status. Use progress/status updates only.
Only end the invocation when one of these terminal conditions fires:
you approved / said `LGTM` or equivalent, the PR merged or closed, or
the user explicitly stopped the loop. The only non-terminal handoffs
that may end the current iteration are a real durable wake-up that was
actually scheduled, or — on a host that can neither schedule a wake-up
nor stay alive in-process — a resumable suspend that hands back an
exact resume command (see "Hosts that cannot self-schedule"). Idle
passes, approval prompts, and empty polls are never completion. Each
iteration:

1. **Pull full context first — every round.** This is the most
   important rule.

   a. **Linked issue(s).** From the PR body, find `Closes #N`,
      `Fixes #N`, `Refs #N`, or any GitHub issue URL. For each:
      - `gh issue view <N> --comments` — body and all comments.
      - Note the acceptance criteria, reproductions, design notes.
      - The PR must address *those* requirements, not just whatever
        the author wrote.

   b. **All prior reviews on this PR.**
      - `gh api repos/:owner/:repo/pulls/<N>/reviews` — every review,
        not just yours, in submitted_at order.
      - For each, fetch body + any inline review-comment thread:
        `gh api repos/:owner/:repo/pulls/<N>/reviews/<id>/comments`
      - Build a mental ledger of: what was raised, who raised it,
        whether the author addressed it, whether the addressor
        explicitly confirmed.

   c. **All issue comments on this PR.**
      - `gh api repos/:owner/:repo/issues/<N>/comments`.
      - Include the author's "Addressed in <sha>" replies — those
        index which commits map to which feedback.

   d. **All inline review comments** (the diff-anchored threads):
      - `gh api repos/:owner/:repo/pulls/<N>/comments` returns the
        flat list; threads are reconstructed via `in_reply_to_id`.

   Skipping this step is the most common review failure mode: you
   re-raise an objection that was already discussed three rounds
   ago, or you miss that an earlier promise was never delivered.

2. **Resolve PR coordinates.**
   - `gh pr view <N> --json
     number,state,headRefName,headRefOid,baseRefName,mergeable,
     reviewDecision,url,body`.
   - If `state != OPEN` → stop, no reschedule.

3. **Check exit conditions.**
   - `reviewDecision == APPROVED` AND latest APPROVED review is
     yours → stop, already done.
   - If this is a self-review and your latest review/comment on the PR
     clearly expresses approval (`LGTM`, `APPROVE`, or equivalent,
     optionally prefixed with a model tag), treat that as goal reached
     and stop unless the user explicitly asked you to keep watching
     through merge / close.
   - PR merged/closed → stop.

4. **Determine what's new since your last review.**
   - "Last review anchor" = `submitted_at` of your last review on
     this PR, or `null` if none.
   - From `gh api repos/:owner/:repo/pulls/<N>/commits`, list
     commits added after `anchor`. These define the new diff scope.
   - From comment surfaces, list author responses since `anchor`.
   - **Shared-identity caveat (do not identify "author responses" by
     login alone).** Distinguishing the author's posts from your own
     by GitHub login only works when the author and you post under
     *distinct* identities. When one operator drives both this loop
     and the paired `work-on-pr` under the **same** GitHub login (you
     tag `[codex]`, the author side tags `[claude]`, both posting as
     the same user), a `select(.user.login != "<me>")` filter hides
     the author's replies and the loop never sees them. Under shared
     identity, discriminate by `timestamp > anchor` **plus** the model
     tag (`[claude]` vs `[codex]`) in the body, not by login: anything
     newer than your anchor that you did not just post is an author
     response. Reserve the login-based filter for genuinely separate
     identities. See the `docs/pr-review-workflow.md` "GitHub identity
     caveat" and `work-on-pr`.
   - If there are no new commits and no new author responses since
     `anchor`, skip the review steps for this pass and go to step 10.

5. **First round (no prior review by you)**:
   - Treat the entire PR diff as in scope.
   - Reconcile diff against the underlying issue's acceptance
     criteria from step 1a.
   - Optionally delegate the detailed code-quality pass to
     `pr-review-toolkit:review-pr` (one-shot) and consume its output
     as input to your synthesis.

6. **Subsequent rounds**:
   - Diff = commits since your last review:
     `gh api repos/:owner/:repo/compare/<your-last-review-sha>...<headRefOid>`
   - For each prior finding of yours not yet resolved, check whether
     the new commits address it.
   - For each new author reply ("Addressed in <sha>"), verify the
     cited commit actually fixes the cited concern.
   - Check for regressions in unrelated code (the author may have
     "fixed" one issue and broken another).

7. **Synthesize the review.**

   Structure findings as severity-tagged one-liners:
   - **blocking**: must fix before merge.
   - **non-blocking**: nit / suggestion.
   - **resolved**: prior concern now addressed (record this so it
     doesn't reappear).

   For each blocking finding, write a self-contained reproduction
   or concrete example. Reviewer one-liners that compress 4
   different concerns into one sentence force the author to guess.

8. **Decide the review event.**
   - Any blocking finding remains → `REQUEST_CHANGES` (or
     `COMMENT` if the project prefers non-blocking events; check
     prior reviews on this PR for the convention).
   - No blocking findings AND all prior concerns resolved AND PR
     addresses the linked issue → `APPROVE`.
   - No blocking findings but unresolved questions → `COMMENT`.

9. **Leave the review.**
   - Single-shot review with inline comments:
     `gh pr review <N> --request-changes --body-file /tmp/body.md`
     `gh pr review <N> --approve --body-file /tmp/body.md`
     `gh pr review <N> --comment --body-file /tmp/body.md`
   - Inline comments anchored to specific lines: use
     `gh api -X POST repos/:owner/:repo/pulls/<N>/reviews
      -f body=... -f event=...
      -f 'comments[][path]=...' -f 'comments[][line]=...'
      -f 'comments[][body]=...'`
     so each blocking finding lands next to the offending line.
   - Prefer inline comments whenever a finding maps cleanly to a line
     in the current diff. A single review pass may therefore submit one
     top-level review body plus several inline file comments.
   - Use `--body-file`, not `-b`, to dodge shell quoting (see
     `gh-git-heredoc-body-file`).
   - In approval-gated sandboxes, preflight the write operations
     likely to recur in this loop: `gh pr review` and any inline
     `gh api .../reviews` posts. Reuse already-approved prefixes when
     possible, and do not treat "approval needed" as loop completion.
   - When the host/model identity is known, prefix every submitted
     top-level review body and inline comment with a short tag such as
     `[codex]` or `[claude]`. If the identity cannot be determined,
     omit the tag rather than guessing.

10. **Schedule next wake-up** unless the loop terminated.
    - Default cadence: **30 seconds**, every pass, idle or active.
    - If the user asks for a different cadence (for example
      "slow down to 180s"), treat that as the active poll interval for
      the rest of the invocation unless the user changes it again.
    - The loop continues until a stop condition fires (you approved /
      said `LGTM` or equivalent, PR merged/closed, or user
      interrupts). Only those terminal conditions end the loop;
      everything else, including idle passes, reschedules.
    - If `ScheduleWakeup` exists and actually survives the current
      turn in this host, use it.
    - Otherwise sleep for the active poll interval and loop
      in-process, but only if the invocation is staying alive. An
      in-process sleep does not survive a `final` handoff.
    - If the host has no durable scheduler AND cannot keep this
      invocation alive even with a blocking `sleep` (the host kills the
      sleep or ends the turn while it runs — codex does neither),
      do not claim polling will continue and do not silently stop.
      Follow the resumable-suspend protocol in "Hosts that cannot
      self-schedule" below: rule out a host-native trigger first, then
      hand back `action=watch suspended:host cannot self-schedule;
      resume with /review-pr-loop <N>`.
    - **Surface status every tick.** Each pass emits one short
      user-facing line so the operator can see what changed (or
      didn't) without opening GitHub. See "Status line" below.

### Pacing

- Target poll interval: **30 seconds** (idle and active alike).
  Frequent polling burns cache but matches user-stated preference
  for tight visibility on PR turnaround.
- A user-provided override (for example `180s`) replaces the default
  cadence for the rest of the invocation and should be reflected in
  every status line's `next=<delaySeconds>s`.
- Runtime caveat: some hosts clamp `ScheduleWakeup`; Claude
  Code, for example, clamps `delaySeconds` to `[60, 3600]`, so
  wake-up-based loops there bottom out at 60s. To honor the 30s
  target exactly on such hosts, drive the loop with an in-process
  `sleep 30` + re-poll within the same invocation rather than via
  `ScheduleWakeup`. Otherwise treat the host's clamp floor as the
  effective minimum.
- Only print `next=<delaySeconds>s` when the next wake-up is real:
  either a durable wake-up was scheduled or the current invocation is
  definitely staying alive to sleep and re-poll. If neither is true,
  branch on *why*, do not gate on whether the host is "forcing
  termination":
  - a host that CAN stay alive in-process (codex included — a blocking
    shell `sleep` holds the session open) does another sleep/poll
    cycle instead of reporting completion;
  - a host that can neither schedule a wake-up nor stay alive even with
    a blocking `sleep` (the sleep is killed or the turn ends while it
    runs) takes the resumable-suspend path in "Hosts that cannot
    self-schedule" and hands back `watch suspended:host cannot
    self-schedule; resume with /review-pr-loop <N>` — never the
    impossible in-process loop.
- The user can override by passing an explicit interval to /loop
  or by saying "slow down to <N>s"; keep using that override on
  subsequent passes until changed.
- Stop conditions still take precedence over the cadence — never
  reschedule after approve / merge / close / user-stop.

### Hosts that cannot self-schedule

Some hosts have neither a durable wake-up scheduler nor the ability to
keep one invocation alive across the wait — not even with a blocking
shell `sleep`, because the host kills long-running commands or ends the
turn while a command is still running. On such a host the loop cannot
poll itself. Do not resolve that by silently stopping.

**Codex is not such a host.** Codex executes shell commands, and a
blocking `sleep <interval>` holds the session open across polls, so
codex is `watch-mode=in-process-only`: keep polling in-process, never
suspend. The skill's originating issue reported a Codex reviewer that
"polled a few rounds, then declared 'no durable wake-up scheduler, so
the in-process watcher is stopped here' and dropped every later author
update" — note it had already polled several rounds in one session,
which proves codex stays alive in-process. The fix for that failure is
to keep sleeping and re-polling, not to suspend. Reach the
resumable-suspend protocol below only on a host where a blocking
`sleep` has actually been killed.

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
     /review-pr-loop <N>`,
   - states plainly that this is a host limitation, **not** loop
     completion, approval, merge, or close,
   - records the current anchor (your last-review `submitted_at`, or
     `none`) so the operator can see where the loop paused. The
     resumed run re-derives all state from GitHub, so no local state
     file is needed — the anchor is informational.

3. **Offer the unattended option.** If the operator wants the loop to
   continue without re-typing the command, note in the suspend handle
   that any external re-trigger works: a shell `cron` entry, a CI
   schedule, or a `watch`-style wrapper that re-invokes
   `/review-pr-loop <N>` on an interval. That converts a
   `suspend-resumable` host into an externally-driven `durable` one.

A resumable suspend is distinct from a voluntary idle stop. Stopping
the watch just because a few polls were idle is still forbidden (see
"Anti-pattern"); suspending because the host physically cannot carry
the loop forward, while handing back an exact resume command, is the
honest behavior for this host class.

### Status line

Every iteration emits a single status line to the user, even when
nothing changed. Format suggestion:

```
PR #<N> r<round> | state=<OPEN/MERGED/CLOSED> head=<sha7>
watch-mode=<durable|in-process-only|suspend-resumable> last-author-activity=<iso>
new-since-last=<n commits, m comments>
action=<leaving REVIEW | idle wait | exit:<reason> | watch stopped:<reason> | watch suspended:<reason>>
next=<delaySeconds>s
```

If a review was posted this pass, also include the event type and a
1-line digest of findings. If the pass was idle, that fact alone is
the status — do not pad with prose.

`next=<delaySeconds>s` is optional. Omit it unless a wake-up was
actually scheduled or the current invocation is about to sleep and
re-poll in-process.

If the watch loop is no longer running in this invocation, say so
explicitly instead of implying polling is still happening, and use the
right token for why:

- `action=watch stopped:<reason>` — a terminal stop: you approved /
  said `LGTM`, the PR merged or closed, or the user stopped the loop.
- `action=watch suspended:host cannot self-schedule; resume with
  /review-pr-loop <N>` — the host has no durable scheduler and cannot
  keep the invocation alive even with a blocking `sleep` (not codex —
  see below). This is a resumable host limitation, not a terminal
  stop. See "Hosts that cannot self-schedule".

Never emit either token on an idle pass while the invocation is still
alive and able to re-poll. Lack of a durable wake-up is not itself a
terminal stop condition — on a host that can stay alive in-process it
just reschedules; on a host that cannot, it suspends with a resume
handle.

### Pre-handoff guardrail

Before any terminal/final handoff, force this checklist:

1. Did a real stop condition fire (approve / `LGTM` / merge / close /
   user stop)?
2. Was a durable wake-up actually scheduled?
3. Can this invocation stay alive in-process to sleep and re-poll
   (codex can — a blocking shell `sleep` holds the session open)? If
   so, do that instead of ending.
4. Is the host one that can neither schedule a wake-up nor stay alive
   even with a blocking `sleep` (not codex)? Then suspend with a resume
   handle per "Hosts that cannot self-schedule" — rule out a
   host-native trigger first, then hand back `watch suspended:host
   cannot self-schedule; resume with /review-pr-loop <N>`. Never
   silently stop.
5. If none of 1, 2, or 4 applies, do not end the invocation; keep
   polling in-process.

### Tone

- One line per finding, severity-tagged.
- No praise, no scope creep, no formatting nits unless they change
  meaning.
- Match the project's reviewer convention by reading prior reviews
  (step 1b) — some projects prefer batched threads, others prefer
  inline comments.
- Keep model tags terse: `[codex] blocking: ...`, `[claude] LGTM ...`.

### Auto-approved operations (reviewer workflow)

The reviewer loop's writes are narrower than the author loop's,
but they still prompt every round without an allow list. Add
these patterns to `~/.claude/settings.json#permissions.allow`:

```json
{
  "permissions": {
    "allow": [
      "Bash(gh pr review:*)",
      "Bash(gh pr comment:*)",
      "Bash(gh api repos/*/pulls/*/reviews)",
      "Bash(gh api repos/*/pulls/*/comments)",
      "Bash(gh api repos/*/pulls/*/comments/*/replies)",
      "Bash(gh issue comment:*)",
      "Write(/tmp/**)"
    ]
  }
}
```

- `gh pr review` is THE main reviewer write — `--approve`,
  `--request-changes`, `--comment`. The default voitta-yolt
  bundle classifies it as UNSAFE; on yolt builds containing
  voitta-ai/voitta-yolt#36 the explicit allow pattern is
  honored (see `work-on-pr` for the equivalent author-side
  notes).
- The `/reviews` POST and `/comments/<id>/replies` POST entries
  cover the inline-comment path when `gh pr review` is not
  enough.
- `Write(/tmp/**)` covers the heredoc-to-file pattern used for
  every review body (`/tmp/body.md`, `/tmp/r<N>.md`,
  `/tmp/approval.md`). Heredoc files must live in `/tmp/`, not
  in the cwd — same convention as `work-on-pr`.

### Avoiding the python3 `-c` inline-script prompt

For any non-trivial introspection (regex tests, fnmatch checks,
JSON shape verification), prefer writing the snippet to a real
`.py` file under `/tmp/` and invoking it as
`python3 /tmp/<name>.py`, rather than `python3 -c "<inline>"`.

The voitta-yolt hook classifies inline `-c` scripts as
`unknown (SyntaxError)` — it can't statically analyze a script
delivered as a single string without parsing it as Python — and
the matcher conservatively asks. A real file at `/tmp/<name>.py`
is analyzable and routes through the safe path.

The `Write(/tmp/**)` allow entry above already covers creating
the script file. Add `Bash(python3 /tmp/*)` to
`permissions.allow` if you also want to silence the run prompt.

### Test-merge into base: prefer worktree to `/tmp` reclone

A common reviewer subroutine — testing that the PR's branch
merges cleanly into current master before approving — has a
trap shape:

```
cd /tmp && rm -rf skillz-mergetest && \
  git clone <local-or-remote> skillz-mergetest && \
  cd skillz-mergetest && git fetch origin <pr-branch>:<pr-branch> && \
  git checkout <pr-branch> && git merge origin/master --no-edit
```

That single chain contains `rm -rf`, `git clone`, `git checkout`,
`git merge` — four mutating verbs in one compound, which any
analyzer will flag and which compound-matches no single allow
entry.

Use a fresh worktree on the PR's branch instead:

```
git -C <main-repo> fetch origin \
  <pr-branch>:refs/remotes/origin/<pr-branch>
git -C <main-repo> worktree add \
  <main-repo>.worktrees/mergetest-<N> origin/<pr-branch>
git -C <main-repo>.worktrees/mergetest-<N> merge --no-edit origin/master
# verify, then:
git -C <main-repo> worktree remove <main-repo>.worktrees/mergetest-<N>
```

One git operation per Bash tool call, no `rm -rf`, no clone, and
the worktree is registered against the original repo so cleanup is
`git worktree remove`. The path is the sibling
`<repo>.worktrees/` directory from `git-worktree-convention`, and
it must be **absolute** — a relative path resolves against the cwd
and nests the worktree inside the repo. The same
`git -C * <subcommand>` allow patterns from `work-on-pr` cover
most of this; `git -C * merge`
and `git -C * worktree add/remove` are the remaining shapes that
may prompt.

**Why the explicit `<pr-branch>:refs/remotes/origin/<pr-branch>`
refspec.** A plain `git fetch origin <pr-branch>` only guarantees
that `FETCH_HEAD` is updated. Whether it also updates
`refs/remotes/origin/<pr-branch>` depends on the remote's fetch
refspec config and on whether the branch is already known
locally — on a fresh clone or a worktree that has never seen the
PR branch, the tracking ref is NOT created, and the next
`git worktree add ... origin/<pr-branch>` fails with
`fatal: invalid reference`. The explicit `<src>:<dst>` refspec
forces creation of the tracking ref every time, so the worktree
add is unconditional. (Alternative: `git worktree add --detach
<path> FETCH_HEAD` works too if you don't care about the symbolic
name, but `origin/<pr-branch>` reads better and matches what the
worktree's status line will show.)

### Approval

When approving, include a one-sentence summary of what's done in
this round (not the whole PR history). The author already has the
history.

**Reviewing your own PR.** GitHub rejects `--approve` and
`--request-changes` events when the reviewer is the PR author
(`GraphQL: Review Can not approve / request changes on your own
pull request`). On self-review, use `--comment` and include explicit
LGTM / "blocking" language so the paired `work-on-pr` skill (or a
later merger) can read intent. Unless the user explicitly asked to
keep watching through merge / close, an explicit self-review approval
comment counts as goal reached for this review loop and should stop the
watch. Do not retry the same `--approve` call expecting a different
answer.

## Verification

After invoking, expect (per iteration):

- A short user-facing update: "Reviewing PR #N round R. Read issue
  #X (acceptance criteria: ...), K prior reviews, M issue comments.
  Found F blocking, G non-blocking. Leaving <REQUEST_CHANGES /
  COMMENT / APPROVE>." OR "No author activity since <timestamp>;
  waiting <delay>s before the next check." If no durable wake-up
  exists but the invocation can stay alive, it polls in-process (codex
  is here — a blocking `sleep` holds the session open). Only on a host
  that can neither schedule nor stay alive even with a blocking `sleep`
  expect a `watch suspended:host cannot self-schedule; resume with
  /review-pr-loop <N>` handoff instead — a resumable host limitation,
  never a silent stop.
- One `gh pr review` call.
- Either a `ScheduleWakeup`, an in-process sleep / poll loop, or
  termination.
- No `final` / terminal handoff while the loop is still in watch mode.

Exit signals:

- You approved → stop.
- PR closed/merged → stop.
- User stops loop → stop.
- 20 idle wake-ups → notify/escalate to the user, but keep polling
  unless the user explicitly stops the loop.

Anti-pattern:

- Do not poll a few times, see no author activity, and then finish by
  declaring "no durable wake-up scheduler, so the watcher is stopped"
  (the exact failure this skill's originating issue reported). That
  drops later author updates on the floor. If no durable wake-up
  exists, the loop stays alive in-process — codex included, via a
  blocking shell `sleep` between polls. Hand back a resumable suspend
  only on a host where a blocking `sleep` is actually killed, with an
  exact `resume with /review-pr-loop <N>` command — never a silent
  stop, and never a suspend on codex.

## Example

User: "/review-pr-loop 20"

Iteration 1:
- PR body: "Closes #16. Follow-up to #14."
- `gh issue view 16 --comments` → acceptance criteria:
  three reproductions must classify as `unsafe`.
- `gh api .../pulls/20/reviews` → empty (first round).
- Diff of all commits → 1 author commit.
- Cross-check diff against #16's three repros. Find:
  - blocking: alias resolution is source-order dependent.
  - blocking: imports inside dead branches still bind.
- `gh pr review 20 --request-changes --body-file /tmp/r1.md`
- `ScheduleWakeup(270s, "/review-pr-loop 20", reason="left
  REQUEST_CHANGES; expect quick turnaround")`

Iteration 2 (after author push):
- Re-read issue #16 (still same).
- Read prior reviews (round 1 by me + 1 author reply).
- New commits since my last review = 1.
- Verify the two prior blocking findings are addressed by the
  new commit.
- Find: blocking — top-level rebind retroactively erases an
  earlier destructive call. Leave REQUEST_CHANGES with the
  concrete repro.
- Sleep 270s.

... continue until:

Iteration 6:
- All prior blocking concerns resolved.
- Latest commit only adds annotation walk → identifies a new
  false-positive risk (PEP 563). Leave REQUEST_CHANGES.

Iteration 7:
- Author removed annotation walk. Re-read everything. No new
  blocking. `gh pr review 20 --approve --body-file /tmp/approval.md`
- Stop.

## Notes

- **Reading the linked issue every round is non-negotiable.** PR
  scope creep is easy to miss when you only look at the diff. A
  good check: can you state the acceptance criteria from the issue
  in your own words before reviewing the diff? If not, re-read.
- **Reading ALL comments every round** matters because:
  - The author may have explicitly responded to a prior concern in
    a comment without including it in a commit — verify the response
    actually resolves the concern.
  - Another reviewer may have raised a separate concern in parallel
    that you should not contradict without acknowledging.
  - The issue itself may have been updated by the user mid-cycle.
- **Diff scope**: review only commits since your last review unless
  this is your first round. Don't re-review approved code.
- **Invoking before the author responds is expected.** The skill's
  job is to keep watching until there is something new to review.
- **In a multi-reviewer PR**, prefer leaving comments addressed to
  the specific author's last response rather than top-level
  comments, so threads stay coherent.
- **First-round delegation**: for the initial sweep, consider
  spawning `pr-review-toolkit:review-pr` as an inner step to get a
  thorough quality pass; consume its output and add issue-fit
  reasoning on top. Subsequent rounds are usually narrow enough to
  do directly.
- **Approval phrase in comments**: if you choose to communicate
  approval via a plain comment ("LGTM") rather than the GitHub
  approve button, the paired `work-on-pr` skill recognizes this.
  Prefer the explicit `--approve` event so `reviewDecision`
  reflects it.
- **gh CLI vs API**: `gh pr review` for the event; `gh api` for
  per-thread inline comments and for fetching review bodies by ID.
- **Scheduler fallback**: if `ScheduleWakeup` is unavailable in the
  host agent, keep the current turn alive with `sleep` + re-poll
  instead of returning early on an idle pass. On codex this is the
  normal mode: a blocking shell `sleep <interval>` holds the session
  open between polls. `watch-mode=in-process-only` only remains valid
  while that invocation stays alive; a `final` handoff ends it. Only if
  the host can do neither — no durable scheduler and a blocking `sleep`
  is killed or the turn ends while it runs — use the resumable-suspend
  protocol in "Hosts that cannot self-schedule": rule out a host-native
  trigger, then hand back an exact `resume with /review-pr-loop <N>`
  command rather than dropping the loop.
- **Approval-aware execution**: in constrained sandboxes, GitHub
  review submissions and inline review-comment writes may need
  approval. Ask once with stable command shapes if needed, then keep
  the loop going until a real stop condition fires.

## References

- [GitHub REST: pulls/reviews](https://docs.github.com/en/rest/pulls/reviews)
- [GitHub REST: pulls/comments (inline)](https://docs.github.com/en/rest/pulls/comments)
- [GitHub REST: issues/comments (top-level)](https://docs.github.com/en/rest/issues/comments)
- [gh pr review](https://cli.github.com/manual/gh_pr_review)

## Related

- `work-on-pr` — the author side of the same loop, and the skill that decides
  what this one is reviewing.
- `codex-adversarial-pr-review` — preferred over this skill when one operator
  drives both sides under one GitHub identity; that same-login case is the one
  this skill cannot filter by author.
- `parallel-agent-session-collisions` — when a second session is reviewing or
  pushing to the same PR.

For a one-shot review rather than a loop, the `pr-review-toolkit` plugin ships
`review-pr`. The body-file pattern for `gh` bodies lives in
`gh-git-heredoc-body-file`, in the sibling `skillz-memory` repo.
