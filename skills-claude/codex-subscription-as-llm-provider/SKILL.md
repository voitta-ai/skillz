---
name: codex-subscription-as-llm-provider
description: |
  Use a ChatGPT plan, through the `codex` CLI's own login, as the model backend
  of your own app or agent instead of a platform API key. Use when: (1) you
  want an OpenAI model provider in an app that runs on a ChatGPT subscription
  you already pay for, with no OPENAI_API_KEY; (2) you are adding a "codex"
  rung to a provider waterfall next to API-key providers; (3) requests to
  https://chatgpt.com/backend-api/codex/responses fail and you need the
  endpoint contract (stream=true and store=false required, no
  max_output_tokens, flat tools with strict=false, CLI headers); (4) your
  provider breaks after a while because the access token expired and you
  are tempted to refresh it yourself (don't - the CLI owns auth.json).
  READ THE CAVEAT FIRST: whether this use of a consumer subscription is
  permitted under OpenAI's terms is unresolved, and the endpoint is
  undocumented.
author: Claude Code
version: 1.0.0
date: 2026-10-08
source: voitta-ai/voitta-compute PR #9 (merged 2026-10-01), mirroring the codex rung in voitta-ai/shmobster's provider waterfall
source_file: skills/codex-subscription-as-llm-provider/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/codex-subscription-as-llm-provider/SKILL.md`). Updates go through the
> repo's worktree + PR workflow - open an issue, branch, PR.

# Codex (ChatGPT subscription) as an LLM provider

## Caveat - read before using

- **Terms are unresolved.** We have not determined whether using a consumer
  ChatGPT/Codex subscription as an application's model backend is permitted
  under OpenAI's terms. Check the current terms for your plan before relying on
  this, and do not use it for anything you could not defend if the answer is
  no. We publish the technique openly rather than quietly; that is not a legal
  opinion either way.
- **Undocumented endpoint, client impersonation.** The requests go to the
  ChatGPT backend the `codex` CLI uses, and identify themselves with the CLI's
  `originator` / `User-Agent` value. OpenAI can change or close this at any
  time without notice, and a provider built on it can break overnight.
- **Your own account only.** The credential is your personal ChatGPT plan's
  OAuth token. Never ship it, share it, or run a multi-user service on one
  person's subscription.

If any of those is a problem, use a platform API key instead.

## Problem

You want an OpenAI model in your own app or agent, and you already have a
ChatGPT plan with Codex. The `codex` CLI authenticates against that plan, not
against an API key. Pointing the official OpenAI SDK at the CLI's backend with
the CLI's token works, but only if requests match what the backend expects;
otherwise they fail in unhelpful ways.

## Solution

Reuse an existing OpenAI **Responses API** adapter. Change only the base URL,
the credential, the headers, and four request fields.

### Endpoint contract (mirrors the CLI)

```
POST https://chatgpt.com/backend-api/codex/responses
Authorization: Bearer <access_token>
ChatGPT-Account-Id: <account_id>          # when present in auth.json
originator: codex_cli_rs
User-Agent: codex_cli_rs
session_id: <uuid4>

body: stream=true and store=false (both required); no max_output_tokens;
      tools flat, each with strict=false
```

### Credentials: read, never write

- **Location:** the token lives in `$CODEX_HOME/auth.json` (default
  `~/.codex/auth.json`), under `tokens.access_token` and `tokens.account_id`.
- **Re-read on every request,** so a token the CLI rotated is picked up
  without a restart.
- **Never refresh or write the file.** The CLI owns it, and a second writer
  races it. `codex login` (or any `codex` run) keeps it fresh.
- **Optionally warn** when the JWT `exp` claim is within ~24h, using an
  unverified decode that is only used for the warning.
- **Signed out:** fail with an actionable message ("run `codex login`")
  instead of a 401.

### Models: no network call

The CLI caches the plan's models in `$CODEX_HOME/models_cache.json`. List the
entries with `visibility == "list"`, sorted by `priority`, and use their
`slug`.

### Minimal adapter (Python, OpenAI SDK)

```python
import json, os, uuid
from pathlib import Path
from openai import AsyncOpenAI

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
ORIGINATOR = "codex_cli_rs"


def codex_home():
    raw = os.environ.get("CODEX_HOME")
    retval = Path(raw).expanduser() if raw else Path.home() / ".codex"
    return retval


def load_auth():
    """(access_token, account_id) from the CLI's auth.json, or None."""
    retval = None
    try:
        tokens = json.loads((codex_home() / "auth.json").read_text()).get("tokens") or {}
        if tokens.get("access_token"):
            retval = (tokens["access_token"], tokens.get("account_id"))
    except FileNotFoundError:
        pass
    return retval


def codex_client():
    auth = load_auth()
    if auth is None:
        raise RuntimeError("codex: not signed in; run `codex login`")
    token, account_id = auth
    headers = {"originator": ORIGINATOR, "User-Agent": ORIGINATOR,
               "session_id": str(uuid.uuid4())}
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    retval = AsyncOpenAI(api_key=token, base_url=CODEX_BASE_URL,
                         default_headers=headers, timeout=300.0)
    return retval


def codex_request_kwargs(kwargs):
    """Adapt Responses API kwargs to what this backend accepts."""
    kwargs.pop("max_output_tokens", None)   # rejected by the backend
    kwargs["store"] = False                 # required
    kwargs["stream"] = True                 # required
    for tool in kwargs.get("tools") or []:
        tool["strict"] = False
    retval = kwargs
    return retval
```

Build a fresh client per request, so a rotated token is picked up. In a
provider factory, `codex` is the one provider that needs no API key; gate it on
"is the CLI signed in" instead.

## Verification

What the source PR verified, and what it did not:

- **Verified:** a live adapter test against the endpoint returned a plain text
  reply, made a tool call, and gave a follow-up answer after the tool result.
  The frontend type-checked and the backend modules compiled.
- **Not verified there:** running inside the full installed app; long-running
  token expiry and rotation behaviour beyond the 24h warning path; rate limits
  and plan quotas under sustained use.

Check it yourself:
1. Run `codex login`.
2. Send one non-tool request, one tool request, and one follow-up after a tool
   result.
3. Confirm `models_cache.json` lists the model you request.

## Notes

- **The request rules are the backend's, not the SDK's defaults.** Leaving
  `max_output_tokens` in, or omitting `store=false`, fails the request.
- **Keep it a separate provider id** (e.g. `codex`) rather than a flag on the
  OpenAI provider, so the "no API key" and "signed-in" logic stays explicit.
- **It works in a waterfall:** try the subscription first, then fall through to
  API-key providers on failure. If the endpoint changes, the waterfall
  degrades instead of breaking.

## Related

- `llm-vendor-waterfall` - ordering providers so one failing rung falls
  through to the next.
