---
name: codex-hook-wire-schema-from-binary
description: |
  Read the Codex CLI hook contract straight out of the shipped native binary
  with `strings` instead of probing it with a live turn: the `PreToolUse`
  payload fields, the output envelope, the `permissionDecision` values the
  host accepts and the ones it refuses by name, the plugin environment
  variables, and the hook-trust gate. Use when: (1) you need Codex's hook
  stdin payload field names and `codex --help` has no `hooks` subcommand;
  (2) you are porting a Claude Code `PreToolUse` hook to Codex and need to
  know what differs before writing a decision; (3) a live Codex probe hangs
  or never reaches a tool call and you need the contract anyway; (4) someone
  reports that Codex has no native binary to inspect, having looked in
  `@openai/codex/bin/` which holds only a JS shim; (5) a hook you installed
  correctly appears to do nothing. Records the load-bearing finding that
  Codex `PreToolUse` accepts `permissionDecision: deny` and refuses `allow`
  and `ask` by name, so a hook that returns `ask` for "unsure" is rejected,
  and that Codex sets `CLAUDE_PLUGIN_ROOT` so a Claude Code plugin hook path
  may resolve unmodified.
author: Claude Code
version: 1.0.0
date: 2026-08-28
source: https://github.com/voitta-ai/skillz
source_file: skills/codex-hook-wire-schema-from-binary/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/codex-hook-wire-schema-from-binary/SKILL.md`). Updates go through
> the repo's worktree + PR workflow — open an issue, branch, PR.

## Problem

Codex CLI documents its hooks thinly. `codex --help` exposes no `hooks`
subcommand, and `~/.codex/hooks.json` on a real machine is usually written by
a third-party wrapper (cmux), so it shows what that wrapper wired -- not what
Codex supports. The obvious next move, a live probe turn with a stub hook, is
slow and fails for reasons unrelated to hooks (provider unreachable, auth,
network-gated router), producing no evidence either way.

Meanwhile the entire contract is compiled into the shipped binary: the wire
structs, the JSON Schema, and -- most usefully -- the literal validation error
strings that name every value the host rejects.

A prior session looked in `@openai/codex/bin/`, found only `codex.js`, and
concluded no native binary existed. The binary is real; it is two
`node_modules` levels deeper in a platform-specific package.

## Context / Trigger Conditions

Invoke when:

- You need Codex's `PreToolUse` (or any hook) stdin payload field names.
- You need to know which `permissionDecision` values Codex honors before
  writing a hook that returns one.
- A live Codex probe hangs, times out, or never reaches a tool call, and you
  need the contract anyway.
- Someone reports "Codex has no native binary to inspect" -- they looked in
  the wrong directory.
- You are porting a Claude Code hook to Codex and need to know what differs.

Do NOT invoke when:

- The question is runtime behavior rather than contract, e.g. "does deny
  actually stop execution under `approval_policy = \"never\"`". Strings cannot
  answer that; only a live turn can.

## Solution

### 1. Find the binary

The `bin/codex` on `PATH` is a JS shim. The native executable lives in the
platform package nested under it:

```
$(dirname $(readlink -f $(which codex)))/../node_modules/@openai/codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex
```

Locate it without guessing the platform triple:

```bash
find "$(dirname "$(readlink -f "$(which codex)")")/.." \
     -path '*vendor*/bin/codex' -type f 2>/dev/null
```

It is large (~205 MB for 0.148.0), which is why `strings` finds so much.

### 2. Pull the hook contract

```bash
CX=<path from step 1>

# Payload fields and decision vocabulary live in one adjacent run of strings
strings -n 4 "$CX" | grep -F 'PreToolUseHookSpecificOutputWire'

# The authoritative part: what the host REFUSES, stated literally
strings -n 20 "$CX" | grep -F 'PreToolUse hook returned'
```

The rejection strings are the contract. They name unsupported values
explicitly, so there is no inference step.

### 3. Read off the answers

For `codex-cli 0.148.0` the result was:

**Input payload** -- a superset of Claude Code's:

```
session_id  turn_id  agent_type  transcript_path  hook_event_name
model  permission_mode  trigger  tool_name  tool_input  tool_use_id
```

