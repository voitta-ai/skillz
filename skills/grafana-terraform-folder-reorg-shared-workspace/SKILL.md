---
name: grafana-terraform-folder-reorg-shared-workspace
description: |
  Move, rename, nest or retire Grafana folders with the grafana terraform provider
  (v4) when more than one terraform state (dev + prod, several teams) deploys into
  the SAME Grafana workspace, without losing a live dashboard. Use when: (1) a plan
  for a folder rename or re-parent shows destroy/recreate, (2) you need a new folder
  that two states both reference and the second state plans a duplicate create /
  412, (3) a `-target`ed apply silently skipped your `import` blocks, (4) a
  `grafana_dashboard` plans "must be replaced" right after you added a data source
  whose uid is only known after apply, (5) an apply that both moved dashboards out
  of a folder and removed that folder ended in
  `[POST /dashboards/db][404] postDashboardNotFound` and the dashboards are gone,
  (6) Grafana refuses a folder move with "a folder with the same name already
  exists" or a depth error. Covers the API-create-then-import pattern for shared
  folders, in-place moves, the two-apply folder retirement, pinning data-source
  uids, and before/after live snapshots via /api/search.
author: Claude Code
version: 1.0.0
date: 2026-09-10
---

# Grafana folder reorganisation with terraform, one workspace, several states

## Problem

A dashboards-as-code repo often has one Grafana workspace and more than one terraform
state writing into it (a dev state and a prod state, or several teams). Folders are
shared objects: the same `grafana_folder` uid is declared in every state that deposits
dashboards into it. Reorganising that tree (new env subfolders, renames, re-parenting,
retiring a folder) has four traps that each read as a normal plan and each cost live
dashboards or a red apply:

1. a folder `uid` change is a destroy + create, and Grafana deletes a folder's
   dashboards with the folder;
2. a NEW shared folder created by one state's apply leaves every other state planning a
   second create of an existing uid (HTTP 412);
3. `terraform apply -target=...` does not run `import` blocks, so an adoption you
   planned into a targeted apply never happens;
4. removing a folder in the same apply that moves its dashboards out runs the folder
   DESTROY before the dashboards' UPDATEs; Grafana cascade-deletes, the updates 404.

A fifth, adjacent trap: a data source whose uid is Grafana-minted is unknown at plan
time, so every dashboard that embeds it has an unknown `config_json`, and the provider's
diff logic plans those dashboards as "must be replaced".

## Context / Trigger Conditions

- Provider: `grafana/grafana` >= 4.x (`resource_folder.go`: only `uid` is `ForceNew`;
  `title` goes through UpdateFolder, `parent_folder_uid` through MoveFolder;
  `resource_dashboard.go` `CustomizeDiff` forces new when the uid parsed from the old
  and new `config_json` differ -- and an unknown new `config_json` parses to "").
- Grafana with nested folders (10.x with the `nestedFolders` toggle, 11+). `Move()`
  enforces: no circular parent, a maximum depth, and **unique sibling titles**
  (`ErrFolderSameNameExists`; assume case-insensitive, MySQL-backed instances
  collate that way). It does NOT refuse a folder that holds alert rules -- but an
  alert rule group's `folder_uid` change recreates the rules, so rule-group folders
  stay where they are.
- Symptoms in the wild: plan shows `-/+` on a folder; apply fails with 412 on a folder
  create; `Plan:` line lacks the `N to import` you expected after `-target`;
  `postDashboardNotFound` on every dashboard that was inside a destroyed folder;
  `must be replaced` on dashboards after adding a data source.

## Solution

### 0. Snapshot live before you touch anything

```bash
G=https://<grafana-host>; H="Authorization: Bearer $TOKEN"
curl -s -H "$H" "$G/api/search?type=dash-folder&limit=5000" > folders_before.json
curl -s -H "$H" "$G/api/search?type=dash-db&limit=5000"     > dashboards_before.json
```

`folderUid` on a folder row is its parent (empty = top level); on a dashboard row it is
the folder it sits in. Count top-level folders and dashboards; you will compare after.

### 1. Every move is an in-place update; never touch `uid`

- Rename: change `title`. Re-parent: set `parent_folder_uid`. Both are in-place.
- A plan line `must be replaced` on a folder means you changed its uid (or the import
  block points at a different object). Stop; a replaced folder deletes its contents.

### 2. Shared folders: create once via the API, then `import` in every state

A folder referenced by more than one state must exist before any state plans it:

```bash
curl -s -H "$H" -H 'Content-Type: application/json' -X POST "$G/api/folders" \
  -d '{"uid":"prod","title":"PROD","parentUid":"<parent-uid-or-omit>"}'
```

```hcl
resource "grafana_folder" "prod_root" {
  title             = "PROD"
  uid               = "prod"            # chosen, human-meaningful, stable
  parent_folder_uid = grafana_folder.team.uid
}
import { to = grafana_folder.prod_root  id = "prod" }
```

