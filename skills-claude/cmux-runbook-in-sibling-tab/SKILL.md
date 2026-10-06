---
name: cmux-runbook-in-sibling-tab
description: |
  Run a multi-step runbook one step at a time in a real terminal tab next to
  the agent's own cmux tab, with the human watching, an exit-code receipt per
  step, and destructive steps staged at the prompt for the human to press
  Enter on. Use when: (1) an agent produced a runbook and told the human to
  run it with the `!` prefix or "in a plain terminal"; (2) a step needs a
  real tty, runs longer than the Bash tool's cap, or should keep its output
  out of the transcript; (3) you want each step gated on the previous one's
  exit code instead of typed blind into a busy shell; (4) a step is
  irreversible (`--apply`, `--delete`, rotate, push) and the human must be the
  one who fires it; (5) you are tempted to `cmux send` a command with `\n`
  into another tab. Ships `scripts/cmux-step` (open / run / stage / wait /
  show / close) and the YOLT rule that stops an agent pressing Enter in
  another surface. Also covers why a sibling tab does NOT satisfy "quit every
  interactive session first", and why a driven tab is still transcribed.
author: Claude Code
version: 1.0.0
date: 2026-08-29
source: https://github.com/voitta-ai/skillz
source_file: skills/cmux-runbook-in-sibling-tab/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/cmux-runbook-in-sibling-tab/SKILL.md`). Updates go through the
> repo's worktree + PR workflow - open an issue, branch, PR.
>
> Companions: [Two agents picked the same job](https://blog.debedb.com/2026/08/27/two-agents-picked-the-same-job-one-said-so-part-1-of-2/)
> and [Pinger, ponger, and the tab that could not say its name](https://blog.debedb.com/2026/08/27/pinger-ponger-and-the-tab-that-could-not-say-its-name-part-2-of-2/)
> are the posts this grew out of: the keystroke transport, tab naming and
> self-identity lessons there are reused here with a human on the other end.

# cmux-runbook-in-sibling-tab

## Problem

An agent finishes an investigation with a runbook and hands it to the human:

```
Runbook (steps 1-5 work with the `!` prefix here; step 6 needs a plain terminal)
cd ~/.cred-audit
python3 probe.py            # ~5 min
python3 classify.py
python3 scrub.py            # dry run
python3 scrub.py --apply
```

The human would rather say "open a tab next to you and run these one by one".
That is four cmux primitives and two rules, and every one of them has a trap.

In the observed case the runbook existed because the agent's own Bash tool had
been refused: the auto-mode classifier denied the dry run and the file writes
("Permission for this action was denied by the Claude Code auto mode
classifier. Reason: Blocked by classifier."), and a `PreToolUse` hook asked
for confirmation on every inline `python3 -c`. `!` is the human running the
command, so it clears both. **A sibling tab must not become a way for the
agent to run what it was just denied** - see "Stage or fire" below.

## What the tab buys over `!` and the Bash tool

| | Bash tool / `!` | sibling tab |
|---|---|---|
| tty | none (`tty` prints `not a tty`) | real pty; Ctrl-C works |
| duration | Bash tool caps a call at 600 s | none |
| output | lands in the conversation | stays in the tab's scrollback |
| survives the session | no | yes - the tab is a separate cmux surface |
| who pressed Enter | the agent (Bash) / the human (`!`) | either, and it is visible which |

## The transport (verified on cmux 0.64.15)

```bash
cmux identify                                    # caller.pane_ref / workspace_ref: where "next to me" is
cmux new-surface --type terminal --working-directory <dir> --pane pane:N --workspace workspace:M --focus false
                                                 # -> "OK surface:K pane:N workspace:M"