**Output envelope** -- identical key names to Claude Code:

```
hookSpecificOutput { hookEventName, permissionDecision,
                     permissionDecisionReason, additionalContext }
```

**`PreToolUse` accepts `deny` and nothing else:**

```
PreToolUse hook returned unsupported permissionDecision:allow
PreToolUse hook returned unsupported permissionDecision:ask
PreToolUse hook returned unsupported decision:approve
PreToolUse hook returned unsupported continue:false
PreToolUse hook returned unsupported stopReason
PreToolUse hook returned unsupported suppressOutput
PreToolUse hook returned permissionDecision:deny without a non-empty permissionDecisionReason
```

A hook that returns `ask` -- the normal Claude Code posture for "unsure" --
is rejected on Codex. Port it to `deny` with a reason, or emit nothing.

**Full event list** (wider than a cmux-wired `hooks.json` shows):

```
pre_tool_use  permission_request  post_tool_use  pre_compact  post_compact
session_start  session_end  user_prompt_submit  subagent_start  subagent_stop
```

**Plugin env vars** -- Codex sets Claude's name too, so a Claude Code plugin
hook path may resolve unmodified:

```
PLUGIN_ROOT  CLAUDE_PLUGIN_ROOT  PLUGIN_DATA  CLAUDE_PLUGIN_DATA
```

**Hook trust is a gate.** Hooks require persisted trust before they run.
`--dangerously-bypass-hook-trust` skips it for automation. A hook that
"silently does nothing" after install is usually untrusted, not broken.

### 4. Isolate any live follow-up

If a live turn is still needed, do not edit the user's `~/.codex/hooks.json` --
it carries their wrapper's wiring. Point Codex at a scratch home instead:

```bash
export CODEX_HOME=/path/to/scratch
ln -s ~/.codex/auth.json "$CODEX_HOME/auth.json"   # symlink; never copy secrets
# write your own config.toml + hooks.json in $CODEX_HOME
codex exec --dangerously-bypass-hook-trust "<prompt>"
```

Note `CODEX_HOME` inherits nothing: a `model_provider` pointing at a private
or VPN-gated router will hang with no session, no logs, and no hook fire.
Drop `model_provider` to fall back to the authenticated default before
concluding the hook layer is at fault.

## Verification

Confirmed when `strings -n 20 "$CX" | grep -F 'PreToolUse hook returned'`
prints a non-empty list of rejection strings. If it prints nothing, the path
from step 1 resolved to the JS shim rather than the native binary -- check
the file size (a shim is kilobytes, the binary is hundreds of megabytes).

Cross-check the payload extraction by confirming both `tool_name` and
`tool_input` appear in the `PreToolUseHookSpecificOutputWire` neighborhood.

## Notes

- The binary also embeds a draft-07 JSON Schema
  (`"title": "pre-tool-use.command.output"`). `strings -n 40` surfaces its
  `$ref` lines; the schema is chunked across the binary, so the rejection
  strings remain the faster read.
- This technique generalizes: any Rust-compiled agent host that validates hook
  output with named errors will leak its contract to `strings` the same way.
- `codex plugin add | list | marketplace` exists, so plugin distribution is a
  real channel; plugin-materialized hooks get trusted through it, which is the
  clean answer to the trust gate above.

## References

- voitta-yolt #114: https://github.com/voitta-ai/voitta-yolt/issues/114

## Related

- `claude-code-codex-plugin-parity` — **read this first if you are porting.**
  It covers where the two plugin systems match and diverge and the shared
  `hooks.json` caveats. This skill answers the narrower question it leaves
  open: what the Codex binary itself says the hook contract is, including the
  decisions it refuses.
- `claude-code-plugin-release-automation` — shipping to both hosts once the
  hook works. Its paired-manifest rule is the other half of the two-runtime
  story: Codex pins on its own version, so a bump that moves only the Claude
  manifest freezes one host silently.
- `agent-host-skill-loading` — the case where the target host has no plugin
  or hook system at all, so there is no contract to extract and you build the
  loading yourself.
- `codex-adversarial-pr-review` — driving Codex as a tool you invoke, rather
  than hooking the tool calls Codex itself makes.
