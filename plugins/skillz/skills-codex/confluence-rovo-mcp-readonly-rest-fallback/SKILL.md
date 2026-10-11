---
name: confluence-rovo-mcp-readonly-rest-fallback
description: |
  Create or update a Confluence Cloud page when the Claude "Atlassian Rovo"
  connector cannot write -- and check first that it still cannot, since the
  connector gets re-authorized and a writable site needs none of this. Use
  when: (1) `createConfluencePage` /
  `updateConfluencePage` fails with `403 Forbidden ... "The app is not installed
  on this instance"`, (1b) an agent-harness permission classifier BLOCKS the
  REST credential probe because it reads API tokens from the environment,
  making the MCP write the only unattended path, (2)
  `getAccessibleAtlassianResources` shows only read scopes
  (`read:page:confluence`, `read:space:confluence`, `search:confluence`) and no
  `write:page:confluence`, (3) you need a numeric `spaceId` from a
  personal-space key like `~7120200000aaaa...`, (4) a REST page create returns 400 on a
  body that the MCP accepted, (5) storage-format XHTML fails to parse because
  of named HTML entities, or (6) you need to EDIT an existing page that contains
  macros (Lucidchart/draw.io diagrams, TOC, images) without silently destroying
  them -- rewriting such a page's body through the MCP saves 200 and drops the
  macros with no error. Covers the REST v2 fallback, which API-token env var
  actually works, the HTML+ -> storage-format conversion table, and the
  surgical storage-format edit that round-trips macros intact.
author: Claude Code
version: 1.4.0
date: 2026-08-27
---

# Confluence page create when the Rovo connector is read-only

## Problem

The Claude Atlassian (Rovo) MCP exposes `createConfluencePage`, but on a site
where the connector was authorized with read-only scopes the call fails with a
message that points at the wrong cause:

```
Failed to create page: 403 Forbidden. Details: {
  "code": 403,
  "message": "The app is not installed on this instance"
}
```

The app *is* reachable — reads work fine. The real cause is the granted scope
set. Nothing in the error says "scope".

**This is a per-site, per-authorization condition, not a property of the Rovo
connector.** The same connector on the same site can be writable later; treat
everything below as a fallback you fall *into* on a 403, never as the default
path. See *Solution* step 1.

## Trigger conditions

- `createConfluencePage` or `updateConfluencePage` returns the 403 above.
  **Verify this on the current site before following the rest of this skill** —
  the connector may since have been granted write scope, in which case none of
  the REST fallback applies. See *Solution* step 1.
- An agent-harness permission layer refuses to run the credential probe in
  step 2 because it reads API tokens from the environment. See *When an agent
  harness blocks this probe*.
- `getAccessibleAtlassianResources` returns scopes containing
  `read:page:confluence` / `read:space:confluence` / `search:confluence` but
  **not** `write:page:confluence`.
- You need to change part of an existing page that contains macros. This one is
  **not** an error condition -- the MCP write may well succeed. See
  *Updating a page that already has macros*; the failure is silent data loss,
  not a status code.

## Solution

### 1. Try the MCP write first -- do not assume it is still read-only

**Attempt `createConfluencePage` / `updateConfluencePage` before doing anything
else.** Connector scopes are re-authorized out of band, so a site that was
read-only when this skill was written can be writable today, and the fastest
scope check is the write itself. On 2026-08-27 a site that had previously
forced the whole REST fallback accepted `createConfluencePage` directly and
returned a page id -- the entire procedure below was unnecessary.

Only if the write returns the 403 above:

```bash
# via the MCP
getAccessibleAtlassianResources
```

If the `scopes` array has no `write:*`, the MCP cannot write. Go to REST.

Note that the MCP write path and the REST path take **different body formats**:
the MCP wants Confluence HTML+ (`data-type` attributes, `<div
data-type="panel-info">`) and rejects storage XML, while REST v2 with
`representation: "storage"` wants exactly the storage XML the MCP refuses. The
MCP converts HTML+ to storage on save and returns the stored value, so a
successful MCP create is also a cheap way to see what storage format your
markup became. The conversion table in step 4 reads in both directions.

### 2. Pick the working credential

Sites commonly have more than one Atlassian token in the environment and they
are **not** interchangeable — one can 404 the exact call the other serves.
Probe rather than guess:

```bash
for t in CONFLUENCE_API_TOKEN ATLASSIAN_API_TOKEN; do
  tok=$(bash -lc "printf '%s' \"\$$t\"")
  [ -z "$tok" ] && continue
  code=$(curl -s -o /tmp/sp.json -w '%{http_code}' \
    -u "$EMAIL:$tok" -H 'Accept: application/json' \
    "https://$SITE/wiki/api/v2/spaces?keys=$SPACE_KEY")
  echo "$t -> HTTP $code"
  [ "$code" = "200" ] && break
done
```

A 404 here usually means *wrong token*, not a missing space — the space lookup
404s before it reports "not found" when the credential lacks Confluence access.
One exception worth ruling out before you go token-hunting: a 404 on a
**personal-space tilde key** (`?keys=~7120200000aaaa...`) can also be the key
filter rather than the credential. Re-probe with an unfiltered
`/wiki/api/v2/spaces?limit=1` — if that returns 200 on the same token, the
token is fine and the tilde-key filter was the problem.

#### When an agent harness blocks this probe

**This loop reads API tokens out of the environment, and a coding-agent
permission layer may refuse to run it on those grounds.** Under Claude Code's
auto mode the probe was denied twice — including a narrowed version that only
read the two credentials this skill already names in `~/.claude.json` — with:

```
Permission for this action was denied by the Claude Code auto mode classifier.
Reason: Blocked by classifier.
```

That is a *denial*, not a failure: nothing was probed, so a denial says nothing
about which token works. It matters because it inverts the fallback's economics
— under such a harness the REST path is the one that cannot run unattended,
while the MCP write may be available. Hence step 1.

If you hit this:

1. Re-try the MCP write (step 1). It needs no token handling at all, which is
   exactly why the classifier does not object to it.
2. If REST is genuinely required, ask the user to run the probe themselves
   (in Claude Code, `! <command>` runs it in-session) or to add a Bash
   permission rule, rather than reshaping the script to slip past the
   classifier.
3. Do not work around it by echoing token values into a command line — that is
   both what the classifier is guarding against and a good way to leak a
   credential into shell history and logs.

### 3. Resolve the numeric spaceId

REST v2 `POST /wiki/api/v2/pages` wants a numeric `spaceId`, not a key. A
personal space key looks like `~7120200000aaaabbbbcccc...`:

```bash
curl -s -u "$EMAIL:$TOKEN" \
  "https://$SITE/wiki/api/v2/spaces?keys=~7120200000aaaabbbbcccc..." \
  | python3 -c "import json,sys; [print(s['id'], s['key'], s['name']) for s in json.load(sys.stdin)['results']]"
```

### 4. Convert the body to storage format

**The MCP body format is not the REST body format.** The MCP accepts
"Confluence HTML+" (`data-type` attributes); REST v2 with
`representation: "storage"` accepts Confluence storage XHTML. Converting is
mandatory:

| HTML+ (MCP)                                        | Storage format (REST)                                                                                          |
|----------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| `<div data-type="panel-info">`                     | `<ac:structured-macro ac:name="info"><ac:rich-text-body>…</ac:rich-text-body></ac:structured-macro>`            |
| `panel-note`                                        | `ac:name="note"`                                                                                                |
| `panel-warning`                                     | `ac:name="note"` (yellow) — `ac:name="warning"` is the red one                                                  |
| `panel-error`                                       | `ac:name="warning"`                                                                                             |
| `panel-success`                                     | `ac:name="tip"`                                                                                                 |
| `<pre><code class="language-x">`                   | `<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">x</ac:parameter><ac:plain-text-body><![CDATA[…]]></ac:plain-text-body></ac:structured-macro>` |
| `<span data-type="status" data-color="green">L</span>` | `<ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">Green</ac:parameter><ac:parameter ac:name="title">L</ac:parameter></ac:structured-macro>` |
| `<ul data-type="decision-list">`                    | no equivalent — use a plain `<ul>`                                                                              |
| `<details><summary>`                                | `<ac:structured-macro ac:name="expand"><ac:parameter ac:name="title">…</ac:parameter><ac:rich-text-body>…</ac:rich-text-body></ac:structured-macro>` |
| `data-layout="full-width"` on `<table>`             | drop it                                                                                                          |

Status `colour` values are capitalized (`Green`, `Red`, `Yellow`, `Blue`,
`Grey`, `Purple`).

**Entities.** Storage format is XHTML and predefines only `&amp; &lt; &gt;
&quot; &apos;`. Named HTML entities (`&mdash;` `&ndash;` `&rarr;` `&middot;`
`&nbsp;`) are an undefined-entity parse error. Use literal UTF-8 characters or
numeric refs (`&#8212;` `&#8594;`).

