---
name: parallel-agent-session-collisions
description: |
  Avoid duplicating, superseding, or clobbering work done by another agent
  session (or teammate) operating on the same repos concurrently. Use when:
  (1) you are about to open a PR and have not checked whether one already exists
  for the same change, (2) you are about to write a fix for a bug and have not
  checked whether an open PR already fixes it, (3) you are about to run
  `terraform apply` / a deploy from a plan you generated more than a few minutes
  ago, (4) you discover a duplicate PR and are deciding which to close,
  (5) a resource you are about to create already exists but is absent from
  terraform state, (6) a plan's change count shrinks between two runs with no
  action from you, (7) you work in an environment where several coding-agent
  sessions run against one repo, (8) you are about to start a sizeable piece of
  work and other agent sessions are live but you have not asked any of them what
  they are doing, (9) you are about to run `git worktree add` or `git checkout -b`
  for shared work -- the first act that claims shared state, and the point where
  two sessions given the same issue pick the same branch name, (10) you find
  uncommitted changes in a working tree that are not yours, (11) a background
  pipeline from an earlier run was reported "stopped" by the harness and you
  are about to relaunch it. Covers the three collision shapes -- duplicate
  work, pre-existing better work, and state changing under you -- the cheap
  pre-flight check for each, and how to reconcile without losing the better
  version.
author: Claude Code
version: 1.5.0
date: 2026-08-20
---

# Colliding with a parallel agent session

## Problem

When more than one agent session (or a human and an agent) works the same repos,
**anything you observed more than a few minutes ago may be false.** Not stale in
the mild sense — actively wrong, in ways that make you do damage or waste work.

Agents make this worse than humans do. A human opening a PR usually remembers
whether they already opened one. A fresh session has no such memory, moves fast,
and is confident.

## The three shapes

They fail differently and need different checks.

### 1. Duplicate work — two sessions do the same task

Two PRs, same story, functionally identical diffs. Both green, both blocked on
review. Neither author knows about the other.

**Before opening a PR**, check whether one already exists for these files:

```bash
gh pr list --state open --json number,title,headRefName \
  --jq '.[] | "\(.number) \(.title)"'

# narrower: PRs touching a file you are about to change
for n in $(gh pr list --state open --json number --jq '.[].number'); do
  gh pr diff "$n" --name-only 2>/dev/null | grep -q "path/to/file" && echo "#$n touches it"
done
```

### 2. Pre-existing better work — an older PR already fixes it, and fixes it more

The dangerous one. You investigate a bug, find a cause, write a fix — and an
unmerged PR from weeks earlier already covers it **plus a second defect you
missed**. Merging yours would half-fix the problem and make it look resolved,
which is worse than leaving it visibly broken because it stops anyone looking.

**Before writing a fix**, search open PRs and issues for the symptom, not just
the file:

```bash
gh pr list --state open --search "alarm" --json number,title
gh issue list --state open --search "in:title,body <symptom>" --json number,title
```

Age is not evidence of irrelevance. A PR open for weeks is often open because it
is waiting for review, not because it is wrong.

### 3. State changed under you — someone acted between your plan and your act

You generate a plan, spend ten minutes analysing it, then recommend or apply. In
between, another session applied. Your analysis describes a world that no longer
exists.

Tells that this happened:

- A plan's change count **shrinks** between two runs with no action from you.
- A resource exists in the live system but terraform says `will be created` —
  someone created it out of band, and applying will likely fail on a name
  conflict or duplicate it.
- A resource is in state but you never applied it.

**Re-plan immediately before acting.** A plan older than a few minutes is a
claim, not a fact:

```bash
terraform plan -out=/tmp/now.tfplan ...   # then apply THAT file, not a bare apply
terraform apply /tmp/now.tfplan
```

Using `-out` and applying the saved plan is the real fix: it makes terraform
refuse if the world moved, instead of silently applying something else.

## Reconciling a collision — do not just close yours

When you find a duplicate, the instinct is to close one and move on. Diff them
first: the loser almost always contains something the winner lacks.

1. **Diff the two.** `gh pr diff N > a.diff; gh pr diff M > b.diff; diff a.diff b.diff`
2. **Pick the survivor by inbound references, not authorship.** Whichever is
   already cited by issues, tickets, or other PRs — keeping it means those links
   stay valid.
3. **Port the difference before closing.** A ticket reference, a sharper comment,
   a measured verification. Commit it to the survivor.
