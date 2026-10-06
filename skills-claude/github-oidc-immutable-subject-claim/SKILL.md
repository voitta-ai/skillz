---
name: github-oidc-immutable-subject-claim
description: |
  Diagnose a GitHub Actions job that fails `Could not assume role with OIDC:
  Not authorized to perform sts:AssumeRoleWithWebIdentity` even though the IAM
  role's trust policy has an org-wide `StringLike` on
  `token.actions.githubusercontent.com:sub` (e.g. `repo:myorg/*`) and other
  repos in the SAME org assume the SAME role successfully. Use when: (1) one
  repo cannot assume a role every sibling repo can, (2) the repo is newer than
  the others, (3) copying a known-working workflow verbatim still fails, (4)
  you are about to widen or duplicate a trust policy and want to know the real
  `sub` first, (5) planning for GitHub's immutable-subject rollout across an
  org. Covers reading the real `sub` claim from a running job without printing
  the token, the `sub_claim_prefix` API that reveals it without a CI round
  trip, and the trust-policy patch that is forward-compatible rather than a
  per-repo exception.
author: Claude Code
version: 1.0.0
date: 2026-08-22
---

# GitHub OIDC: `repo:ORG/*` stops matching once GitHub issues immutable subjects

## Problem

A GitHub Actions job configures AWS credentials by OIDC and dies:

```
Assuming role with OIDC
Retry AssumeRole: attempt 1 of 12 failed: Could not assume role with OIDC:
  Not authorized to perform sts:AssumeRoleWithWebIdentity. Retrying after 26ms.
...
Error: Could not assume role with OIDC: Not authorized to perform sts:AssumeRoleWithWebIdentity
```

Everything you can check looks correct:

- `permissions: {id-token: write}` is on the job (and the token clearly *was*
  issued — the action got as far as calling `AssumeRoleWithWebIdentity`).
- The role's trust policy allows the whole org:
  `"StringLike": {"token.actions.githubusercontent.com:sub": "repo:myorg/*"}`
  and `"StringEquals": {"...:aud": "sts.amazonaws.com"}`.
- The role's *permission* policies are fine — and this is not a permissions
  error anyway, it is a trust error.
- **Other repos in the same org assume the same role in the same account with
  a workflow you copied verbatim.**

That last point is what makes it feel impossible, and it is the tell.

## Cause

GitHub is migrating the OIDC `sub` claim from

```
repo:ORG/REPO:ref:refs/heads/BRANCH
```

to the **immutable** form, which interpolates the numeric org and repo IDs:

```
repo:ORG@ORG_ID/REPO@REPO_ID:ref:refs/heads/BRANCH
```

`repo:myorg/*` does not glob past the `@11314822`, because the wildcard sits
after a `/` that is no longer where the pattern expects it. The subject simply
does not match, and AWS reports that as "not authorized".

**Which form a repo presents depends on the repo, not the org** — in practice
on when it was created. So an org can have twenty repos on the old form and
one on the new, with no setting anywhere that says so, and the newest repo is
the one that breaks. Every repo created from that point on inherits the
problem, and the error names nothing that would lead you to it.

## Diagnosis

### Fast path — no CI run needed

Ask GitHub what prefix each repo presents, and compare a broken repo against a
working one:

```bash
for r in new-repo known-good-repo another-good-repo; do
  printf '%-30s ' "$r"
  gh api "/repos/ORG/$r/actions/oidc/customization/sub" --jq '.sub_claim_prefix'
done
```

```
new-repo                       repo:myorg@11314822/new-repo@1315404603
known-good-repo                repo:myorg/known-good-repo
another-good-repo              repo:myorg/another-good-repo
```

One of these is not like the others. Correlate with `gh api repos/ORG/$r --jq
.created_at` and the pattern is usually "everything after date X".

Note `use_immutable_subject` in that response can read `false` while
`sub_claim_prefix` already carries the IDs. **Trust the prefix, not the
boolean.**

This endpoint needs only repo read access. The *org*-level equivalent
(`/orgs/{ORG}/actions/oidc/customization/sub`) requires `admin:org`, so do not
plan around having it.

### Proof path — read the claim from a real job

