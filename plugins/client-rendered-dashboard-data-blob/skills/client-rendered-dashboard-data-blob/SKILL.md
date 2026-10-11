---
name: client-rendered-dashboard-data-blob
description: |
  Pull trustworthy numbers out of a dashboard that renders entirely
  client-side, by decoding the data blob it ships instead of scraping the DOM
  or driving a browser. Use when: (1) you want a dashboard's data as a feed for
  a report, a script, or another skill, (2) `curl` returns a big HTML page whose
  numbers are nowhere in the HTML, (3) you are about to reach for Playwright /
  headless Chrome just to read some totals, (4) you copied a rank or a
  percentage off the screen and want to know what it actually measures before
  quoting it, (5) numbers you derived from a decoded blob disagree with what
  the page displays. Covers finding the blob, decoding a positional-tuple event
  schema from the page's own render loop, porting derived-metric formulas
  rather than guessing them, and validating against a screenshot. Includes two
  traps that silently produce plausible-but-wrong numbers: a displayed rank
  that is really a row number under the active sort, and a "velocity"/delta
  that is intra-window rather than period-over-period.
author: Claude Code
version: 1.1.0
date: 2026-08-20
---

# Decode a client-rendered dashboard's data blob

## Problem

A dashboard shows exactly the numbers you want. You `curl` it and get a
megabyte of HTML with none of those numbers in it -- they are computed in the
browser. The obvious next step is a headless browser, which is slow, needs a
session, and gives you back only what is on screen.

Often you do not need any of that. Dashboards of this shape frequently ship
their **entire dataset** inline as a JavaScript literal and do all aggregation
client-side. One GET can therefore contain far more than the page displays --
every row, not just the visible page; the full history, not just the selected
window; every entity, not just the one you filtered to.

The second, subtler problem: once you have the raw data, the derived numbers
(ranks, percentages, scores) are **not** in it. You have to recompute them, and
the natural guess at what they mean is frequently wrong -- in a way that still
produces a believable number.

## Context / Trigger conditions

- `curl <dashboard-url>` returns HTTP 200 and a large HTML body, but
  `grep` for a value you can see on screen finds nothing.
- The page has one or two `<script>` blocks and no `application/json`.
- You are about to script a browser purely to read numbers.
- You want a dashboard as an upstream data source for a scheduled report.
- Your recomputed metric disagrees with the rendered one.
- You are about to quote "I'm ranked #N" from a URL that has a sort parameter
  in it.

## Solution

### 1. Find the blob

```bash
curl -sS -o page.html "<dashboard-url>"
grep -o '<script[^>]*>' page.html | sort | uniq -c        # how many script blocks
grep -n -o 'const [A-Za-z_]* *= *[[{]' page.html | head   # top-level data vars
```

Also worth trying, in rough order of how common they are:
`__NEXT_DATA__`, `window.__INITIAL_STATE__`, `self.__remixContext`,
`<script type="application/json">`, and a plain `const DATA = {...}`.

Extract and parse. Anchor the regex to the line so a trailing `;` or a second
statement on the same line does not corrupt the JSON:

```python
m = re.search(r"^const DATA = (\{.*\});?\s*$", html, re.M)
data = json.loads(m.group(1))
```

Note what that anchoring assumes: `.` does not cross newlines, so the blob must
stay on **one line**. That is load-bearing -- say so at the regex, and if the
page ever pretty-prints, widen with `re.S`.

### 2. Learn the schema from the page's own render loop

Big dashboards compress rows into **positional tuples of integers** with
parallel lookup arrays, because it is much smaller than repeated JSON keys. A
raw record looks meaningless:

```
[0, 4, 0, 0, 15, 49, 0]
```

Do not guess the fields. The page destructures them somewhere; find that and
read the names off it:

```bash
grep -n -o 'for(const \[[a-zA-Z, ]*\] of [A-Z]*' page.html
# for(const [p,off,o,r,c,pr,rv] of EV)
```

That single line names all seven positions, and the surrounding loop body tells
you the units -- including which fields are **indexes into lookup arrays**
(`people[p]`, `repos[r]`) rather than values, and which are **offsets** rather
than absolute (a day counted back from a `today` field, not a date).

### 3. Port derived formulas; never re-derive them from intuition

Anything on screen that is not a raw sum -- rank, score, percentage, "velocity",
a status label -- is computed in that JavaScript. Read the function and port it
literally. Two specific traps, both observed:

**Trap 1: the displayed rank is a row number.**

A rank column often renders the row's position **under whatever sort is
active**, not a standing. If the URL carries a sort parameter, the number is
sorted by that. In one case a URL ending `?s=name` displayed `#194` -- that was
alphabetical position among active people. The same person's actual standing by
the dashboard's default metric was **#49 of 606**.

The tells: a sort parameter in the URL, and a rank that does not move when you
change the metric. Rank by the metric yourself, and always report the
denominator (`#49 of 606`) so the number is interpretable.

**Trap 2: "velocity" / deltas are often intra-window, not period-over-period.**

