---
name: github-issue-migration-across-owners
description: |
  Move GitHub issues where `gh issue transfer` cannot go: to a repo with a
  different owner (org -> user account), or from a private repo to a public
  one. Use when: (1) transfer is refused or impossible and the issues must be
  recreated with their comments, (2) the issues cross-reference each other and
  the links must point at the new numbers, (3) the issues embed images uploaded
  to a private repo (`github.com/user-attachments/assets/<uuid>`), which return
  404 to anonymous viewers and to API tokens alike, (4) the target is public and
  the text must be scrubbed of private references first.
author: Claude Code
version: 1.0.0
date: 2026-11-09
source: https://github.com/voitta-ai/skillz
source_file: skills/github-issue-migration-across-owners/SKILL.md
---

# GitHub issue migration across owners and visibility

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/github-issue-migration-across-owners/SKILL.md`).

## Problem

`gh issue transfer` only works between repositories with the same owner, and
never from a private repo to a public one. Spinning a project out of a private
org repo into a public user-owned repo therefore means recreating its issues.
Three things break when you do it naively:

- Cross-references (`#211`, full issue URLs) still point at the old numbers in
  a repo the public cannot see.
- Images attached in the private repo do not render. The markdown holds
  `https://github.com/user-attachments/assets/<uuid>`, which for a private repo
  is access-controlled by browser session. A personal access token in an
  `Authorization` header still gets **404**.
- Private text (internal paths, org names, other private issue numbers) leaks
  into a public tracker.

## Context / Trigger Conditions

- Moving issues from `<src-org>/<private-repo>` to `<user>/<public-repo>`.
- `curl -H "Authorization: token $GH_TOKEN" https://github.com/user-attachments/assets/<uuid>` returns 404.
- Copied issues show broken images when viewed logged-out.

## Solution

1. **Snapshot the source issues** (body, comments, state, stateReason,
   createdAt, closedAt) to local JSON. Work from the snapshot so reruns are
   deterministic.

2. **Scan for anything that must not go public** before writing anywhere:
   credential shapes, internal paths, org and customer names, and references
   to private issues that are not moving. Decide per hit: rewrite, drop, or
   keep.

3. **Download private attachments through signed URLs.** Request the
   rendered HTML:

   ```bash
   gh api repos/<src-org>/<private-repo>/issues/<n> \
     -H "Accept: application/vnd.github.full+json" --jq .body_html
   gh api --paginate repos/<src-org>/<private-repo>/issues/<n>/comments \
     -H "Accept: application/vnd.github.full+json"
   ```

   `body_html` rewrites each attachment to a short-lived signed URL
   `https://private-user-images.githubusercontent.com/...?jwt=...` that
   downloads **without auth**. Match each `<uuid>` from the markdown `body` to
   the signed URL that contains it, unescape `&amp;`, and download right away,
   because the JWT expires within minutes. Fetch the HTML per issue,
   immediately before downloading its images, not all up front.

   **Set a network timeout.** Python `urllib.request.urlretrieve` has none by
   default, and one stalled download hung a run for 30 minutes. Call
   `socket.setdefaulttimeout(60)` and make the loop resumable by skipping
   files already on disk. macOS has no `timeout` command to wrap it with.

   Optionally convert to JPEG (`sips -s format jpeg -s formatOptions 82`) to
   cut a multi-MB PNG set roughly 10x before committing.

4. **Re-host the images in the target repo** (e.g. `media/<old-number>/`),
   commit, and **push before creating any issue**, then rewrite image links to
   `https://raw.githubusercontent.com/<user>/<public-repo>/<default-branch>/media/...`.
   Check the default branch first (`gh repo view --json defaultBranchRef`):
   `gh repo create --license` may create `master`, not `main`, and a guessed
   branch name breaks every image link. Verify one raw URL returns 200 before
   continuing.

5. **Pre-compute the new numbers.** Issues and PRs share one counter. Read the
   last used number:

   ```bash
   gh api "repos/<user>/<public-repo>/issues?state=all&per_page=1&sort=created&direction=desc" \
     --jq '.[0].number // 0'
   ```

   Then map old -> `last + 1 + i` in ascending old order. That lets every body
   be rewritten before creation, including forward references. While creating,
   **assert each returned URL ends in the expected number and stop on drift**.
   Someone opening an issue in the target mid-run would otherwise silently
   shift every later reference.

6. **Rewrite references**:
   - Full issue URLs and bare `#N` for migrated issues -> `#<new>`.
   - References to private issues that are not moving -> plain text such as
     `<private-repo>#N` (not a link), so nothing points into the private repo.
   - Private blob URLs (`.../blob/<branch>/file.png?raw=true`) -> the
     re-hosted copy.

7. **Create, fold comments, close.** For each issue: create it with a header
   line ("Migrated from the private tracker, opened YYYY-MM-DD"), then post each
   original comment with a dated header, then close it if the source was
   closed (preserve `completed` / `not planned`). Pass bodies through
   `gh ... -F -` on stdin so markdown survives. Do **not** write `@user` in
   the headers, because each one notifies.

8. **Close the originals** with a comment `Moved to <new-url>`. Open ones
   close as `not planned`; closed ones only get the comment.

9. **Dry-run first.** Run the whole pipeline with gh calls printed, not
   executed, and assert that no `user-attachments`, private-repo URLs or
   missing `media/` paths remain in the rewritten text.

## Verification

- `gh issue list -R <user>/<public-repo> --state all` shows the expected
  numbers, states and comment counts.
- A logged-out `curl -o /dev/null -w '%{http_code}'` on a new issue and on a
  re-hosted image returns 200.
- Every source issue is closed and its last comment is the "Moved to" link.

## Notes

- Comments are re-posted by the migrating account, so original authorship and
  timestamps survive only in the header text.
- Reactions, labels and milestones are not carried over. Recreate labels in
  the target first if you need them.
- If the target must not hold media, the signed-URL download still applies:
  re-host anywhere public (a CDN, the project's site media library) and
  rewrite to that.
- Related: `gist-to-repo-migration` (moving gist history into a repo),
  `pre-open-source-credential-audit` (deeper scrub before going public).

## References

- [Transferring an issue to another repository](https://docs.github.com/en/issues/tracking-your-work-with-issues/administering-issues/transferring-an-issue-to-another-repository):
  same-owner only, no private -> public.
- [Media types: `application/vnd.github.full+json`](https://docs.github.com/en/rest/using-the-rest-api/getting-started-with-the-rest-api#media-types)
  returns `body_html` alongside `body`.
