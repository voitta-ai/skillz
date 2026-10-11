---
name: slack-socket-mode-shared-app-token
description: |
  Diagnose and fix a Slack bot that silently misses some @-mentions because a
  second program holds a Socket Mode connection on the same app-level (`xapp-`)
  token. Use when: (1) identical mentions are answered some of the time and
  ignored the rest, with no reaction, no reply and no log line for the missed
  ones; (2) the bot's own Socket Mode connection is healthy throughout (same
  session id before and after the miss, pings answered, watchdog green), so it
  does not look like a wedged socket; (3) you are wiring an approval-button
  listener, card handler or any other tool that needs inbound Slack events or
  interactions, and are about to reuse an existing bot's `xapp-` token;
  (4) button clicks on cards "sometimes do nothing". Headline: Slack spreads an
  app's events and interactions across ALL of that app's open Socket Mode
  connections and delivers each to only one, so every other consumer of the same
  token takes a share. One Socket Mode consumer per app. Incoming webhooks and
  `chat.postMessage` only post and cannot cause this.
author: Claude Code
version: 1.0.0
date: 2026-10-07
source: https://github.com/voitta-ai/skillz
source_file: skills/slack-socket-mode-shared-app-token/SKILL.md
---

# Two Socket Mode clients on one Slack app split its events

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/slack-socket-mode-shared-app-token/SKILL.md`). Updates go through the
> repo's worktree + PR workflow.

## Problem

A chat bot answers `@`-mentions over Socket Mode. Some mentions get no reaction
and no reply, and the bot's log shows nothing for them. The same question
asked ten minutes later is answered normally. Nothing in the bot looks broken.

The cause was outside the bot. A different tool, an approval-button listener,
had been configured with the bot's app-level token. Slack treated it as a second
connection of the same app and routed part of the app's traffic to it. That
listener acked every envelope (so Slack never retried) and kept only button
clicks, so each mention routed there disappeared without a trace.

## Context / Trigger Conditions

- Identical inputs, inconsistent outcome: one mention answered, an identical one
  silently ignored, with no pattern by user, channel or wording.
- The miss leaves nothing behind: no "eyes"/ack reaction (if the bot adds one
  first thing on receipt, the handler never ran), no error, no log line.
- The bot's connection is demonstrably fine across the miss: same Socket Mode
  session id before and after, pongs within seconds, no reconnect. This is what
  separates it from a half-open socket wedge, where the session stops ponging or
  keeps churning.
- Button clicks on interactive cards that "sometimes do nothing" are the same
  failure seen from the other side: interactions are split across connections
  too.
- Any long-running program with a Socket Mode client (Bolt `SocketModeHandler`,
  `slack_sdk.socket_mode.SocketModeClient`, `@slack/socket-mode`) whose config
  names an app token you did not create for it.

## Solution

### 1. Confirm it is a second consumer, not the bot

- Check that the missed message really is a normal human message with a real
  mention: fetch it raw (`conversations.history` with `latest`=`oldest`=its
  `ts`, `inclusive=true`) and look for `user` set, no `bot_id`, no `subtype`,
  no `edited`, and a `user` element in its blocks. An edit that adds a mention
  never fires `app_mention`.
- Check the bot's own connection over the window (session id, ping age). If it
  was healthy and nothing was logged, the event went somewhere else.

### 2. Find every program that opens a socket with that token

- **Do not print tokens.** Compare by hash: for each env var that another tool's
  config names as its app token (`<APP_TOKEN_ENV>`), compare
  `sha256(value)[:10]` with the same hash of the bot's own token.
- **Do not trust an environment scan.** If tokens are exported from a shell
  profile and synced into the login session, every process inherits them, so
  "which processes have an `xapp-` in their env" lists nearly everything. Look
  at what actually opens a Socket Mode connection instead: long-running jobs
  (`launchctl list`, systemd units, containers) whose command runs a Socket Mode
  client, and the config each one reads (`app_token_env`, `SLACK_APP_TOKEN`,
  `appToken`).
- Include containers (`docker inspect` env, compared by hash) and dev runs from
  other checkouts or worktrees. One may have run at the time of the miss and
  exited since, so check job histories, not only what is running now.

### 3. Fix: one Socket Mode consumer per app

- **Never point another tool at a chat bot's app.** Give it its own Slack app.
- **Approval / card listeners: one shared app, not one per agent.** The click is
  delivered to the app that *posted* the card, so the same app must both post
  the cards (its bot token in the poster's config) and hold the listener (its
  app-level token). Cards posted with the chat bot's token send their clicks to
  the chat bot's app, whichever listener you start.
- **One listener per app**, unless that listener routes each click to the owner
  of the proposal or card. Two per-agent listeners on one shared app split the
  clicks, and each refuses the other's ("unknown proposal", "wrong channel").
- **Webhooks and posting are fine to share.** Incoming webhooks and
  `chat.postMessage` only post; they never receive events, so they cannot steal
  anything. Their only side effect is that posts appear under that app's name.
- Stopping the stray consumer is the immediate mitigation. If it is a
  KeepAlive/RunAtLoad job, unloading it lasts only until the next login or
  reinstall; disable or repoint it, don't just stop it.

## Verification

- No other program's app token hashes equal to the bot's.
- No Socket Mode job other than the bot is running with that app's token.
- Repeat the mention that was missed several times: every one gets the bot's
  receipt reaction and a reply.
- Better for next time: log every event the bot receives (its `ts`) at INFO.
  Then "Slack never sent it" and "another connection took it" stop looking the
  same.

## Example

A bot answered `@bot Anything from <client> in our email or contracts?` at one
time and ignored the identical question ten minutes earlier: no reaction, no log
line, and the same socket session id with healthy pings across both. Another
team's approval-button listener had been configured with
`app_token_env: <APP_TOKEN_ENV>`, whose value hashed equal to the bot's token. It
had run for a week, so a share of mentions had been vanishing all that time.
Unloading the listener stopped the misses. The lasting fix was a dedicated app
for all approval cards and their listener.

## Notes

- **A different problem with similar symptoms:** an agent never receives a
  mention posted by its *own* app (its bot token or its app's incoming webhook),
  because Slack does not deliver `app_mention` for the app's own messages. That
  fails every time, not intermittently. See `slack-agent-cannot-wake-itself`.
- A consumer that acks every envelope and then ignores it makes the loss
  permanent: Slack sees the payload as delivered and never retries it.
- Running a dev and a live instance of the same bot on one app causes the same
  split. Use a separate app for dev.
- Rotating the token does not help if both programs read it from the same env
  var; the fix is separate apps.

## References

- Slack Developer Docs, "Using Socket Mode", section "Using multiple
  connections": https://docs.slack.dev/apis/events-api/using-socket-mode/ --
  "Socket Mode allows your app to maintain up to 10 open WebSocket connections
  at the same time. When multiple connections are active, each payload may be
  sent to any of the connections."
