---
name: agent-team-orchestration
description: |
  Run a team of AI agents against the outstanding issues of a GitHub repo:
  an architect plans what can be parallelized, then each issue gets a small
  squad - a developer, an adversarial reviewer, an SDET/QA, and a productivity
  engineer that watches for process bottlenecks - while a product manager turns
  underspecified issues into buildable ones, with every agent individually
  watchable and steerable. Use when: (1) you want to work a whole backlog (not
  one issue) with agents and need a division of labor that an architect derives
  from the issue graph; (2) you want per-issue dev + review + QA roles rather
  than a single do-everything agent; (3) you want each agent visible/steerable
  on its own surface - a cmux tab, or Claude Code's native agent list plus
  SendMessage; (4) you want to capture where the run stalled (what needed your
  confirmation, what info was missing) as telemetry for improving the loop.
  Encodes the role set, the parallelization decision, the watchability
  convention, and the bottleneck-telemetry pass. cmux is the default interaction
  surface but not required; the same structure works over plain terminals or
  other multiplexers. Also use when (5) a spawned wave produces no commits, no
  dirty files and no replies - agents that are visible but wedged.
author: Claude Code
version: 1.9.1
date: 2026-10-09
source: https://github.com/voitta-ai/skillz
source_file: skills/agent-team-orchestration/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/agent-team-orchestration/SKILL.md`). Updates go through the repo's
> worktree + PR workflow - open an issue, branch, PR.

# agent-team-orchestration

## Problem
You have a repo with a backlog of open issues and you want a *team* of agents to
work them - not a single agent grinding one issue at a time. Two things make
that more than "spawn N agents":

1. **What can run in parallel is a judgment call.** Some issues touch the same
   files, share a migration, or must land in order. Deciding the parallel set is
   architectural work that should happen *before* any developer agent starts.
2. **One agent per issue is too few.** A lone developer agent marks its own
   homework. Real throughput-with-quality comes from giving each issue a small
   squad with separated concerns (build / attack / verify) plus a meta-role that
   watches the *process*, not the code.

This skill is the orchestration recipe: the roles, who reports to whom, how the
parallel set is chosen, and how to keep every agent watchable and steerable.

## The shape
```
                        ┌─────────────┐
        you  ◄────────► │  architect  │   (plans parallel set; owns the conversation)
                        └──────┬──────┘
            ┌──────────────────┼──────────────────┐
        ┌───┴───┐          ┌───┴───┐          ┌───┴───┐
        │issue A│          │issue B│          │issue C│      (parallel where safe)
        └───┬───┘          └───┬───┘          └───┬───┘
       dev│rev│qa         dev│rev│qa         dev│rev│qa       (a squad per issue)
              └──────── productivity engineer ───────┘        (watches the whole run)
