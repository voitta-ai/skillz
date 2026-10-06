---
name: openclaw-model-cascade-debugging
description: |
  Debug OpenClaw model cascade failures causing Slack lag or unresponsiveness.
  Use when: (1) Slack messages are slow but console/Claude Code works fine,
  (2) logs show "No API key found for provider" or rate limit errors,
  (3) "allow-always is unavailable" error when approving exec commands,
  (4) model fallback errors like "All models failed" in gateway.err.log,
  (5) the gateway PROCESS is up but every agent run dies with FailoverError
  because all cascade providers are down at once (codex cooldown + paid
  fallbacks out of credit), (6) you want to build a FREE OpenRouter fallback
  basket so codex cooldowns stop killing the agent, (7) a free model fails with
  "Upstream error from OpenInference: Unknown role: final" and times out.
  Covers config hierarchy, auth profile locations, cascade diagnostics, config
  hot-reload, free-model selection by live tool-calling test, and one-shot
  cascade verification via `openclaw agent`.
author: Claude Code
version: 1.2.0
date: 2026-06-26
source: https://github.com/voitta-ai/skillz
source_file: skills/openclaw-model-cascade-debugging/SKILL.md
---

# OpenClaw Model Cascade Debugging

## Problem

OpenClaw Slack channel is slow or unresponsive while direct console access
(Claude Code) works fine. This usually indicates model cascade failures where
the primary model is rate-limited and fallbacks are misconfigured.

## Context / Trigger Conditions

- Slack messages take a long time or fail silently
- Console/terminal Claude Code sessions work normally
- Gateway logs show errors like:
  - `Provider openai-codex is in cooldown (all profiles unavailable)`
  - `No API key found for provider "openrouter"`
  - `Your credit balance is too low to access the Anthropic API`
  - `All models failed (3): ...`
- UI shows "allow-always is unavailable because the effective policy requires approval every time"

## Key Insight: Console vs Slack Routing

**Console (Claude Code)** connects directly to Anthropic's API - it does NOT
route through OpenClaw's gateway or model cascade.

**Slack** routes through:
```
Slack -> OpenClaw Gateway -> Model Cascade (primary -> fallback1 -> fallback2) -> response
```

This is why Slack can fail while console works perfectly.

## Solution

### 1. Check Model Cascade Status

```bash
# View recent errors
tail -100 ~/.openclaw/logs/gateway.err.log | grep -E "(rate|limit|quota|error|fail)"

# Check current status
openclaw status
```

### 2. OpenClaw Config File Hierarchy

| Config | Path | Purpose |
|--------|------|---------|
| Main config | `~/.openclaw/openclaw.json` | Gateway settings, model cascade, channels, tool policies |
| Agent auth | `~/.openclaw/agents/main/agent/auth-profiles.json` | Per-agent API keys and OAuth tokens |
| Agent models | `~/.openclaw/agents/main/agent/models.json` | Per-agent model overrides |
| Exec approvals | `~/.openclaw/exec-approvals.json` | Allowlisted commands |
| Logs | `~/.openclaw/logs/gateway.log` / `gateway.err.log` | Runtime logs |

### 3. Fix "allow-always unavailable" Error

This is caused by `tools.exec.ask: "always"` in main config.

```bash
# Check current setting
openclaw config get tools.exec.ask

# Fix: Edit ~/.openclaw/openclaw.json
# Change: "ask": "always"
# To:     "ask": "on-miss"

# Restart gateway
openclaw gateway restart
```

### 4. Add Missing Provider Auth (e.g., OpenRouter)

Auth profiles go in the AGENT config, not main config:

```bash
# Edit ~/.openclaw/agents/main/agent/auth-profiles.json
# Add new provider profile:
```

```json
{
  "profiles": {
    "openrouter:default": {
      "type": "api-key",
      "provider": "openrouter",
      "apiKey": "sk-or-v1-..."
    }
  }
}
```

```bash
# Restart gateway to pick up new auth
openclaw gateway restart
```

### 5. Verify Fix

```bash
# Check Slack reconnected
openclaw logs | tail -20 | grep slack

# Should see: "slack socket mode connected"

# Test send
openclaw message send --target "slack:USER_ID" --message "Test"
```

## Verification

