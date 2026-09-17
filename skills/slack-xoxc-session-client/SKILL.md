---
name: slack-xoxc-session-client
description: |
  Drive the Slack web API as yourself in a workspace where you cannot create or
  install an app (no xoxb/xoxp token path) by reusing your live browser session.
  Use when: (1) you participate in a Slack workspace but lack admin/app-install
  rights, so OAuth bot/user tokens are off the table; (2) you need to read history,
  list channels, search, or post programmatically acting as the logged-in user;
  (3) you want to leave UNSENT drafts in the person's Slack for them to review
  and send themselves (`drafts.create` / `drafts.update`); (4) a prior attempt failed because the `d` auth cookie is httpOnly and
  document.cookie / JS extraction returns it empty (the wall every
  browser-automation attempt hits). Headline insight: decrypt the httpOnly
  `d` cookie straight from the browser cookie store with pycookiecheat, and scrape
  the `xoxc-` web token from the authenticated workspace HTML (`"api_token"` key).
  Ships a working, generalized Python client (slack_client.py) that self-labels
  outgoing posts with a good-faith agent marker by default.
author: Claude Code
version: 1.3.0
date: 2026-09-16
source: https://github.com/voitta-ai/skillz/issues/67
source_file: skills/slack-xoxc-session-client/slack_client.py
---

# Slack session-token (xoxc + d cookie) programmatic access

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/slack-xoxc-session-client/SKILL.md`). The runnable client is the
> sibling `slack_client.py`. Updates go through the repo's worktree + PR
> workflow.

## Problem

You belong to a Slack workspace but **cannot create or install an app** there
(common in community / customer / employer workspaces where you are not an
admin). No app means no `xoxb`/`xoxp` OAuth token, so the documented Slack SDK
path is closed. You still want to read channels, search, or post
programmatically **as yourself**.

Headless browser automation (Playwright/Selenium) does not rescue this: Slack
detects the automation and blanks the page, and the captured session cookies are
missing the critical `d` auth token because it is **httpOnly** —
`document.cookie` and any in-page JS extraction return it empty. That is exactly
where a browser-automation workaround stalls: it drives the already-open
Slack tab, so it inherits every UI change and login prompt.

## Context / Trigger Conditions

Invoke when:

- You participate in a Slack workspace as yourself but lack admin / app-install
  rights (no OAuth bot/user token available).
- You need programmatic read (history, channel list, search) or write
  (post message) acting as the logged-in user.
- A human wants to review text before it goes out: create it as a Slack
  **draft** (see "Drafts: leave it unsent for a human" below) instead of
  posting it.
- A previous attempt failed because the `d` cookie came back empty from
  `document.cookie` / Claude-in-Chrome JS (httpOnly barrier).
- You are logged in to the target workspace in a local browser whose cookie
  store pycookiecheat can decrypt (Chrome/Chromium/Brave/Edge/Firefox/Arc/...).

Do NOT use when:

- You can install a Slack app — use a proper `xoxb`/`xoxp` token and the Slack
  SDK instead. This path is undocumented and ToS-gray.
- You need to act for other people or at scale — this is personal use only.

## Solution

Two secrets, both auto-extracted (no manual DevTools copy):

1. **`d` (+ `d-s`) session cookie.** `d` is **httpOnly**, so JS extraction is
   blocked. Decrypt the browser's cookie store directly with **`pycookiecheat`**
   (handles the macOS Keychain unlock, Linux Secret Service, Windows DPAPI). The
   real `d` value starts with `xoxd-`; if it does not, you are not logged in to
   that workspace in that browser.
2. **`xoxc-` web token.** Lives in localStorage, but is also embedded in the
   authenticated workspace HTML as `"api_token":"xoxc-..."`. Scrape it with an
   HTTP GET that carries the `d` cookie — no headless browser needed.

Then POST to `https://<subdomain>.slack.com/api/<method>` with
`data={"token": xoxc, ...}` and `cookies={"d":..., "d-s":...}`. Standard
web-API methods work: `auth.test`, `conversations.history`,
`users.conversations`, `search.messages` (user-token power), `chat.postMessage`.