### 5. POST it

Build the JSON with a real serializer — the body is large and full of quotes:

```bash
python3 - storage.xhtml payload.json <<'PY'
import json, sys
json.dump({
  "spaceId": 123456789,             # numeric, from step 3
  "status": "current",
  "title": "…",
  "body": {"representation": "storage", "value": open(sys.argv[1], encoding='utf-8').read()},
}, open(sys.argv[2], 'w', encoding='utf-8'))
PY

curl -s -X POST -u "$EMAIL:$TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  --data-binary @payload.json \
  "https://$SITE/wiki/api/v2/pages"
```

To update instead, `PUT /wiki/api/v2/pages/{id}` with the current `version.number + 1`.
If the page contains macros, do **not** re-author its body -- see
*Updating a page that already has macros* below.

## Verification

A `200` with an `id` in the response means the storage XHTML parsed —
Confluence rejects malformed storage with `400`, so a 200 is a real parse
receipt, not just transport success. The response `_links.webui` appended to
`https://$SITE/wiki` is the page URL.

## Updating a page that already has macros

The one-line "PUT with `version.number + 1`" above hides a data-loss trap, and it
is a *different* failure from everything else in this skill: it returns **200**
and destroys content.

**The trap.** Reading a macro-bearing page through the MCP
(`getConfluencePage` with `contentFormat: "html"`) returns each macro as a
`<div data-type="extension" data-extension-key="…" data-parameters="{…}">`, where
`data-parameters` is a large escaped-JSON blob carrying document tokens, instance
ids, macro ids and sizing. If you then write a body back through
`updateConfluencePage`, anything you did not faithfully reproduce is **silently
dropped**. The page saves, the response is a success, and the diagrams are gone.
No error, no warning. Reproducing that blob by hand is not realistic, so the
answer is not "be careful" — it is "never re-author the body".

**The rule.** For a page whose body you did not write from scratch, fetch
**storage format over REST**, do a *surgical string replacement*, and PUT the
result back. Storage format round-trips macros as `<ac:structured-macro>`
byte-for-byte.

```bash
# 1. GET the storage body
curl -s -u "$EMAIL:$TOKEN" \
  "https://$SITE/wiki/api/v2/pages/$PAGE_ID?body-format=storage" > page.json
```

```bash
# 2. Replace ONLY the fragment you mean to change, and prove you did.
python3 - <<'PY'
import json
p = json.load(open('page.json'))
b = p['body']['storage']['value']
before = b.count('ac:structured-macro')

OLD = '<p>Note: this page might be outdated.</p>'          # exact, copied from the GET
NEW = '<ac:structured-macro ac:name="info">…</ac:structured-macro>'

assert OLD in b, 'anchor not found - do NOT fall back to appending'
nb = b.replace(OLD, NEW, 1)
assert nb.count('ac:structured-macro') >= before, 'a macro was lost'

json.dump({
    "id":      p['id'],
    "status":  "current",
    "title":   p['title'],
    "spaceId": p['spaceId'],
    "body":    {"representation": "storage", "value": nb},
    "version": {"number":  p['version']['number'] + 1,
                "message": "what changed, and that nothing was removed"},
}, open('update.json', 'w'))
print('macros', before, '->', nb.count('ac:structured-macro'))
PY
```

```bash
# 3. PUT it back
curl -s -o resp.json -w '%{http_code}\n' -X PUT -u "$EMAIL:$TOKEN" \
  -H 'Content-Type: application/json' \
  --data @update.json "https://$SITE/wiki/api/v2/pages/$PAGE_ID"
```

Why each guard earns its line:

- **`assert OLD in b`** — an anchor that has drifted must fail loudly. The
  tempting fallback (append instead) silently produces a page carrying two
  contradictory banners, which is worse than not editing at all.
- **macro count before and after** — the only cheap receipt that the replacement
  did not eat a neighbouring element. Storage format is XHTML; an unbalanced
  `OLD` can swallow whatever follows it.
- **Echo back `title` and `spaceId` from the GET** rather than hardcoding them.
  The v2 PUT treats the payload as the page's new state, not as a patch.
- **`version.message`** is shown in page history. Say what changed *and* that
  nothing was removed — the first question anyone asks about an edited page they
  did not edit is what got deleted.

