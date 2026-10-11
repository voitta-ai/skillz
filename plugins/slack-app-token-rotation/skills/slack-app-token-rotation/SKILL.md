---
name: slack-app-token-rotation
description: |
  Actually rotate a leaked Slack app credential, and survive the side effects.
  Use when: (1) a bot (`xoxb-`) or app-level (`xapp-`) token leaked and must be
  replaced; (2) you clicked "Reinstall to Workspace" to rotate a bot token and
  the old token still works; (3) after rotating, the bot returns
  `channel_not_found` on channels it was clearly in; (4) the reinstall screen
  demands "a channel to post as an app" and you are unsure whether it pins the
  bot to one channel; (5) the `incoming-webhook` scope will not delete because
  its trash button is greyed out; (6) `apps_connections_open()` raises TypeError
  and you are reading it as an auth failure. Headline: reinstalling does NOT
  mint a new bot token -- only destroying the OAuth grant does.
author: Claude Code
version: 1.0.0
---

# Rotating Slack app tokens

## Problem

A bot token leaked. The obvious move — *OAuth & Permissions -> Reinstall to
Workspace* — appears to work, reports success, and **hands back the same
`xoxb-`**.

Same installing user, same scopes, same OAuth grant, so Slack has no reason to
mint a new token. Verified the hard way: after a full reinstall the leaked token
still passed `auth.test` with an identical fingerprint. If you stop there you
have done nothing except believe you rotated.

## The rule

For a **static (non-rotating) bot token there is no rotate-in-place.** The token
*is* the handle to the OAuth grant. To get a different one you must destroy the
grant:

```
auth.revoke(old bot token)  ->  grant destroyed  ->  app is UNINSTALLED
install again               ->  genuinely new xoxb-
```

Both routes end in a reinstall, but **revoke first** under a known leak: it
closes the exposure immediately rather than whenever you next reach the UI.

App-level (`xapp-`) tokens behave the way you would expect — *Basic Information
-> App-Level Tokens -> delete, then create* with `connections:write` — and do
rotate.

## What uninstalling breaks

### The bot leaves every channel

This is the big one, and it does not look like what it is.

After reinstall the bot is a member of **nothing**. Calls against channels it
used to serve return:

```
channel_not_found
```

which reads like a bad token or a bad channel id. It means neither — it means
**not a member**. Private channels especially.

Re-invite per channel (`/invite @<app>`) and verify each rather than assuming:

```python
WebClient(token=bot).conversations_info(channel=cid)["channel"]["is_member"]
```

### Incoming webhook URLs are revoked

If the app has Incoming Webhooks enabled, reinstalling invalidates existing
webhook URLs. Every consumer needs the new one. If those URLs sat anywhere near
the leaked credentials, treat them as leaked too and rotate regardless.

## The channel picker that looks like a trap

The reinstall screen shows **"Channel for webhook — `<app>` requires a channel to
post as an app"**, implying the bot will be pinned to a single channel.

It will not. That picker appears *only* because the app carries the
`incoming-webhook` scope, which mints one webhook URL bound to one channel. Bot
posting is `chat:write` over Socket Mode and is completely unaffected.

- **Not using webhooks** -> drop the scope. The picker disappears and you have
  one fewer credential to manage.
- **Using webhooks** -> keep it and pick any channel; the choice is cosmetic
  with respect to bot posting.

### Why the scope will not delete

The scope's **trash button is greyed out** while *Features -> Incoming Webhooks*
is activated: the feature owns the scope. Unchecking the row does nothing. Turn
the feature off first, or edit the App Manifest, which flips both at once.

## Runbook

1. **Remove the leak source first** — whatever relayed, logged or committed the
   credentials. Rotating into the same pipe just produces a fresh leak.
2. **`auth.revoke` the old bot token.** Confirm it now returns `invalid_auth`.
3. **Delete and recreate the app-level token** with `connections:write`. Confirm
   the old one returns `invalid_auth`.
4. **Reinstall the app** -> new `xoxb-`. Confirm the fingerprint differs from the
   old one.
5. **Land both values** in the service's config, kept `chmod 600`.
6. **Re-invite the bot to every channel** it needs, verifying `is_member` on each.
7. **Restart the service.** Watch for a clean startup with no reconnect churn,
   then send a real mention as an end-to-end check.
8. **Clean up dead exported token vars** in shell profiles, and sweep for the old
   values on disk (see `agent-credential-leak-surfaces`).

## Verification

```python
WebClient(token=bot).auth_test()                       # bot token + identity
WebClient().apps_connections_open(app_token=app)       # app-level token
WebClient(token=bot).conversations_info(channel=cid)   # ["channel"]["is_member"]
```

**Gotcha:** `apps_connections_open()` takes `app_token=` as a *required keyword
argument*. Constructing `WebClient(token=app_token)` and calling it bare raises
`TypeError`, which is very easy to misread as an authentication failure and send
you rotating a token that was fine.

Same check without the SDK:

```bash
curl -s -X POST https://slack.com/api/auth.test -H "Authorization: Bearer $T" \
  | python3 -c "import json,sys;print(json.load(sys.stdin).get('ok'))"
```

## Do not print the tokens

Rotation is exactly the task where an agent leaks the thing it is fixing. Prove
the rotation with fingerprints instead:

```bash
fp() { printf '%s' "$1" | shasum | cut -c1-10; }
fp "$OLD"    # then confirm auth.test on it returns ok=false
fp "$NEW"    # different fingerprint, ok=true
```

See `secrets-in-agent-sessions` for moving the new values into a config file
without them passing through the transcript.

## If this keeps happening

Slack supports **token rotation** (`token_rotation_enabled` in the manifest):
refresh-token-based `xoxe-` tokens that rotate *without* uninstalling, which
removes the whole channel-membership blast radius. The cost is that your app can
no longer read a static token out of a config file — it needs a refresh path in
code. Worth it only if rotation is recurring rather than a one-off incident.

## Provenance

Derived from a real rotation documented in
[voitta-ai/shmobster#67](https://github.com/voitta-ai/shmobster/issues/67),
where the reinstall-does-not-rotate behaviour cost a full round trip before it
was spotted.

## Related

- `agent-credential-leak-surfaces` — finding every copy of the old token before
  and after rotating.
- `secrets-in-agent-sessions` — handling the values without adding copies.
- `slack-xoxc-session-client` — the different problem of driving Slack as
  *yourself* when you cannot install an app at all.
