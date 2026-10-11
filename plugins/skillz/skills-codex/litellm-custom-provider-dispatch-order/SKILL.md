---
name: litellm-custom-provider-dispatch-order
description: |
  Fix a LiteLLM `CustomLLM` provider that is registered correctly and still
  never runs — the call silently goes to a built-in provider instead, billed
  to whatever API key that provider finds in the environment. Use when:
  (1) you registered a handler via `litellm.custom_provider_map` and your
  `completion()` override is never entered (no logs, no breakpoint hit),
  (2) a call to `myprovider/<model>` returns an error naming a DIFFERENT
  vendor — `Incorrect API key provided: sk-...`, `invalid_api_key`,
  or an auth failure for a service you never configured,
  (3) `litellm.get_llm_provider("myprovider/<model>")` correctly returns
  your provider, and the call STILL goes somewhere else,
  (4) a `Router` refuses the deployment at construction time with
  `LLM Provider NOT provided. Pass in the LLM provider you are trying to
  call`, before any completion is attempted,
  (5) you are bridging a subscription/OAuth backend (ChatGPT-Codex, a
  gateway, an internal proxy) into a waterfall and reusing the upstream's
  real model ids.
  Root cause: `litellm.completion()` dispatches through one long if/elif
  chain, and SEVEN branches that match on the BARE MODEL NAME
  (`model in litellm.open_ai_chat_completion_models`, `.replicate_models`,
  `.together_ai_models`, `.petals_models`, `.snowflake_models`,
  `.ovhcloud_models`, `.clarifai_models`) come BEFORE the
  `custom_llm_provider in litellm._custom_providers` branch. LiteLLM strips
  your prefix first, so a custom row reusing a known upstream model id is
  captured by an earlier branch and never reaches your handler.
  Covers the two-line registration (map + `custom_llm_setup()`), the
  namespaced-model fix, the collision check, and the assertion that proves
  the handler actually ran.
author: Claude Code
version: 1.0.0
date: 2026-08-20
source: https://github.com/voitta-ai/skillz
source_file: skills/litellm-custom-provider-dispatch-order/SKILL.md
---

# LiteLLM dispatches on the model name before your custom provider

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/litellm-custom-provider-dispatch-order/SKILL.md`). Updates go through
> the repo's worktree + PR workflow - open an issue, branch, PR.

## Problem

You bridge some backend into LiteLLM as a custom provider — the documented way:

```python
class MyLLM(litellm.CustomLLM):
    def completion(self, model, messages, ..., optional_params, ...):
        ...

litellm.custom_provider_map = [{"provider": "myprovider", "custom_handler": MyLLM()}]
```

You call it with the model string the upstream actually wants:

```python
litellm.completion(model="myprovider/gpt-5.5", messages=[...])
```

And you get, from a service you never configured:

```
litellm.APIConnectionError: MyproviderException - Error code: 401 -
{'error': {'message': 'Incorrect API key provided: sk-proj-****...****YNQA.
 You can find your API key at https://platform.openai.com/account/api-keys.',
 'type': 'invalid_request_error', 'code': 'invalid_api_key'}}
```

Your handler was never entered. Note the exception *name* says `Myprovider`,
which is why this reads as "my provider is broken" rather than "my provider was
bypassed" — LiteLLM labels the exception with the resolved `custom_llm_provider`
even when a different branch serviced the call.

**The failure is silent and it costs money.** If `OPENAI_API_KEY` happens to be
valid in that environment, there is no error at all: you get a plausible answer,
billed to the platform account, from a vendor you thought you had replaced. A
fallback rung you believe is free is quietly metered.

## Root cause

`litellm.completion()` is one long `if / elif` chain over dispatch conditions.
Several of those branches match on the **bare model name**, not on the provider,
and they sit **earlier in the chain** than the custom-provider branch.

LiteLLM splits `myprovider/gpt-5.5` into provider `myprovider` and model
`gpt-5.5` before the chain runs. So by the time dispatch happens, the bare
`gpt-5.5` is sitting in a variable that an earlier branch tests against its own
model list — and wins.

Find them yourself (line numbers move between releases; the shape does not):

```bash
M=$(python -c "import litellm.main as m; print(m.__file__)")
CUSTOM=$(grep -n "custom_llm_provider in litellm._custom_providers" "$M" | head -1 | cut -d: -f1)
grep -n "model in litellm\." "$M" | awk -F: -v c="$CUSTOM" '$1 < c'
```

On litellm 1.83.7 that prints seven branches ahead of the custom one at 4324:

| Line | Condition | Catches |
| ---- | --------- | ------- |
| 2564 | `model in litellm.open_ai_chat_completion_models` | every OpenAI chat model id |
| 2740 | `model in litellm.replicate_models` | Replicate ids |
| 2789 | `model in litellm.clarifai_models` | Clarifai ids |
| 3404 | `model in litellm.together_ai_models` | Together ids |
| 4087 | `model in litellm.petals_models` | Petals ids |
| 4116 | `model in litellm.snowflake_models` | Snowflake ids |
| 4226 | `model in litellm.ovhcloud_models` | OVHcloud ids |

The OpenAI list is the dangerous one: it is large, it tracks new releases, and
it is the namespace most bridges reuse. A model id that is safe today can be
added to it by a routine LiteLLM upgrade, so a bridge that works now can be
hijacked by a dependency bump with no code change on your side.

`custom_llm_provider` being correct does **not** save you. These branches are
`or`-ed against model membership:

```python
elif (
    model in litellm.open_ai_chat_completion_models
    or custom_llm_provider == "custom_openai"
    ...
):
```

Passing `custom_llm_provider="myprovider"` explicitly changes nothing — the
first disjunct already matched.

## Check for a collision

```python
import litellm
BARE = "gpt-5.5"          # what is left after your prefix is stripped
for lst in ("open_ai_chat_completion_models", "replicate_models",
            "clarifai_models", "together_ai_models", "petals_models",
            "snowflake_models", "ovhcloud_models"):
    if BARE in getattr(litellm, lst, []):
        print("COLLISION:", lst)      # this model id will never reach your handler