4. **Close with a comment saying what was kept from each**, so the record shows
   nothing was dropped.
5. **Repoint anything that referenced the loser** — issues that say "fixed by
   #N".

If the *other* PR is better than yours, say so plainly, including what you got
wrong. That is the useful outcome, not the embarrassing one.

## The check that fires before any artifact exists

Every check above reads an **artifact** — an open PR, a branch, a changed plan.
That only works once the other session has produced one. Two sessions that are
both *about to* do the same work have nothing for each other to find, and this is
the most expensive moment to collide: both are about to spend the full cost.

In that window the only detector is the other session itself. If your host
exposes live peer sessions, enumerate them and ask:

```
ListAgents                      # who else is live
SendMessage -> <peer name>      # "are you working on X?"
```

A real case: two sessions independently resumed the same handoff document and
independently chose the same lane — adversarial review of the same four PRs.
Neither had pushed anything, so `gh pr list` was silent for both. The collision
surfaced only because one session asked the other directly, roughly one minute
before four duplicate reviews would have been posted to four PRs.

### Deconflict into lanes, then gate

Splitting the work is not enough; the two lanes usually have an ordering
dependency, and without a gate the second lane races the first.

1. **Name the lanes explicitly** and say which session owns which. Not "you do
   some of it" — one session owns review, the other owns merge; one owns the fix,
   the other owns re-review.
2. **Declare what each side will NOT do.** The valuable half. "I will post
   nothing to those PRs" is what makes the split safe.
3. **Gate the downstream lane.** If merging before review makes the review
   pointless, the merge lane blocks on the review lane *by design*, and says so.
4. **Route the decision through the shared human.** Two agents agreeing a split
   between themselves is not authorization. Surface it and let the human rule.
5. **Preserve the loser's work.** The session standing down usually has real
   output already. Hand it over rather than discarding it — in the case above the
   stood-down session's dry-run findings were folded into the surviving review as
   an independently-produced corroborating pass.

### Treat a peer's claim as evidence, not authority

A peer session can be wrong, and it can also be right in a way that overrides
your own source. Both happened in the case above:

- The peer corrected a claim inherited from a handoff document (that an
  append-only conflict would hit the second *and* third merge). It had actually
  simulated the sequence with `git merge-tree --write-tree` against synthetic
  commits, touching no refs. The simulation beat the document, and the correction
  was accepted.
- The peer was asked whether some agents had survived a restart and answered "no
  evidence either way" — explicitly refusing to let its own empty listing read as
  a negative result, since it had never observed the earlier state.

So: verify a peer's factual claims the way you would your own, and state plainly
which of your claims are verified versus inherited. A peer that distinguishes
"I checked" from "I did not observe that" is worth more than one that answers
every question.

### The asymmetry that bites

Session-to-session addressing is not symmetric with parent-to-teammate
addressing: a peer session and a spawned teammate may need different names for
the *same* target. Briefing an agent with the wrong reply address produces
silence that is indistinguishable from a wedge. The authoritative value is echoed
back on any outbound message you send — read it from the tool result rather than
assuming one name works in both directions.

## Check before you claim shared state, not before you open a PR

Every check in this skill so far fires at **opening a PR** or **writing a fix**.
A live drill showed both are too late. Two sessions were given the same
underlying bug, described differently. Neither contacted a peer during planning.
Both wrote code. The collision was discovered an hour later, and by then it had
already done damage.

**They collided at the first act that claimed shared state: creating a worktree.**
Both independently ran `git worktree add` on the *same path*, having
independently derived the *same branch name* from the issue.

That convergence is not bad luck, it is the default. A branch name derived from
an issue title or number is chosen identically by any two competent agents given
the same issue. So is the worktree path, if the convention derives it from the
branch. **The moment you name a branch after shared work, assume someone else
would name it the same.**

So move the check earlier. Before `git worktree add`, `git checkout -b`, or the
first write into a shared tree — not before the PR:

```bash
# 1. Has someone already claimed this name, locally or remotely?
git worktree list
git branch -a --list '*<topic>*'
git ls-remote --heads origin '*<topic>*'

# 2. Is the directory already there, with someone else's work in it?
ls -la ../<repo>.worktrees/ 2>/dev/null

# 3. Ask the live peers. This is the half the artifact checks cannot do.
ListAgents          # who is live right now
SendMessage -> peer # "are you working on <topic> in <repo>?"
```

