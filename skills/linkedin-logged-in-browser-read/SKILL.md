---
name: linkedin-logged-in-browser-read
description: |
  Read LinkedIn surfaces (a member profile, a company page, page admin status,
  post activity and analytics, the developer-portal app list) through the
  user's already-logged-in Chrome session via claude-in-chrome, when no API
  route exists. Use when: (1) you need to audit or inventory someone's own
  LinkedIn presence - profile sections, company pages they administer,
  posting cadence, impressions; (2) an API plan hits the wall that
  r_member_social is a closed permission and feed/comment/mention reading has
  no self-serve route; (3) get_page_text on a profile URL returns only the
  headline card and nothing below it; (4) you need to know whether the user
  is an admin of a company page, or its numeric organization id, without a
  Community Management API app; (5) a keychain or env holds LinkedIn
  client-id/secret values but you cannot tell which app they belong to.
  Read-only, human-paced; not a scraper.
author: Claude Code
version: 1.0.0
date: 2026-09-10
source: method-and-apparatus LinkedIn presence prep pass, 2026-09-10
---

> **Canonical source.** `voitta-ai/skillz`, `skills/linkedin-logged-in-browser-read/SKILL.md`.

# LinkedIn: read through the logged-in browser

## Problem

LinkedIn's API cannot read most of what a presence audit needs. In the 2026
Marketing API (`li-lms-2026-08`): `r_member_social` (read a member's posts and
social activity) is a **closed permission, not accepting requests**; reading
comments, reactions and analytics needs Community Management API partner
review (registered legal entity, verified page, two review tiers with a
screencast); there is no endpoint for the feed, mentions, or third-party
posts. Only *posting* as a member is self-serve (`w_member_social`, Posts API).

So the read side is the browser. The user's own Chrome, already logged in,
driven read-only through `claude-in-chrome`, is a normal browsing session with
no stored cookies, no headless fingerprint and no bulk pattern. It is not a
substitute for a search scraper; it is how you read a handful of pages.

## Trigger conditions

- Task is "check / audit / inventory my LinkedIn" or "what does our company
  page say", not "find 500 people".
- `get_page_text` on `https://www.linkedin.com/in/<slug>/` came back with the
  headline, location and "500+ connections" but no About or Experience.
- You need admin status or the numeric org id of a company page.
- Someone wants to know whether an existing LinkedIn app / client secret is
  still attached to their login.

## Solution

Load the core browser tools in one `ToolSearch` call, get tab context, and
open one tab per surface. Then use these URLs; each was verified to return
the full section as page text unless noted.

| Need | URL | Notes |
|---|---|---|
| Full experience list | `/in/<slug>/details/experience/` | Full text of every role. The bare profile URL renders sections lazily and `get_page_text` gets only the top card. |
| Skills, education, etc. | `/in/<slug>/details/skills/`, `/details/education/` | Same pattern. |
| Own posting activity | `/in/<slug>/recent-activity/all/` | Text extraction returns only the first article. Take a **screenshot** and scroll; the feed shows age, impressions, reactions, follower count and draft count in the left card. |
| Company page facts | `/company/<slug>/about/` | Overview, website, size, founded, type, specialties, associated members, admin names ("X works here"). |
| Am I an admin? Numeric org id? | `/company/<slug>/admin/dashboard/` | Redirects to `/company/<numeric-id>/admin/dashboard/` if admin (the id is what the Posts API wants as `urn:li:organization:<id>`), and to `/company/unavailable/` if not. No error, so read the final URL from the tab context. |
| Page health | admin dashboard text | Shows "Add description", "Add logo", post count in 90 days, followers, visitors. |
| Which apps does this login own? | `https://www.linkedin.com/developers/apps` | Lists active and deactivated apps. An empty list with a client-id/secret sitting in a keychain means the app was created under another login or deleted; treat the pair as orphaned. |
| Find a company page you do not know the slug of | `/search/results/companies/?keywords=<name>` | Results carry three duplicate link refs per company and clicking them may not navigate; take the slug from `find` output and `navigate` to `/company/<slug>/about/` directly. |

Order of operations for an audit:

1. Profile: `details/experience/` text, then `recent-activity/all/` screenshot.
2. Each company page: `about/` text, then `admin/dashboard/` to learn admin
   status and id.
3. `developers/apps` if any API work is planned.
4. Close every tab you opened.

Keep it read-only. Do not click Follow, Connect, Boost, or any composer; do
not scroll feeds for hundreds of items. If the user needs bulk search, that is
a separate decision with account-risk tradeoffs, not this skill.

## Verification

- `details/experience/` text contains role titles and date ranges, not just the
  headline.
- The admin probe's final URL is one of the two shapes above; anything else
  (a login wall, a "page not found") means the session is not logged in or
  the slug is wrong.
- Numbers you report (followers, impressions) are read from a screenshot or
  page text you actually captured in this session, with the date.

## Example

Audit found: profile headline and 1,1xx followers; two blog-link posts in the
last month with impressions in the low hundreds; company page A exists with a
different admin and the user unaffiliated; company page B exists, user is
admin (numeric id captured from the redirect), no description, no posts; the
developer portal lists no apps although a client pair exists in the keychain.
That is a complete presence inventory in about a dozen tool calls, with no API
credentials.

## Notes

- Posting is a different problem with a real API. Member posting is self-serve
  via the "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect"
  products, scope `w_member_social`, versioned Posts API. Organization posting
  needs Community Management review. There is no scheduling endpoint; native
  scheduling is UI-only.
- Unrelated pages can share your company's name in search. Note the exact
  slug you verified so later sessions do not audit the wrong page.
- LinkedIn's DOM changes; the URL patterns above are the stable part. If a
  detail URL stops returning text, screenshot it instead before concluding
  the section is empty.

- If the audit turns into edits: LinkedIn's "Add a role" dialog has, below
  the fold, an "Update your profile headline" radio that defaults to the new
  role and a "Share with your network" toggle that defaults to On. Saving
  without scrolling replaces the headline and notifies connections; skipping
  the "share this update" modal afterwards undoes neither. Scroll to the
  bottom, keep the "(current)" headline, switch sharing off, and check the
  sticky header after save.

- Typing long text into LinkedIn's rich-text boxes through browser
  automation can silently drop characters. Put the text on the system
  clipboard and send a real Cmd-V instead, then check the field length
  against the source. A company-page Save that follows an earlier save in
  the same editor session can fail with "Another admin is trying to make
  changes to this page at the same time as you" and redraw the form half
  blank. Do a full reload, refill, and verify on a fresh load.

## References

- Community Management overview, tiers and the closed `r_member_social`:
  https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview
- Posts API:
  https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api
- Community Management app review:
  https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review
