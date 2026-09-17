---
name: wordpress-com-publish
description: |
  Publish a post to a WordPress.com (or Jetpack-connected) blog in one step,
  or, if no usable token exists yet, get one first and then publish. Use when:
  (1) the user asks to post or draft something to their WordPress.com site,
  (2) you have content to publish and need to resolve or mint a WordPress.com
  OAuth2 bearer token, (3) a publish call returns 401 / authorization_required
  and the token must be re-minted, (4) a token exchange fails with
  invalid_client or invalid_grant, (5) a published post comes out mangled
  (newlines inside headings, missing code blocks) - author in Markdown and
  convert to Gutenberg block markup, (6) a table, list, quote or horizontal rule
  lands as raw HTML or as a block the editor flags as invalid, (7) you are
  drafting a multi-post series and need the posts to cross-link before the
  publish dates exist, (8) you need to update/append to an
  existing post by ID without clobbering it. Operating contract: resolve a
  token (env then Keychain); if present, publish; if absent, run the
  authorization-code flow, store the token, then publish. NOT for self-hosted
  WordPress using application-password REST - this targets public-api.wordpress.com.
author: Claude Code
version: 1.4.0
date: 2026-09-16
source: https://github.com/voitta-ai/skillz
source_file: skills/wordpress-com-publish/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/wordpress-com-publish/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

# wordpress-com-publish

Publish to **WordPress.com** / **Jetpack-connected** sites via the REST API at
`public-api.wordpress.com`, authenticated with a long-lived OAuth2 bearer
token. (NOT self-hosted WordPress application-password REST - different auth.)

## Operating procedure - post, or get a token if we can't

This is the contract. Given content to publish:

1. **Resolve a token**, in order:
   - `$WPCOM_TOKEN` if set;
   - else macOS Keychain: `security find-generic-password -s wpcom_token -w 2>/dev/null`.
2. **Token found -> Publish** (below). If Publish returns `401` /
   `authorization_required`, the token was revoked: treat as no token.
3. **No token -> Authorize** (below), store the token in Keychain, then Publish.

**Site**: use `$WPCOM_SITE` (a `blog_id` or domain, e.g. `blog.example.com`),
or ask the user. List the sites a token can reach with
`GET /rest/v1.1/me/sites`.

The one-shot `publish.sh` below implements this whole contract; run it, or
follow the steps by hand.

## Publish

```bash
curl -sS -X POST "https://public-api.wordpress.com/rest/v1.1/sites/$WPCOM_SITE/posts/new" \
  -H "Authorization: Bearer $WPCOM_TOKEN" \
  --data-urlencode "title=My title" \
  --data-urlencode "content=<p>Body as HTML.</p>" \
  --data-urlencode "status=draft"
```
- Use `--data-urlencode` (not `-d`) so titles/bodies with spaces, `&`, or
  markup are sent intact.
- `status`: `draft` (verify first), then `publish`. Also `private`, `pending`,
  `future` (+ `date`).
- Response JSON includes the new post's `ID`, `URL`, `status`. Update later by
  POSTing to `.../posts/<ID>`; delete via `.../posts/<ID>/delete`.