After fixes:
1. `openclaw status` shows Slack channel as "OK"
2. `openclaw logs` shows `slack socket mode connected`
3. No new rate limit or auth errors in `gateway.err.log`
4. Test message sends successfully

## Example

Diagnosing Slack lag:

```bash
# Step 1: Check error logs
$ tail -50 ~/.openclaw/logs/gateway.err.log | grep -E "(error|fail|limit)"
[model-fallback/decision] decision=skip_candidate reason=rate_limit
[model-fallback/decision] decision=candidate_failed reason=billing
[diagnostic] lane task error: error="No API key found for provider openrouter"

# Step 2: Identify the cascade
# Primary: openai-codex/gpt-5.4 -> rate limited
# Fallback 1: anthropic/claude-opus-4-6 -> billing failure
# Fallback 2: openrouter/auto -> no API key

# Step 3: Fix the weakest link (add OpenRouter key)
# Edit ~/.openclaw/agents/main/agent/auth-profiles.json

# Step 4: Restart and verify
$ openclaw gateway restart
$ openclaw message send --target "slack:U0AALM0KJKX" --message "Test"
Sent via Slack. Message ID: 1778215494.325669
```

## Diagnosis: gateway process UP != agent ALIVE (2026.5.7+)

A running gateway does NOT mean the agent can answer. When all cascade providers
are down at once, the process stays up but every run dies with `FailoverError`.

```bash
openclaw gateway status --deep     # shows pid + "File logs:" path
ps -o pid,lstart,etime -p <pid>    # continuous uptime => it never crashed
```

In 2026.5.7 file logs are JSONL at `/tmp/openclaw/openclaw-YYYY-MM-DD.log` (NOT
`~/.openclaw/logs/gateway.err.log`). Parse them, don't grep raw. Look for the
per-candidate decision + the terminal error:

```bash
log=/tmp/openclaw/openclaw-$(date +%F).log
# every fallback decision (which candidate, why it was skipped/failed/succeeded)
python3 -c '
import json,sys
for l in open(sys.argv[1]):
    l=l.strip()
    if not l.startswith("{"): continue
    try: d=json.loads(l)
    except: continue
    if d.get("message")=="model fallback decision":
        for k,v in d.items():
            if isinstance(v,dict) and v.get("event")=="model_fallback_decision":
                print(d.get("time","")[11:19], v.get("candidateModel"), "->",
                      v.get("decision"), v.get("reason"), (v.get("errorPreview") or "")[:70])
' "$log" | tail -20
```

Reading the reasons:
- `Provider openai-codex is in cooldown (all profiles unavailable)` reason=`rate_limit`
  => TRANSIENT ChatGPT-sub usage window; codex primary recovers on its own.
- `Your credit balance is too low` / OpenRouter `billing error` => provider out of credit.
- All candidates failing => agent is dead until you add a working provider.

## Config hot-reload (no restart for cascade edits)

Editing `agents.defaults.model.{primary,fallbacks}` or `subagents.model` in
`~/.openclaw/openclaw.json` HOT-RELOADS. Confirm with:

```bash
grep "config hot reload applied" /tmp/openclaw/openclaw-$(date +%F).log | tail -1
# -> "config hot reload applied (agents.defaults.model.fallbacks)"
```

Restart is still required for NEW providers/auth profiles, not for reordering an
existing cascade. Always back up first: `cp openclaw.json openclaw.json.bak-$(date +%s)`.

## Free OpenRouter fallback basket (survive codex cooldowns for $0)

Goal: keep codex primary, then fall through to FREE OpenRouter models so a codex
cooldown stops meaning death. Model ref format is `provider/model` split on the
FIRST slash, so free models are `openrouter/<vendor>/<model>:free` (two slashes ok).

1. Get current free + tool-calling models from the authoritative API (the list
   churns; never rely on memory). Free models WITHOUT tool support are useless to
   OpenClaw — it needs function calling for exec/message tools.

```bash
curl -s https://openrouter.ai/api/v1/models | python3 -c '
import json,sys
for m in json.load(sys.stdin)["data"]:
    p=m.get("pricing",{})
    free=all(float(p.get(k,0) or 0)==0 for k in ("prompt","completion","request"))
    sp=m.get("supported_parameters",[]) or []
    if free and ("tools" in sp or "tool_choice" in sp):
        print(m.get("context_length"), m["id"])
'
```

