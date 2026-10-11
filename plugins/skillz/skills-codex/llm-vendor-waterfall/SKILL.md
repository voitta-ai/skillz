---
name: llm-vendor-waterfall
description: |
  Serve one LLM call from an ordered list of vendors so a rate limit, a dead
  key, or an out-of-credits account fails over instead of failing the request.
  Use when: (1) building an agent or bot that must stay responsive across
  vendor 429s and outages, (2) an agent's responsiveness "looks random" and a
  silently dead fallback is the suspect, (3) choosing between a hand-rolled
  try/except chain and LiteLLM's Router, (4) deciding which Router knobs
  actually matter (cooldown_time, allowed_fails, context_window_fallbacks,
  per-deployment budgets) and which are noise, (5) a long thread hard-errors
  on context length even though fallbacks are configured, (6) porting the
  waterfall into a second codebase and wondering whether to share code.
  Covers the ordered-config to Router mapping, the knobs worth turning and
  why, the ones to leave alone, what must not be waterfalled, and how to
  prove failover actually happens.
author: Claude Code
version: 1.1.0
date: 2026-08-24
source: Extracted from voitta-ai/shmobster (shmobster/llm.py, README "Own / rent / delegate", issues #5 and #51). Second consumer tracked as voitta-ai/agents #9.
source_file: skills/llm-vendor-waterfall/SKILL.md
---

# LLM vendor waterfall: ordered failover is configuration, not code

## Problem

An agent that calls one vendor has that vendor's rate limit as its own
availability ceiling. In practice three separate things take a vendor out:

- **429** — the account's rate limit, usually mid-conversation and at the worst
  moment.
- **Out of credits** — the key is valid, the account is not funded.
- **Revoked or wrong key** — a 401 that looks like every other error at the
  call site.

The obvious response is a try/except chain over N vendor SDKs. That buys you
ownership of retries, backoff, cooldown, per-vendor auth shapes, and — the
expensive part — translating tool-call schemas between vendors.

## Do not write the waterfall. Configure it.

LiteLLM's `Router` **is** the waterfall: ordered `fallbacks`, retries, and
per-deployment cooldown are already its semantics. The only part worth owning
is the mapping from an ordered config list to a `model_list` plus a `fallbacks`
chain, so vendors are data rather than code:

```python
from litellm import Router


def _deployment(model_name, vendor):
    params = {"model": vendor["model"], "api_key": vendor.get("api_key")}
    if vendor.get("api_base"):            # OpenAI-compatible endpoints
        params["api_base"] = vendor["api_base"]
    retval = {"model_name": model_name, "litellm_params": params}
    return retval


def build_router(waterfall):
    """waterfall: ordered list of vendor dicts; index 0 is primary."""
    if not waterfall:
        raise SystemExit("waterfall is empty -- add at least one vendor")
    model_list = [_deployment("primary", waterfall[0])]
    rest = waterfall[1:]
    for i, vendor in enumerate(rest):
        model_list.append(_deployment(f"fb{i}", vendor))
    fallbacks = [{"primary": [f"fb{i}" for i in range(len(rest))]}] if rest else []
    retval = Router(
        model_list=model_list,
        fallbacks=fallbacks,
        num_retries=1,
        cooldown_time=60,
    )
    return retval
```

Call sites then ask for the **group name**, never a vendor:

```python
resp = router.completion(model="primary", messages=messages, tools=tools)
```

The naming matters more than it looks. `primary` / `fb0` / `fb1` are *routing
groups*, so adding, reordering, or dropping a vendor is a config edit; nothing
downstream names a model. Config carries `name`, `model` (a LiteLLM id),
`api_key`, and optionally `api_base`:

```json
{
  "waterfall": [
    { "name": "vendor-a", "model": "vendor-a/some-model",  "api_key": "REPLACE" },
    { "name": "vendor-b", "model": "vendor-b/other-model", "api_key": "REPLACE" },
    { "name": "vendor-c", "model": "openai/compat-model",  "api_key": "REPLACE",
      "api_base": "https://compat.example.com/v1" }
  ]
}
```

That file holds live keys. Keep it out of version control and `chmod 600`.

## Which knobs to turn, and when

Set from the start:

| Knob | Why |
|------|-----|
| `fallbacks` | The waterfall itself: ordered failover on error. |
| `cooldown_time` | Without it, a 429'd vendor is re-hit on **every** call — you pay the primary's latency to fail, every turn, for the whole rate-limit window. |
| `num_retries=1` | Absorbs a transient 5xx before spending a failover rung. |

Turn only when the matching symptom is real:

| Knob | Symptom that earns it |
|------|----------------------|
| `context_window_fallbacks` | A long thread hard-errors on context length. Plain `fallbacks` catch **failures, not context-length errors** — so without this a context overflow is a hard error even with four vendors configured. Add a big-context rung. |
| `allowed_fails` (+ `allowed_fails_policy`) | Rate-limit-heavy traffic. `cooldown_time` alone does nothing until the default fail threshold is crossed, so a vendor keeps being retried while it is plainly limited. Cool on first 429. |
| `max_budget` + `budget_duration` (per deployment) | Uncapped per-vendor spend, e.g. a bot any number of people can talk to. The Router enforces caps natively; do not build a meter. |

## Leave these alone

- **`routing_strategy`** — the default ordered failover *is* the waterfall.
  Latency- or usage-based routing turns a deterministic preference order into
  a scheduler, which is a different feature.
- **Multi-key load balancing** — nothing to balance while config is one key per
  vendor.
- **Cross-vendor tool-call fidelity shims** — add one reactively, per observed
  degradation, when a vendor actually misbehaves. Written up front they encode
  guesses about failures that never arrive.

## The failure that actually costs you: an invisible dead fallback

The waterfall's own failure mode is that it works. A misconfigured rung (bad
key, unfunded account) is not experienced as an error — it is experienced as
*the agent seems slow and flaky sometimes*, because every call quietly walks
further down the chain before something answers. Primary timing out, second
vendor out of credits, third missing a key reads to a user as random
unresponsiveness even when nothing else is wrong.