```

## Start with a conversation, not a spawn
The run **begins with the architect**, in a conversation with you - not by
immediately fanning out agents. The architect:
- reads every open issue (`gh issue list`, `gh issue view`) and the repo,
- groups issues into a **parallel set** (independent) vs **serialized chains**
  (shared files / ordering / a migration that must land first),
- proposes the wave plan and the per-issue squad assignments,
- gets your go-ahead before squads start.

Arm the architect with the team's own reusable knowledge: this `skillz`
catalog (https://github.com/voitta-ai/skillz) and any internal playbook repo, so
its plan reuses existing skills (e.g. `work-on-pr`, `review-pr-loop`) instead of
reinventing the loop.

## Step 0: runtime precondition (before any spawn)
Detect the surface **before** the first agent is spawned, not at spawn time. The
architect runs, as a precondition:
```bash
which tmux        # is a tmux/cmux shim on PATH?
echo "$TMUX"      # are we inside a tmux/cmux session?
which cmux        # is cmux installed at all?
```
All three results matter - `which cmux` is not decoration. Shim + `TMUX` is
**necessary but not sufficient**: without the `cmux` CLI you are inside a
claude-teams session yet cannot enumerate or name surfaces. This is a
**once-per-run** check whose result drives an **opinionated default**:

- **Shim on PATH, `TMUX` set, `cmux` CLI present**: proceed with watchable
  per-agent tabs - the cmux path below.
- **Shim on PATH, `TMUX` set, but `cmux: command not found`**: proceed anyway
  and **skip the tab-naming section entirely** - `cmux tree --all` and
  `cmux tab-action` are unavailable, so there is nothing to name. State that
  you're doing so; don't ask, and don't re-check later.
- **Not under cmux at all**: **proceed automatically via the Workflow /
  background-agent surface** - state that you're doing so, don't ask. The role
  structure and wave plan work fine without tabs; you only lose the live-watch
  ergonomics.

Only surface a choice if the user explicitly wants watchable tabs and isn't under
cmux - then they restart the root session under `cmux claude-teams`. Do **not**
add a spawn-time default that steers away from cmux: the precondition has already
decided, opinionatedly, and it decided once.

**Ask each surface/runtime decision at most once.** Once step 0 has resolved the
surface, no later step re-asks it (gate 4 must not re-pose gate 2). Record the
resolved surface and reuse it for the whole run.

### The three checks above are NOT sufficient

Observed 2026-09-29: `which tmux`, `$TMUX` and an untargeted
`tmux display-message -p '#{pane_id}'` all passed, and every `Agent(name: ...)`
spawn still failed with `Could not determine current tmux pane/window`.

Add the check that ends the argument - replay what Claude Code itself queries
(2.1.284, `TmuxBackend.getCurrentWindowTarget`). It must print an `@...`:

```bash
tmux -S "${TMUX%%,*}" display-message -t "$TMUX_PANE" -p '#{window_id}'
```

Two independent causes produce that same error:

- **The lead's tab was moved to another cmux workspace after launch.** `TMUX`
  and `CMUX_WORKSPACE_ID` still name the dead launch workspace, and the shim
  answers `Error: not_found: Workspace not found`. Fix: `/exit`, then
  `cmux claude-teams --chrome -n <name> --resume <session-id>` **in the same
  tab** - cmux 0.64.25 re-resolves the workspace at launch.
- **cmux >= 0.64.23 `ControlClientRateLimiter`.** Any `-t %pane` query makes
  more than 9 polling reads in one call, so it returns
  `Error: rate_limited: Polling rate limited for this connection` every time.
  Relaunching and waiting do not help. Fixed upstream in manaflow-ai/cmux
  #12757 / PR #12832, merged 2026-09-17 and **not** in 0.64.25.

### Fallback that works: peer-session tabs

When teammate spawns cannot work, create each agent as its own cmux surface
instead:

```bash
cmux new-surface --type terminal --workspace <ws> --pane <pane> \
  --command "bash launch.sh <name> <dir>"
cmux rename-tab --surface <ref> <name>
```

where the launcher execs
`cmux claude-teams -n <team>:<name> --permission-mode <lead's mode> "<brief>"`.

Three caveats, each of which cost a run:

- **A relayed OK from the lead never counts in a peer session.** The operator
  approves prod steps in each agent's own tab.
- **Peers address the lead by its session name**, not `team-lead`.
- **Start each peer in an already-trusted folder** - check
  `~/.claude.json` `.projects[dir].hasTrustDialogAccepted`. Otherwise it sits
  silently on the folder-trust prompt. The step 0b probe catches this: one run
  scored 4/5 PROBE_OK with the fifth stuck on that dialog.

## Step 0b: executability precondition (a single probe agent, before the wave)
Step 0 answers "will agents be **visible**." It does not answer "can agents
**act**." Those are independent preconditions, and passing the first is not
licence to fan out. A wave can be perfectly visible - names in the agent list,
elapsed time ticking up - while every agent is wedged on its first tool call.

Do not try to introspect the permission mode. **Probe it.** Spawn exactly
**one** agent on the smallest issue in the wave, briefed to prove liveness
before anything else:

> As your very first tool call, run `<trivial command> && echo PROBE_OK`, then
> immediately `SendMessage` to `<architect's addressable name>` reporting
> `PROBE_OK` or `PROBE_BLOCKED - <what happened>`. Do not batch this with other
> work.

**Brief the probe with the architect's real address, and verify it before you
spawn.** `main` is the documented address for a *background subagent* to reach
the main conversation, but a **teammate-spawned agent is not in that
relationship**: for it, `main` resolves to *itself*, and the send bounces with
`You are the main conversation - "main" addresses you`. A probe that cannot
report is indistinguishable from a probe that is wedged - the exact failure this
step exists to rule out, reintroduced by the brief.

Resolve the address once, before the first spawn: call `ListAgents` and use the
name teammates see for you (commonly `team-lead`). The cheapest confirmation is
the routing metadata on your own first outbound `SendMessage`, which echoes back
the `sender` name your teammates must reply to. Do not guess, and do not assume
`main` because the surrounding docs use it.

Measured cost of getting this wrong: the probe ran fine, produced `PROBE_OK`,
failed to deliver it, self-recovered via `ListAgents`, and sent its report to an
**unrelated peer session** that happened to be named plausibly. The architect saw
silence and came within seconds of `TaskStop`ping a perfectly healthy agent.