cmux tab-action --action rename --tab surface:K --title <name>
cmux send --surface surface:K "bash ~/x/.cmux-step/step-1.sh\n"   # \n is Enter
cmux wait-for <token> --timeout 900              # blocks; signals are retained (tmux semantics)
cmux read-screen --surface surface:K --lines 60
```

- Text sent 0 s after `new-surface` is typed-ahead and runs once the prompt
  appears; no settle needed after opening, but the first step's start is
  delayed by shell startup (~3 s with a heavy profile), and a Ctrl-C during
  that startup discards the typed-ahead line. `run 0 'true'` first if the
  human is likely to interrupt early.
- `cmux send` converts `\n`, `\r` and `\t` in its argument into key events.
  `echo 'a\tb'` arrives as `echo 'a` + Tab + `b'`. **Never ship command text
  through the keystroke channel.** Write the step to a file and send
  `bash <file>`.
- No delivery receipt on `send`. The step file writes `$?` to a receipt file
  and signals `cmux wait-for -S <token>`; the driver blocks on the token and
  reads the file. Never detect completion by scraping the screen.
- `wait-for` signals are retained: a late waiter returns at once. That means a
  **token must be unique per invocation**, or a stale signal from an earlier
  run of the same step satisfies the next wait.
- `cmux identify` refuses processes that are not descendants of the cmux app
  (`Failed to write to socket (Broken pipe)`). An Agent-tool subagent cannot
  open the tab; drive the runbook from the main session
  (`cmux-session-self-identity`).
- `$CMUX_TAB_ID` can equal `$CMUX_WORKSPACE_ID`; always pass `--tab` /
  `--surface` explicitly.
- Refs (`surface:K`) survive as long as the cmux app runs; after a relaunch
  they are reassigned. Store the title too and re-resolve via `cmux tree --all`.

## The two rules

1. **Never send step N+1 before step N has a receipt.** Text typed into a
   busy terminal goes to the running program's stdin, or the tty queues it and
   the shell runs it, unreviewed, the moment the program exits. With an
   `--apply` step in the runbook that is how it fires by accident.
2. **Stage or fire.** `cmux send` *without* a trailing `\n` leaves the line at
   the prompt: the human reads it, presses Enter (or Ctrl-U to discard). With
   `\n` the agent fired it. Which one:

   | step | do |
   |---|---|
   | the agent's own Bash tool would be allowed to run it, and it is not irreversible | fire (`run`) |
   | it was denied or confirmation-gated in this session | **stage** - a human Enter is the human running it, same as `!`. Firing it from the tab is the permission laundering the `SendMessage` tool warns about, one costume over. |
   | `--apply`, `--delete`, rotate, push, anything irreversible | stage |
   | it needs every interactive agent session gone | stage, then the human quits the sessions and presses Enter; the tab outlives them |

   Decide from the runbook's own labels (dry run vs apply), the session's
   denial history, and the human's explicit word. No heuristics.

Staging is a convention: `cmux send-key --surface surface:K enter` exists.
The script never calls it, and the YOLT rule below makes the call itself
ask for confirmation.

## `scripts/cmux-step`

```
cmux-step open  <dir> [title]     terminal tab in the caller's pane, cwd <dir>; reused if already open
cmux-step run   <n> <command...>  write step file, type `bash <file>  # n: cmd`, Enter, wait, exit with its rc
cmux-step stage <n> <command...>  same line without Enter; marks the tab unread; returns at once
cmux-step wait  <n> [seconds]     block on step n's receipt (after stage, or after a timeout); exit with its rc
cmux-step show  [lines]           the tab's last lines (default 60)
cmux-step close
```

State is `<dir>/.cmux-step/` (`tab`, `step-<n>.sh`, `.rc`, `.tok`, `.staged`,
`last`; a `.gitignore` of `*` so a repo never sees it). The tab is remembered
per caller surface under `~/.local/state/cmux-step/by-caller/`, so a second
session can drive a second runbook. `CMUX_STEP_DIR` overrides.

What the step file does for you:

- receipt (`echo $? > step-n.rc; cmux wait-for -S <token>`) after the command;
- `trap` on INT and TERM, so Ctrl-C in the tab yields **rc 130 with a
  receipt** instead of a wait that times out (interactive bash aborts the rest
  of a `;` list on SIGINT, which is why the receipt lives inside the file);
- a unique token per invocation.

`run` blocks up to `CMUX_STEP_TIMEOUT` (default 540 s, under the Bash tool's
600 s cap) and exits 124 without a receipt; the step keeps running in the tab
and `wait <n>` resumes the wait - **waits are resumable**, nothing is lost by
timing out. For a step you expect to take longer, or for any staged step, do
not block a foreground tool call at all: `stage`, end the turn with one line
telling the human which tab, and run `cmux-step wait <n> 3600` in the
background so the exit code re-invokes you.

`run`/`stage` refuse (exit 2) while the previous step has no receipt - rule 1
is structural, not remembered.

The line at the prompt reads `bash ~/x/.cmux-step/step-4.sh  # 4: python3
scrub.py --apply`; the comment is display only (backslashes stripped, one
line), the file is what runs.

Ship it: the skillz bundle plugin exposes it as `plugins/skillz/bin/cmux-step`,
and Claude Code puts every plugin's `bin/` on `PATH`, so it is `cmux-step`
in any session with the bundle installed. Elsewhere call it by path.

## Worked example: the credential-audit runbook

| step | verb | why |
|---|---|---|
| 1 `python3 probe.py` | stage | denied to the agent in-session; ~5 min; output stays in the tab |
| 2 `python3 classify.py` | stage | denied in-session |
| 3 `python3 scrub.py` (dry run) | stage | denied in-session |
| 4 `python3 scrub.py --apply` | stage | irreversible |
| 5 rotate live secrets | **not in the tab at all** | the new secret must never be displayed where an agent reads it back - `show` output becomes transcript |
| 6 `python3 scrub.py --apply --outside-session` | stage; human quits every interactive session, then presses Enter | the scrubber refuses (exit 2) while `~/.claude/sessions/<pid>.json` lists an interactive session or `CLAUDECODE` is set; the driving session's own transcript is one of the files it rewrites. A sibling tab does not clear that - only quitting does. The tab outlives the sessions, and `wait 6` still works on resume. |

Six Enters in one tab, no typing, every exit code back to the agent.

## The YOLT rule

Drop this in `~/.claude/yolt/shell.json` (merges into the bundled rules per
top-level key; `cmux` and `tmux` are otherwise unruled). It makes an agent's
Enter - `send-key enter/return/kp_enter/ctrl+m/ctrl+j`, `send` text carrying
`\n`/`\r`, `respawn-pane`, `rpc surface.send*`, the tmux-compat `send-keys` -
an `ask` (a `deny` inside subagents). `cmux send` **without** a newline stays
unruled: that is staging by hand. `cmux-step` itself is an unknown command to
YOLT and falls through to the platform classifier, which sees the inner
command in argv.

```json
{
  "_meta": {
    "note": "cmux-runbook-in-sibling-tab hardening: an agent must not press Enter, or type a newline, into another terminal surface. A human presses Enter on staged steps; `cmux-step run` is the sanctioned fire path and is visible in argv. Everything else under cmux stays unruled."
  },
  "commands": {
    "cmux": {
      "default": "subcommand",
      "_note": "Keystroke or text injection into another terminal surface runs commands where this session's permission checks cannot see them.",
      "valueless_flags": ["--", "--all", "--no-focus", "--scrollback", "--json", "--help", "--reconnect", "--no-ack", "--no-heartbeat", "--no-caller", "--print", "-p", "--signal", "-S", "--processes", "--flat"],
      "unsafe_subcommands": ["respawn-pane"],
      "nested_subcommand": {
        "send-key":       {"empty_decision": "unsafe", "unsafe_subcommand_patterns": ["[Ee][Nn][Tt][Ee][Rr]", "[Rr][Ee][Tt][Uu][Rr][Nn]", "[Kk][Pp]_[Ee][Nn][Tt][Ee][Rr]", "[Cc][Tt][Rr][Ll]+[MmJj]", "*\\n*", "*\\r*"]},
        "send-key-panel": {"empty_decision": "unsafe", "unsafe_subcommand_patterns": ["[Ee][Nn][Tt][Ee][Rr]", "[Rr][Ee][Tt][Uu][Rr][Nn]", "[Kk][Pp]_[Ee][Nn][Tt][Ee][Rr]", "[Cc][Tt][Rr][Ll]+[MmJj]", "*\\n*", "*\\r*"]},
        "send":           {"empty_decision": "unsafe", "unsafe_subcommand_patterns": ["*\\n*", "*\\r*", "*\n*", "*\r*"]},
        "send-panel":     {"empty_decision": "unsafe", "unsafe_subcommand_patterns": ["*\\n*", "*\\r*", "*\n*", "*\r*"]},
        "rpc":            {"unsafe_subcommand_patterns": ["surface.send*", "surface.input*", "*send_key*", "*send_text*", "*send_input*"]},
        "__tmux-compat":  {"unsafe_subcommands": ["send-keys", "paste-buffer", "respawn-pane", "respawn-window", "pipe-pane"]}
      }
    },
    "tmux": {
      "default": "subcommand",
      "_note": "Inside cmux, tmux is the claude-teams shim (skill cmux-agent-tabs): send-keys types into another pane exactly like cmux send-key.",
      "unsafe_subcommands": ["send-keys", "paste-buffer", "respawn-pane", "respawn-window", "pipe-pane"]
    }
  }
}
```

Two escaping facts that cost an hour: YOLT's patterns are Python `fnmatch`,
where a backslash is a literal character, not an escape - so `"*\\n*"` in the
JSON (one backslash after decoding) matches the two characters `\` `n` that a
double-quoted `"...\n"` argument carries, and `"*\n*"` (a real newline after
decoding) matches a literal newline. Write `"*\\\\n*"` and nothing matches.
Also `--` is treated as a value-taking flag unless listed in
`valueless_flags`, which would swallow the text after it.

Treat the rule as a **permission-system bypass guard**, not as "send-keys is
mutating": a line staged in another surface and fired with Enter never passed
`PreToolUse` at all, the same shape as writing `~/.claude/settings.json`. That
is the case for carrying it in YOLT's bundled rules as a non-delegable entry
(voitta-yolt #100, #121) instead of a per-machine override.

Hazard while it is an override: any validation error in
`~/.claude/yolt/shell.json` - a typo, a renamed key - makes the hook log
`rules-validation-error` and exit 0 for **every** command, so the whole guard
is silently off until the file is fixed (voitta-yolt #123; a bad override
should be discarded with the bundled rules still enforcing). After editing it,
run one command and check the log.

Not covered: writing to the cmux socket directly, and a tab the human types
into while the agent expects to. The tab is the agent's; the human presses
Enter, Ctrl-C or Ctrl-U there and nothing else.

## Verification

- `cmux tree --all` shows the new surface in the **same pane** as the caller,
  with the title you gave, and `--focus false` left your own tab in front.
- `run` of `echo hi; false` exits 1 and prints `step 1: rc=1`.
- `run` of `printf "a\tb\n" | od -c` shows `\t` - the tab survived, because it
  never crossed the keystroke channel.
- `stage` leaves the line at the prompt (`show` shows it after the prompt with
  no output below); `run` of the next step exits 2 until it is pressed.
- Ctrl-C in the tab during a `run` returns `rc=130`, not a timeout.
- `run` with `CMUX_STEP_TIMEOUT=3` on a 5 s step exits 124; `wait <n>` then
  exits 0.
- With the YOLT rule installed, feeding
  `{"tool_name":"Bash","tool_input":{"command":"cmux send-key --surface surface:1 enter"}}`
  to `hooks/yolt_analyzer.py --hook` returns `permissionDecision: ask`, and
  `cmux send --surface surface:1 "echo hi"` returns nothing.

## Related

- `cmux-session-self-identity` - `cmux identify`'s `caller` is how the script
  knows which pane is "next to me", and why a subagent cannot do this.
- `cmux-agent-tabs` - the tab-naming recipe and the `select-pane -T` no-op;
  `cmux open` is not a way to run a command in a tab.
- `cmux-claude-codex-cross-runtime-messaging` - the same keystroke transport
  with an agent, not a human, on the other end.
- `cmux-search` - `read-screen --scrollback` over every tab, including the one
  this skill opened.
- `cmux-cross-session-visibility` - the sidebar pill, if you want the runbook's
  progress visible without looking at the tab.
- `agent-session-credential-audit` - the runbook in the worked example, and the
  live-writer rule that makes step 6 require the driver to be gone.
- `claude-code-cross-session-messaging` - the permission-laundering rule this
  skill applies to a terminal instead of a peer session.
