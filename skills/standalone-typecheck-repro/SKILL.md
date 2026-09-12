---
name: standalone-typecheck-repro
description: |
  Verify a TypeScript change compiles without installing a huge monorepo's
  node_modules, and avoid reading a crashed compiler invocation as a clean
  typecheck. Use when: (1) you edited TS in an Nx/Angular/Turborepo workspace
  that has no node_modules and `npm ci` is slow or blocked by a node engine
  mismatch, (2) CI failed with a type error like TS2352/TS2322/TS2345 and you
  need to confirm a fix before re-pushing, (3) you are about to "verify" a
  compiler or linter by grepping its output for an error pattern. Covers
  reconstructing a minimal type graph, pinning the compiler to the repo's
  version, the orig/broken/fixed three-variant check, and the exit-code
  discipline that keeps a crashed tool from reading as a pass.
author: Claude Code
version: 1.0.0
date: 2026-09-11
---

# Standalone typecheck repro

## Problem

You changed TypeScript in a large monorepo, the working copy has no
`node_modules`, and a full install is slow, or fails because the repo pins a
node version you do not have. Skipping the typecheck and letting CI find the
error costs 25-30 minutes per attempt and burns reviewer trust when the push
is red.

The second, worse failure is verifying badly: running a compiler through a
pipe and grepping its output for `error TS`. If the compiler never started,
there is no output to match, the grep finds nothing, and the crash reads as a
pass.

## Context / Trigger conditions

- A fresh `git worktree` with no `node_modules` (worktrees do not share it).
- `npm ci` would take many minutes, or `package.json` `engines.node` does not
  match the local runtime (e.g. repo wants `^22.11.0`, local is `v24.2.0`).
- CI reported a type error and you want to confirm a fix before re-pushing.
- Any moment you are about to write `<tool> ... | grep -E "error|TS[0-9]+"`
  and treat "no match" as success.

## Solution

### 1. Never infer success from absent output

Capture the tool's own exit status, not a pipeline's.

```bash
# WRONG - $? is grep's status, and a crashed tool prints nothing to match
tsc --noEmit file.ts | grep -E "TS[0-9]+"
echo "exit=$?"

# RIGHT - redirect, then check the tool's status, then read the file
tsc --noEmit file.ts > out.txt 2>&1
echo "tsc exit=$?"
head -20 out.txt
```

A passing typecheck and a compiler that never launched look identical through
a grep. They differ in exit code: `0` vs anything else.

### 2. Get a real compiler binary

`npx -y <pkg> <bin>` fails when the binary name is not what the package
resolves to, and the failure is an npm message, not a compiler one:

```
npm error could not determine executable to run
```

Use `npx -y -p <pkg> <bin>`, or just install into a scratch directory, which
is more reliable and lets you pin the repo's version:

```bash
mkdir -p /tmp/tsrepro && cd /tmp/tsrepro
npm install --silent --no-audit --no-fund typescript@5.4   # match package.json
./node_modules/.bin/tsc --version                          # PROVE it runs
```

Always print the version. That single line separates "compiler ready" from
"npm printed an error and I did not read it".

### 3. Reconstruct the minimal type graph

Copy the real declarations the failing expression depends on — the class or
interface being cast to, and anything structural it references. Stub the rest;
imports that do not participate in the type relation can be one-line
placeholders.

```ts
// types.ts - real shapes copied verbatim, unrelated imports stubbed
export enum RecordType { Person = 'Person' }
export interface DialogConfig { x?: number }      // stub, not load-bearing

export class Config {                              // real, load-bearing
  id: string;
  toJson<T extends Config>(): T { /* ... */ }
}

export class AppState {
  config = new Config();
  dialogConfig: DialogConfig;
}
```

Fidelity matters only for types the error message names. If CI said
`Type '{ a: X }' is missing the following properties from type 'Y': url, toJson`,
then `Y` must be copied exactly; everything else can be stubbed.

### 4. Use the repo's compiler options

Read them out of `tsconfig.base.json` (or the nearest tsconfig) rather than
guessing. Guessed flags — especially `strict`, `strictNullChecks`, and
`useDefineForClassFields` — change whether the error reproduces at all.

```bash
python3 -c "
import json,re,io
s=re.sub(r'//.*','',io.open('tsconfig.base.json',encoding='utf-8').read())
co=json.loads(s).get('compilerOptions',{})
for k in sorted(co):
    if k!='paths': print(k,'=',co[k])
"
```

### 5. Run three variants, not one

```
orig    - the code as it is on the base branch     -> must exit 0
broken  - the change that CI rejected              -> must reproduce CI's exact error
fixed   - the proposed fix                         -> must exit 0
```

`broken` is the important one. If it does not reproduce the CI error, the
repro is not faithful and `fixed` passing proves nothing. Only once `broken`
fails with the same error code and message does a green `fixed` mean anything.

### 6. Runtime behavior is a separate question

A typecheck says the code compiles, not that it is correct. If the change has
behavior (a branch, a merge, a copy-vs-alias), also run the old and new bodies
as plain JS with assertions. Type-correct and behavior-correct are independent
failures.

## Verification

The repro is trustworthy when all three hold:

- `orig` exits `0`
- `broken` exits non-zero **and** its message matches CI's, error code included
- `fixed` exits `0`

If `broken` passes, stop and widen the repro before trusting anything.

## Example

CI reported:

```
reducer.ts:176:14 - error TS2352: Conversion of type
'{ config: { items: any[]; }; ... }' to type 'AppState' may be a
mistake because neither type sufficiently overlaps with the other.
```

Repro with `typescript@5.4` and the repo's flags reproduced it byte-for-byte
and added the line CI had truncated:

```
Type '{ items: any[]; }' is missing the following properties
from type 'Config': id, toJson
```

That extra line named the fix. Total cost: under two minutes, versus a 25-30
minute CI round trip that would have shown less.

## Notes

- Git worktrees do not share `node_modules` with the main checkout. A fresh
  worktree always starts without one.
- This technique suits type-level errors, which are local. It does not suit
  errors that depend on real module resolution, path aliases, or generated
  code — install for those.
- The scratch directory is disposable. Do not commit it, and keep it out of
  the repo so it cannot be picked up by a workspace glob.
- The general rule outlives TypeScript: any verification that treats absent
  output as success will report a crashed tool as a clean run. Check the exit
  code of the tool itself.