So observability is not a follow-up; it is what makes the pattern operable:

- Log **which vendor served each call**, not just that a call succeeded.
- Surface a dead rung **explicitly at startup or on first use** — a rung that
  can never serve is a config bug, not a runtime condition.

## Do not waterfall everything

A waterfall assumes the rungs are substitutable. That holds for text
completion; it does not hold for capability-bearing work. If a task needs
browser control, computer use, or any tool only one host has, failing over
means failing over into a vendor that cannot do the job at all — and the error
surfaces far from the cause. Delegate those to the host that owns the
capability (e.g. shell out to a CLI agent that has the browser tool) and let
the waterfall cover the plain model calls.

## Prove it works

Failover is exactly the code path that is never exercised until it matters.
Test it deliberately:

1. Point the primary at an exhausted or invalid key; make a call.
2. Expect: a later vendor serves the request, and the log names it.
3. Make several more calls inside the cooldown window. Expect: the failed
   vendor is **skipped**, not retried each time (watch latency, not just
   success — repeated primary attempts show up as a delay before every reply).
4. Break one fallback's key on purpose. Expect: a clear report of that rung,
   not silence.

## Extracting it to a second codebase

Resist sharing this as a library across repos until there is a real second
consumer. The owned surface is roughly thirty lines whose entire job is
adapting *that* codebase's config shape to `model_list`; two codebases with
different config shapes get a shared dependency plus two adapters, which is
more moving parts than a copy. The transferable asset is this document — the
knob rationale, the skip list, and the dead-fallback failure mode — not the
code.

## Related

- `litellm-custom-provider-dispatch-order` — read it before adding a
  `CustomLLM` rung to the Router this skill builds. A provider registered
  correctly can still never run: the call goes to a built-in provider instead
  and is billed to whatever key that provider finds in the environment, which
  is the dead-rung failure above with a bill attached. It also covers the
  Router refusing such a deployment at construction time.
- `openclaw-model-cascade-debugging` — the same waterfall seen from the other
  end, when the cascade is someone else's and you are working out which rung
  actually served a call.
