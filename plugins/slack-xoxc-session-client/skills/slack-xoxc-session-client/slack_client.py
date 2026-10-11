"""
slack_client.py -- programmatic Slack access via a live browser session
(xoxc web token + d session cookie). No Slack app, no admin, no OAuth.
Acts as the logged-in browser user.

Both auth secrets are auto-extracted from the local browser profile:

  - `d` (+ `d-s`) session cookie  -> decrypted from the browser cookie store via
                                     pycookiecheat (beats the httpOnly barrier that
                                     document.cookie / JS extraction cannot cross)
  - `xoxc-` web token             -> scraped from the authenticated workspace HTML
                                     (key "api_token" in the bootstrap payload)

Then POST to https://<subdomain>.slack.com/api/<method> with
data={"token": xoxc, ...} and cookies={"d":..., "d-s":...}.

Personal use only. Undocumented Slack internals; ToS-gray. Do not scale, share,
or run on behalf of others. Secrets rotate on logout / password change / session
expiry -> the client re-extracts automatically when a call returns invalid_auth.

SECURITY: tokens are held in memory only. This script never writes them to disk.
Do not print, log, or commit the xoxc token or the d / d-s cookies.

Agent self-labeling (good-faith convention):
  Because this client posts AS the logged-in human, Slack cannot tell an
  agent-authored message from one the human typed. The only thing that can mark
  a post as agentic is a voluntary convention -- a "robots.txt for agents":
  no enforcement, just good faith. So by default every outgoing post is
  prefixed with a visible, greppable marker:

      🤖 [agent]                -> no label given
      🤖 [agent: openclaw]      -> agent_label="openclaw"

  Readers (human or machine) detect agent posts by the leading "🤖 [agent"
  (see AGENT_MARKER_RE). Pass agent_label to identify which agent; pass
  label_posts=False / --no-label to opt out. We ship it on-by-default so the
  honest behavior is the path of least resistance.

Requires: pycookiecheat, requests  (install in a .venv).

Cross-platform / cross-browser:
  pycookiecheat decrypts the cookie store for the named browser. Pass --browser
  to target Firefox or a Chromium variant. Supported names depend on the installed
  pycookiecheat version; common values: chrome, chromium, brave, edge, firefox,
  slack, arc, opera. macOS unlocks the Keychain (may prompt); Linux uses the
  Secret Service / libsecret; Windows uses DPAPI.

Usage (library):
    from slack_client import SlackSessionClient
    sc = SlackSessionClient("<workspace-subdomain>")          # e.g. acme-corp
    print(sc.call("auth.test"))
    print(sc.call("conversations.history", channel="C0123ABCD", limit=50))

    # Firefox instead of Chrome:
    sc = SlackSessionClient("<workspace-subdomain>", browser="firefox")

CLI:
    python3 slack_client.py [--browser NAME] [--agent-label NAME] [--no-label] \
        <subdomain> <method> [k=v ...]
    python3 slack_client.py <workspace-subdomain> auth.test
    python3 slack_client.py <workspace-subdomain> conversations.history channel=C0123 limit=20
    # Posts are self-labeled by default:
    python3 slack_client.py --agent-label openclaw <sub> chat.postMessage channel=C0123 text='hi'
    # -> posts: "🤖 [agent: openclaw] hi"
    python3 slack_client.py --no-label <sub> chat.postMessage channel=C0123 text='hi'
"""
import re
import sys
import json

import requests
import pycookiecheat

_UA = "Mozilla/5.0"

# --- Agent self-labeling (good-faith "robots.txt for agents") ---------------
# Web-API methods that create/edit a visible message and therefore get labeled.
_LABELED_METHODS = frozenset(
    {"chat.postMessage", "chat.update", "chat.scheduleMessage", "chat.meMessage"}
)
# A post is agent-authored iff its text begins with this pattern. Keep the regex
# and the marker emitted by _agent_marker() in sync -- this is the whole protocol.
AGENT_MARKER_RE = re.compile(r"^\U0001F916 \[agent\b")


def _agent_marker(agent_label=None):
    """Return the visible marker that prefixes an agent-authored post."""
    if agent_label:
        retval = f"\U0001F916 [agent: {agent_label}]"
    else:
        retval = "\U0001F916 [agent]"
    return retval