- `content` is **HTML/Gutenberg blocks**, not markdown. WordPress runs the body
  through `wpautop`, which **mangles raw HTML** (injects newlines inside long
  headings, drops some code). Author in Markdown and convert to Gutenberg block
  markup - see [Formatting](#formatting-markdown---gutenberg-blocks).

## Formatting: Markdown -> Gutenberg blocks

WordPress is hostile to raw HTML posted via the REST API - `wpautop` reflows it,
and you get newlines inside headings (`Making\ncmux ...`) and dropped/garbled
code blocks. The fix: send **Gutenberg block markup** (`<!-- wp:heading -->`,
`<!-- wp:paragraph -->`, `<!-- wp:code -->`, `<!-- wp:list -->`), which WordPress
stores verbatim. Author in Markdown, then convert with `md2wp.py` below.

**Emit the shape the editor itself saves**, or the block shows up flagged as
"unexpected or invalid content" and the author has to click through a recovery
prompt. The converter below covers paragraph, heading, code, list, quote, table
and separator; anything else falls through to `wp:html`, which renders but is
opaque to the editor. Three shapes are easy to get subtly wrong:
- **Lists** need `wp:list-item` inner blocks, not a bare `<ul>` inside
  `wp:list`. Same for **quotes**: inner `wp:paragraph` blocks, not a bare `<p>`.
- **Tables** are `<figure class="wp-block-table">` wrapping the `<table>`. Pass
  `{"hasFixedLayout":false}` explicitly rather than relying on the default,
  which has changed across WordPress versions and decides whether the saved
  `<table>` is expected to carry `has-fixed-layout`. Strip pandoc's
  `<tr class="header|odd|even">` and the whitespace between tags.
- **Horizontal rules** are `wp:separator` with
  `class="wp-block-separator has-alpha-channel-opacity"`.

**Two non-obvious traps (each cost real time):**
- pandoc's default `--wrap=auto` line-wraps the HTML output - that is what
  injects `\n` into long headings (it is NOT WordPress doing it). You MUST pass
  `--wrap=none`. Also `--no-highlight` so code is plain `<pre><code>`, not
  highlight-span soup. (Do NOT use `--syntax-highlighting=none` - it is not a
  real pandoc flag and makes pandoc exit non-zero, failing the whole convert.)
- The POST/PUT response `content` is the **rendered** HTML (block comments
  stripped), so it never matches what you sent. To verify the stored block
  markup, GET the post with `?context=edit`.

```python
#!/usr/bin/env python3
# md2wp.py FILE.md [shift]  - Markdown -> WordPress Gutenberg block markup.
# shift = heading-level offset (default 1, so "# H1" -> <h2>); pass 0 when the
# markdown's top headings should stay h2 (e.g. replacing a whole post body).
import subprocess, sys, re
from html.parser import HTMLParser

def _items(raw, tag):
    """<li> children -> wp:list-item inner blocks (what the editor itself saves)."""
    body = re.sub(rf"</{tag}>$", "", re.sub(rf"^<{tag}\b[^>]*>", "", raw, count=1), count=1)
    if re.search(r"<(ul|ol)\b", body):
        raise SystemExit("nested list: convert by hand")
    out = []
    for item in re.findall(r"<li>(.*?)</li>", body, flags=re.S):
        paras = re.findall(r"<p>(.*?)</p>", item.strip(), flags=re.S)  # loose list
        if len(paras) > 1:
            raise SystemExit("multi-paragraph list item: convert by hand")
        text = paras[0] if paras else item.strip()
        out.append(f"<!-- wp:list-item -->\n<li>{text}</li>\n<!-- /wp:list-item -->")
    retval = "".join(out)
    return retval

def to_blocks(md_path, shift=1):
    html = subprocess.run(
        ["pandoc", "-f", "gfm", "-t", "html", "--no-highlight",
         "--wrap=none", f"--shift-heading-level-by={shift}", md_path],
        capture_output=True, text=True, check=True).stdout

    class P(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.depth = 0; self.blocks = []; self.cur = ""; self.curtag = None
        def handle_starttag(self, tag, attrs):
            if self.depth == 0: self.curtag = tag; self.cur = ""
            self.cur += self.get_starttag_text() or ""; self.depth += 1
        def handle_startendtag(self, tag, attrs):
            text = self.get_starttag_text() or ""
            if self.depth == 0: self.blocks.append((tag, text))   # <hr />
            else: self.cur += text
        def handle_endtag(self, tag):
            self.depth -= 1; self.cur += f"</{tag}>"
            if self.depth == 0:
                self.blocks.append((self.curtag, self.cur)); self.cur = ""; self.curtag = None
        def handle_data(self, data):
            if self.depth > 0: self.cur += data
        def handle_entityref(self, name):
            if self.depth > 0: self.cur += f"&{name};"
        def handle_charref(self, name):
            if self.depth > 0: self.cur += f"&#{name};"

    p = P(); p.feed(html)
    out = []
    for tag, raw in p.blocks:
        if re.fullmatch(r"h[1-6]", tag or ""):
            lvl = int(tag[1])
            raw = re.sub(rf"^<h{lvl}\b", f'<h{lvl} class="wp-block-heading"', raw, count=1)
            attr = "" if lvl == 2 else f' {{"level":{lvl}}}'
            out.append(f"<!-- wp:heading{attr} -->\n{raw}\n<!-- /wp:heading -->")
        elif tag == "p":
            out.append(f"<!-- wp:paragraph -->\n{raw}\n<!-- /wp:paragraph -->")
        elif tag == "pre":
            raw = re.sub(r"^<pre\b[^>]*>", '<pre class="wp-block-code">', raw, count=1)
            out.append(f"<!-- wp:code -->\n{raw}\n<!-- /wp:code -->")
        elif tag == "ul":
            out.append('<!-- wp:list -->\n<ul class="wp-block-list">'
                       f"{_items(raw, 'ul')}</ul>\n<!-- /wp:list -->")
        elif tag == "ol":
            out.append('<!-- wp:list {"ordered":true} -->\n<ol class="wp-block-list">'
                       f"{_items(raw, 'ol')}</ol>\n<!-- /wp:list -->")
        elif tag == "blockquote":
            ps = "".join(f"<!-- wp:paragraph -->\n<p>{p}</p>\n<!-- /wp:paragraph -->"
                         for p in re.findall(r"<p>(.*?)</p>", raw, flags=re.S))
            out.append('<!-- wp:quote -->\n<blockquote class="wp-block-quote">'
                       f"{ps}</blockquote>\n<!-- /wp:quote -->")
        elif tag == "table":
            t = re.sub(r'<tr class="[^"]*">', "<tr>", raw)   # pandoc adds header/odd/even
            t = re.sub(r">\s+<", "><", t)                    # keep the block validator happy
            out.append('<!-- wp:table {"hasFixedLayout":false} -->\n'
                       f'<figure class="wp-block-table">{t}</figure>\n<!-- /wp:table -->')
        elif tag == "hr":
            out.append('<!-- wp:separator -->\n'
                       '<hr class="wp-block-separator has-alpha-channel-opacity"/>\n'
                       '<!-- /wp:separator -->')
        elif tag is None:
            continue
        else:
            out.append(f"<!-- wp:html -->\n{raw}\n<!-- /wp:html -->")
    return "\n\n".join(out)

if __name__ == "__main__":
    print(to_blocks(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1))
```

Send the result as the `content` body (it is large - use
`--data-urlencode "content@blocks.html"`).

**Sibling note:** Confluence is the opposite - its `createConfluencePage` takes
`contentFormat=markdown` directly and renders clean code macros, so none of this
block conversion is needed there.

## A series: cross-link posts before you know the dates

Posts in a series link each other, but a permalink contains the publish date, so
the links cannot be written until the dates are fixed - and the dates usually are
not fixed while drafting. Do not leave bracketed placeholders and plan to "fix
them at publish time"; that makes the series publish in a forced order and the
edits get forgotten.

**Use `?p=<ID>` instead.** WordPress 301-redirects `https://<site>/?p=<ID>` to
that post's permalink, so a link written against the ID keeps working whatever
date the post ends up with.

1. Create every post in the series as a title-only draft first
   (`POST /sites/<site>/posts/new` with `title` and `status=draft`). The response
   `ID` is what you link to; the IDs exist from that moment.
2. Write the bodies with `https://<site>/?p=<ID>` links, then POST each body.
3. Record the ID-to-post mapping somewhere durable (the repo, the tracking
   issue), not in scratch files - the publish week outlives the session that
   drafted it.

**The caveat that bites: a forward link 404s until its target is live.** This is
invisible when the whole series publishes at once and obvious when it does not.
If posts go out one a day:

- Strip **forward** links to plain text before the first post publishes, keeping
  the sentence intact. Backward links are always safe.
- On each publish day, flip today's post to `status=publish`, then edit the
  previously published post to wrap its teaser text in a link to today's.
- Write down the exact text to wrap for each day, per post. A teaser sentence is
  usually a clause inside a paragraph, and re-finding it under time pressure is
  where the mistakes happen.

Count the forward links rather than eyeballing them: in a seven-post series the
first post often carries several (next post, plus asides pointing further ahead),
not just one.

## Update or append to an existing post

To revise a post (id `<ID>`) instead of creating one, POST to
`/sites/$SITE/posts/<ID>`. To ADD to an existing post without clobbering it,
read first, then concatenate:

```bash
# fetch current raw markup, append your new blocks, write back (keep it a draft first)
cur=$(curl -sS "$API/rest/v1.1/sites/$SITE/posts/<ID>?context=edit" \
        -H "Authorization: Bearer $TOK" | python3 -c 'import sys,json;print(json.load(sys.stdin)["content"])')
printf '%s\n\n%s' "$cur" "$(cat new-blocks.html)" > merged.html
curl -sS -X POST "$API/rest/v1.1/sites/$SITE/posts/<ID>" -H "Authorization: Bearer $TOK" \
  --data-urlencode "content@merged.html" --data-urlencode "status=draft"
```

Omit `title` to leave it unchanged. Verify the merge via `?context=edit` (the
POST response is rendered, not the stored blocks).

## Authorize (only when there is no token)

Needs an app at https://developer.wordpress.com/apps/ (Settings tab:
**Client ID**, **Client Secret**, **Redirect URL**).

