---
name: terraform-noninteractive-prod-apply
description: |
  Apply terraform to production from a non-interactive context (an agent, a
  script, CI) when the repo's `apply.sh` / `deploy.sh` wrapper calls
  `terraform apply` WITHOUT `-auto-approve` and therefore blocks on the
  "Enter a value:" prompt. Use when: (1) a wrapper script hangs or dies at
  the approval prompt, (2) you are about to reach for `echo yes | ./apply.sh`,
  (3) you reviewed a plan and want the apply to be that plan rather than a
  freshly recomputed one, (4) a wrapper auto-detects variables (image tag,
  version) from `terraform output` and you need to reproduce them, (5) you
  want an apply that fails loudly if state moved under you. Covers the
  approve-the-wrong-plan race that `yes |` creates, the saved-plan-file
  alternative, reproducing a wrapper's computed variables, and why a plan
  file is a secret.
author: Claude Code
version: 1.1.0
date: 2026-08-24
---

# Non-interactive terraform prod apply: use a saved plan file, not `yes |`

## Problem

You need to apply terraform to prod, but the repo's wrapper prompts:

```bash
$ ./apply.sh prod
...
Do you want to perform these actions?
  Terraform will perform the actions described above.
  Only 'yes' will be accepted to approve.

  Enter a value:      # <- hangs forever with no TTY
```

Because the wrapper ends in a bare `terraform apply`, with no `-auto-approve`:

```bash
terraform apply -var-file=env/$ENV.tfvars -var="service_version=$VERSION"
```

This is common and deliberate: CI applies **dev** with `-auto-approve`, while
**prod** is applied by a human through the wrapper, and the prompt *is* the
gate. An agent driving the same wrapper hits the gate too.

## The tempting fix, and why not for prod

```bash
echo yes | ./apply.sh prod          # works. do not do this for prod.
```

It runs. The problem is not that it fails — it is **what it approves.**

`terraform apply` with no plan file **recomputes the plan at apply time**. So
`yes` approves whatever terraform decides *at that moment*, which is not
necessarily what you read and agreed to. Between your review and the apply:

- CI may have applied on a merge,
- someone else may have applied,
- a `data` source may now read differently (a rotated secret, a new AMI, a
  changed SG),
- drift may have appeared.

You typed `yes` to a plan you never saw. On dev that is a bad day; on prod it
is an outage with your approval attached to it.

It also destroys the audit story. "I reviewed the plan and approved it" and
"I piped `yes` into a command that computed its own plan" are different
claims, and only one of them is true.

## Solution — plan to a file, apply the file

```bash
# 1. Plan, saving it
terraform plan -lock-timeout=5m -var-file=env/prod.tfvars -out=/tmp/x.tfplan

# 2. READ IT. This is the whole point.

# 3. Apply exactly that plan -- no prompt, because there is nothing left to approve
terraform apply -lock-timeout=5m /tmp/x.tfplan

# 4. Delete it (see "A plan file is a secret")
rm -f /tmp/x.tfplan
```

`terraform apply <planfile>` **does not prompt** — the approval already
happened when you chose to apply that file. So this is non-interactive
*without* bypassing any gate; it moves the gate to where a human actually is.

And it fails closed. If state moved between plan and apply:

```
Error: Saved plan is stale
The given plan file can no longer be applied because the state was changed
by another operation after the plan was created.
```

That error is the feature. `yes |` would have silently applied the new plan.

## Reproducing what the wrapper computes

Do not just run `terraform plan -out` and assume it matches. Wrappers usually
compute variables first, and getting them wrong plans a *different change*:

```bash
# typical wrapper body
VERSION="$(terraform output -raw service_version)"          # auto-detect!
CANARY_VERSION="$(terraform output -raw canary_version)"
terraform apply -var-file=env/$ENV.tfvars \
  -var="service_version=$VERSION" -var="canary_version=$CANARY_VERSION"
```

