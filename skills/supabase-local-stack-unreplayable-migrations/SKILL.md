---
name: supabase-local-stack-unreplayable-migrations
description: |
  Build a local Supabase stack from a repo whose migration history does not
  replay on an empty database. Use when: (1) `supabase start` or `db reset`
  stops with `MigrationApplyError` on a foreign key or on "column ... contains
  null values"; (2) the migrations, often written by an AI app builder, mix
  schema changes with data changes; (3) you must show that the local schema
  equals production's and you have no access to production. Covers a
  migration-free `--workdir`, applying the history in replica mode as
  `postgres`, a retry rule for data-dependent constraints, missing platform
  roles, objects created twice, a column-level check against the generated
  types, seeding from a JSON row snapshot with a count check, and a smoke
  check that refuses a non-local URL.
author: Claude Code
version: 1.0.0
date: 2026-11-15
source: https://github.com/voitta-ai/skillz
source_file: skills/supabase-local-stack-unreplayable-migrations/SKILL.md
---

# Local Supabase stack from migrations that do not replay

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/supabase-local-stack-unreplayable-migrations/SKILL.md`).

## Problem

A project has one backend, production, and you need a local copy to try a
change. The repo has a full `supabase/migrations/` directory, so
`supabase start` should build the database. It does not. The history was
written against a live database, by a tool that mixed schema changes with data
changes, and it only ever ran forward on that one database. On an empty
database it fails part of the way through.

The CLI gives you no way to skip or repair the replay at start. This skill
replays the history outside the CLI and then proves, column by column, that the
result is the schema production is believed to have.

## Context / Trigger Conditions

- `supabase start` or `supabase db reset` ends with `MigrationApplyError`.
  Typical messages: `insert or update on table "x" violates foreign key
  constraint` with a key that "is not present in table", and later
  `column "y" of relation "x" contains null values`.
- Many migration files contain `insert`, `update` or `delete` beside the DDL.
  In the session that produced this skill, 55 of 107 did.
- The repo commits a generated `Database` types file. It is the only copy of
  the production schema that a clone can read.
- You have no credentials for the production database, or you must not use
  them.

## Solution

Checked with the Supabase CLI 3.1.0 run through `npx`, Docker from Rancher
Desktop, on 2026-11-15. Flag names differ between CLI major versions, so read
`--help` first.

Two helpers are used below. `SB` is the CLI with a fixed work directory, and
`psql_db` runs psql inside the database container as the superuser. The
password is the stock one of the local stack.

```bash
PROJECT_ID="myapp-local"
SB="npx --yes supabase@3.1.0 --workdir .local-stack"
psql_db() {
  docker exec -i -e PGPASSWORD=postgres "supabase_db_${PROJECT_ID}" \
    psql -q -h 127.0.0.1 -U supabase_admin -d postgres "$@"
}
```

1. Give the CLI a work directory that has no migrations. `start` has no flag
   that skips them, and it replays whatever it finds in `supabase/migrations/`.
   The generated directory holds a copy of the config with a local
   `project_id`, and a symlink to the real functions, so the edge runtime
   serves the code you edit. Ignore the directory in git.

   ```bash
   mkdir -p .local-stack/supabase
   sed -E "s/^project_id *=.*/project_id = \"$PROJECT_ID\"/" supabase/config.toml \
     > .local-stack/supabase/config.toml
   ln -sfn ../../supabase/functions .local-stack/supabase/functions
   $SB start -x realtime,imgproxy,logflare,vector,supavisor
   ```

   Every later CLI call (`status`, `stop`) needs the same `--workdir`. A call
   without it works on the real `supabase/` directory and writes a
   `supabase/.temp/` there.

2. Apply the history yourself, one transaction per file. Replica mode skips
   foreign-key checks and triggers, so a row that points at a production-only
   row is accepted. `set role postgres` makes `postgres` the owner of what the
   files create, as it is on the hosted platform. Record each applied file in a
   marker table, so that a second run skips it.

   ```bash
   psql_db -v ON_ERROR_STOP=1 -c "create schema if not exists local_stack;
     create table if not exists local_stack.applied (name text primary key);"

   run_migration() {
     psql_db -v ON_ERROR_STOP=1 -1 \
       -c "set session_replication_role = replica" -c "set role postgres" -f - < "$1"
   }
   ```

   If the repo has a second migration directory from a later tool, apply it
   after the first, in its own order.

3. Add one retry rule. A file can still fail on a constraint: an earlier file
   inserted rows, a backfill in between needed production rows and changed
   nothing, and a later file sets `NOT NULL`. The rows that are in the way are
   in tables that the seed (step 7) reloads anyway. Empty those tables and run
   the file once more. Use `delete` in replica mode, not `truncate`: `truncate`
   refuses a table that another table references.

   ```sql
   set session_replication_role = replica;
   do $$ begin
     if to_regclass('public."plan_questions"') is not null then
       delete from public."plan_questions";
     end if;
   end $$;
   ```

   Emit one such block per seed table. The `to_regclass` test matters because
   an early file runs before some of those tables exist.

4. Create the roles of the hosting platform that the history grants to. List
   the role names that follow `TO` and `FROM` in `GRANT`, `REVOKE` and
   `CREATE POLICY`, and compare them with `select rolname from pg_roles`.
   Create each missing one as `nologin` before step 2. The error that tells
   you one is missing is `role "..." does not exist`.

5. Watch for an object that the history creates twice, with no drop in
   between. In the session it was a trigger on `auth.users`: an early file
   created it and a much later file created it again. That means production
   had lost it in between. The cause was not established. Drop the object once,
   after the files that precede the second creation, and record that in the
   marker table so that a re-run does not drop it again.

6. Check the result against the committed types, at column level. Read the
   database, not the output of `gen types`: in CLI 3.x that output is
   unformatted and does not parse the same way as the committed file.

   List views as well as tables: the generated types carry a `Row` for both,
   so a query limited to base tables reports every view column as missing.

   ```bash
   psql_db -tA -c "select table_name || '.' || column_name
     from information_schema.columns where table_schema = 'public'" \
     | python3 check_schema.py src/integrations/supabase/types.ts
   ```

   ```python
   import re, sys
   text = open(sys.argv[1]).read().split("\n  public: {", 1)[1]
   committed = set()
   pattern = r"\n      (\w+): \{\n        Row: \{\n(.*?)\n        \}"
   for m in re.finditer(pattern, text, flags=re.S):
       for col in re.findall(r"^\s{10}(\w+)\??:", m.group(2), flags=re.M):
           committed.add(m.group(1) + "." + col)
   local = set(line.strip() for line in sys.stdin if line.strip())
   for name in sorted(committed - local):
       print("only in the committed types: " + name)
   for name in sorted(local - committed):
       print("only in the local database: " + name)
   sys.exit(1 if committed ^ local else 0)
   ```

   The regular expressions rely on the two-space layout of the committed file.
   A check on table names alone is not enough. In the session every table name
   matched, and this check then found three columns that production has and no
   migration creates. Add such columns with `add column if not exists`, and say
   that their types and defaults are inferred from the types file and from the
   code that reads them.

7. Seed from the row snapshot that the repo carries, if it has one. Name only
   the columns the snapshot holds, so that defaults fill the rest. Use one
   transaction per table: when the insert fails, the delete is undone and the
   table keeps what the migrations put there.

   ```sql
   set session_replication_role = replica;
   begin;
   delete from public."plans";
   insert into public."plans" ("id", "name", "status")
   select "id", "name", "status"
   from jsonb_populate_recordset(null::public."plans", $seed$[ ...rows... ]$seed$::jsonb);
   commit;
   ```

   Run the seed without `ON_ERROR_STOP`, so that one bad table does not stop
   the others, and end it with a query that lists every table whose row count
   differs from the snapshot. No rows means every table loaded. A required
   column that the snapshot leaves out, such as an owner id, makes that table
   fail; fill it in before you generate the SQL.

8. Create one local admin through the auth admin API, not with SQL. Read
   `API_URL`, `ANON_KEY` and `SERVICE_ROLE_KEY` from `$SB status -o env`. When
   the seeded rows cite one user id, pass that id, so that the rows belong to a
   user that exists.

   ```bash
   curl -s -X POST "$API_URL/auth/v1/admin/users" \
     -H "apikey: $SERVICE_ROLE_KEY" -H "Authorization: Bearer $SERVICE_ROLE_KEY" \
     -H 'Content-Type: application/json' \
     --data '{"id":"<id the rows cite>","email":"admin@local.test","password":"<local password>","email_confirm":true}'
   ```

   Then give that user the admin row in the app's own roles table.

9. Point the frontend at the local API with a git-ignored override file. For a
   Vite app that is `.env.local`, which wins over a committed `.env`.

10. End with a smoke check, and make it refuse a URL that is not on
    `127.0.0.1` or `localhost`, so that it cannot be aimed at production. It
    signs in (`POST /auth/v1/token?grant_type=password`), reads a few seeded
    tables as the admin through PostgREST (`HEAD` with `Prefer: count=exact`
    and `Range: 0-0`, then the number after the slash in `Content-Range`),
    checks that the same read with no user returns zero rows, and calls one
    edge function.

## Verification

Stop the stack and delete its data with `$SB stop --no-backup`, remove the
generated directory, and run the whole procedure once. It is done when all of
these hold on that one run:

- every migration file is applied, with only the retries you expect;
- the column check prints no difference and exits 0;
- the count check after the seed lists no table;
- the smoke check passes, including the read with no user.

In the session the run from nothing applied 132 files with one retry, matched
79 tables and 993 columns, loaded 36 tables and took 41 seconds with the
images already downloaded. A browser sign-in then loaded a seeded screen with
every backend request answered by the local stack.

## Example

A migration inserts rows into `plan_questions` with a hard-coded `plan_id`.
That plan was created through the app, so it exists only in production, and
the replay stops on the foreign key. Replica mode lets the rows in. Forty
files later a migration backfills `plan_questions.topic_id` from a join that
finds nothing locally and then sets the column `NOT NULL`, which fails. The
retry rule empties `plan_questions`, the file applies, and step 7 reloads the
table from the snapshot. A later file grants on a table to `platform_exec`, a
role that only the hosting platform has; step 4 creates it.

## Notes

- "Matches production" here means "matches the committed generated types". No
  production database was queried. If the types file is stale, so is the
  claim.
- The CLI 3.x follows `import` lines that sit inside comments. A comment that
  shows an example import of a file that does not exist stops `start` with
  `failed to read file`. Reword the comment.
- `brew install supabase/tap/supabase` refused with "Your Command Line Tools
  are too outdated". `npx --yes supabase@<version>` needed no system change.
- The first image pull can log `toomanyrequests: Rate exceeded` several times
  and still finish.
- `start` already serves the edge functions at `/functions/v1`. A function
  that reads a secret fails until you supply one. Functions that call a model
  were not run locally in the session.
- The stock local password and the local admin password are defaults of a
  throwaway stack. Do not reuse a real credential for either.
- Rows that the migrations insert into tables outside the snapshot stay as the
  replay left them, with foreign keys unchecked. Treat them as scaffolding.

## Related

- `supabase-edge-function-repo-audit` - auditing the same kind of repo for
  queries that fail silently, missing caller checks and deployed functions.