Steps 1 and 2 cost seconds. Step 3 is the only one that fires when the other
session has planned but not yet written, which is the window where stopping is
free.

### If you find changes in a shared tree that are not yours

The drill's real damage came from the recovery, not the collision. The session
that found foreign uncommitted edits ran `git add -A` and swept another
session's in-flight work into its own commit, under a message describing only
its own change. The attribution in that commit is wrong permanently.

- **Never `git add -A` in a tree you do not exclusively own.** Stage explicit
  paths. `git add -A` cannot distinguish your work from someone else's, and a
  commit is not a reversible mistake once pushed and merged.
- Run `git status --short` first and **read it**, rather than staging past it.
- If foreign changes are present, ask whose they are and whether they are
  finished **before** committing anything. Do not commit another session's work
  on its behalf without consent — even if the change is correct.
- If you have already swept someone's work in, **say so plainly**, name the
  commit, and state that the message misattributes it. That disclosure is what
  makes the error recoverable rather than silently wrong.

### Interpreting a peer's silence

A peer that does not answer is not necessarily ignoring you, and `ListAgents`
state is part of reading it:

| state | meaning |
|---|---|
| `waiting` | **blocked on user input.** It will not process your message until its human interacts with that session. A message can sit undelivered indefinitely. |
| `busy` | working; it will drain your message at its next tool round. |
| `idle` | should respond promptly. |

A message to a `waiting` peer is not a failed send and not a refusal — it is
queued behind a human. Check the state before concluding anything from silence,
and tell your own operator if an answer you need is parked behind another tab.

When you are waiting on a peer to finish rather than to answer, **ask for an
explicit done-signal and subscribe to its idle notice** (`notify_when_idle`)
rather than polling `ListAgents` in a loop. Polling burns turns and still races
the moment it finishes; a one-shot subscription costs the peer nothing and
fires even if it exits instead of answering.

And one apparent peer can never answer at all: an orphaned process tree with
no session behind it. It holds no address, so no send reaches it and no
silence-reading applies — see "The peer that is not a session" below.

## The collision with no name to check: a shared counter

Every check above finds a collision by **name** — same branch, same worktree,
same PR, same resource. A monotonic counter in a shared file has no name to
check, collides between sessions doing entirely unrelated work, and is invisible
until the merge.

Observed across four sessions in one afternoon on a skills catalog whose bundle
`plugin.json` carries a version that CI requires to advance. Three sessions and
a fourth actor were merging concurrently; the version line conflicts textually
with *any* other change to it, so subject-matter independence bought nothing.
One PR lost the race five times in a row.

**Take the number at merge time, not at build time.** A version chosen when the
branch is written is a claim on a value someone else will take before you land:

```bash
base=$(git show origin/master:$VERSION_FILE | jq -r .version)
next=$(echo "$base" | awk -F. '{printf "%d.%d.0", $1, $2+1}')   # at MERGE time
```

Then rebase, set it, push, merge, and **retry the whole cycle on conflict** —
losing the race is the normal case, not the exception.

Three traps inside that loop, each of which reports success:

- **A rebase deletes your bump when the base took the identical change.** Not
  "the numbers are equal" — the hunk is dropped as already applied and vanishes
  from `git diff origin/master...HEAD` entirely. The gate then passes on a PR
  that ships no bump at all, and every installed copy stays frozen. After every
  rebase, re-read the version out of the file rather than trusting that you set
  it once.
- **`gh pr merge --auto` is a silent no-op when auto-merge is disabled on the
  repository.** It exits 0 and prints nothing; `gh pr view --json autoMergeRequest`
  stays `null` while you wait for a merge that was never armed. Check that
  field, or watch checks and merge explicitly.
- **`gh pr merge --squash --delete-branch` deletes the branch even when the
  merge did not happen.** A peer lost a PR that way: the delete closed it, and
  the content left the queue silently. Merge, confirm `state == MERGED`, and
  only then delete — as separate steps.

If `gh pr merge` itself flakes (GraphQL has, repeatedly), the REST path works:

```bash
gh api -X PUT repos/OWNER/REPO/pulls/N/merge -f merge_method=squash
```

**The structural fix is not a better retry loop.** A counter shared by every PR
is a lock discovered at merge time. Either give it one writer who batches, or
pin it on an integration branch and bump once at merge-back — the same
serialise-what-shares-a-file split this skill applies to worktrees and branches.

## When several sessions are landing into one repo