**The probe's report channel must itself be un-gated**, or the probe wedges on
its own liveness report and produces exactly the silence it was built to
detect. Whatever the report rides on - a marker file, an echo - must be
something the *resolved mode* already permits: write markers **inside the
worktree**, never to `/tmp` or another path outside the project, because
`acceptEdits` does not cover paths outside the working directory. Check the
first call against the mode before you spawn. (Learned the hard way: a probe
briefed to report via `Write` to a scratchpad path hung on that very call.)

Fan out to the remaining squads **only after the probe confirms**. The probe
costs ~90 seconds and catches every cause of a wedge - permission mode, quota,
a dead runtime - not just the one you thought to check.

**If the probe stays silent past ~2 minutes, that is a hard stop.** Do not spawn
the rest of the wave. Surface it to the operator, because in the common case
(the session is in a permission mode that gates each tool call, and a background
subagent has no operator to prompt) **only they can change it.** Recover with
`TaskStop` per agent by name: it leaves worktrees, branches, and any prepared
baseline intact, so a restart after the mode is fixed is cheap.

**When the probe goes silent, one question is the operator's alone.** Silence
has two readings and the agent cannot tell them apart: the harness never
surfaced a permission request (a wedge - escalate), or it surfaced one nobody
answered (approve it, or pre-authorize and re-run). Ask the operator to look at
their screen **while the probe is still hung**, before you `TaskStop` it - once
it's stopped, that evidence is gone and the run is unfalsifiable. Tell them what
to look for before you spawn, not after it stalls.

**Any** tool call that needs permission wedges this way - not just `Bash`. A
measured case: a background subagent's first call was a `Write`, under
`acceptEdits`, to a path outside the project. Transcript, in full:

```
21:02:21  assistant   text: "I'll follow these steps exactly in order."
21:02:22  assistant   tool_use: Write -> /private/tmp/.../probe.log
<no tool_result, ever>
```

Two and a half hours later: no result, no error, no timeout, no prompt shown to
the operator. Treat any per-tool mitigation (a hook that denies gated `Bash` in
subagents, say) as covering one tool, not the class.

Every squad brief carries the same liveness first call, not just the probe's -
it turns a 45-minute silent stall into a sub-minute signal.

## The roles
Each issue in the active wave gets a squad. Roles are deliberately separated so
no agent both writes and blesses the same code.

| Role | Job | Tool / skill it leans on |
|---|---|---|
| **Architect / integrator** | Plans the parallel set, assigns squads, integrates merged work, resolves cross-issue conflicts. One per run. | `gh`, the issue graph; `multi-phase-feature-pr-worktrees` for isolation |
| **Developer** | Implements the issue on its own branch/worktree, opens the PR, addresses review. | `work-on-pr` (author-side PR loop) |
| **Adversarial reviewer** | Tries to *break* the developer's PR, not rubber-stamp it. A **different model provider** than the author; sees the **diff + contract only**; posts a **PR-visible verdict**. | `review-pr-loop`; Codex `/codex:adversarial-review` |
| **SDET / QA** | Exercises the change like a user - crawls routes/forms, watches console+network, files real findings. | `sdet-explore`, `sdet-email-flow` |
| **Product manager** | Turns an underspecified issue (a one-line idea, "brainstorm: can we do X?") into buildable ones. Interviews the operator on scope, users, constraints and appetite (legal/ToS, budget), then files each result as **task / guardrails / done when / verification**. Runs *before* any developer is assigned to that issue. | `AskUserQuestion`; the idempotency pre-flight |
| **Productivity engineer** | Meta-role. Watches the whole run for *process* bottlenecks: what needed your confirmation, what info was missing, where agents stalled. Feeds improvements back. | telemetry pass below; `continuous-learning` / claudeception |

Keep the developer and reviewer as **distinct agents**. The value of the
adversarial review collapses if the same context that wrote the code also
reviews it.

## Adversarial review: independence, artifact, aggregation
Separate-agent is the floor, not the ceiling. Four rules make the review
actually load-bearing:

- **Independence is by model *provider*, not just a separate agent or harness.**
  A reviewer from the author's own model family shares its blind spots. Prefer a
  reviewer on a **different provider** (author = Claude -> reviewer = Codex/GPT,
  and vice-versa). A different *harness* on the **same** provider (e.g. two tools
  both driving GPT) is **not** an independent review - say so, and treat it as
  weaker. (External convergence: Databricks' Omnigent routes every diff to a
  reviewer of a different vendor than the one that wrote it.)
