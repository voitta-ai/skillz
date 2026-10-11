---
name: actions-log-secret-scrub
description: |
  Remove a secret that a CI job printed into GitHub Actions logs, and verify the
  removal without being fooled by three tool-level false cleans. Use when:
  (1) a `terraform plan` in CI printed a secret because a NON-sensitive attribute
  embeds one - a subscription endpoint carrying a routing key, a connection
  string, a webhook URL - and the config only holds a placeholder; (2) every push
  to the default branch reprints it, so the leak is growing; (3) you need to
  delete a run's logs and `gh api -X DELETE .../logs` returns 500; (4) a grep over
  `gh api .../jobs/<id>/logs` reports zero hits and you are about to call that
  clean; (5) a post-delete check still shows the secret and you cannot tell
  whether the deletion failed. The three false cleans are the point: `gh api`
  prints NOTHING for a log containing terminal escape sequences unless told
  otherwise, `gh api | grep` hides gh's own failure behind the pipe's exit
  status, and `gh run view --log` leaves a zip of the whole log on disk that a
  later check reads instead of the API.
author: Claude Code
version: 1.0.0
date: 2026-10-07
hosts: [claude, codex]
---

# Scrubbing a secret out of GitHub Actions logs

## Problem

**A destroy plan prints attributes FROM STATE.** A non-sensitive attribute that
*embeds* a secret - an SNS https subscription endpoint carrying a routing key, a
connection string, a webhook URL - appears in clear text in the plan even when
the config holds only a placeholder plus `ignore_changes`. Terraform is not
leaking the config; it is rendering state.

So CI that runs `terraform plan` on every push to the default branch writes that
secret to the Actions log, **and keeps doing so on every merge** until the
destroy is applied. The leak grows while you investigate it.

Then every obvious way to verify the cleanup lies to you.

## Context / Trigger conditions

- A CI `terraform plan` printed a secret through a non-sensitive attribute.
- Every default-branch push reprints it.
- `gh api -X DELETE .../logs` returns 500.
- A grep over a job's logs reports zero hits and you are about to report clean.
- A post-delete check still shows the secret and you cannot tell why.

## Solution

### 1. Stop the bleeding, then delete the logs

The leak repeats until the resource is gone from state, so applying the destroy
is part of the fix, not a follow-up.

```bash
gh api -i -X DELETE repos/<O>/<R>/actions/runs/<ID>/logs
```

**204** is success; afterwards `GET runs/<ID>/logs` and `GET jobs/<JOB>/logs`
both return **404**.

**A recently finished run returns 500.** Observed: four 500s, then 204 about
**10 minutes** after the run completed. Retry with backoff rather than
concluding the API refuses.

### 2. The three false cleans

**`gh api` prints nothing for a log with escape sequences.** Any terraform log
has them. Without `--allow-escape-sequences`, `gh api .../jobs/<JOB>/logs`
writes **nothing to stdout** and puts its refusal on **stderr** - so
`| grep -c -F "$K"` returns **0**, and that zero means *"I could not read it"*,
not *"it is not there"*. A leak watcher built this way reports clean forever.

**`gh api ... | grep` hides gh's failure.** A pipeline's exit status is the last
command's. Demonstrated:

```
(exit 7) | head   -> $? = 0
set -o pipefail
(exit 7) | head   -> $? = 7
```

So read gh's own status - `gh api -i`, or `set -o pipefail` - and never infer
success from the exit code of whatever you piped into.

**`gh run view --log` caches the whole log to disk**, at
`~/.cache/gh/run-log-<runid>-<n>.zip`. That is a **second copy of the secret**
on your machine, and a post-delete check through `gh` reads the stale cache and
reports the leak as still present. Delete the zip, and verify through the API.

### 3. Redact what you keep

If a log must be kept locally, strip the escapes and the secret in one pass:

```bash
perl -pe 's/\e\[[0-9;]*[A-Za-z]//g; s#(<url-prefix>/)[^/"\s]+#${1}<REDACTED>#g'
```

Keying the second substitution on the **URL prefix** rather than on the secret's
value means a rotated secret is still redacted, and the pattern never contains
the thing it is hiding.

### 4. Detect by fixed-string equality, and never print it

```bash
grep -c -F "$K" <file>     # K held in a shell variable, never echoed
```

`-F` so the secret is not read as a regex, and a count rather than a match so no
output can carry it. **Do not print the secret to confirm you have the right
one** - compare a hash if you must.

## Verification

After the delete, all three must hold, and the first two are the ones that fail
silently if you skip step 2:

1. `gh api -i .../runs/<ID>/logs` returns **404**, read from `-i` output rather
   than from a pipeline's exit code.
2. The same for `.../jobs/<JOB>/logs`.
3. `~/.cache/gh/run-log-<runid>-*.zip` is gone.

A clean grep is only evidence if you have shown the reader could produce output
at all. Exercise it on a string you know is present first.

## Notes

- The rotation question is separate and comes first in severity: a secret that
  reached a log should be rotated regardless of whether the log is deleted,
  because deletion does not reach anything that already read it.
- Applies to any CI that renders state, not only terraform, and to any
  non-sensitive field that embeds a credential.

## Related

- `agent-credential-leak-surfaces` - the same question on the local surfaces an
  agent accumulates. Surface 7 there is the sibling of this one: a harness
  recording a diff of a tracked file, where the leak is likewise something a tool
  wrote rather than something anyone typed.
- `credential-redactor-audit` - scanning discipline, including why a scan that
  cannot read its input reports clean.
