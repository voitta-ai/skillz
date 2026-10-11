---
name: neon-vercel-db-identify-and-migrate
description: |
  Identify which Neon Postgres project backs a Vercel app, and migrate/split it into
  new Neon projects (e.g. separate prod vs staging DBs). Use when: (1) you have a
  Vercel DATABASE_URL pointing at `ep-xxxx...neon.tech` but don't know which Neon
  project/account owns it, (2) the Neon project name doesn't match the repo (naming
  drift after a rename), (3) you need to clone a Neon DB to a new project and cut
  Vercel over to it, (4) `pg_dump` fails with "server version: 17.x; pg_dump version:
  16.x; aborting because of version mismatch". Covers neonctl account/org discovery,
  matching connection-string host to DATABASE_URL, the pg_dump-must-be->=-server rule,
  and a safe non-destructive cutover (dump is read-only; switch env; verify; delete last).
author: Claude Code
version: 1.0.0
date: 2026-06-14
source: https://github.com/voitta-ai/skillz
source_file: skills/neon-vercel-db-identify-and-migrate/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> `skills/neon-vercel-db-identify-and-migrate/SKILL.md`.

# Identify and migrate the Neon DB behind a Vercel app

## Problem
A Vercel app's `DATABASE_URL` points at a Neon endpoint (`ep-<slug>.<region>.aws.neon.tech`)
but you don't know which Neon **account/org/project** owns it (often because the
project was renamed and the Neon project kept the old name). You then need to clone
or split it (e.g. give staging its own DB) and cut Vercel over safely.

## Context / Trigger conditions
- `DATABASE_URL` host looks like `ep-<slug>.<region>.aws.neon.tech`.
- `neonctl projects list` is empty under the first account you try (wrong account).
- Neon project name != repo name (e.g. repo `my-app`, Neon project `old-name`).
- `pg_dump` aborts: `server version: 17.x; pg_dump version: 16.x` (Neon runs PG17+).

## Solution

### A. Find the owning Neon project (account may not be obvious)
1. `neonctl auth` (interactive browser OAuth) — try each likely account/email; the DB
   may be under a *different* account than your default. `neonctl me` shows the email;
   `neonctl orgs list` shows orgs (`projects_limit: 0` on personal means projects live
   under an org -> pass `--org-id`).
2. `neonctl projects list --org-id <org>`. To confirm WHICH project is the app's DB,
   match the connection-string host to the Vercel `DATABASE_URL` host:
   ```
   neonctl connection-string --project-id <pid> --org-id <org>   # compare the ep-... host
   ```
   A "compute last active" timestamp that moves when you hit the live app is a strong
   confirmation too.

### B. Use a pg_dump that matches the server major version
`pg_dump` REFUSES a server newer than itself. Neon runs PG17+, so install/use a
v17 client (macOS: `brew install postgresql@17`; use
`/opt/homebrew/opt/postgresql@17/bin`). Verify with `pg_dump --version`.

### C. Safe, non-destructive migration + cutover
The dump is read-only on the source; the only "switch" is the Vercel env var.
```
neonctl projects create --name <new> --org-id <org> --region-id <region>
SRC=$(neonctl connection-string --project-id <old> --org-id <org>)
DST=$(neonctl connection-string --project-id <new> --org-id <org>)
pg_dump "$SRC" --no-owner --no-acl -Fc -f /tmp/db.dump
pg_restore --no-owner --no-acl -d "$DST" /tmp/db.dump
# verify row counts match, then switch Vercel env (values piped, not printed):
vercel env rm DATABASE_URL production -y
printf '%s' "$DST" | vercel env add DATABASE_URL production
# redeploy production; verify; ONLY THEN delete the old project.
```
Use `--no-owner --no-acl` so the default `neondb_owner` role in the fresh project
doesn't cause restore errors.

## Verification
- Same row counts across source and destination:
  `psql "$URL" -tAc "select count(*) from \"User\";"` on each.
- After cutover, a DB-backed API endpoint returns valid JSON (not a 500). A live
  write (e.g. a record's flag flips) appearing in the NEW project proves the app
  reads/writes it.

## Notes
- **Don't delete the old project until the new one is verified live.** The dump
  doesn't modify the source, so you can roll back by pointing `DATABASE_URL` back.
- An "empty" Neon account (org with 0 projects) just means wrong account — keep trying
  logins; one account can be reached via multiple providers (google vs keycloak) which
  Neon treats as separate accounts.
- Vercel runtime injects env per **environment tier** (Production/Preview), so set
  `DATABASE_URL` on each tier separately to isolate prod vs staging DBs.
- A literal `\n` (backslash-n) accidentally stored in a Vercel env value is a real
  failure mode — inspect with `... | od -c` to catch hidden chars.

## References
- neonctl: https://neon.tech/docs/reference/neon-cli
- Neon branching (alternative to separate projects): https://neon.tech/docs/introduction/branching
- pg_dump version compatibility: https://www.postgresql.org/docs/current/app-pgdump.html