**What to tell the user to set** (once; then auth is hands-off except one paste):

| Env var (either prefix) | Where it comes from |
|---|---|
| `WPCOM_CLIENT_ID` / `WORDPRESS_CLIENT_ID` | app Settings -> Client ID |
| `WPCOM_CLIENT_SECRET` / `WORDPRESS_CLIENT_SECRET` | app Settings -> Client Secret |
| `WPCOM_REDIRECT_URI` / `_URL` / `WORDPRESS_REDIRECT_URI` / `_URL` | app Settings -> **Redirect URL**, byte-for-byte |
| `WPCOM_SITE` (or pass as the 4th `publish.sh` arg) | the target blog domain, e.g. `blog.example.com` |

The script accepts the `WORDPRESS_*` names and both `_URI` and `_URL` spellings,
because WordPress's own field is labelled "Redirect URL" - users naturally export
`WORDPRESS_REDIRECT_URL`. Only the **token** comes from the flow below; the rest
the user sets once in their shell profile.

**Redirect-URL tip:** the simplest registered Redirect URL is the blog's own URL
(e.g. `https://blog.example.com`). On approval the browser lands on
`https://blog.example.com/?code=...` - the homepage loads fine and the `code` is
right there in the address bar to copy. (Any registered URL works; it just has to
byte-match. A non-listening URL also works - the page fails to load but the `code`
is still in the bar.)