The shipped `slack_client.py` implements exactly this:

```python
from slack_client import SlackSessionClient

sc = SlackSessionClient("<workspace-subdomain>")        # e.g. acme-corp
print(sc.call("auth.test"))
print(sc.call("conversations.history", channel="C0123ABCD", limit=50))
```

CLI:

```
python3 slack_client.py <workspace-subdomain> auth.test
python3 slack_client.py <workspace-subdomain> conversations.history channel=C0123 limit=20
python3 slack_client.py --browser firefox <workspace-subdomain> auth.test
```

## Key gotchas (encoded in the client)

- **`d` is httpOnly -> pycookiecheat, not `document.cookie`.** This is the
  headline insight. JS-based cookie reads never see `d`.
- **BASE host must be `https://<team>.slack.com/api`** (the team subdomain),
  NOT generic `slack.com` — the wrong host silently fails auth.
- **Include `d-s` alongside `d`;** some workspaces require it.
- **Secrets rotate** on logout / password change / session expiry. On
  `invalid_auth` the client re-extracts once and retries; if it still fails,
  re-login in the browser.
- **Multiple workspaces = multiple subdomains.** The subdomain is a constructor
  / CLI parameter.
- **Cross-platform / cross-browser** is the `browser=` arg, passed straight to
  pycookiecheat. Chrome is the default; Firefox and Chromium variants work by
  name (availability depends on the installed pycookiecheat version).

## Secret handling

- Tokens live **in memory only**. The client never writes `xoxc` or `d`/`d-s`
  to disk. Keep it that way — do not add a cache file.
- **Never print, log, or commit** the token or cookies. They grant full
  act-as-you access to the workspace.
- Do not hardcode a subdomain that identifies a real private workspace into any
  file committed to a public repo. Use a `<workspace-subdomain>` placeholder in
  examples (this skill does).

## Agent self-labeling (good-faith convention)

Because this client posts **as the logged-in human**, Slack cannot distinguish
an agent-authored message from one the person typed by hand — the same session,
the same identity. Nothing structural marks a post as agentic. So the only thing
that *can* mark it is a **voluntary convention**: a "robots.txt for agents" —
a norm anyone can honor or ignore, no enforcement, purely good faith.

This client ships that convention **on by default**, so the honest behavior is
the path of least resistance:

- Every outgoing post (`chat.postMessage`, `chat.update`, `chat.scheduleMessage`,
  `chat.meMessage`) is prefixed with a visible, greppable marker:

  ```
  🤖 [agent]                -> no label
  🤖 [agent: openclaw]      -> agent_label="openclaw"
  ```

