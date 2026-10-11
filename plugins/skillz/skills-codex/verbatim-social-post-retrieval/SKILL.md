---
name: verbatim-social-post-retrieval
description: |
  Retrieve the exact original text of a Truth Social or X/Twitter post for
  fact-checking or citation, including posts that have since been DELETED.
  Use when: (1) you need a politician's or public figure's post word-for-word
  rather than a news outlet's paraphrase, (2) a claim quotes a post and you
  must confirm the wording, capitalization or whether a specific word is
  actually theirs, (3) you need the post's real timestamp to establish who
  said what first, (4) x.com and truthsocial.com return login walls,
  Cloudflare challenges or JS-only shells to your fetcher, (5) a news site
  returns HTTP 451/403 and you need another route to the same wire copy.
  Covers the api.fxtwitter.com JSON endpoint for X posts (no auth, returns
  full text + created_at + quoted post), the trumpstruth.org archive for
  Truth Social including its deletion flags and its `query=` search
  parameter, date-bounded searching to prove a negative, and syndication
  fallbacks for HTTP 451 paywalled/geoblocked wire stories.
author: Claude Code
version: 1.0.0
date: 2026-08-11
source: https://github.com/voitta-ai/skillz
source_file: skills/verbatim-social-post-retrieval/SKILL.md
---

# Verbatim Social Post Retrieval

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/verbatim-social-post-retrieval/SKILL.md`).

## Problem

Fact-checking a claim about what someone posted requires the post, not
coverage of the post. But `x.com` and `truthsocial.com` serve login walls,
Cloudflare challenges, or empty JS shells to non-browser fetchers, and news
outlets paraphrase, truncate, silently fix spelling, and drop the
timestamp. Posts also get **deleted and reposted**, so the version quoted
in coverage may not be the version that survives.

## Context / Trigger Conditions

- You must confirm whether a specific word in a claim is the speaker's own.
- You need a timestamp precise enough to order two events.
- Your fetcher gets a Cloudflare interstitial, a login wall, or an empty
  shell from a social host.
- A wire story you need is behind HTTP 451 or 403.
- You need to establish a **negative** — "no such post exists in this
  window."

## Solution

### X / Twitter — `api.fxtwitter.com`

```
https://api.fxtwitter.com/<screen_name>/status/<status_id>
```

Plain `GET`, no auth, returns JSON. Useful fields under `tweet`:

- `text` — the full post verbatim, newlines preserved
- `created_at` — e.g. `Sun Oct 19 00:04:33 +0000 2025` (**UTC** — convert
  before reasoning about local-time ordering)
- `author.screen_name`, `views`
- `quote` — the **quoted post**, fully expanded with its own author and
  text. Often carries context the quoting post assumes.

```bash
curl -sL "https://api.fxtwitter.com/<user>/status/<id>" \
  | python3 -c "import json,sys; t=json.load(sys.stdin)['tweet']; \
print(t['created_at']); print(t['text'])"
```

Do **not** bother with `r.jina.ai` in front of `x.com` — it returns a
Cloudflare "Just a moment…" challenge page.

### Truth Social — `trumpstruth.org`

Per-post: `https://trumpstruth.org/statuses/<archive_id>` (an archive id,
**not** the platform status id — the platform id appears in the page body).

**Search** — the parameter is `query`, on the `/search` path. `search=` and
`searchterm=` are silently ignored and return an unrelated recent feed,
which reads exactly like a real zero-hit result. Getting this wrong is the
main failure mode.

```
https://trumpstruth.org/search?query=<term>&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
```

**Deleted posts are preserved and flagged.** Look for body text like
`Removed from Truth Social.` / `This post is no longer on the platform; it
is preserved here for the archive.` plus a dated confirmation. This is how
you catch a delete-and-repost: the same statement can exist twice, minutes
apart, differing in one detail.

### Establishing a negative

Date-bounded search is evidence. "A date-bounded archive search for
`<term>` over `<range>` returns exactly N results" is a citable finding,
and is how you support "no announcement of an event on date D exists."
Cross-check against an independent tally before asserting the negative.

### HTTP 451 / 403 on news sites — syndication fallback

Wire and network copy is republished by affiliates and partners that do not
carry the same geoblock. When a major outlet returns 451, search a
distinctive verbatim sentence from the story and take the syndicated copy;
cite the original byline and note the retrieval route. Syndicated copies may
be **pre-correction** — compare against the canonical version when you can.

### General fetch discipline

- Browser `User-Agent` on `curl` beats most fetch tools against `.gov` and
  news hosts that 403 a bare client.
- Record HTTP status and retrieval date for **every** attempt, including
  failures. A documented 403 is a finding, not a gap.
- Prefer an archive that preserves deletions over a live platform read; the
  live read cannot show you what was removed.

## Verification

- Independently re-fetch the one or two artifacts your conclusion rests on,
  rather than trusting a single pass (or a subagent's report).
- For a deleted post, confirm the archive's removal flag is present rather
  than inferring deletion from a 404 elsewhere.
- Sanity-check `created_at` against an independent report of the same post.
- When two versions exist, quote the surviving one and note the deleted one.

## Example

Auditing "X threatened aid cuts after Y accused the US of a killing":

1. `trumpstruth.org/search?query=<country>&start_date=…&end_date=…` → exactly
   3 posts in the window, so the set is complete.
2. Two are the same statement 73 minutes apart; the earlier is flagged
   `Removed from Truth Social` — a delete-and-repost over a misspelling.
   Quote the survivor, note the deletion.
3. Full text shows the post declares the cutoff as accomplished fact, and
   **never mentions tariffs** — so a claim that tariffs were announced in
   the post fails against the primary artifact.
4. `api.fxtwitter.com` on the accuser's posts gives UTC timestamps proving
   the accusation preceded the response by ~9–13 hours.
5. The accuser's own words say "territorial waters"; the claim said
   "international waters" — the opposite, and the crux of the dispute.

## Notes

- **Third-party mirrors, not systems of record.** `fxtwitter` and
  `trumpstruth.org` are independent projects. For anything load-bearing,
  cite the original URL and status id alongside the mirror, and re-verify.
- Extract the **platform status id** from the archive page so the citation
  survives the mirror going away.
- Transcripts of spoken remarks are a separate and often better artifact
  than posts — a figure may address in a gaggle what the post omits.
  `rollcall.com/factbase` carries timestamped transcripts.
- `.gov` press-release slugs are not reliably guessable; a guessed URL that
  404s is not evidence the document does not exist.
- Some outlets render tweet embeds in JS, so tweet ids will not appear in
  raw HTML — pull the quoted text from the body copy instead.

## References

- [FxTwitter / FixTweet](https://github.com/FxEmbed/FxEmbed) — the project behind `api.fxtwitter.com`
- [Trump's Truth Social archive](https://trumpstruth.org/)
- [Roll Call Factbase transcripts](https://rollcall.com/factbase/trump/)
- [HTTP 451 (Unavailable For Legal Reasons), RFC 7725](https://www.rfc-editor.org/rfc/rfc7725)