- **The reviewer sees the diff + acceptance contract only - never the
  implementer's worktree.** Point it at the worktree and its stray edits can
  reach the deliverable; only the implementer opens/updates the PR. The reviewer
  **reports, it does not fix.**
- **Leave a PR-visible verdict (auditability).** The review lands as an artifact
  on the PR - `gh pr review` (approve / request-changes) or a comment with
  per-finding `Real/Valid/Reject` + rationale, tagged with the reviewer's
  identity (`[claude]` / `[codex]`). A verdict that lives only in an agent's
  transcript is unverifiable; "both approved first pass, zero rework" with **no
  artifact on the PR** is a claim, not evidence. A squash-merge collapses review
  comments out of mainline history, so the **PR thread is the durable record** -
  keep it there, don't rely on the merge body.
- **Aggregating multiple reviewers (the council) - aggregate by output type.**
  On a high-blast-radius PR you may run more than one reviewer. Do **not**
  majority-vote everything:
  - **Bug findings -> union, then verify.** Take the union of what *any* reviewer
    flags (a real high-severity bug is often caught by only one), then run one
    cheap confirmer per finding to drop false positives. Majority-vote on
    findings *suppresses the minority-but-real bug* - the wrong aggregator for
    recall.
  - **The APPROVE / REQUEST_CHANGES verdict -> majority.** The verdict is a
    judgment call; an outlier approving what the others would block should be
    outvoted.
  - **N=3 is the cost/recall knee** for a small diff - a 4th/5th reviewer rarely
    adds a finding. Scale N with diff size and blast radius, not a fixed count.

## Choosing the parallel set
The architect's core deliverable. **Triage first:** classify each issue as
*ready* (it has a definition of done a reviewer could check) or *underspecified*.
Underspecified issues don't enter the parallel set: they go to the product-manager
lane. A developer handed a one-line idea produces confident work against invented
requirements.

The PM lane uses wall-clock well. The PM interviews the operator in the
**foreground** while ready squads build in the background, so the operator's
attention (the real supervision cap) is spent on purpose rather than by
interruption. The PM writes each resulting issue as task / guardrails / done when /
verification, not as a step list. In a measured comparison, that shape beat step
lists on outcome, and step lists got exactly the listed steps and nothing more. Issues
the PM files become eligible for the *next* wave, so re-plan once the lane closes.

Heuristics for the ready set:
- **Independent** (parallelize): different directories/modules, no shared
  schema, no ordering dependency, separate PRs that won't conflict on merge.
- **Serialize** (one wave after another): issues that edit the same files, a
  migration or interface change others build on, or anything where issue B's
  acceptance depends on A having landed.
- **Cap the wave** to the number of squads you can actually watch and unblock.
  Parallelism you can't supervise just moves the bottleneck onto you.

**Scope/wave default (don't ask when you don't have to).** The default scope is
**all ready/independent issues, parallelized up to the supervision cap.** The
architect picks the wave by that rule and proceeds; it only asks you to narrow
scope when the ready set **exceeds** what the supervisor can watch (then it asks
which subset, once). Don't ask "how many issues?" or "which ones?" when the
independent set already fits under the cap - that's a decision the default
already makes.

Run a wave, integrate, then re-plan the next wave from what's left - dependencies
look different once the first wave merges.

## Shared indexes need one writer, not N

A repo usually has a few files that **every** contribution touches no matter how
independent its subject matter: a catalog or registry, a plugin/package list, a
README table of contents, a monotonically-increasing version. Subject-matter
parallelism is real; *shared-index* parallelism is not. Fan out the first,
serialize the second, or every concurrent contribution turns into a rebase.

The **productivity engineer** owns those writes for the duration of a run. That
is the natural fit because this is a process bottleneck, and recording where
agents stall is the same job as owning the thing they stall on.

**Handoff for a contributing agent:**

> Produce the content - the new file, its own directory, its own per-item
> version. **Do not touch shared indexes.** Hand off what you added, and let the
> responsible agent register it.

The responsible agent batches what is pending, lands it in one coherent change,
and runs the gates once.

### Two rules that matter more than the role

- **Edit shared lists in place. Never regenerate or re-sort them.** This is the
  single highest-leverage habit here. An in-place insert three-way-merges
  cleanly; a regenerated or re-sorted list produces hundreds of lines of churn
  in exactly the file everyone else is also editing, and "keep both sides" then
  yields something that is valid, reads fine, and is wrong - it resurrects
  entries deliberately removed upstream.