```

## Fix: namespace the model past the check, strip it in the handler

Add a segment that is not a known model id in any of those lists. LiteLLM splits
on the **first** `/` only, so everything after your provider prefix arrives at
your handler intact.

```python
_MODEL_PREFIX = "upstream/"        # any segment that is not a real model id

class MyLLM(litellm.CustomLLM):
    def completion(self, model, messages, ..., optional_params, ...):
        # model == "upstream/gpt-5.5" -> send "gpt-5.5" on the wire
        wire_model = model[len(_MODEL_PREFIX):] if model.startswith(_MODEL_PREFIX) else model
```

Verify the resolution before you write anything else:

```python
>>> litellm.get_llm_provider(model="myprovider/upstream/gpt-5.5")
('upstream/gpt-5.5', 'myprovider', None, None)
>>> "upstream/gpt-5.5" in litellm.open_ai_chat_completion_models
False
```

Document the segment where the config lives. It looks like decoration and the
next person will "clean it up":

```json
{"name": "myvendor", "model": "myprovider/upstream/gpt-5.5"}
```

**Do not** solve this by renaming the model to something the upstream does not
accept — you trade a silent mis-route for a 400 from the backend. The namespace
segment exists precisely so the wire model can stay correct.

## The other half: registration is two calls, not one

`custom_provider_map` alone tells LiteLLM how to *call* your provider. It does
not make LiteLLM *recognise the prefix*. That is `custom_llm_setup()`, which
appends the name to `litellm.provider_list` and `litellm._custom_providers`.

```python
from litellm.utils import custom_llm_setup

def register():
    if not any(e.get("provider") == PROVIDER for e in litellm.custom_provider_map):
        litellm.custom_provider_map = list(litellm.custom_provider_map) + [
            {"provider": PROVIDER, "custom_handler": _HANDLER}
        ]
    custom_llm_setup()
```

A bare `litellm.completion()` gets away without the explicit call, because
`custom_llm_setup()` runs from `function_setup()` inside the `@client`
decorator that wraps it — on the way *into* the call. **`Router` does not get
that grace**: it resolves every deployment's provider in `_add_deployment()` at
**construction** time, long before any wrapped call runs, so the row is rejected
up front:

```
litellm.BadRequestError: LLM Provider NOT provided. Pass in the LLM provider
you are trying to call. You passed model=myprovider/upstream/gpt-5.5
```

That one is loud and easy. It is the *silent* mis-route above that costs you.
Register before the Router is built, and make `register()` idempotent —
`custom_provider_map` is module-global, and a Router rebuild that appends a
second entry shadows itself.

## Prove the handler ran

Resolution succeeding is not evidence of dispatch. `get_llm_provider()` returned
the right provider in the broken case too. Assert on the handler, not the result:

```python
called = []
orig = MyLLM.completion
MyLLM.completion = lambda self, *a, **k: (called.append(1), orig(self, *a, **k))[1]

litellm.completion(model="myprovider/upstream/gpt-5.5",
                   messages=[{"role": "user", "content": "say PONG"}])
assert called, "handler was bypassed -- an earlier branch matched the bare model name"
```

Keep this assertion in whatever offline check the project already runs. The
collision can be reintroduced by a LiteLLM upgrade rather than by an edit, so a
one-time manual verification is not enough.

## Symptom-to-cause table

| Symptom | Cause |
| ------- | ----- |
| Handler never entered; error names another vendor's API key | bare model name matched an earlier branch |
| Handler never entered; **no error**, plausible answer, unexpected bill | same, and that vendor's key was valid |
| `LLM Provider NOT provided` at `Router(...)` construction | `custom_llm_setup()` not called |
| Worked for months, broke after a dependency bump | the model id was added to a built-in list |
| `get_llm_provider()` right, dispatch wrong | resolution and dispatch are separate steps |

## Applies to

Any `litellm.CustomLLM` bridge that reuses an upstream's real model ids —
subscription/OAuth backends (a ChatGPT-Codex bridge is the case this came from),
internal gateways, proxies, and local runtimes fronting well-known model names.