2. LIVE-test candidates with a real tool-call before trusting them (isolated test
   != real behavior — see the gpt-oss gotcha below). Send a tools request with the
   key from `$OPENROUTER_API_KEY` and check for `tool_calls` in the response.

3. Build a BROAD, vendor-diverse basket. Free endpoints 429 constantly at the
   provider level; breadth means one is always up. OpenClaw skips a 429'd
   candidate and tries the next. Example working cascade (verified 2026-06):

```json
"model": {
  "primary": "openai-codex/gpt-5.5",
  "fallbacks": [
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
    "openrouter/cohere/north-mini-code:free",
    "openrouter/google/gemma-4-31b-it:free",
    "openrouter/qwen/qwen3-coder:free",
    "openrouter/meta-llama/llama-3.3-70b-instruct:free"
  ]
},
"subagents": { "model": "openrouter/nvidia/nemotron-3-super-120b-a12b:free" }
```

Also fix `subagents.model` — if it points at an exhausted paid model, subagents
die even when the main cascade is healthy.

### GOTCHA: gpt-oss `:free` + codex history => "Unknown role: final"

`openrouter/openai/gpt-oss-*:free` FAILS every real call behind a codex primary
with `Upstream error from OpenInference: Unknown role: final`, then TIMES OUT
(~80s), making runs take 80-99s. Its provider rejects the `final` role that
codex/gpt-5.5 emits into transcript history. It passes an ISOLATED tool test
(no such history) but fails in production. Drop gpt-oss from a codex-primary
cascade; lead with a lenient provider (nemotron proved fine). Real-run logs > isolated tests.

### Free-tier daily cap

Free models work at $0 balance but are capped (~50 req/day; ~1000/day after a
one-time $10 lifetime purchase on the account). For a cron-heavy instance, the
one-time $10 is worth it. Provider-level 429s ("temporarily rate-limited") are a
separate, transient throttle — not the daily cap.

## Verify the live cascade in one shot

```bash
openclaw agent --agent main -m "Reply exactly: CASCADE OK" --json \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["result"]; t=d["executionTrace"]; \
    print(d["finalAssistantVisibleText"][:80]); print("winner:", t["winnerModel"], "fallbackUsed:", t["fallbackUsed"])'
```

- `openclaw agent` needs a session selector: `--agent main` (or `--to`/`--session-id`).
- Omit `--deliver` to test without posting to a channel.
- `--model <override>` is BLOCKED for the CLI caller (`provider/model overrides
  are not authorized for this caller`) — you cannot force a specific fallback from
  the CLI; rely on real-run logs (`candidate_succeeded`) to confirm a fallback works.

## Notes

- The model cascade is defined in `~/.openclaw/openclaw.json` under `agents.defaults.model`
- Rate limit cooldowns are temporary; cascade failures become permanent if ALL fallbacks fail
- Cascade edits (primary/fallbacks/subagents.model) HOT-RELOAD; restart only for new providers/auth
- Large log files (gateway.log can grow to GB) may indicate high activity or logging issues

## Slack ID Types (Important for Allowlisting)

Slack uses three ID prefixes:

| Prefix | Type | Example | Identifies |
|--------|------|---------|------------|
| `U0...` | User ID | U0AHB3HJU49 | A person |
| `C0...` | Channel ID | C0ACJGUGB0A | A public/private channel |
| `D0...` | DM Channel ID | D0ACYMM81V2 | A DM conversation |

**Key insight:** OpenClaw's `channels` config uses **channel IDs** (C0.../D0...), not user IDs (U0...).

For DMs:
- DM channel IDs are created on first message
- To allowlist a DM, you need the D0... ID, not the U0... user ID
- Find DM IDs in logs: `grep "D0[A-Z0-9]" ~/.openclaw/logs/gateway.log`

Commands to discover IDs:
```bash
# List users
openclaw directory peers list --channel slack

# List channels
openclaw directory groups list --channel slack

# Find DM channel IDs from logs
grep -E "delivered.*D0" ~/.openclaw/logs/gateway.log | tail -10
```

## Related

- `litellm-custom-provider-dispatch-order` - the same shape one layer down: a
  provider that is registered correctly, reports no error, and is never the one
  that actually runs.
