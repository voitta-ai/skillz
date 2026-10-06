---
name: terraform-check-block-warn-only-ci-gate
description: |
  Make Terraform `check` blocks actually fail CI. Use when: (1) you wrote a
  check block to guard an invariant (e.g. a set of secret values must be
  pairwise distinct) and discovered `terraform plan` prints the failure as a
  Warning and exits 0, so the CI plan step stays green, (2) you are
  reviewing a PR that encodes a safety guard as a check block and need to
  know whether anything enforces it, (3) you need a guard over sensitive
  values whose failure message must name the offending items without
  leaking them. Core facts: check blocks are advisory by design - failed
  assertions never affect plan/apply exit status, so a guard written as one
  is silent by construction; the working CI gate is `set -o pipefail` +
  `tee` the plan output + grep for "Check block assertion failed" and exit
  1; write the error_message to name offenders via nonsensitive() applied
  to KEYS only, never values. Proven end to end: a forced collision exits 1
  and names the colliding pair with no values leaked; the passing path
  leaves plan behavior unchanged.
author: Claude Code
version: 1.0.0
date: 2026-08-27
source: https://github.com/voitta-ai/skillz
source_file: skills/terraform-check-block-warn-only-ci-gate/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/terraform-check-block-warn-only-ci-gate/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

# Terraform check blocks warn and exit 0 - gate CI on them explicitly

## Problem

You encode an invariant as a `check` block - say, listener rules match on
per-service secret tokens, and two services sharing one token value would
silently shadow each other, so the values must be pairwise distinct:

```hcl
check "auth_tokens_distinct" {
  assert {
    condition = length(distinct([
      for k, v in local.auth_tokens : sha256(v)
    ])) == length(local.auth_tokens)
    error_message = join(" ", [
      "Two callers share one token value; the pair(s):",
      join(", ", [
        for pair in local.colliding_pairs : pair   # built from nonsensitive KEYS
      ]),
      "Each caller must have a distinct secret."
    ])
  }
}
```

`terraform plan` duly reports the violation - as a **Warning** - and exits
**0**. Every CI pipeline that gates on the plan step's exit code stays
green. The guard you shipped protects nothing: **a check block is silent
by construction.**

This is by design: check blocks (Terraform 1.5+) are advisory
post-evaluation assertions. Unlike variable `validation` and resource
`precondition`/`postcondition` blocks - which hard-fail - a failed check
never affects the exit status of `plan` or `apply`.

## When a check block is still the right tool

Preconditions must hang off a resource or data source; a cross-object
invariant (pairwise distinctness across several data sources, an
environment-wide consistency rule) has no single natural host. A check
block - which may scope its own data sources - is the idiomatic place.
You just have to supply the teeth yourself.

## The CI gate

Wrap the plan step so the warning text becomes a hard failure:

```yaml
- name: Terraform plan (hard-fail on check blocks)
  run: |
    set -o pipefail
    terraform plan -input=false -var-file=env/dev.tfvars 2>&1 | tee /tmp/plan.out
    if grep -q "Check block assertion failed" /tmp/plan.out; then
      echo "::error::a terraform check block failed - see plan output above"
      exit 1
    fi
```

- `set -o pipefail` keeps a genuinely failing plan failing (the `tee`
  would otherwise mask its exit code).
- `tee` preserves the full plan in the job log, so the failure message -
  which names the offenders - is right there.
- The grep target `Check block assertion failed` is Terraform's own
  diagnostic summary line for a failed check assertion.

Proven end to end on a real pipeline:

- **Passing path:** the wrapper changed nothing - plan succeeded, apply
  proceeded.
- **Failure path** (forced by pointing two entries at one secret): exit
  code 1, and the message named the colliding pair (`service-a +
  service-b`) with **no secret values in the output**.

## Naming offenders without leaking them

The values under test are `sensitive` (secret data sources), and a naive
`error_message` interpolating them would either error ("sensitive value in
error message") or worse, print them. The pattern that works:

- Compute collisions over **hashes** of the values (`sha256(v)`), never
  the values.
- Build the human-readable pair list from the map **keys** (service
  names), passing only those through `nonsensitive()`.
- Never apply `nonsensitive()` to anything derived from the value itself.

A reviewer's caveat worth keeping: `nonsensitive()` declassifies whatever
feeds it. Applied to keys it is safe today - but a future edit that
widens what feeds that expression widens what gets declassified. Comment
the call site accordingly.

## Caveats

- The grep is on human-readable output; wording could change across
  Terraform versions. Pin the phrase to your Terraform version, or - more
  robust, though not what was validated here - use
  `terraform plan -json | jq` and match the structured diagnostic
  (`"summary":"Check block assertion failed"`) instead of prose.
- Check assertions evaluate against **planned** values; a check that
  depends on computed-at-apply values may pass at plan and only warn on a
  later plan. For invariants over data sources (the common case) this
  does not arise.
- Do not "fix" the silence by converting to a resource `precondition` on
  an arbitrary unrelated resource just to get a hard failure - it couples
  the guard's lifecycle to that resource and confuses the next reader.
  The wrapper keeps the guard where it belongs and adds the enforcement.
- `terraform validate` does not evaluate check assertions at all - only
  `plan`/`apply` do. A green `validate` says nothing here.