The sections above are written for two sessions discovering each other. A day
of four sessions and ~36 merges into one catalog surfaced four more rules, none
of which follow from the two-session case.

### Decide merge order by the shape of the change, not by arrival

Two PRs that both touch the shared indexes have to be ordered somehow, and
"whoever asked first" is the wrong answer. Order by what the changes mean to
each other:

- A **leaf** change — one skill, one entry, one file — goes **first**. It is
  cheap to rebase, and it is complete on its own.
- A **sweep** — a change that touches every entry, or that claims a property of
  the whole ("coverage is now 100%") — goes **last**. If it lands first, the
  next leaf PR falsifies the claim within minutes, and the sweep has to be run
  again anyway.

Observed: a peer asked to merge two single-skill PRs ahead of a sweep that
brought per-skill-plugin and README coverage to 100%. Yielding was not
politeness — going second let the same sweep cover the peer's two new skills,
so the number was true when it landed. A first-come lock cannot make that call;
it serialises by arrival, not by meaning.

### A peer's *instruction* is not your user's instruction

Distinct from "a peer's claim is evidence, not authority", which is about
facts. This is about a peer relaying a **decision**: *"the user decided X;
stand down."*

All three obvious responses are wrong. Obeying treats a peer as your operator.
Ignoring assumes your own information is fresher, which it often is not — the
peer may be relaying something your user said thirty seconds ago in another
session. Quietly continuing is the worst of the three, because the work
proceeds while the contradiction stays invisible.

Put the contradiction to your own user, in one message, naming both
instructions and when each arrived, and act only on their answer:

> You told me to merge #224 and #229. A peer session says you decided
> afterwards that those four skills belong to the other catalog and must not
> merge. I have already merged both. Which stands?

Observed exactly this, and the peer was **right** — which is why "ignore the
peer" fails as a rule. Two merged PRs were reverted, correctly, on the user's
confirmation. Escalating cost one message; guessing either way would have cost
a revert or a rebuild.

### Publish findings; do not rely on relaying them

A peer session can exit between your message and its next turn, and its address
stops resolving with no warning beyond a notice. Anything you learn that is
worth another session knowing belongs in a **durable artifact** — a PR, an
issue, the skill itself — not in a message queued to a session that may be
gone.

Observed: a finding was owed to a peer that exited first. It survived only
because it had already been written into a skill and a PR body; the relay would
have lost it.

### A green gate is not proof when someone can push around it

Branch protection may not be on, and an actor with push rights can land on the
default branch with no PR, no review, and no gate run at all. After that, "CI
is green on master" says only that the last *PR* passed, not that the invariant
holds.

So re-derive the state you depend on from the tree — the version you are about
to advance past, the file you are about to edit — rather than inferring it from
the existence of a check. This is the same discipline as reading the counter at
merge time, applied to everything the gate is supposed to guarantee.

## The peer that is not a session: your own orphaned predecessor

A session restart can orphan a background pipeline twice over. The harness
loses track of the task and reports it "stopped" or "[exited with code 144]"
— a statement about *tracking*, not about the processes. A worker tree
parented away from the dead session keeps running, keeps writing into its
state directory, and holds no address: `ListAgents` will never show it, and
no message can reach it. Meanwhile the restarted session — or a sibling that
picked up the same "retry" — relaunches the same pipeline. Observed as a
three-way collision over one adversarial-review batch: a zombie swarm still
filling the old state dir, a live swarm on a new one, and a third session
about to launch, all reviewing the same PRs.

Rules, in order:

1. **"Marked stopped" means lost tracking, not dead processes.** Before
   relaunching any background pipeline reported stopped, check for its
   worker tree — and check again *after* your own launch, because an orphan
   can sit mid-phase with an empty state dir at probe time, and a sibling
   can launch seconds after you looked.
2. **Detect by state-dir argv, and know the two false readings.** The state
   dir appears in every worker's argv, so `ps -ww` the matches and compare
   each process's state-dir argument against yours. A bare `pgrep -f` count
   lies twice over: pipeline subshells and round-robin workers carry the
   parent's argv, so one run shows as N identical processes — dedupe by
   PPID tree and start time, never by counting matches; and the probe's own
   shell can match its own pattern — exclude yourself before trusting ALIVE.