1. Open the authorize URL, approve, copy the `code` from the
   `redirect_uri?code=...` landing (the page may fail to load if nothing
   listens on the redirect - the `code` is still in the URL bar):
   ```
   https://public-api.wordpress.com/oauth2/authorize?client_id=CLIENT_ID&redirect_uri=REDIRECT_URI&response_type=code&scope=global
   ```
2. Exchange the `code` (single-use, expires in minutes - do this immediately):
   ```bash
   curl -sX POST https://public-api.wordpress.com/oauth2/token \
     -d client_id=CLIENT_ID -d client_secret=CLIENT_SECRET \
     -d redirect_uri=REDIRECT_URI -d grant_type=authorization_code -d code=CODE
   ```
   Returns `{"access_token":"...","blog_id":"0","blog_url":null,"scope":"global"}`.
3. **Store the token** (never the secret) in Keychain, then publish:
   ```bash
   security add-generic-password -a "$USER" -s wpcom_token -U -w "$ACCESS_TOKEN"
   ```

**Secret handling:** never echo the Client Secret into the conversation, a
file, a commit, or memory. Take it from a hidden prompt (`read -rs`) and pass
it once to the token curl.

## One-shot script

Save as `publish.sh`. With a token in `$WPCOM_TOKEN` or Keychain it posts; with
no token it runs the auth flow, stores the token, then posts. `--data-urlencode`
keeps content intact. No placeholders to leave un-substituted.

