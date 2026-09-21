---
name: vendor-api-registration-gate
description: |
  Decide whether a third-party API is actually available to a NEW integration,
  when the vendor's documentation answers a different question than the one
  you asked. Use when: (1) a doc says an API is "supported until <date>" or
  "deprecated in <year>" and you are about to design around that date, (2) an
  official API exists on paper but every code sample in the wild comes from an
  unofficial wrapper and you cannot find the signup page, (3) you are choosing
  a cloud bridge for consumer hardware - a BLE scale, a watch, a sleep tracker
  - and need to know which vendor you can register with TODAY, (4) a migration
  guide names a successor API and you infer the predecessor is still open to
  newcomers, (5) an integration is blocked and nobody can say whether the
  blocker is credentials, app type, or partner status. The trap: runtime
  lifecycle and registration gate are separate fields, and a page that answers
  "when does this stop working" is silent on "can I start using it". Concrete
  instance: Google Fit's REST and Android APIs run until the end of 2026 but
  closed to new developer signups on 2024-05-01, so for any project started
  after that date the answer is no, whatever the deprecation date says.
author: Claude Code
version: 1.0.0
date: 2026-09-21
---

# The registration gate is not the deprecation date

## Problem

You are choosing an integration path. You search, you find the vendor's
lifecycle page, and it says something reassuring and specific: *supported
until the end of 2026*. You write that date into the design, pick the API,
and discover weeks later that you cannot obtain credentials at all - not
because it shut down, but because the door for new developers closed long
before the lights go off.

This is the "check the field that would have said I could not" failure in
vendor-documentation form. The deprecation date is a real field and it is
accurately reported. It is simply answering a different question. Nothing
errors; you just get a confident answer to the wrong question.

## Three independent gates

An API is usable by you only if all three are open. They fail separately and
are documented in separate places, often by separate teams.

| Gate | Question | Where it is usually stated |
|---|---|---|
| **Runtime** | Is it still serving traffic? | Lifecycle / deprecation page. The one you will find first. |
| **Registration** | Can a new developer still get credentials? | A one-line aside in a migration FAQ, a greyed-out console, or a support post. Rarely on the lifecycle page. |
| **Eligibility** | Does *your* app type / org / volume qualify? | Partner program page, application form, or nothing at all. |

Runtime open plus registration closed is the common and most expensive
combination, because everything you read looks fine.

## Procedure

1. **Find the lifecycle date, then stop treating it as the answer.** Write it
   down as the runtime gate only.
2. **Try to reach the signup surface.** Open the developer console or app
   registration page. If you cannot create an application, that is the
   registration gate answering, and it outranks every date you found.
3. **Search the negative form explicitly.** The phrases that surface this are
   "no longer accepting new", "new signups closed", "existing clients only",
   "partner access", "by application", "allowlist". Searching the API name
   alone will not surface them; the positive documentation dominates.
4. **Treat a thriving unofficial wrapper as a signal, not a solution.** When
   the ecosystem around an official API is entirely reverse-engineered
   clients, the registration or eligibility gate is usually shut. That is
   information about the gate, before it is a decision about the wrapper.
5. **Report which gate you checked.** "Available" is not a finding.
   "Runtime open to 2026-12, registration closed 2024-05-01" is. If you did
   not check registration, say so rather than implying availability.

## Worked example

Bridging a consumer Bluetooth body-composition scale into a backend on
Android. The scale's own app offers three sync targets: Apple Health, Google
Fit, and Fitbit.

- Apple Health - eligibility gate: wrong platform. Closed.
- Google Fit - runtime gate open, documentation says supported to end of
  2026 and the migration FAQ recommends Health Connect. Registration gate:
  **closed since 2024-05-01**, no new developer signups. So the reassuring
  2026 date is irrelevant to a project starting now.
- Health Connect - runtime open, but it is an on-device Android API. A
  scheduled server-side job cannot read it without shipping an app. That is
  an architecture mismatch, not a gate, and it is still a no.
- Fitbit - all three gates open. Free account, ordinary OAuth2 app
  registration, documented Web API for weight and body fat.

The decision is Fitbit, and it takes ten minutes once the gates are separated.
Reading only the lifecycle pages points at Google Fit and costs days.

Same shape, different vendor: Garmin publishes an official Health API, so the
runtime gate is open and the documentation is public - but it is partner-
gated, so the eligibility gate is shut for an individual. Which is precisely
why every Garmin integration in the wild is an unofficial client of the
consumer Connect endpoints.

## Gotchas

- **A migration guide is evidence about the successor, not the predecessor.**
  "We recommend migrating to X" tells you X is open. It says nothing about
  whether you may still start on the old one.
- **"Deprecated" and "closed" drift apart by years.** Two years between
  signup closure and shutdown is normal. The gap is exactly where this bites.
- **The console lies by omission.** A registration page that renders but
  rejects on submit, or silently lists zero available API products, reads as
  a transient error. Try twice, then treat it as the gate.
- **Existing credentials keep working.** Anyone who integrated before the
  cutoff will tell you honestly that it works fine. Their answer does not
  transfer to you.
- **Pricing pages outlive access.** A published price list is not proof that
  new customers can buy.

## Related

- `us-federal-open-data-claim-verification` - the same discipline applied to
  data availability claims: verify the access path, not the announcement.
- `llm-vendor-waterfall` - choosing among vendors when access, not
  capability, is the binding constraint.