- **A monotonic counter guarded by a CI gate is a lock.** Two concurrent
  contributions cannot both be correct: whoever merges second is stale by
  construction. If the repo has one, either serialize behind the responsible
  agent, or **remove it from the contested path** - e.g. an integration branch
  where the counter is exempt and one real bump happens at merge-back. The
  second scales better, because it makes the conflict impossible rather than
  merely coordinated.

Distinguish the two kinds of collision before designing around them: a shared
*list* is a soft collision that auto-merges if edited in place, while a shared
*counter* is a hard one that cannot. Only the hard one needs a lock.

### Telling the agents apart matters here

The responsible agent has to know what is in flight in order to batch it, which
means the run needs agent-to-agent messaging, not just parallel spawns. See
`claude-code-cross-session-messaging` for the transport and
`cmux-cross-session-visibility` for making that traffic visible to the human
supervising the wave.

## Idempotency pre-flight (before creating any issue or PR)
**Mandatory.** Before the architect (or any squad) creates an issue or opens a
PR, it first checks for work that already covers the same change:
```bash
gh issue list --state all        # is this already filed?
gh pr list --state all           # is there already a PR for it?
git branch -a                    # is there already a branch/worktree?
```
If existing work is found, **extend or reference it instead of duplicating** -
comment on the existing issue, push to the existing branch, or note the overlap
in the plan. Duplicate issues/PRs/branches are pure friction at integration time.
(Concretely: running `gh issue list` before filing surfaced pre-existing overlap
that would otherwise have become a duplicate.)