The intuitive reading of a trend arrow is *this period vs the previous period*.
Dashboards frequently mean something else -- commonly *latest half of the
window over the earliest half*, which needs only the data already loaded:

```javascript
// from the page; note both halves come from the SAME window
if (off < half) { a.cL += c; } else { a.cE += c; }   // latest / earliest
const pct = Math.round(100 * latest / earliest);
```

For a 30-day window that compares days 0-14 against days 15-29. Reading it as
this-30-days vs previous-30-days gave `21% / 89% / 3%` where the page showed
`184% / 376% / -71%` -- three plausible numbers, all wrong. Hover text on the
column header (`title="... latest half / earliest half"`) is often the fastest
confirmation.

Also port the degenerate cases. `earliest == 0` is a division by zero the page
handles explicitly (usually rendering "new"); emit `None` rather than
`Infinity` or a crash.

### 4. Resolve entities by stable id, not display name

Blobs of this kind carry a people/entity array with login or id fields:

```json
{"name": "A Person", "level": "P5",
 "profiles": [["host-a", "login-a"], ["host-b", "login-b"]]}
```

Match on the login, not `name` -- display names collide and change. Matching on
login also keeps a tool user-derived (pass the caller's own login in) instead of
hardcoding a person, and a multi-host profile list is exactly what lets one
fetch cover several source systems at once.

### 5. Validate against a rendered view before trusting anything

This is the step that turns a scrape into a source you can quote. Take a
screenshot or reading of the page for one entity and reproduce **every** number:

```
                mine        page
commits/prs/rv  142/100/36  142/100/36   ok
commit vel      184%        184%         ok
contrib/day     9.3         9.3          ok
rank            #49         #194         <-- investigate, do not "fix"
```

A single mismatch against many matches is a finding, not noise. Here it was
Trap 1 -- and the correct response was to keep the computation and explain the
displayed value, not to bend the code until it printed 194.

## Verification

- Re-run against a live fetch and diff every derived field against the rendered
  page for at least one entity.
- Keep an **offline** self-check with a small synthetic blob, asserting the
  window arithmetic, the empty-denominator case, and rank ordering. It runs
  with no network and no credentials, so it survives VPN loss and page changes.
- Fail loudly when the blob is missing, and **distinguish the failure modes**.
  An SSO bounce returns 200 with a login page, which is not a format change:

```python
def no_blob_reason(html):
    if "const DATA" in html:
        retval = "blob is no longer on one line; page format changed"
    elif re.search(r"\b(sign in|log in|login|sso|okta)\b", html, re.I):
        retval = "got a login page; not authenticated (SSO/VPN?)"
    else:
        retval = "page format changed"
    return retval
```

  Collapsing those into one message sends you debugging the wrong thing. A
  silent empty result that flows into a report is worse still.

## Example

End to end, for a contribution dashboard:

```python
m = re.search(r"^const DATA = (\{.*\});?\s*$", html, re.M)
data = json.loads(m.group(1))
# events[i] = [personIdx, dayOffset, orgIdx, repoIdx, commits, prs, reviews]
for p, off, _org, r, c, pr, rv in data["events"]:
    if off >= window:
        continue
    ...
```

Yield: 180 days of per-day, per-repo activity spanning two source hosts, from
one GET -- including entities the page's default filters hide. That last part is
usually where the value is: rows that a filtered UI view, or an
authored-content API query, would never surface.

A worked implementation of exactly this pattern reads the blob once and uses
it for two things at once: rendering a standing header, and finding the days
that should have a page but do not.

## Notes

- **Check authorization before pointing this at anything.** Everything here is
  read-only, but it is still automated access. An internal tool on a network you
  are already trusted on is one thing; a third-party site is a different
  question with terms of service attached.
- Do not commit the fetched HTML -- a personalized dashboard body may carry
  other people's names, orgs, and identifiers. This is also why the skill is
  written generically: the *technique* transfers, the payload does not.
- This is brittle by nature: the blob's variable name and tuple order are
  private implementation details. Pin the assumption in one place, fail loudly,
  and keep the offline self-check so a break is obvious rather than silent.
- Re-fetching a multi-megabyte blob per query is waste. One fetch should serve
  every day/entity your caller needs; that falls out naturally if the decoder
  returns the whole decoded structure instead of one answer.
- The general "prefer an embedded data blob over headless rendering" advice is
  well covered in scraping literature (see References). What that literature
  does **not** cover is everything after you have the data: derived metrics are
  where the wrong answers come from.

## Related

- `spa-request-capture-and-block` -- the outbound direction: capturing the
  request body an app *sends*, when you need the payload rather than the view.

## References

- [Scraping JavaScript-rendered web pages (ScrapingBee)](https://www.scrapingbee.com/blog/scraping-javascript-rendered-web-pages/)
- [Scraping dynamic JavaScript websites: techniques & fixes](https://tendem.ai/blog/scraping-dynamic-javascript-websites)
- [Scraping JavaScript-heavy websites and SPAs: 2026 guide](https://www.papalily.com/blog/scraping-javascript-spas.html)