```bash
#!/usr/bin/env bash
# publish.sh "Title" "Body HTML" [draft|publish] [site]   - post to WordPress.com
# publish.sh --auth                                       - just mint+store a token
# Token: $WPCOM_TOKEN, else macOS Keychain item `wpcom_token`.
# Site:  4th arg, else $WPCOM_SITE (blog_id or domain).
# Auth (only if no token): $WPCOM_CLIENT_ID, $WPCOM_REDIRECT_URI|_URL (+ prompts).
set -euo pipefail
API=https://public-api.wordpress.com

token() { [[ -n "${WPCOM_TOKEN:-}" ]] && { printf '%s' "$WPCOM_TOKEN"; return; }
          security find-generic-password -s wpcom_token -w 2>/dev/null || true; }

authorize() {
  # accept WORDPRESS_* as aliases for WPCOM_* (users name the app creds either way).
  # WordPress's app field is literally "Redirect URL", so accept _URL as well as _URI.
  : "${WPCOM_CLIENT_ID:=${WORDPRESS_CLIENT_ID:-}}"
  : "${WPCOM_REDIRECT_URI:=${WPCOM_REDIRECT_URL:-${WORDPRESS_REDIRECT_URI:-${WORDPRESS_REDIRECT_URL:-}}}}"
  : "${WPCOM_CLIENT_ID:?set WPCOM_CLIENT_ID or WORDPRESS_CLIENT_ID (apps live at https://developer.wordpress.com/apps/ - NOT wp-admin)}"
  : "${WPCOM_REDIRECT_URI:?set WPCOM_REDIRECT_URI/_URL or WORDPRESS_REDIRECT_URI/_URL (must byte-match the app's registered Redirect URL)}"
  echo "Open, approve, copy the ?code= from the redirect:" >&2
  echo "  $API/oauth2/authorize?client_id=$WPCOM_CLIENT_ID&redirect_uri=$WPCOM_REDIRECT_URI&response_type=code&scope=global" >&2
  local code secret tok
  read -rp 'Paste code: ' code
  # secret from env (WPCOM_/WORDPRESS_CLIENT_SECRET) if present, else hidden prompt
  secret="${WPCOM_CLIENT_SECRET:-${WORDPRESS_CLIENT_SECRET:-}}"
  [[ -n "$secret" ]] || { read -rsp 'Paste client secret: ' secret; echo >&2; }
  tok=$(curl -sS -X POST "$API/oauth2/token" \
        -d client_id="$WPCOM_CLIENT_ID" -d client_secret="$secret" \
        -d redirect_uri="$WPCOM_REDIRECT_URI" -d grant_type=authorization_code -d code="$code" \
        | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))')
  [[ -n "$tok" ]] || { echo "token exchange failed (check client_id/secret, redirect match, fresh code)" >&2; exit 1; }
  security add-generic-password -a "$USER" -s wpcom_token -U -w "$tok"
  printf '%s' "$tok"
}

[[ "${1:-}" == "--auth" ]] && { authorize >/dev/null && echo "token stored in Keychain (wpcom_token)"; exit 0; }

TITLE="${1:?usage: publish.sh \"Title\" \"Body HTML\" [draft|publish] [site]}"
BODY="${2:-}"; STATUS="${3:-draft}"
SITE="${4:-${WPCOM_SITE:?set WPCOM_SITE or pass site as 4th arg}}"

post() { curl -sS -X POST "$API/rest/v1.1/sites/$SITE/posts/new" \
           -H "Authorization: Bearer ${1}" \
           --data-urlencode "title=$TITLE" --data-urlencode "content=$BODY" \
           --data-urlencode "status=$STATUS"; }

TOK="$(token)"; [[ -n "$TOK" ]] || TOK="$(authorize)"
RESP="$(post "$TOK")"
if echo "$RESP" | grep -q '"error":"authorization_required"'; then
  echo "token rejected (revoked/expired); re-authorizing..." >&2
  TOK="$(authorize)"; RESP="$(post "$TOK")"
fi
echo "$RESP" | python3 -c 'import sys,json
d=json.load(sys.stdin)
print(d["URL"]) if d.get("URL") else (print(json.dumps(d)) or sys.exit(1))'
```