This applies to every macro, not just diagrams: `<ac:image>` embeds,
`<ac:structured-macro ac:name="toc">`, and any app macro (Lucidchart, draw.io,
Mermaid). It matters most on pages you did not author, which is exactly when
you are least able to notice something went missing.

> Marking an old page superseded rather than deleting it is the common case here:
> replace its top paragraph with an `info` panel linking the current source, add a
> `note` panel recording what is now obsolete, and leave the body untouched. The
> surgical edit is what makes "do not delete anything" actually true.

## Putting a diagram on the page

Storage format has **no inline `<svg>`**. A diagram has to be an attachment,
embedded by filename. Confluence renders an SVG attachment as a real `<img>`,
so hand-authored SVG works and stays crisp — no PNG conversion needed.

### 1. Author the SVG standalone

It renders inside an `<img>`, so it is fully isolated from the page:

- **No CSS custom properties from the page** — `var(--x)` resolves to nothing.
  Use literal hex colors.
- **No web fonts.** Use system stacks (`'Helvetica Neue',Helvetica,Arial,sans-serif`,
  `'SF Mono',Menlo,Consolas,monospace`).
- **Paint your own background.** Confluence dark mode does not invert images, so a
  transparent SVG with dark text vanishes for dark-mode readers. Draw a light
  `<rect>` over the full viewBox and use dark ink on it — it then reads in both themes.
- Set both `viewBox` and `width`/`height` so Confluence can size the thumbnail.
- Keep `<title>`/`<desc>` with `aria-labelledby` for accessibility.

Validate before uploading — a malformed SVG uploads fine and fails silently at render:

```bash
python3 -c "import xml.dom.minidom as m; m.parse('diagram.svg'); print('OK')"
```

### 2. Upload as an attachment (v1 API — there is no v2 equivalent)

```bash
curl -s -X POST -u "$EMAIL:$TOKEN" \
  -H 'X-Atlassian-Token: nocheck' \
  -F "file=@diagram.svg;type=image/svg+xml" \
  -F "comment=what the diagram shows" \
  "https://$SITE/wiki/rest/api/content/$PAGE_ID/child/attachment"
```

`X-Atlassian-Token: nocheck` is required — without it the POST is rejected as XSRF.
The page must already exist, so the order is **create page -> upload attachment ->
update page body with the embed**.

### 3. Embed it in the storage body

```xml
<ac:image ac:align="center" ac:width="960" ac:alt="what the diagram shows">
  <ri:attachment ri:filename="diagram.svg"/>
</ac:image>
```

Reference by **filename**, not by attachment id. Re-uploading the same filename
makes a new version and the embed follows it, so the diagram can be revised
without touching the page body.

### 4. Verify it actually rendered

A 200 on the page update only means the storage XHTML parsed; it says nothing
about whether the attachment resolved. Check the rendered view:

```bash
curl -s -u "$EMAIL:$TOKEN" \
  "https://$SITE/wiki/rest/api/content/$PAGE_ID?expand=body.view" \
  | python3 -c "import json,sys; h=json.load(sys.stdin)['body']['view']['value']; \
      i=h.find('diagram.svg'); print(h[max(0,i-300):i+200] if i>=0 else 'NOT RENDERED')"
```

A resolved embed appears as
`<span class="confluence-embedded-file-wrapper ..."><img class="confluence-embedded-image" ... src=".../download/thumbnails/...">`.
If it did not resolve you get the raw macro or an "unknown attachment" placeholder.

**False positives when grepping the rendered HTML for trouble:** `aui-iconfont-error`
is the icon class of a correctly-rendered `warning` panel, and
`data-unresolved-comment-count="0"` sits on every image. Neither is a failure.


## Notes

- Fixing the connector instead: re-authorize the Atlassian connector with write
  scopes. That is the cleaner long-term answer; the REST path is what unblocks
  the current task.
- Do not echo token values. Probe by variable *name* and print only HTTP codes.
- Citing code from a GitHub/GHE repo in the page? Pin permalinks to a commit
  SHA, and re-verify the line numbers against the remote default branch first —
  line anchors copied from an older doc or a local checkout drift silently and
  land the reader on a blank line.
- The separate `mcp-atlassian` server is a different path with different
  rules: it accepts `content_format: "storage"` directly, so the workaround
  here is unnecessary there, and it has its own handling for image upload and
  the TOC macro. Nothing in this skill transfers to it unchanged.

## References

- Confluence Cloud REST API v2 — Pages: https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/
- Confluence storage format reference: https://confluence.atlassian.com/doc/confluence-storage-format-790796544.html