**Merge-order default.** Independent PRs **merge on green review** - no human
gate, because they were chosen as independent in the first place. Escalate to you
**only** for genuine ordering or shared-file conflicts (two PRs touch the same
file, or B's acceptance depends on A landing). Don't ask "which merges first?"
when the PRs don't actually interact.

## Cross-repo / cross-lane coordination
When the backlog spans **multiple repos** (one feature whose lanes live in
separate services), the issue graph is not enough - the friction moves to the
*seams between lanes*. The architect maintains a lightweight **coordination
contract**, kept current as waves land:

- **Team-handoff doc** - one scannable page, the architect's + every lane's entry
  point. Per repo: folder, branch/PR, issue(s), current state; plus the goal,
  cost, and the gates below. Link each repo's own detailed handoff rather than
  inlining it.
- **Inter-lane dependency registry** - the concrete outputs one lane hands
  another, named explicitly so a lane never blocks guessing. (e.g. infra lane ->
  consumer lane: the exact cross-cluster DNS the consumer must call; the consumer
  cannot deploy without it.)
- **Gates / freeze-windows** - "do NOT apply X while Y is live", "do NOT merge A
  until B verifies". The multi-repo analogue of the serialized chains above - make
  the ordering explicit so no lane trips another's live state.
- **Per-project handoff files** - each repo keeps its own detailed handoff
  (`.claude/` / `.handoffs/`); the team doc links them. A lane resuming mid-run
  reads its own file; the architect reads the team doc.

Treat the contract as living: re-publish it each time a gate clears or a
dependency is delivered. Most multi-repo stalls trace to a missing entry here -
an unstated address, an unflagged freeze - not to the code.

## Make every agent watchable and addressable
The rule that keeps a multi-agent run legible: **every agent must be
individually watchable and addressable mid-run.** cmux tabs are one mechanism;
they are not the only one. Two that satisfy the rule:

- **cmux surfaces** - one tab per agent you can watch and type into. Requires
  step 0 to have resolved to the full cmux path (shim + `TMUX` + `cmux` CLI).
- **Claude Code's native agent list** - Agent-tool subagents render in-TUI under
  the `main` node with live elapsed time, and are steerable by name via
  `SendMessage`. No cmux tabs are involved and the run is still legible.

Which one you get depends on the **spawn path**, not just the launch wrapper -
see the [`cmux-agent-tabs`](../cmux-agent-tabs/SKILL.md) skill for the full why,
but the short version:

- **Claude Code teammates** only tab if the root session was launched through the
  `cmux claude-teams` wrapper (it prepends a tmux shim to PATH).
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` alone is a red herring. (This is what
  the step-0 `which tmux` + `echo $TMUX` check detects.)
- **Claude Code Agent-tool subagents** do **not** tab even under
  `cmux claude-teams` - they run in Claude Code's own subagent runtime and
  surface in the native agent list instead. Launching correctly does not change
  this; the spawn path does.
- **Codex** subagents tab automatically under `cmux codex-teams` /
  `cmux hooks setup codex`.

When you are on the cmux path, name tabs `<project>-<issue>-<role>` so the wall
of panes is readable:
```bash
cmux tab-action --action rename --tab surface:N --title "<project>-<issue>-dev"
# ...-rev, ...-qa, ...-arch
cmux tree --all      # list every surface + ref
```
Both commands need the `cmux` CLI. If step 0 found the shim without the CLI, or
the agents came from the Agent tool, skip this block - the agents are watchable
in the native list and there is nothing to rename.

cmux is the default surface because you can watch and steer mid-run, but it is
**not required** - the role structure and wave plan work over plain terminals,
tmux, or any multiplexer. If you skip cmux, just lose the live-watch ergonomics.

## Bottleneck telemetry (the productivity engineer's output)
The reason to instrument the run, not just complete it. Throughout the wave the
productivity engineer records:
- **Confirmation stalls** - every point an agent had to stop for your approval.
  Which were genuinely judgment calls vs. things a better-scoped permission or
  skill could have pre-authorized?
- **Missing-info stalls** - where an agent lacked context (a convention, a
  credential, an acceptance criterion) and had to ask or guess.
- **Rework** - review/QA findings that a sharper initial brief would have
  prevented.

Each recurring stall is a candidate fix: a new skill, a permission allowlist
entry, a sharper issue template, or a default the architect should set next
time. Promote the reusable ones via `continuous-learning` / claudeception into
this catalog; keep the project-specific ones in memory or the project's docs.

### Measuring the run (where each number actually lives)
**Never measure permission friction from the session transcript.** When the human
approves a prompt, the `tool_use` goes straight to its `tool_result`, which looks
exactly like a call that never prompted. Only a denied or interrupted call leaves
a marker. A transcript-only count of "0 stalls" means "0 denials", not "0 prompts".
`permissionMode: acceptEdits` auto-accepts file edits only; Bash still prompts unless
a hook or a static `permissions.allow` entry covers it.

| Metric | Source |
|---|---|
| Bash prompted and approved | a `PermissionRequest` hook counts prompts directly. Alternatively, join the permission hook's decision log (`ask`) with its PostToolUse "ran" log: an `ask` that later ran was approved. With yolt: `~/.claude/yolt.log` and `~/.claude/yolt-ran.log` |
| Bash auto-allowed | the hook's `safe` decisions. PreToolUse hooks run even when a static `permissions.allow` rule matches (verified on Claude Code 2.1.296), so allow-listed calls show up in the hook's log too |
| Bash that fell through to a raw prompt | the hook's `unknown` decisions that later ran: a rules gap |
| Permission mode | transcript `permissionMode`; segment every gating number by it |
| Human judgment gates | transcript `AskUserQuestion` calls |
| Rejections and steers | transcript `interrupted: true` |
| Throughput, roles that ran, timestamps | transcript (`tool_use` counts, agent spawns) and `gh` (PRs, commits) |
| Claims vs reality | transcript claims joined with `gh` PR, issue and deploy state |

**Capture protocol.** A run counts as measured only if, at run end, the productivity
engineer snapshots a telemetry bundle:
1. Copies of the hook logs, taken per run. They rotate (yolt at 5 MB), so a long
   run loses its early history if they are read later.
2. The session transcripts.
3. A `gh` snapshot of every touched repo's PRs and issues.
4. The active permission mode(s) and the effective `permissions.allow` set.

Then it emits the table above for the run. Only two bundles captured the same way
can be compared, so this is what makes run-over-run claims valid.

## Defaults: don't ask for cheap process decisions
A confirmation stall is only worth it for a real judgment call. **Cheap process
decisions default to *yes*, with an opt-out** the supervisor can flip at any time:
- **Auto-save reusable learnings.** When the productivity engineer spots a
  durable learning, it's saved via claudeception by default - no "should I save
  this?" prompt. Opt out if you don't want catalog churn this run.
- **Auto-continue the SDET pass.** Once a deploy/preview is up, the SDET starts
  its exploration automatically rather than asking permission to begin.

These are reversible, low-cost, and not architectural - so they don't earn a gate.
Reserve your attention for the decisions below.

The product manager is the exception: its job *is* asking. Its interview questions
about scope and requirements are not process stalls, and the productivity
engineer doesn't count them as such.

## Decisions that stay human gates - posed once
Some decisions are genuine architectural judgment and should **not** be
auto-resolved:
- **Design reconciliation** (e.g. which navbar/header/component wins when two
  issues disagree) stays a **human gate**. The architect does not pick for you.

But a real gate must still be **de-duplicated**: once a decision is posed, the
architect **records it and never re-poses the same decision.** The architect
maintains an explicit list of open vs. decided decisions, so an integration-time
question isn't re-asked just because it resurfaces in a later wave (the F10
meta-bug: gate 13 duplicating gate 12). Posing a kept gate once is correct;
posing it twice is friction.

## Workflow
1. **Step-0 runtime precondition.** Architect runs `which tmux` + `echo $TMUX` +
   `which cmux` and resolves the surface **once**, opinionatedly - full cmux,
   shim-without-CLI (proceed, skip tab naming), or background-agent. No
   spawn-time re-ask.
2. **Architect conversation.** Architect reads issues + repo, triages each as
   ready or underspecified, proposes the wave plan and squads. Default scope =
   all ready/independent issues up to the supervision cap; only narrow if it
   exceeds what you can watch. Underspecified issues go to the product-manager
   lane, which runs in the foreground alongside the wave and files buildable
   issues for the next one.
3. **Idempotency pre-flight.** Before filing/creating anything, run
   `gh issue list` / `gh pr list` / `git branch -a`; extend existing work rather
   than duplicate.
4. **Launch the surface.** If step 0 resolved to full cmux, start the root
   session via `cmux claude-teams` (or `cmux codex-teams`) so agents tab, and
   verify with `cmux tree`. If the CLI is absent, or you're on the
   background-agent surface, proceed without tabs - don't re-ask.
5. **Step-0b executability probe.** One agent on the smallest issue, liveness
   first call, `SendMessage` back. Silent past ~2 min = hard stop, `TaskStop`,
   escalate to the operator. No fan-out until it confirms.
6. **Spin up wave-1 squads.** One dev + reviewer + SDET per active issue, each on
   its own worktree (`multi-phase-feature-pr-worktrees`), each individually
   watchable (a named tab, or an entry in the native agent list).
7. **Run the loops.** Developers use `work-on-pr`; reviewers use `review-pr-loop`
   / adversarial review; SDETs exercise the change (auto-started once a deploy is
   up) and file findings.
8. **Productivity engineer watches** and logs confirmation/info/rework stalls;
   auto-saves durable learnings by default. Liveness is checked against the
   filesystem, not the agent list.
9. **Integrate + re-plan.** Architect merges independent PRs on green review,
   escalating only genuine ordering/shared-file conflicts; tracks open vs.
   decided design gates so none is re-posed; re-derives the next wave.
10. **Retrospective.** Turn telemetry into concrete process fixes; promote
    reusable learnings as skills.

## Outcomes this is built to produce
- The backlog gets worked with build/attack/verify separation per issue.
- You get **telemetry on how the team ran** - where it stalled and why.
- The recurring stalls become durable improvements (skills, permissions,
  templates) so the next run needs less of your intervention.

## Caveats
- **Supervision is the real cap.** More squads than you can watch and unblock
  just relocates the bottleneck to you - size the wave to your attention.
- **Don't merge the dev and review roles** to save agents; that defeats the
  adversarial review. And separate-agent alone is weak: independence is by model
  **provider**, the reviewer sees **diff + contract only**, and its verdict must
  land as a **PR artifact** - a narrated "approved" with nothing on the PR is
  unverifiable.
- **Majority-vote is the wrong aggregator for bug recall.** A real high-severity
  bug is often caught by only one reviewer; union-then-verify keeps it, majority
  drops it. Reserve majority for the approve/request-changes verdict.
- **cmux tabbing is asymmetric** across runtimes, and "no tabs" has more than one
  cause (`cmux-agent-tabs`): the session wasn't launched via `cmux claude-teams`;
  the agents came from the **Agent tool** rather than teammate spawning (correct
  launch, still no tabs); or the tmux shim is present but the `cmux` CLI isn't
  installed, so surfaces can't be enumerated or named. Resolve this at step 0,
  not at spawn time - and don't chase the launch-wrapper theory when the run was
  in fact launched that way.
- **Visible is not the same as working, and there is no progress signal.**
  Elapsed-time counters keep incrementing for a wedged agent, so a stalled wave
  is indistinguishable from "agents are thinking hard" - especially under a brief
  that (correctly) says diagnose before you change code. `SendMessage` does not
  rescue you: a wedged agent never reaches its inbox, so the one channel you'd
  reach for to diagnose it is dead for exactly the same reason it's stuck. The
  reliable liveness oracle is **filesystem state**, which an idling agent cannot
  fake:
  ```bash
  git -C <worktree> status --porcelain      # any dirty files?
  git -C <worktree> rev-list --count HEAD ^origin/master   # any commits?
  ls <worktree>/**/__pycache__ 2>/dev/null  # did anything even run?
  stat -f %m <worktree>                     # mtime still at creation time?
  ```
  Zero across all of them, with the agent list ticking, means wedged - not busy.
  Check whose activity you're reading before drawing conclusions: an architect's
  own earlier validation run in one worktree can look like a live agent.

  **Filesystem silence is not proof of a wedge in the opening minutes.** A brief
  that (correctly) says *read the issue before you touch code* sends the agent to
  `gh issue view`, `WebSearch`, and its own reasoning - none of which write
  anything into the worktree. A healthy agent can therefore read zero on every
  check above for several minutes. Measured: a probe agent showed no dirty files,
  no commits and no `__pycache__` for 3.5 minutes while its transcript showed six
  completed tool calls and zero dangling ones. Treat filesystem state as
  *positive* evidence of life when it moves, never as *negative* evidence when it
  does not - and never `TaskStop` on filesystem silence alone.
  To *confirm* - and to name the exact call that wedged - read the agent's
  transcript for a **`tool_use` with no matching `tool_result`**. That signature
  is unambiguous where mtimes are circumstantial, and it survives both the
  agent's death and the session's. Filesystem state stays the cheap first check;
  the transcript is the one that ends the argument.
- **Re-plan between waves.** A parallel set chosen up front goes stale once the
  first PRs merge; dependencies shift.
- **Ask each decision at most once.** Surface/runtime, scope, and design gates are
  all resolved once and recorded; re-posing a settled decision is friction, not
  diligence.
- **Keep real gates; drop cheap ones.** Design reconciliation stays a human gate;
  reversible process decisions (save-learning, start-SDET) default to yes.

## Quick reference
| Goal | Command / skill |
|---|---|
| Step-0 surface check (once) | `which tmux` + `echo $TMUX` + `which cmux` - all three results count |
| Step-0b executability check | one probe agent, liveness first call, `SendMessage` back; fan out only on `PROBE_OK` |
| Probe report channel | must be un-gated in the resolved mode - marker inside the worktree, never `/tmp` |
| Probe report address | resolve via `ListAgents` before spawning - `main` bounces for teammates (it addresses themselves); usually `team-lead` |
| Liveness oracle (wedged vs busy) | transcript first (dangling `tool_use`); filesystem is positive evidence only - silence in the first minutes is normal while an agent reads |
| Confirm the wedge, name the call | agent transcript: a `tool_use` with no matching `tool_result` |
| Wedged wave, recovery | `TaskStop` per agent by name; worktrees + branches + baseline survive |
| Idempotency pre-flight | `gh issue list` / `gh pr list` / `git branch -a` before creating |
| Plan parallel set | architect reads `gh issue list` / `gh issue view`, groups independent vs serialized |
| Default scope | all ready/independent issues up to the supervision cap |
| Default merge order | independent PRs merge on green; escalate only ordering/shared-file conflicts |
| Cheap process decisions | default yes with opt-out (auto-save learnings, auto-continue SDET) |
| Design conflicts | human gate, posed once, recorded - never re-posed |
| Claude teammates -> tabs | launch via `cmux claude-teams ...` |
| Claude Agent-tool subagents | never tab; watch in the native agent list, steer via `SendMessage` |
| Codex agents -> tabs | `cmux codex-teams ...` / `cmux hooks setup codex` |
| Is Claude bridge active? | `which tmux` (shim) + `TMUX` set + `which cmux` (CLI) |
| Name a squad tab | `cmux tab-action --action rename --tab surface:N --title "<proj>-<issue>-<role>"` (needs the `cmux` CLI) |
| Per-issue isolation | `multi-phase-feature-pr-worktrees` |
| Dev loop | `work-on-pr` |
| Review loop | `review-pr-loop` / `/codex:adversarial-review` |
| Reviewer independence | different model **provider**, not just a separate agent/harness |
| Reviewer inputs | diff + acceptance contract only - never the implementer's worktree |
| Review verdict | PR artifact (`gh pr review` / comment, per-finding + identity tag) - not the merge body |
| Council aggregation | bug findings -> union-then-verify; approve/RC verdict -> majority; N=3 knee |
| QA pass | `sdet-explore`, `sdet-email-flow` |
| Promote learnings | `continuous-learning` / claudeception |
