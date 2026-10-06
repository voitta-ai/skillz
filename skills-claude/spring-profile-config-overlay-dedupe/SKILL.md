---
name: spring-profile-config-overlay-dedupe
description: |
  Strip an `application-<profile>.yml` down to the values that actually differ from
  `application.yml`, and prove the change altered nothing. Use when: (1) a Spring Boot or
  Grails repo has profile configs that are near-copies of the base config and you cannot tell
  which lines are real overrides, (2) you are about to change a value in the base config and
  need to know which profiles silently inherit it, (3) a staging/production config drifted
  because someone edited one copy of a duplicated key, (4) you want to delete config
  duplication but cannot risk changing runtime behaviour, (5) you need to decide whether a
  duplicated value should be deleted or deliberately kept. Covers the flatten-and-diff
  verification, confirming profiles really are layered before trusting it, and the case where
  keeping a duplicate is the correct call.
author: Claude Code
version: 1.0.0
date: 2026-08-19
---

# De-duplicate Spring profile configs, and prove the strip changed nothing

## Problem

Spring Boot loads `application.yml` first, then layers `application-<profile>.yml` on top,
merging **per property key** rather than per YAML node. Any key in a profile file whose value
equals the base value is therefore inert — it does nothing except make the file longer and
create a second place to edit.

Left alone this rots in a specific way: someone updates a value in one file, the other copy
keeps the old value, and now two environments disagree for reasons nobody can see by reading
either file. Real numbers from one Grails service: the staging profile carried 128 keys of
which **118 were byte-identical to the base**, and production carried 142 of which 55 were.

The reason people don't clean it up is that a config file is scary to delete from — the
failure mode is a service that starts and then behaves subtly wrong. The fix is to make the
change *verifiable* rather than to eyeball it.

## Context / Trigger Conditions

- `application.yml` plus `application-staging.yml` / `application-production.yml` (or any
  profile names) that look like near-copies.
- You are about to change a base value and want to know who inherits it.
- Two environments differ and neither file explains why.

## Solution

### 1. Confirm the files really are layered

Do not assume. Spring's overlay behaviour depends on the profile actually being activated, and
some deployments pass an explicit config location that replaces rather than supplements the
base. Find the activation and read it:

```bash
grep -rn "SPRING_PROFILES_ACTIVE\|spring.profiles.active\|spring.config" \
  deploy/ .deploy/ helm/ k8s/ Dockerfile* 2>/dev/null
```

You want something like `SPRING_PROFILES_ACTIVE: staging` per environment. If instead you find
`--spring.config.location=...` pointing at a single file, the base is **not** merged and none
of this applies.

Grails note: separate `application-<env>.yml` files mean Spring profile loading, not the
classic Grails `environments:` block inside one file. Both can appear in the same codebase.

### 2. List what is actually inert

Flatten each file to dotted keys and compare:

```bash
python3 - <<'PY'
import yaml, io

def flat(d, p=''):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flat(v, f"{p}.{k}" if p else str(k)))
    else:
        out[p] = d
    return out

def load(path):
    m = {}
    for doc in yaml.safe_load_all(open(path)):   # multi-document files are common
        if doc:
            m.update(flat(doc))
    return m

base = load('src/main/resources/application.yml')
for prof in ['staging', 'production']:
    d = load(f'src/main/resources/application-{prof}.yml')
    same = [k for k in d if k in base and base[k] == d[k]]
    over = [k for k in d if k in base and base[k] != d[k]]
    new  = [k for k in d if k not in base]
    print(f"\n### {prof}: {len(d)} keys | inert {len(same)} | overrides {len(over)} | new {len(new)}")
    for k in sorted(over): print(f"  OVERRIDE {k}: {base[k]!r} -> {d[k]!r}")
    for k in sorted(new):  print(f"  NEW      {k} = {d[k]!r}")
PY
```

Rewrite each profile file to contain only the OVERRIDE and NEW keys.

### 3. Prove the effective config is unchanged

This is the step that makes the edit safe. Merge base + profile *before* and *after*, and diff
the resulting key sets. Anything lost, added, or changed is a bug in your rewrite:

```bash
python3 - <<'PY'
import yaml, io, subprocess

def flat(d, p=''):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(flat(v, f"{p}.{k}" if p else str(k)))
    else:
        out[p] = d
    return out

def merge(text):
    m = {}
    for doc in yaml.safe_load_all(io.StringIO(text)):
        if doc:
            m.update(flat(doc))
    return m

old = lambda p: subprocess.run(['git','show',f'HEAD:{p}'],capture_output=True,text=True).stdout
new = lambda p: open(p).read()
BASE = 'src/main/resources/application.yml'

ok = True
for prof in ['staging', 'production']:
    pp = f'src/main/resources/application-{prof}.yml'
    before = {**merge(old(BASE)), **merge(old(pp))}
    after  = {**merge(new(BASE)), **merge(new(pp))}
    lost    = {k: before[k] for k in before if k not in after}
    changed = {k: (before[k], after[k]) for k in before if k in after and before[k] != after[k]}
    added   = {k: after[k] for k in after if k not in before}
    if lost or changed or added:
        ok = False
    print(f"{prof}: {len(before)} effective keys -> {'IDENTICAL' if ok else 'DIFFERS'}")
    for k, v in lost.items():          print(f"   LOST    {k} = {v!r}")
    for k, (a, b) in changed.items():  print(f"   CHANGED {k}: {a!r} -> {b!r}")
    for k, v in added.items():         print(f"   ADDED   {k} = {v!r}")
print("\nRESULT:", "no behavioural change" if ok else "REVIEW NEEDED")
PY
```

Parsing both files is itself part of the check — a YAML syntax error fails here rather than at
service startup.

## Verification

The script prints `IDENTICAL` for every profile and `no behavioural change`. Quote the
effective key counts in the commit message; they are what a reviewer needs to trust a diff
that deletes a couple of hundred lines.

## Notes

- **Sometimes the duplicate should stay.** If the base value is about to change underneath the
  profile, an inherited value silently follows it. Concretely: a base pointing at a production
  endpoint that is about to be repointed at a dev endpoint for the staging cutover — delete the
  production override as "duplicate" and production quietly follows the base to dev. Keep those
  explicit and put the reason in a comment, or the next person deletes them again as noise.
- Related, keep credential/endpoint blocks whole. Splitting `keyID` / `bucket` / `blobName`
  across two files so only the differing lines remain is technically correct and much harder to
  read; the block is a unit.
- **Lists do not merge.** Spring replaces a whole list, so a list in a profile file is always a
  full override even when it looks identical. The flatten above treats a list as one leaf value,
  which is the right semantics for this comparison.
- Watch for keys that are identical in *every* profile but absent from the base. Those belong in
  the base, but hoisting them changes local/dev behaviour — a separate decision, not part of a
  no-op cleanup.
- Multi-document YAML (`---` separators) is common in Grails configs; iterate `safe_load_all`
  and merge, or you will silently compare only the first document.