def apply_agent_label(method, params, agent_label=None):
    """Return params with the agent marker prepended to `text`, when applicable.

    Pure/idempotent: only touches labeled methods that carry a `text`, and never
    double-marks an already-labeled message. Returns a new dict; input untouched.
    """
    text = params.get("text")
    if method not in _LABELED_METHODS or not text:
        retval = params
    elif AGENT_MARKER_RE.match(text):
        retval = params
    else:
        retval = {**params, "text": f"{_agent_marker(agent_label)} {text}"}
    return retval


class SlackSessionClient:
    """Slack web-API client authenticated by a live browser session."""

    def __init__(self, subdomain, browser="chrome", agent_label=None,
                 label_posts=True):
        self.subdomain = subdomain
        # BASE must be the team subdomain host. A generic slack.com host
        # silently fails auth for these session-token calls.
        self.base = f"https://{subdomain}.slack.com/api"
        self._browser = browser
        # Good-faith agent self-labeling: on by default so the honest behavior
        # is the path of least resistance. See apply_agent_label / module docs.
        self.agent_label = agent_label
        self.label_posts = label_posts
        self._cookies = None
        self._token = None

    def _extract_cookies(self):
        """Decrypt the d / d-s session cookies from the local browser store."""
        raw = pycookiecheat.chrome_cookies(
            f"https://{self.subdomain}.slack.com", browser=self._browser
        )
        d = raw.get("d", "")
        if not d.startswith("xoxd-"):
            raise RuntimeError(
                f"No valid 'd' cookie for {self.subdomain}.slack.com "
                f"(not logged in to this workspace in {self._browser}?)"
            )
        # d-s is needed by some workspaces; include it when present.
        retval = {"d": d, "d-s": raw.get("d-s", "")}
        return retval

    def _extract_token(self):
        """Scrape the xoxc- web token from the authenticated workspace HTML."""
        html = requests.get(
            f"https://{self.subdomain}.slack.com/",
            cookies=self._cookies,
            headers={"User-Agent": _UA},
        ).text
        m = re.search(r'"api_token":"(xoxc-[^"]+)"', html)
        if not m:
            raise RuntimeError(
                "Could not find xoxc- token in workspace HTML "
                "(session may be expired; re-login in the browser)"
            )
        retval = m.group(1)
        return retval

    def _ensure_auth(self):
        if self._cookies is None:
            self._cookies = self._extract_cookies()
        if self._token is None:
            self._token = self._extract_token()

    def _reset_auth(self):
        """Force re-extraction on the next call (after invalid_auth)."""
        self._cookies = None
        self._token = None

    def call(self, method, **params):
        """POST to a Slack web-API method, return parsed JSON dict.

        On invalid_auth (rotated/expired secrets), re-extract once and retry.
        Outgoing posts are self-labeled per the good-faith agent convention
        unless label_posts is False.
        """
        if self.label_posts:
            params = apply_agent_label(method, params, self.agent_label)
        self._ensure_auth()
        result = self._post(method, params)
        if result.get("error") == "invalid_auth":
            self._reset_auth()
            self._ensure_auth()
            result = self._post(method, params)
        return result

    def _post(self, method, params):
        resp = requests.post(
            f"{self.base}/{method}",
            data={"token": self._token, **params},
            cookies=self._cookies,
        )
        retval = resp.json()
        return retval


def _main(argv):
    args = argv[1:]
    browser = "chrome"
    agent_label = None
    label_posts = True
    # Leading option flags, in any order, before the positional args.
    while args and args[0].startswith("--"):
        flag = args[0]
        if flag == "--no-label":
            label_posts = False
            args = args[1:]
        elif flag in ("--browser", "--agent-label"):
            if len(args) < 2:
                print(__doc__)
                retval = 2
                return retval
            if flag == "--browser":
                browser = args[1]
            else:
                agent_label = args[1]
            args = args[2:]
        else:
            print(__doc__)
            retval = 2
            return retval
    if len(args) < 2:
        print(__doc__)
        retval = 2
        return retval
    subdomain = args[0]
    method = args[1]
    params = {}
    for kv in args[2:]:
        k, _, v = kv.partition("=")
        params[k] = v
    client = SlackSessionClient(
        subdomain, browser=browser, agent_label=agent_label,
        label_posts=label_posts,
    )
    result = client.call(method, **params)
    print(json.dumps(result, indent=2))
    retval = 0 if result.get("ok") else 1
    return retval


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