Read the wrapper and mirror it exactly, including any `init` it performs
(`-backend-config=env/$ENV-backend.tfvars -reconfigure` is common, and
skipping it plans against the *wrong state file* — often silently, if the
previous init left a different backend configured).

**Check whether the wrapper forwards extra args before assuming
`--auto-approve` passes through.** Some do (`terraform apply "$@"`), most do
not. Passing a flag a wrapper ignores looks like it worked and does not.

## A plan file is a secret

A saved plan contains the **cleartext values** of everything in the diff,
including data-source reads — secrets, tokens, connection strings. It is not
a summary; it is a snapshot.

- Write it **outside the repo** (`/tmp`, not the working tree) so no
  `git add -A` can catch it. Add `*.tfplan` to `.gitignore` regardless.
- Delete it after applying.
- Never attach one to a PR, an issue, or a chat message.
- A plan file also **freezes secret values at plan time**. If a secret rotates
  between plan and apply, the apply writes the stale one. Keep the window
  short, and re-plan rather than reusing a plan file from yesterday.

## Guarding a saved plan, and two ways the guard lies

A saved plan is only as safe as the guard that reads it. Both traps below
produced FALSE POSITIVES that refused a correct apply - the right direction for
a guard to fail, but each cost a cycle, and the second is a plain bash bug.

**Terraform's own continuation line shares the action-line prefix.** A guard
that whitelists resource addresses by grepping `^  # ` also matches the
explanation terraform prints underneath:

```
  # aws_lb_target_group.example[0] will be destroyed
  # (because index [0] is out of range for count)
```

So "is every action line one I expect?" answers NO on a plan containing only
expected actions. Exclude the continuation:

```bash
grep -E '^  # ' plan.txt | grep -v '^  # (because' | grep -v '<expected address>'
```

**`grep | head` returns head's status, which is always 0.** This always sets
FAIL:

```bash
grep -E 'image .*->' plan.txt | head -3 && FAIL=1     # WRONG
```

Use `grep -q` in an `if`, with no pipe:

```bash
if grep -qE 'image .*->' plan.txt; then echo "GUARD: image change"; FAIL=1; fi
```

A guard that held, for an expected 0 add / 0 change / 1 destroy:

```bash
FAIL=0
grep -qE '^Plan: 0 to add, 0 to change, 1 to destroy\.$' plan.txt || FAIL=1
U=$(grep -E '^  # ' plan.txt | grep -v '^  # (because' | grep -v '<expected address>' || true)
[ -n "$U" ] && FAIL=1
if grep -qE 'image .*->' plan.txt; then FAIL=1; fi
[ "$FAIL" -ne 0 ] && { echo "NOT APPLYING"; exit 1; }
terraform apply -auto-approve "$PLAN"
```

**Why `image .*->` is worth guarding on even when images are not the subject.**
A wrapper taking POSITIONAL arguments and passing no flags through turned
`./plan.sh prod -no-color -out=p.tfplan` into
`-var="service_version=-no-color"`. The plan read as ordinary drift - `4 to
change`, Deployments updated in place - while actually setting every prod pod's
image tag to the literal string `-no-color`. It was caught only by opening the
deployment diff. So: guard that no image changes, and confirm the wrapper
echoed a real version.

## Checklist

1. Read the wrapper. Note its `init` flags and any computed vars.
2. `init` exactly as it does.
3. `plan -out=/tmp/<name>.tfplan` with the same vars.
4. **Read the plan.** If it shows changes beyond what you intend, decide
   full-vs-targeted deliberately rather than shrugging.
5. Get human approval on *that* output if the change is production-facing.
6. `apply /tmp/<name>.tfplan`.
7. `rm` the plan file.
8. If your org requires a deploy announcement, note that a genuinely no-diff
   apply (`0 added, 0 changed, 0 destroyed`) usually does not qualify — check
   the rule rather than announcing reflexively.

## When `yes |` is fine

Dev, throwaway environments, and anywhere a wrong apply is cheap and
reversible. The distinction is not interactivity — it is whether approving an
unseen plan is acceptable. On prod it is not.
