#!/bin/bash
#
# post-batch.sh -- post the payloads saved by batch-review.sh as GitHub PR reviews.
#
# Each pr-N.json produced by `--dry-run` is byte-for-byte the review POST body,
# so this needs no Codex pass at all.
#
# Usage:
#   post-batch.sh --repo owner/name --out DIR [--dry-run] [--approve-clean]
#
# Before each post the live PR is checked: a payload whose PR is no longer
# open, or whose head moved past the pinned commit_id, goes to DIR/stale/
# instead of being posted (re-review those). A posted payload moves to
# DIR/posted/pr-N.<sha>.json so the next batch can review the PR afresh.
#
# --approve-clean posts a clean payload (verdict approve, no inline comments,
# no out-of-diff findings) as an APPROVE review instead of COMMENT.
#
# To drop a finding you judged a false positive before posting, edit the payload:
#   jq '.comments |= map(select((.body|test("PATTERN"))|not))' pr-N.json > tmp && mv tmp pr-N.json
set -uo pipefail

REPO=""; OUT=""; DRY=0; APPROVE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO=$2; shift 2;;
    --out) OUT=$2; shift 2;;
    --dry-run) DRY=1; shift;;
    --approve-clean) APPROVE=1; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
[ -n "$REPO" ] && [ -n "$OUT" ] || { echo "--repo and --out are required" >&2; exit 2; }
mkdir -p "$OUT/logs" "$OUT/stale" "$OUT/posted"

CLEAN='.event=="COMMENT" and (.comments|length)==0
       and ((.body|split("\n")|index("## Codex Adversarial Review — approve"))!=null)
       and ((.body|test("### Findings outside the diff"))|not)'

ok=0; fail=0
for p in $(find "$OUT/payloads" -name 'pr-*.json' -size +0 | sort -V); do
  n=$(basename "$p" .json); n=${n#pr-}
  live=$(gh api "repos/$REPO/pulls/$n" --jq '.state+" "+.head.sha' 2>/dev/null)
  state=${live%% *}; head=${live##* }
  stale=""
  if [ "$state" != open ]; then stale="PR is ${state:-unreachable}"
  elif [ "$head" != "$(jq -r .commit_id "$p")" ]; then stale="head moved, re-review it"; fi
  if [ -n "$stale" ]; then
    echo "stale $n: $stale"; [ "$DRY" = 1 ] || mv "$p" "$OUT/stale/"; continue
  fi
  event=$(jq -r .event "$p")
  if [ "$APPROVE" = 1 ] && jq -e "$CLEAN" "$p" >/dev/null; then event=APPROVE; fi
  v=$(jq -r '.body' "$p" | grep -m1 '^## Codex' | sed 's/.*— //')
  if [ "$DRY" = 1 ]; then
    echo "would post $n as $event ($v, $(jq '.comments|length' "$p") inline)"
    continue
  fi
  body=$p
  if [ "$event" != "$(jq -r .event "$p")" ]; then
    jq --arg e "$event" '.event=$e' "$p" > "$p.tmp"; body=$p.tmp
  fi
  if gh api "repos/$REPO/pulls/$n/reviews" --method POST --input "$body" \
       >/dev/null 2>"$OUT/logs/post-$n.err"; then
    echo "posted $n ($event)"; ok=$((ok+1)); mv "$p" "$OUT/posted/pr-$n.$head.json"
  else
    echo "FAILED $n: $(tail -2 "$OUT/logs/post-$n.err" | tr '\n' ' ')"; fail=$((fail+1))
  fi
  rm -f "$p.tmp"
done
[ "$DRY" = 1 ] || echo "posted=$ok failed=$fail"
