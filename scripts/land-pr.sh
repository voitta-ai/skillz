#!/usr/bin/env bash
#
# land-pr.sh - land one skillz branch on master: rebase, renumber the bundle,
# validate, push, open or update the PR, wait for CI, squash-merge, clean up.
#
# Usage: scripts/land-pr.sh <worktree> <pr-title> <pr-body-file>
#
# Meant for the one landing session (#188): capture sessions push branches or
# leave commits in worktrees, and a single session lands them one at a time,
# so master never moves under a rebase in progress.
#
# What it does that is easy to get wrong by hand:
# - Bundle version: always set to master's + 1 minor after the rebase, in both
#   manifests. Two branches that claimed the same next number rebase with NO
#   conflict, so a conflict-driven fix would silently leave the bump a no-op.
# - Registry files: scripts/merge-skill-registry.py runs ONLY when catalog.json,
#   a marketplace file or README.md is itself conflicted. It rebuilds those from
#   master and re-adds new entries only, so running it otherwise drops the
#   branch's edits to existing entries (#416). Review those files after it runs.
# - Any other conflict stops the script for a human to resolve.
# - "bundle X.Y.Z" in the title and body file is rewritten to the final number.
# - The branch and worktree are deleted only after the merge succeeded.
#
# Per-plugin version bumps stay the author's job; check-plugin-version-bumps.py
# stops the script if one is missing. bash 3.2 compatible.

set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <worktree> <pr-title> <pr-body-file>" >&2
  exit 2
fi
W=$(cd "$1" && pwd); TITLE="$2"; BODY="$3"
REGISTRY='^(catalog\.json|\.claude-plugin/marketplace\.json|\.codex-plugin/marketplace\.json|README\.md)$'
BUNDLE_FILES="plugins/skillz/.claude-plugin/plugin.json plugins/skillz/.codex-plugin/plugin.json"

cd "$W"
MAIN=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')
BR=$(git rev-parse --abbrev-ref HEAD)
git fetch -q origin

set_bundle() {
  python3 - "$1" $BUNDLE_FILES <<'PY'
import re, sys
for f in sys.argv[2:]:
    s = open(f).read()
    s = re.sub(r'<<<<<<< [^\n]*\n(\s*"version": )"[^"]*",\n=======\n\s*"version": "[^"]*",\n>>>>>>> [^\n]*\n',
               r'\1"0.0.0",\n', s)
    s = re.sub(r'"version": "[^"]*"', '"version": "%s"' % sys.argv[1], s, count=1)
    open(f, "w").write(s)
PY
}

if ! git rebase origin/master >/dev/null 2>&1; then
  while [ -d "$(git rev-parse --git-path rebase-merge)" ]; do
    if git diff --name-only --diff-filter=U | grep -qE "$REGISTRY"; then
      python3 scripts/merge-skill-registry.py HEAD >/dev/null 2>&1 \
        || python3 scripts/merge-skill-registry.py >/dev/null 2>&1 || true
      echo "NOTE: registry merge ran; check the branch's edits to existing entries survived." >&2
    fi
    for f in $BUNDLE_FILES; do
      if grep -q '<<<<<<<' "$f"; then set_bundle 0.0.0; git add $BUNDLE_FILES; fi
    done
    git add -u 2>/dev/null || true
    if git diff --name-only --diff-filter=U | grep -q . || grep -lq '<<<<<<<' $(git diff --cached --name-only) 2>/dev/null; then
      echo "UNRESOLVED conflicts - resolve in $W, then rerun:" >&2
      git diff --name-only --diff-filter=U >&2
      exit 3
    fi
    GIT_EDITOR=true git rebase --continue >/dev/null 2>&1 || true
  done
fi

MV=$(git --no-pager show origin/master:plugins/skillz/.claude-plugin/plugin.json \
     | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')
NV=$(python3 -c "a,b,c='$MV'.split('.'); print(f'{a}.{int(b)+1}.0')")
set_bundle "$NV"
git diff --quiet || git commit -q -am "Bundle $NV after rebase"

bash scripts/validate-catalog.sh >/dev/null || { bash scripts/validate-catalog.sh | tail -5; exit 4; }
python3 scripts/check-plugin-version-bumps.py origin/master

TITLE=$(printf '%s' "$TITLE" | sed -E "s/bundle [0-9]+\.[0-9]+\.[0-9]+/bundle $NV/")
sed -E -i.bak "s/bundle [0-9]+\.[0-9]+\.[0-9]+/bundle $NV/g" "$BODY" && rm -f "$BODY.bak"

git push -q --force-with-lease -u origin HEAD
N=$(gh pr list --head "$BR" --json number --jq '.[0].number // empty')
if [ -z "$N" ]; then
  N=$(gh pr create --base master --head "$BR" --title "$TITLE" --body-file "$BODY" | grep -oE '[0-9]+$')
else
  gh pr edit "$N" --title "$TITLE" --body-file "$BODY" >/dev/null 2>&1 \
    || gh api -X PATCH "repos/{owner}/{repo}/pulls/$N" -f title="$TITLE" >/dev/null
fi

sleep 8
if ! gh pr checks "$N" --watch --interval 10 >/dev/null 2>&1; then
  echo "CI failed on #$N:" >&2; gh pr checks "$N" >&2 || true; exit 5
fi
gh pr merge "$N" --squash >/dev/null
git push -q origin --delete "$BR" 2>/dev/null || true
cd "$MAIN" && git worktree remove "$W" && git branch -D "$BR" >/dev/null
echo "MERGED #$N ($TITLE)"
