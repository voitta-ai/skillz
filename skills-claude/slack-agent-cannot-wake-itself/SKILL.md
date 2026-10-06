---
name: slack-agent-cannot-wake-itself
description: |
  Before posting to Slack on a human's behalf, check which identity the posting
  tool uses, because a Slack agent never responds to a message posted by its own
  app. Use when: (1) you are about to post into a thread to hand a Slack-resident
  agent (a bot answering @mentions) a follow-up, retry request or instruction on
  the operator's behalf; (2) a Slack MCP server or script is available and you
  have not checked whose token it holds; (3) you posted "@agent please ..." and
  the agent did nothing: no reaction, no reply, no line in its log; (4) the post
  appeared under the agent's name and avatar instead of the operator's; (5) you
  are considering an incoming webhook as a way to post as someone else. Headline:
  Slack does not deliver `app_mention` for a message posted by the same app, so
  the agent's own bot token, and any incoming webhook owned by the agent's app,
  cannot wake it. Such a post also carries no human user, so it cannot carry a
  trusted person's authority. Post as the human, e.g. with
  `slack-xoxc-session-client`, or hand them the text to paste.
author: Claude Code
version: 1.0.0
date: 2026-09-17
source: https://github.com/voitta-ai/skillz
source_file: skills/slack-agent-cannot-wake-itself/SKILL.md
---

# A Slack agent cannot wake itself: post as the human

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/slack-agent-cannot-wake-itself/SKILL.md`). Updates go through the
> repo's worktree + PR workflow.

## Problem

An operator asks you to post into a Slack thread and tag both a person and the
workspace's agent (a bot that acts on `@mention`), so that the agent retries
something. You post through the Slack tool you have. The message appears, but:

- it is shown as **written by the agent**, under its name and avatar, so the
  first-person "I updated the config" now reads as the agent talking about
  itself, and
- the agent **does not react**: no acknowledging reaction, no reply, nothing in
  its log.

The cause is that the Slack tool held the **agent's own bot token**. This is
common: the Slack MCP server or helper script on an operator's machine is
often configured with the same app the agent runs as, because that app was
already installed. Slack does not send an `app_mention` event to an app for a
message that app posted itself. The mention never reaches the agent's event
handler, so the agent's code never gets a chance to decide whether to ignore it.

An incoming webhook does not fix this if the webhook belongs to the agent's
app, which is likely when the app has the `incoming-webhook` scope: the post
is still authored by that app.

There is a second, independent reason to post as the human. Agents that gate
actions on a trusted-user list (approvals, policy changes) key that trust on the
posting **user id**. A bot or webhook post has a `bot_id` and no human `user`, so
at best it counts as "another agent" and cannot carry the operator's authority.

## Context / Trigger Conditions

- You are about to post, on a human's behalf, a message whose purpose is to make
  a Slack agent do something.
- The posting tool is a Slack MCP server, an SDK script, or a webhook, and you
  have not confirmed whose token it uses.
- After posting: the response shows `bot_id` / `app_id` equal to the agent's,
  or `user` equal to the agent's bot user id.
- The agent's log has no entry for the message timestamp, although the agent
  is up and connected.

## Solution

1. **Identify the posting identity before posting.** Cheapest checks, in order:
   - Call `auth.test` with the tool's token, or read the tool's configuration,
     and compare the returned `user_id` / `bot_id` with the agent's.
   - If you cannot check, assume the tool posts as the app it was installed as.
     On a machine that runs the agent, that is usually the agent.
2. **If the tool posts as the agent, do not use it** for this message. Pick one:
   - **Post as the human** with their own session:
     `slack-xoxc-session-client` (xoxc web token plus the `d` cookie from the
     browser). A human-authored `<@agent>` mention fires `app_mention` normally,
     and the agent sees the real user id, so trusted-user checks behave as if
     the human typed it. Say in the text that an agent drafted it if the
     client's self-label is off.
   - **Hand the human the text** to paste. This is always safe and needs no
     credentials.
   - A webhook or bot from a **different** app avoids the same-app filter, but
     whether Slack delivers `app_mention` from another app in a channel was not
     verified here, and the post still has no human user id. Use it only for
     informational posts, never to deliver a person's approval or instruction.
3. **Split informational posts from action requests.** A status note ("config
   updated, agent restarted") can go out as any identity if it is worded neutrally.
   The part that asks the agent to act must come from a human account.
4. **If a wrong-identity post already went out**, tell the operator plainly: it
   reads as the agent speaking, and it did not trigger the agent. Offer the
   corrected text. The agent's token usually cannot delete or edit the post
   through a limited MCP tool set, so deleting it may be up to the human.

## Verification

- The posted message's `user` is the human's id, and there is no `bot_id`.
- The agent adds its acknowledging reaction (often `:eyes:`) within seconds, and
  its log shows a turn for that message `ts`.
- If the agent parks an action for approval, the approval can come from the same
  human account.

## Example

An operator added `api.figma.com` to an agent's per-channel network allowlist,
restarted the agent, and asked for a thread reply tagging the requester and the
agent. The reply went through a Slack MCP server whose token was the agent's
bot token. Slack showed the reply as the agent's, starting "I just updated this
channel's config ... <agent>, please try again". The agent's log had nothing after
its startup lines. The fix was to give the operator the text to post from their
own account, and to record that this machine's Slack MCP server posts as the agent.

## Notes

- Reading is unaffected. The same token is fine for fetching the thread and looking
  up user ids (`users.list`). `users.profile.get` may fail with `missing_scope`
  on a bot token.
- Slack's docs state explicitly that messages in DMs to an app, including those
  from other apps, are not dispatched as `app_mention`. The same-app behavior in
  channels was observed, not quoted.
- Do not fix this by having the agent respond to its own app's messages. That is
  the loop the filter exists to prevent.
- Related: `slack-xoxc-session-client` (posting as yourself),
  `slack-app-token-rotation` (the `incoming-webhook` scope on the agent's app).

## References

- Slack `app_mention` event: https://docs.slack.dev/reference/events/app_mention
- Slack `auth.test`: https://docs.slack.dev/reference/methods/auth.test
