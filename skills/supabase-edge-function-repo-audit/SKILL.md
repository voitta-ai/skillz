---
name: supabase-edge-function-repo-audit
description: |
  Audit a Supabase project from a clone of its repo when behaviour is
  inconsistent and no error shows. Use when: (1) rules, settings or rows "do
  not load" and the code logs nothing; (2) you must say which Edge Functions
  check their caller; (3) you need to know whether a function in the repo is
  deployed, without invoking it. Covers queries that fail silently because
  `error` is never read (compare the columns a query names with the generated
  `Database` types), a per-function caller-check table including
  `verify_jwt = false`, and a CORS-preflight deployment probe with two
  controls.
author: Claude Code
version: 1.0.0
date: 2026-11-15
source: https://github.com/voitta-ai/skillz
source_file: skills/supabase-edge-function-repo-audit/SKILL.md
---

# Supabase Edge Function repo audit

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/supabase-edge-function-repo-audit/SKILL.md`).

## Problem

A Supabase app, often one written mostly by an AI app builder, behaves
inconsistently. A rule set "does not load", a feature works on one screen and
not on another, and nothing is logged. Three causes are visible from a clone of
the repo, and each has a cheap check:

1. A query fails and the code never reads `error`, so the failure looks like
   "no rows".
2. An Edge Function does not check who is calling it.
3. Nobody knows whether a function in the repo is deployed.

## Context / Trigger Conditions

- You have the repo, and perhaps the site URL, but no dashboard, database or
  secrets access.
- The symptoms are of the kind "the rules never apply", "it ignores the
  settings" or "it works in the demo and not live".
- The code is full of `const { data } = await supabase.from(...)`.
- The owner asks whether the backend is safe to open to more users.
- `supabase/config.toml` lists functions with `verify_jwt = false`.

## Solution

### 1. Queries that fail silently

supabase-js does not throw when a query fails. It returns `{ data, error }`,
and on a failure `data` is `null`. Code that destructures only `data` and then
writes `data ?? []` or `if (data?.length)` turns "the query is wrong" into
"there are no rows".

The failure that lasts longest is a wrong column name. The table exists, the
query is well formed, and PostgREST rejects it on every call. The status is
HTTP 400 by inference: the PostgREST error table lists 42P01 (undefined table)
as 404, has no row for 42703 (undefined column), and ends with "other | 400".

1. Measure the habit. A high first number says where to look. It does not say
   that every one of those calls is broken.

   ```bash
   grep -rnE 'const \{ data(: \w+)? \} = await' supabase/functions src | wc -l
   grep -rnE 'const \{ data(: \w+)?, error' supabase/functions src | wc -l
   ```

2. Find the generated types file. It is commonly
   `src/integrations/supabase/types.ts` or `database.types.ts`, and it exports
   `Database` with `Tables`, then one entry per table, then `Row`. Parse the
   `Row` columns:

   ```python
   import re
   src = open("src/integrations/supabase/types.ts").read()
   tables = {}
   for m in re.finditer(
       r"\n      (\w+): \{\n        Row: \{\n(.*?)\n        \}", src, flags=re.S
   ):
       cols = re.findall(r"^\s{10}(\w+)\??:", m.group(2), flags=re.M)
       tables[m.group(1)] = set(cols)
   print(len(tables), "tables")
   ```

   The pattern depends on the generator's indentation: 6 spaces for the table,
   8 for `Row`, 10 for a column. If it prints 0 tables, fix the indents. Do not
   conclude that there are no tables.

3. For each query you suspect, list every column it names: the
   `.select("a, b")` list, and the columns in `.eq()`, `.in()`, `.order()` and
   inside `.or("x.eq.true,y.eq.<id>")`. Then compare:

   ```python
   checks = {"<table>": "col_a, col_b, col_c"}  # table -> columns the code names
   for t, cols in checks.items():
       want = [c.strip() for c in cols.split(",")]
       if t not in tables:
           print(t, "TABLE NOT IN GENERATED TYPES")
           continue
       print(t, "missing:", [c for c in want if c not in tables[t]] or "none")
   ```

   A column that is missing from `Row` means the query fails every time. Check
   the filters as well as the select list: an `.or()` that names a column the
   table lacks fails the whole query even when the select list is right.

4. Read the lines to confirm the code drops the error. Then find what calls
   the function, so that you can say which screen is affected.

What this proves: the code disagrees with the generated types. It does not
query the live database, and generated types can be stale. Report which file
you compared against and the date of its last commit.

### 2. Who can call each Edge Function

Build one row per function from `supabase/functions/<name>/index.ts`:

- Does it create a client with the service-role key?
- Does it establish the caller in code? Look for `auth.getUser`, `getClaims`, a
  per-resource access helper, or a shared secret compared on the server.
- Is it listed with `verify_jwt = false` in `supabase/config.toml`?

```bash
for f in supabase/functions/*/index.ts; do
  svc=$(grep -cE 'SERVICE_ROLE' "$f")
  caller=$(grep -cE 'auth\.getUser|getClaims' "$f")
  echo "$f service_role=$svc caller_check=$caller"
done
grep -nB1 'verify_jwt *= *false' supabase/config.toml
```

A grep count is a lead and not a finding. A function may check its caller in a
shared helper, so read every function the table flags before you report it, and
say how many you read in full.

What the gateway check gives you: with JWT verification on, the platform
"validates the JWT before your handler runs" (Supabase docs). That does not
tell the function which user is calling, or whether that user may touch the
resource named in the request. The function must establish both itself. Whether
a request that carries only the project's public key passes the gateway depends
on the key type and the platform version. Test it on the project in question,
with the owner's consent. Do not assume either answer.

Red flags, worst first:

1. `verify_jwt = false`, a service-role client, and a table name or rows taken
   from the request body, with no caller check. That is an unauthenticated
   write to any table. Leftover import and migration helpers look like this.
2. A service-role client with no caller check, behind the gateway check only.
3. An endpoint that mints tokens for a third-party service with no caller
   check. It is worse when it falls back to returning the long-lived key if the
   short-lived token cannot be minted.
4. A paid upstream call, such as a model or a speech service, with no caller
   check. Anyone who can reach the function spends the owner's credit.

### 3. Deployed or not, without invoking

A CORS preflight shows whether a function of that name exists on the project
and does not run the function's logic. Read the source first: the handler must
return early on `OPTIONS`, before it reads the body or touches the database.

```bash
for fn in <suspect-function> <known-deployed-function> zz-does-not-exist-control; do
  code=$(curl -s -o /dev/null -m 15 -w '%{http_code}' -X OPTIONS "$SUPABASE_URL/functions/v1/$fn")
  echo "$fn -> $code"
done
```

- A deployed function answers 200 or 204 from its own `OPTIONS` branch.
- A name that does not exist answers 404.
- Run both controls in the same run. Without the made-up name you cannot tell
  "deployed" from "the gateway answers every preflight". Without the
  known-deployed name you cannot tell "not deployed" from "blocked on my
  network".

Send no credentials and no body.

What this proves: a function of that name is deployed. It does not prove that
the deployed code equals the code in the repo.

### Judgement

- Do not send the request that would prove a hole on a system you do not own.
  The source, the config and the preflight result are enough to report. The
  owner can confirm the rest.
- Deleting a function from the repo may not undeploy it. Where the platform
  that deploys the project does not apply pushes made outside it, the function
  stays live and its source is gone from the repo, which is worse. Have it
  removed through whatever deploys it, then repeat the preflight and expect
  404.
- If a write hole has been open for some time, tell the owner to review the
  role and permission tables for rows they do not recognise.

## Verification

- Check 1: another person can reproduce the missing-column list from the types
  file and the quoted query lines.
- Check 2: you read each reported function in full.
- Check 3: in one run, the suspect and the known-deployed control answer 200 or
  204, and the made-up control answers 404.

## Example

All names here are placeholders.

A function that builds a prompt from rule tables contained:

```ts
const [{ data: tone }, { data: notes }] = await Promise.all([
  admin.from("tone_rules").select("label, advice").limit(20),
  admin.from("coach_notes").select("title, body").eq("enabled", true).limit(15),
]);
```

The generated types gave `tone_rules` the columns `pattern`, `weight` and
`kind`, and gave `coach_notes` the columns `payload` and `status`. Every column
the code named was missing, both loads returned `data: null`, and the code went
on with an empty rules block. The screen that called the function ran with none
of its rules.

In the same repo, `supabase/config.toml` set `verify_jwt = false` for a short
helper that took a table name and rows from the request body and upserted the
rows with a service-role client. Nothing in the repo called it. The preflight
run was:

```text
import-helper -> 200
public-form -> 200
zz-does-not-exist-control -> 404
```

The report gave the source lines, the config entry and those three status
codes. No request was sent to the helper's write path.

## Notes

- How far this was verified in November 2026: check 1 statically against
  generated types, on a project where three rule loads named columns the types
  did not have. Check 2 statically, with three flagged functions read in full.
  Check 3 live, with both controls; a function with default JWT verification
  answered the preflight without credentials. Not tested: whether the gateway
  accepts a request that carries only the project's public key.
- A wrong column name is a compile error only when the client is typed. Check
  whether the functions create the client with the `Database` generic and
  whether anything type-checks them at all. If not, the compiler says nothing.
- Projects on legacy JWT keys and projects on the newer publishable and secret
  keys may behave differently at the gateway. Record which kind the project
  uses, from the key's prefix, and never print the key.

## References

- [Securing Edge Functions](https://supabase.com/docs/guides/functions/auth),
  Supabase docs, fetched 2026-11-15.
- [PostgREST error codes](https://supabase.com/docs/guides/api/rest/postgrest-error-codes),
  Supabase docs, fetched 2026-11-15.