- The marker is **human-visible** (readers see who they're talking to) and
  **machine-parseable** (`AGENT_MARKER_RE` — a post is agent-authored iff its
  text begins with `🤖 [agent`). That single regex *is* the whole protocol.
- Labeling is **idempotent** (already-marked text is left alone) and only
  touches posting methods carrying `text` — reads and non-text posts pass
  through untouched.

```python
sc = SlackSessionClient("<workspace-subdomain>", agent_label="openclaw")
sc.call("chat.postMessage", channel="C0123", text="on it")
# posts: "🤖 [agent: openclaw] on it"
```

Opt out per-client with `label_posts=False` (or `--no-label` on the CLI) — but
the point is to leave it on. It earns legitimacy by adoption, not by a
gatekeeper; other agents are free to adopt the same `🤖 [agent…]` marker so a
channel of mixed humans and agents stays honestly readable.

## Drafts: leave it unsent for a human

When the person wants to read, edit and send the message themselves, do not
post it: create a **draft**. It appears in their composer (or under "Drafts &
sent") exactly as if they had started typing it, and nothing is visible to
anyone else until they press send. `drafts.*` is the internal web-client API,
so it is undocumented; the shape below was verified against a live workspace
on 2026-09-16.

```python
import json, time, uuid

blocks = [{"type": "rich_text", "elements": [{"type": "rich_text_section",
           "elements": [{"type": "text", "text": "Draft body here. "},
                        {"type": "text", "text": "code", "style": {"code": True}},
                        {"type": "link", "url": "https://example.com"}]}]}]

sc = SlackSessionClient("<workspace-subdomain>", label_posts=False)
r = sc.call("drafts.create",
            blocks=json.dumps(blocks),
            destinations=json.dumps([{"channel_id": "C0123ABCD"}]),
            client_msg_id=str(uuid.uuid4()),
            file_ids="[]",
            is_from_composer="false",
            client_last_updated_ts=f"{time.time():.6f}")
draft_id = r["draft"]["id"]
```

Gotchas, each one an error string you will otherwise meet:

- **`client_msg_id` is required** (any fresh UUID). Without it:
  `invalid_arguments` / `missing required field: client_msg_id`.
- **Exactly one destination.** An empty list gives
  `invalid_destinations_count`; a draft cannot be left unaddressed.
- **One draft per destination.** A second draft into the same channel composer
  gives `attached_draft_exists`. A thread is its own destination
  (`{"channel_id": "C…", "thread_ts": "…", "broadcast": false}`), and the
  person's self-DM (`conversations.open users=<own user id>`) takes the overflow
  when there is no natural thread.
- **The composer slot may already be taken by the person's own draft.**
  `drafts.list` returns their hand-typed drafts too. Never update or delete a
  draft you did not create; route yours elsewhere.
- **A draft the person deleted in the app can keep holding the slot.** It
  lists with `is_deleted: true`, yet `drafts.create` to that destination still
  gives `attached_draft_exists`, and `drafts.update` / `drafts.delete` on it
  give `draft_update_invalid` / `draft_delete_invalid`. The API cannot free
  it: ask the person to open that composer and clear it, then retry.
- **Editing: `drafts.update`** with `draft_id` plus the same fields as create.
  A DM destination read back from `drafts.list` carries both `channel_id` and
  `user_ids`; passing both back gives
  `both_user_ids_and_channel_id_provided_in_destination`, so send only
  `channel_id`.
- **Text is rich_text blocks, not mrkdwn.** Links need a `link` element and
  inline code a `code` style; a raw URL inside a `text` element stays plain.
- **Labeling.** The human sends the draft as themselves after reading it, so
  create drafts with `label_posts=False`; the agent marker is for posts that go
  out without that review. (The client's labeler only touches `chat.*` methods
  anyway.)

Verify with `drafts.list`: find your id, check `is_deleted` / `is_sent` are
false, and read the text back out of `blocks`.

## Relationship to the interactive fallback

When the local-cookie path is unavailable (no decryptable profile, or you only
have an interactive browser), fall back to the **Claude-in-Chrome** approach
from browser automation: navigate the already-authenticated Chrome
tab and read the rendered page with the MCP tools. That avoids the httpOnly wall
by never needing the cookie at all, at the cost of being interactive rather than
scriptable.

## Verification

Verified working end-to-end on 2026-06-11 against a community workspace:
read history, list channels, and post — acting as the logged-in user, no Slack
app, no admin, no OAuth.

Smoke test after install:

1. Log in to the target workspace in your browser.
2. `python3 slack_client.py <workspace-subdomain> auth.test`
3. Expect `{"ok": true, "user": "<you>", "team": "<workspace>", ...}`.
4. `conversations.history channel=<C-id> limit=5` returns recent messages.

If `auth.test` returns `{"ok": false, "error": "invalid_auth"}` after the
auto-retry, re-login in the browser (the session expired). If it returns
`not_authed` against `slack.com`, check that the subdomain (team host) is
correct.

## Notes

- `search.messages` is a user-token capability — it works here because the
  `xoxc` web token carries your user scope, which a bot token would not.
- pycookiecheat may prompt for Keychain access on macOS the first time; grant it
  for the browser whose store you are decrypting.
- This supersedes the older conclusion that "session cookies never capture the
  `d` auth token" for the scriptable case. The interactive Claude-in-Chrome
  fallback is still the right move when you need a human-driven session.

## References

- [Slack web API methods](https://api.slack.com/methods)
- [pycookiecheat](https://github.com/n8henrie/pycookiecheat)