3. **Salvage is a pre-launch step.** Relaunching into the *same* state dir
   is self-deduping for a resumable batch — the artifact-existence skip
   turns an undetected orphan into an accidental co-worker. The dangerous
   combination is a fresh dir plus an undetected orphan on the old one. So
   before starting anywhere new, no-clobber-copy the old dir's finished
   artifacts (non-empty only; interrupted ones are zero-byte by that
   design) into the new tree. Then kill by the distinctive path —
   `pkill -f "<old-state-dir>"` — never by script name, which matches the
   survivor too.
4. **Killing the processes does not kill their intentions.** A colliding
   session may hold a watcher whose firing condition is exactly "workers
   gone" — and whose action is to relaunch, re-entering the race one cycle
   after your cleanup. The handoff must reach *every* colliding session,
   not just the designated owner, and each stand-down session stops its own
   monitors itself.
5. **One session owns the publishing tail.** A pipeline whose last step
   publishes — posts reviews, comments, deploys — must end in exactly one
   session, designated by the user, however many sessions contributed
   artifacts. The handoff to the owner carries what was already published
   (the do-not-repost list), what was salvaged and from where, and what
   remains gated on the user.
6. **Resumable state outlives sessions; house it accordingly.** A state
   directory under `/tmp` loses to reboots and periodic temp cleaning
   mid-run — observed as an archive of already-published artifacts silently
   gone between resumes, and as a skill's own `/tmp` example path seeding
   the next collision. Use `~/.cache/<pipeline>/`, and scope any progress
   monitor to that dir: liveness is "processes whose argv contains MY state
   dir", never a script name that a stranger's run also matches.

## Pre-flight, in one place

Before opening a PR, writing a fix, or applying anything:

```bash
git fetch --prune                              # your local view is also stale
gh pr list --state open --limit 50             # is someone already on this?
gh issue list --state open --limit 50
# for infra: re-plan, and apply a saved plan file rather than a bare apply
# for a shared counter: read its value now, and again at merge time
# for a background pipeline reported "stopped": ps -ww matches on its state dir,
#   dedupe by PPID tree, exclude self - and re-check after your own launch
```

Cheap. A single `gh pr list` costs seconds; a duplicate PR costs a review cycle
from someone else, and a stale apply can cost an outage.

## Verification

You have collided if any of these are true. Check before acting, not after:

- `gh pr list` shows an open PR touching your files.
- A re-plan differs from the plan you were about to act on.
- A resource you intend to create already exists in the live system.
- `git log origin/<default-branch>` moved since you branched.
- A version or counter your branch advances already holds that value on the
  default branch — or has silently disappeared from your diff since the rebase.
- A process tree from a prior run is still writing into a state directory
  you are about to reuse (`pgrep -fl <state-dir>` before any relaunch).
- Work you merged is **gone from the default branch**. A peer acting on a newer
  decision may have reverted it, correctly. Check that the revert is *complete*
  before doing anything else — a partial one leaves the catalog inconsistent —
  and do not re-land it without asking your user.

## Notes

- **This compounds with worktrees.** Sessions in separate worktrees of one repo
  share the remote and the terraform state but not the working tree, so they can
  each look internally consistent while disagreeing.
- **Branch from a freshly fetched default branch, always.** A branch cut from a
  local default that is hours behind produces a plan missing whatever landed
  since — which reads as "my change is small" right up until the merge applies
  someone else's work too.
- **A merge applies more than your diff.** Where CI auto-applies from the default
  branch, merging applies everything the branch describes, including drift you
  did not create. Read the plan, never infer it from your own diff.
- The failure is not carelessness — it is a fresh session's missing memory. The
  remedy is the pre-flight check, not trying harder to remember.
- Related: `github-api-list-endpoint-staleness-fresh-pr` (list endpoints can
  return `[]` for minutes on a fresh PR, so an empty result is not proof of
  absence).

## Related

- `agent-traffic-log` — the durable record of who asked whom what, which is how
  a collision gets noticed by someone who was not watching at the time.
- `cmux-cross-session-visibility` — the live view of the same traffic, for the
  human deciding whether to intervene.
- `claude-code-cross-session-messaging` — the addressing this skill's
  "ask the live peers" step depends on.
- `git-worktree-convention` — the layout whose derived paths make two sessions
  choose the same worktree name from the same issue.
- `claude-code-plugin-release-automation` — the shared-counter case in full,
  including the merge mechanics that report success and do nothing.
- `codex-adversarial-pr-review` — the resumable review batch the orphaned-
  predecessor case was observed on: artifact-existence dedupe is what makes
  salvage-then-kill lossless, and its post step is the publishing tail that
  needs a single owner.