## Gotchas

- **No placeholders to forget.** The manual-curl path repeatedly failed when a
  literal placeholder was left in (`client_id=YOUR_CLIENT_ID` ->
  `{"error":"invalid_client"}`; `WPCOM_TOKEN='PASTE_...'` -> empty `/me/sites`).
  The script takes every value from env or a `read` prompt, so there is nothing
  to leave un-substituted. Prefer it over hand-typed curls.
- **`invalid_client` / "Unknown client_id"**: the request used a placeholder or
  wrong Client ID. The number in the app URL is usually the client_id, but
  confirm on the Settings page.
- **`invalid_grant`**: the `code` expired (single-use, ~minutes) or was reused,
  or `redirect_uri` does not **byte-match** a registered Redirect URL (a
  trailing slash counts). Get a fresh code and exchange immediately.
- **`blog_id:"0"`, `blog_url:null` after exchange**: normal for a
  `scope=global` (account-wide) token; it is not bound to one blog. Pick the
  site per call; get real site IDs from `GET /rest/v1.1/me/sites`.
- **401 / `authorization_required` on publish**: token was revoked - re-run the
  auth flow (the script does this automatically once).
- **Raw HTML/markdown gets mangled.** `content` is treated as HTML and run
  through `wpautop`; the symptom is newlines inside long headings and
  dropped/garbled code blocks. Send Gutenberg block markup instead - see
  [Formatting](#formatting-markdown---gutenberg-blocks).
- **OAuth apps live at https://developer.wordpress.com/apps/, NOT in wp-admin.**
  wp-admin has no OAuth apps; Client ID / Secret / Redirect URL are only in that
  developer portal. Creds may be in env as `WPCOM_*` or `WORDPRESS_*`.
- **The publish/update response is rendered, not stored.** Its `content` has the
  block comments stripped, so it never matches what you POSTed - verify the
  stored markup with `GET .../posts/<ID>?context=edit`.
- **Invoked as a slash command (`/wordpress-com-publish ...`)?** The command
  framework substitutes bare positional placeholders (`$1`..`$9`, `$ARGUMENTS`)
  in this SKILL.md when it injects the body, so a bare `$1` in the embedded
  script renders as empty (e.g. `Authorization: Bearer ` with no token). Brace
  forms (`${1}`, `${1:?...}`, `${1:-}`) survive untouched - the script uses
  `${1}` for exactly this reason. If you copy the script out of a rendered
  invocation, confirm the `Bearer ${1}` token did not get blanked.

## Quick reference

| Goal | Call |
|---|---|
| Resolve token | `$WPCOM_TOKEN`, else `security find-generic-password -s wpcom_token -w` |
| List reachable sites | `GET /rest/v1.1/me/sites` |
| Publish / draft | `POST /rest/v1.1/sites/$SITE/posts/new` (Bearer; `--data-urlencode`) |
| Update post | `POST /rest/v1.1/sites/$SITE/posts/$ID` |
| Markdown -> blocks | `python3 md2wp.py post.md > blocks.html` (see Formatting) |
| Verify stored markup | `GET /rest/v1.1/sites/$SITE/posts/$ID?context=edit` |
| Authorize (browser) | `GET /oauth2/authorize?client_id=..&redirect_uri=..&response_type=code&scope=global` |
| Exchange code -> token | `POST /oauth2/token` (`grant_type=authorization_code`) |
| Revoke token | https://wordpress.com/me/security/connected-applications |

Base URL for all calls: `https://public-api.wordpress.com`.
