---
name: archive-today-fetcher-hierarchy
description: |
  Retrieve a page from archive.today (archive.ph / archive.is / archive.li /
  archive.fo / archive.md / archive.vn) when automated fetchers are refused,
  and cite what you get in a way a reader can reproduce. Use when:
  (1) a publisher returns 403 and you need the archived copy,
  (2) archive.today returns HTTP 429 or a CAPTCHA challenge to curl, to an
  agent's built-in fetch tool, or to a headless scraping API even with a
  stealth proxy, (3) the Wayback Machine also fails, including its
  availability API reporting no snapshot while playback separately 403s,
  (4) you need a stable citation for an artifact that is unreachable by
  automation. Covers the fetcher hierarchy in practice, the URL patterns
  that work, why the operator's own browser is a legitimate route rather
  than a bypass, and the three constraints that keep it legitimate.
author: Claude Code
version: 2.0.0
date: 2026-08-11
source: https://github.com/voitta-ai/skillz
source_file: skills/archive-today-fetcher-hierarchy/SKILL.md
---

**Canonical source:** this file lives at `skills/archive-today-fetcher-hierarchy/SKILL.md`
in `voitta-ai/skillz`. Edit it there.

## Send a truthful user agent

**Do not spoof.** A user agent states who is asking, and hosts use it to decide
what to serve; a browser string sent from a script is a false statement about the
requester, however conventional. Send something that identifies you:

    curl -A 'yourproject/1.0 (+https://your.url/; purpose; contact)'

**This is not merely a scruple, and the empirical part is the surprise.** Measured
2026-08-11 across nine hosts a research task actually depends on —
federalregister.gov, uscode.house.gov, justice.gov, supremecourt.gov,
clerk.house.gov, a State Department embassy site, dhs.gov, theguardian.com and a
public JSON API — an honest identifying agent and a spoofed Chrome string returned
**identical status codes on all nine.** Every one 200. The spoofing bought
nothing at all.

The mistake that produced the original advice was diagnostic. The failures that
prompted it were an agent framework's *own* fetch tool being blocked at the
framework level — something plain curl never shared. That is a fetcher
difference, not a user-agent difference, and conflating the two yielded a
technique both ineffective and dishonest.

**Diagnosis order when a fetch fails:** change fetcher before you touch identity.
If an honest agent genuinely fails where a spoofed one succeeds, that is a finding
about the host's access policy, to be recorded — not a lock to be picked.

## The finding

archive.today's tolerance for automation has tightened. Measured 2026-08-10
against a single target URL, in one session, minutes apart:

| Route | Result |
|---|---|
| `curl`, any User-Agent | **429** |
| Agent built-in fetch tool | **hard-blocked** by the host agent's domain blocklist |
| Headless scraping API, `proxy: basic` | **429** |
| Headless scraping API, `proxy: stealth` | **429**, body is a reCAPTCHA challenge page |
| **The operator's own browser, driven through a browser extension** | **200, full article text** |

Earlier guidance that a headless scraping API "works" for archive.today is no
longer reliable. Assume every automated route fails and that the browser is the
route that remains.

Also measured on the same target, so the fallback chain does not mislead:
`web.archive.org` playback returned **403**, and `archive.org/wayback/available`
reported **no snapshot at all** for a URL that archive.today had captured hours
after publication. Wayback failing is not evidence the artifact is unarchived.

## URL patterns

| Pattern | Meaning |
|---|---|
| `archive.ph/newest/<URL>` | latest snapshot; redirects to the dated form |
| `archive.ph/oldest/<URL>` | first snapshot |
| `archive.ph/<URL>` | listing page, all snapshots |
| `archive.ph/<YYYYMMDDHHMMSS>/<URL>` | **canonical dated snapshot — cite this** |

The inner URL goes in raw and unencoded. Navigating to `/newest/` lands on the
dated form, and that resolved dated URL is what belongs in a citation: it is
stable, it names the capture moment, and anyone can open it.

Memento endpoints (`/timemap/`, `/timegate/`) return the homepage. Do not use them.

## Procedure

1. Try the cheap routes first and **record what each returned**. The failures are
   part of the provenance, not noise to discard.
2. Try Wayback: `web.archive.org/web/<URL>`. Independent of archive.today, and
   friendlier to `curl` — when it works.
3. Navigate the operator's browser to `archive.ph/newest/<URL>` and extract the
   page text.
4. **Cite the resolved dated URL**, not `/newest/`, and record that the fetch was
   performed by a human through a browser.

## Why this is a legitimate route, and the constraints that keep it so

A CAPTCHA establishes that a human is present. When the operator opens the page
in their own browser, in their own session, and solves any challenge themselves,
**a human is present**. The signal is satisfied rather than faked.

That is categorically different from automating a CAPTCHA solve or driving a
browser at machine rates. Those defeat the control instead of meeting it. Do not
do them.

Three constraints:

1. **Record the fetch as human-performed.** It widens what you can reach and
   narrows what a reader can independently verify, and that trade belongs on the
   record rather than hidden.
2. **Prefer routes the reader can also take.** This is what makes an archive
   capture unusually clean: anyone with a browser can open the same dated URL.
   A quotation transcribed from behind a paywall is strictly worse, because the
   reader cannot check it.
3. **Human rate.** A page at a time, because a person is reading it.

**What the browser route is not.** It is not spoofing. The operator's own browser
sends its own true agent and a human is genuinely present, which is exactly why it
is defensible where a scripted request in a browser costume is not: one makes a
true statement about who is asking, the other a false one. The unresolved question
there is rate limits and challenges, not identity.

**The residue, stated:** you are the party deciding that your own use satisfies
the spirit of someone else's access control. That is self-serving however
carefully argued. Write down what you did so a reader who disagrees can object
on the record.

## Reproducing content

Extract what you need; do not republish the article. Short quotations for
criticism or analysis, attributed and linked to the dated capture, are a
different act from reposting the body.

## Related

- `wordpress-com-publish` — unrelated, but the same house style for
  auth-then-act procedures.
