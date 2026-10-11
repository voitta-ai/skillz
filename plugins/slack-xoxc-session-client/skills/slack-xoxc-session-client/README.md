# slack-xoxc-session-client

Drive the Slack web API **as yourself** in a workspace where you can't create or
install an app (no `xoxb`/`xoxp` OAuth path). It reuses your live browser
session: the httpOnly `d` cookie (decrypted via `pycookiecheat`) plus the `xoxc`
web token scraped from the authenticated page.

> **Personal use only — ToS-gray.** This posts as your own account, so Slack
> can't tell it from you typing. For a *shared* channel, use a real scoped Slack
> app/bot instead. Don't scale, share, or run it on behalf of others.

## Agent self-labeling (good-faith convention)

Because posts go out as the human, the only thing that marks a message as
agent-authored is a **voluntary convention** — a "robots.txt for agents", no
enforcement. So the client prefixes outgoing posts by default:

```
🤖 [agent]                -> no label
🤖 [agent: openclaw]      -> agent_label="openclaw"
```

Human-visible and machine-parseable (a post is agentic iff its text starts with
`🤖 [agent`). Opt out with `label_posts=False` / `--no-label`.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install pycookiecheat requests
# Log in to the workspace in your browser first, then:
.venv/bin/python3 slack_client.py <workspace-subdomain> auth.test
.venv/bin/python3 slack_client.py --agent-label openclaw <workspace-subdomain> \
    chat.postMessage channel=C0123 text='on it'   # posts: "🤖 [agent: openclaw] on it"
```

## Full detail

- **[SKILL.md](SKILL.md)** — the complete skill (trigger conditions, gotchas,
  secret handling, the labeling convention, verification). Source of truth.
- **[slack_client.py](slack_client.py)** — the runnable client.
