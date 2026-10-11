---
name: us-federal-open-data-claim-verification
description: |
  Check a quantitative public claim about US federal grants, awards or
  revenue against the government's own open-data APIs, instead of against
  news coverage of those numbers. Use when: (1) a claim asserts a trend
  ("funding fewer grants than last year", "revenue is down"), (2) a claim
  asserts a UNIVERSAL ("in every area", "across the board", "no exceptions")
  and you need to find the counter-example or establish there is none,
  (3) a claim cites a dollar figure you want to reconcile against the
  primary series, (4) a news article's own cited figure and the claim's
  figure differ and you need both stated precisely, (5) you are auditing
  or fact-checking and need unrounded numbers with a reproducible query.
  Covers the count-vs-dollars trap (grant COUNTS and grant DOLLARS
  routinely move in opposite directions, so the claim's verb decides which
  series is the right test), how to test a universal at subunit
  granularity (NIH institute, NSF directorate via CFDA), and working
  request shapes for NIH RePORTER, USAspending, Treasury FiscalData and
  NSF. Includes the `curl` bracket-parameter exit-3 gotcha on
  `page[size]` URLs and why the NSF awards API cannot count.
author: Claude Code
version: 1.0.0
date: 2026-08-11
source: https://github.com/voitta-ai/skillz
source_file: skills/us-federal-open-data-claim-verification/SKILL.md
---

# Verifying Quantitative Claims Against US Federal Open Data

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/us-federal-open-data-claim-verification/SKILL.md`).

## Problem

Claims about federal science funding and federal revenue circulate as
round numbers laundered through several layers of aggregation — an agency
figure becomes a wire story becomes an aggregator's headline becomes a
social post. By the time you see it, the number may be a different series
than the one the claim's words describe, off by a factor of two, or
correct-but-for-a-narrower-universe.

All the underlying data is published with open APIs and no key. Query it.

## Context / Trigger Conditions

- A claim states a trend in grants, awards, or receipts over time.
- A claim states a **universal** — "every area", "all agencies", "across
  the board". Universals are the cheapest claims to test, because a single
  subunit that moved the other way falsifies them.
- A claim's dollar figure needs reconciling against a primary series.
- You need unrounded figures and a query someone else can re-run.

## Solution

### Step 0 — Decide which series the claim's verb actually names

**This is the step people skip, and it decides everything downstream.**

"Funding fewer grants" is a statement about **counts**.
"Cutting funding" is a statement about **dollars**.

These routinely diverge, and the divergence is not noise — an agency under
pressure to obligate its appropriation will push the same money out through
fewer, larger awards. A real observed pattern: grant counts fell in *100%*
of subunits at two agencies in the same year that total dollars were
roughly flat, with mean award size rising sharply to absorb the difference.

So: **pull both, report both, and say which one the claim's wording tests.**
Reporting only the series that favors a verdict is the failure mode.

### Step 1 — Pick the granularity that can falsify a universal

An agency-level total cannot test "in every area". Go one level down and
enumerate:

- **NIH** → institutes and centers (IC): `NCI`, `NIAID`, `NIGMS`, `NHLBI`,
  `NIA`, `NINDS`, `NIDDK`, `NIMH`, `NICHD`, `NIDA`, `NEI`, `NIAMS`,
  `NIEHS`, `NIDCD`, `NIAAA`, `NIDCR`, `NIBIB`, `OD`, `NIMHD`, `NHGRI`,
  `NCATS`, `FIC`, `NCCIH`, `NINR`, `NLM`.
- **NSF** → directorates, addressed by CFDA/Assistance Listing number
  (see table below).

Then state the result as a fraction: "0 of 25 rose", "3 of 11 rose". That
sentence is the finding.

### Step 2 — Query

#### NIH RePORTER — project counts

`POST https://api.reporter.nih.gov/v2/projects/search`, `Content-Type: application/json`.

Read **`meta.total`** with `limit: 1`. You never need to page just to count.

```json
{"criteria": {"fiscal_years": [2025],
              "agencies": ["NCI"],
              "exclude_subprojects": true},
 "limit": 1, "offset": 0}
```

- `exclude_subprojects` **materially changes the answer** — one observed
  fiscal year returned ~76k including subprojects vs ~66k excluding them,
  a ~14% swing. Pick one, state which, keep it constant across years.
- Some plausible-looking `agencies` values are administrative rather than
  funding units and return `0` for every year. Detect zeros and drop those
  rows rather than reporting a fake 100% decline.
- The API is rate-sensitive under a loop. Sleep between calls and retry
  with backoff.

#### USAspending — new award counts, and subunit breakdowns

`POST https://api.usaspending.gov/api/v2/search/spending_by_award_count/`

The key is `date_type: "new_awards_only"`. Without it you count everything
touched in the window, including continuations, which is not what "funded
fewer grants" means.

```json
{"filters": {
   "time_period": [{"start_date": "2024-10-01",
                    "end_date": "2025-09-30",
                    "date_type": "new_awards_only"}],
   "agencies": [{"type": "awarding", "tier": "toptier",
                 "name": "National Science Foundation"}]},
 "subawards": false}
```

Returns `{"results": {"contracts": N, "grants": N, ...}}`.

Add `"program_numbers": ["47.074"]` to the filters to slice one agency into
its subunits. NSF directorates:

| CFDA | Directorate |
|---|---|
| 47.041 | Engineering |
| 47.049 | Mathematical & Physical Sciences |
| 47.050 | Geosciences |
| 47.070 | Computer & Information Science & Engineering |
| 47.074 | Biological Sciences |
| 47.075 | Social, Behavioral & Economic Sciences |
| 47.076 | STEM Education |
| 47.078 | Polar Programs |
| 47.079 | International Science & Engineering |
| 47.083 | Integrative Activities |
| 47.084 | Technology, Innovation & Partnerships |

For **dollars** instead of counts, the same filter block works against
`/api/v2/search/spending_by_category/awarding_agency/` — sum `amount` over
`results`. Use `tier: "subtier"` for sub-agencies (e.g. NIH within HHS).

#### Treasury FiscalData — receipts, incl. customs duties

`GET https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_9`

MTS Table 9 is the authoritative monthly + fiscal-year-to-date receipts
series. Filter by line item and select the fields you need:

```
?filter=classification_desc:eq:Customs%20Duties
&fields=record_date,current_month_rcpt_outly_amt,current_fytd_rcpt_outly_amt,record_fiscal_year
&page[size]=200&sort=-record_date
```

Two things worth knowing:

- These are **net** figures. A **negative monthly value** means refunds
  exceeded collections that month — that is how a court-ordered refund
  program shows up in the primary data, and it is often the cleanest
  available evidence that refunds are actually flowing.
- `record_date` is the period end; `record_fiscal_year` is the *fiscal*
  year, so October–December of calendar year N carry fiscal year N+1.
  Build calendar-year sums yourself from the monthly column rather than
  assuming FY == CY.

#### NSF's own awards API — do not use it to count

`https://api.nsf.gov/services/v1/awards.json` returns award records but
**no total count** in its response envelope. Counting means paging the
whole result set. Use USAspending for counts and reserve the NSF API for
per-award detail.

### Step 3 — Anchor to the claim's date

A claim made on date D could only have used data published by D. Federal
series publish on a lag — the Monthly Treasury Statement for month M lands
roughly mid-M+1. Before calling a figure wrong, check what was actually
available when the claim was made, and report both "the latest figure
public at the time" and "the final figure now".

### Step 4 — Report unrounded, with the query

State exact figures (`$194,865,739,872.82`, not "about $195B") and enough
of the request to re-run it. Where the claim's number and the source's
number differ, print **both**, and name the most plausible series the
claim's number came from rather than only declaring it wrong. A figure
that is wrong as a total is often right as a subset.

## Verification

- Cross-check one month against an independent report of the same month.
  A wire story quoting "$30.75 billion in tariffs last month" matching
  your `30,755,952,020.41` confirms you are on the right line item.
- Confirm your FY totals reproduce the API's own `current_fytd_*` column.
- Re-run one subunit query by hand and confirm it matches the loop's row.

## Example

Testing "fewer grants in every area of science this year":

1. NIH, `exclude_subprojects: true`, 25 ICs × 3 fiscal years via
   `meta.total` → every IC lower than the prior year; sum −8.6%.
2. NSF, USAspending `new_awards_only`, 11 directorates via CFDA → every
   directorate lower; agency grants ~11.7k → ~9.2k.
3. Dollars, same window → NSF new-assistance obligations −9.4%, NIH −1.8%,
   and the agency's own reported total commitments approximately flat.

Finding: **on counts the universal survives at every granularity tested
(0 of 25 and 0 of 11 rose); on dollars it does not.** Both get reported,
with the note that the claim's verb was "funding fewer grants" — a count.

## Notes

- **`curl` exit code 3 on bracket parameters.** FiscalData uses
  `page[size]=200`. Bare `curl` treats `[` `]` as glob metacharacters and
  dies with exit 3 and no useful message. Pass **`-g`/`--globoff`**, or
  percent-encode the brackets. Same trap on any API using `filter[...]` or
  `page[...]` style params.
- **Long API loops need backgrounding.** Enumerating ~30 subunits × 3 years
  with polite sleeps exceeds a typical 2-minute foreground tool timeout.
  Launch with `nohup ... > log 2>&1 &` and poll the log. Note that
  `timeout(1)` is **not** present on stock macOS — it ships as `gtimeout`
  with GNU coreutils — so don't reach for it as the guard.
- **`.gov` hosts frequently 403 a plain fetcher** while serving `curl` with
  a normal browser User-Agent fine. Where a fetch tool returns 403, retry
  via `curl -sL -A '<browser UA>'` before concluding the page is
  unreachable. Record HTTP status and date for every attempt, including
  failures — a documented 403 is a finding, not a gap.
- These APIs need no key and no auth. Read-only.
- Series get revised. Record the retrieval date alongside the figure.

## References

- [NIH RePORTER API v2](https://api.reporter.nih.gov/)
- [USAspending API documentation](https://api.usaspending.gov/docs/endpoints)
- [Treasury FiscalData API](https://fiscaldata.treasury.gov/api-documentation/)
- [Monthly Treasury Statement dataset](https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/)
- [NSF Award Search API](https://resources.research.gov/common/webapi/awardapisearch-v1.htm)
- [Assistance Listings (CFDA) at SAM.gov](https://sam.gov/content/assistance-listings)