Before asking another team to change an IAM trust policy, prove what is
actually on the wire. Add a temporary step **before** the credentials step.
It prints claims only — never the token:

```yaml
      - name: Print OIDC subject
        run: |
          tok=$(curl -sS -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
            "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=sts.amazonaws.com" | jq -r .value)
          payload=$(echo "$tok" | cut -d. -f2)
          pad=$(( (4 - ${#payload} % 4) % 4 ))
          payload="$payload$(printf '=%.0s' $(seq 1 $pad 2>/dev/null))"
          echo "$payload" | tr '_-' '/+' | base64 -d \
            | jq '{sub, aud, repository, repository_owner, repository_id, repository_owner_id}'
```

```json
{
  "sub": "repo:myorg@11314822/new-repo@1315404603:ref:refs/heads/fix/ci-oidc-role",
  "aud": "sts.amazonaws.com",
  "repository": "myorg/new-repo",
  "repository_owner": "myorg",
  "repository_id": "1315404603",
  "repository_owner_id": "11314822"
}
```

`aud` matches the trust policy; `sub` does not. That is the whole bug, in one
object. Remove the step once you have the output — `git reset --hard HEAD~1`
+ force-push keeps the branch a single clean commit.

Two things this step is careful about, both worth keeping if you adapt it:

- It requests the token with the **same audience** the credentials action
  will use. A different audience proves nothing about the failing call.
- It selects specific claims through `jq` rather than dumping the payload, so
  a future claim addition cannot turn a debug step into a token leak.

## Fix

Accept both forms in the trust policy. `StringLike` takes a list and ORs it:

```hcl
locals {
  github_org_id = "11314822"

  # Both mean "any repository in the org, any branch / environment". GitHub is
  # migrating from `repo:ORG/REPO` to the immutable `repo:ORG@ORG_ID/REPO@REPO_ID`,
  # and which form a repo presents depends on when it was created. Keep both
  # until every repo has migrated.
  github_subject = [
    "repo:myorg/*",
    "repo:myorg@${local.github_org_id}/*",
  ]
}
```

The `assume_role_policy` itself needs no change if it already interpolates
that local — `jsonencode` renders a list as a JSON array, which is what
`StringLike` expects.

**This is not a widening.** Org `11314822` *is* `myorg`; the second pattern is
the same set of repositories written in the format GitHub now uses. Say so
explicitly when you file the request, because "please loosen the trust policy
on the shared CI role" reads as a security ask and will stall otherwise.

## Traps

- **Do not fix it per repo.** Adding `repo:myorg@11314822/new-repo@1315404603:*`
  for the one broken repo works and guarantees the next new repo repeats the
  whole investigation. The org-wide pattern costs the same and ends it.
- **Do not narrow while you are in there.** Tightening to a single repo or to
  `:ref:refs/heads/main` is a *narrowing* relative to the current policy and a
  separate decision; bundling it turns a one-line unblock into a security
  review.
- **Do not conclude "the role lacks permissions".** `AssumeRoleWithWebIdentity`
  failing is a *trust* problem. Checking the role's attached policies (and
  finding them fine) is a detour — and if you check them first, as is natural,
  you can convince yourself the role is correct and go looking in the workflow.
- **"The reference repo does it this way" is not transferable evidence here.**
  It is exactly the reasoning that fails, because the difference is per-repo
  and invisible in both workflows.
- **The org-level `sub` customization endpoint 403s without `admin:org`.**
  Diagnose per repo instead; you do not need org admin to find this.
- **Check the action's inputs are supported before blaming the version.**
  If the workflow uses `output-credentials` / `unset-current-credentials`,
  confirm against `gh api repos/aws-actions/configure-aws-credentials/contents/action.yml?ref=vN`
  rather than downgrading to match a working repo on a guess. A pinned-major
  difference is a plausible-looking red herring next to a real subject mismatch.

## Related

Once the trust policy matches, the *other* half of moving a repo from static
keys to OIDC still applies: assumed-role credentials carry a session token and
static keys do not, so any step that materialises a named AWS profile must
write **four** values including `aws_session_token`. Omitting it fails every
`profile = "..."` consumer with an opaque signature error rather than an auth
one.