The import block is a no-op in a state that already holds the resource and adopts it in
one that does not. Refuse the alternative "let dev create it, import into prod later":
the prod plan is red (412) in between.

Folders only ONE state needs (a dev-only subfolder) are `count`-gated to that state, so
the other state never references them and no import dance is needed.

### 3. Check Grafana's move rules before planning the tree

- Sibling titles unique per parent, case-insensitively to be safe (`Pilot [prod]` and
  `pilot [prod]` under one parent will collide).
- Depth: `height(moved folder) + depth(new parent) + 1 <= MaxNestedFolderDepth`.
- Rule groups pin to a folder uid; do not move dashboards that must stay next to their
  rule group, or accept that the group stays in the old folder.

### 4. Retire a folder in TWO applies

1. Apply A: re-point every dashboard (`folder = <new uid>`), keep the folder resource.
2. Verify live: `GET /api/search?type=dash-db&folderUIDs=<old>` returns nothing.
3. Apply B: remove the folder resource (or `count = 0`).

Do not combine them. Terraform ordered the folder destroy before the dependents'
updates; Grafana's folder delete cascades; every subsequent update 404s
(`postDashboardNotFound`). If it already happened and the dashboards are code-owned,
rerun the apply: refresh sees 404, the resources are recreated. Hand-built dashboards
are gone for good (unless a backup / version export exists). `prevent_destroy_if_not_
empty = true` on the folder makes the provider refuse the delete while it is non-empty.

### 5. `-target` skips `import` blocks

A targeted plan/apply shows no `N to import` even when the targeted resource has an
import block; the import lands on the next untargeted plan. Harmless, but do not read
the missing import as "already in state", and do not expect a targeted apply to adopt.

### 6. Pin the uid of any data source dashboards embed

```hcl
resource "grafana_data_source" "amp_west" {
  name = "eks-amp-us-west-1-${var.env}"
  uid  = "eks-amp-us-west-1-${var.env}"   # known at plan time
  ...
}
```

Without it, `config_json` of every dashboard referencing `grafana_data_source.x.uid` is
`(known after apply)` until the data source exists, the provider's uid-diff cannot parse
the new uid, and the dashboards plan as replacements (`4 to destroy`). With the uid
pinned they are in-place updates (`0 to destroy`), and the datasource + dashboards can
land in one apply.

### 7. Verify

- One plan per state; every folder row `will be updated in-place`, `0 to destroy`
  unless you are in step 4's Apply B.
- `terraform console -var-file=<env>.tfvars` with the backend initialised evaluates
  locals against state; select only known fields (titles, query strings), because any
  expression touching an unknown attribute prints `(known after apply)`.
- After the apply, re-take the two snapshots; the dashboard count must be unchanged,
  and each top-level folder count must match the design.

## Verification

- `curl "$G/api/search?type=dash-db&limit=5000" | jq length` equals the before count.
- `GET /api/folders/<uid>` returns the expected `parentUid` for every moved folder.
- A fresh untargeted plan in every state shows only the pre-existing drift you knew
  about (no folder rows, no dashboard rows).

## Example

Two states (dev, prod) share one workspace. Goal: split a team folder into `PROD` and
`DEV` subfolders holding the env-specific instances of six dashboards.

1. Snapshot: 42 folders / 240 dashboards.
2. `POST /api/folders` for `prod` and `dev` (parent = the team folder).
3. Declare both with `import` blocks; add
   `local.env_folder = var.env == "prod" ? grafana_folder.prod_root.uid : grafana_folder.dev_root.uid`
   and point the six dashboards at it.
4. Plans: dev `0 add / N change / 0 destroy`, prod same shape. Apply dev (CI), apply
   prod targeted at the dashboards + any new data source (imports land on the next
   untargeted prod plan).
5. Snapshot again: 44 folders / 240 dashboards.

The failure that produced step 4 of the Solution: a previous iteration also removed a
now-empty intermediate folder in the same apply -- 15 dashboards deleted, 15 x 404,
recovered by rerunning the apply because all 15 were code-owned.

## Notes

- Do not let the "full apply is the default" habit apply here if the states flip-flop
  shared objects (e.g. env-templated data source uids on an env-less dashboard uid): a
  full apply from one state rewrites what the other state owns. Target what you own.
- Keep the resource NAMES stable when you change titles (`grafana_folder.campaigns_prod`
  can be titled anything); renaming addresses needs `moved` blocks and buys nothing.
- Everything above holds for Amazon Managed Grafana (10.4 measured) as well as OSS.

## References

- grafana/terraform-provider-grafana `internal/resources/grafana/resource_folder.go`
  (ForceNew on `uid`, `UpdateFolder` -> MoveFolder on parent change) and
  `resource_dashboard.go` (`CustomizeDiff` uid comparison).
- grafana/grafana `pkg/services/folder/folderimpl/folder.go` `Move()` (sibling-name,
  depth and circular-reference checks).
- Terraform `import` blocks: https://developer.hashicorp.com/terraform/language/import
