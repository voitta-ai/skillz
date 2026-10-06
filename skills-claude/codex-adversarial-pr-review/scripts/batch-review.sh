#!/bin/bash
#
# batch-review.sh -- dry-run codex-adversarial-pr-review over many PRs in parallel,
# saving each review payload to disk. The saved payload is the exact GitHub POST
# body, so posting later is `gh api --input` and costs no second Codex pass.
#
# Usage:
#   batch-review.sh --repo owner/name --repo-dir /path/to/checkout --out DIR \
#                   [--workers N] [--base origin/main] [--min-confidence 0.75] \
#                   [--author LOGIN | --prs "1 2 3"] [--focus TEXT]
#
# Then inspect DIR/payloads/pr-N.json and post with post-batch.sh (or by hand).
#
# Resumable: a PR whose payload already exists is skipped. An interrupted run
# leaves a zero-byte payload, which is treated as absent.
set -uo pipefail

REPO=""; REPO_DIR=""; OUT=""; WORKERS=3; BASE=""; MINCONF=0.75; AUTHOR=""; PRS=""; FOCUS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO=$2; shift 2;;
    --repo-dir) REPO_DIR=$2; shift 2;;
    --out) OUT=$2; shift 2;;
    --workers) WORKERS=$2; shift 2;;
    --base) BASE=$2; shift 2;;
    --min-confidence) MINCONF=$2; shift 2;;
    --author) AUTHOR=$2; shift 2;;
    --prs) PRS=$2; shift 2;;
    --focus) FOCUS=$2; shift 2;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
[ -n "$REPO" ] && [ -n "$REPO_DIR" ] && [ -n "$OUT" ] || {
  echo "--repo, --repo-dir and --out are required" >&2; exit 2; }
[ -n "$AUTHOR" ] || [ -n "$PRS" ] || { echo "pass --author or --prs" >&2; exit 2; }

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REVIEW=$HERE/codex-adversarial-pr-review.mjs
mkdir -p "$OUT/payloads" "$OUT/logs" "$OUT/wt"

# Resolve the PR set to (number, headRef, headOid) up front so every worker reads
# a static table instead of re-querying the API.
if [ -n "$PRS" ]; then
  FILTER=$(printf '%s' "$PRS" | tr ' ' '\n' | paste -sd, -)
  gh pr list --repo "$REPO" --state open --limit 500 \
     --json number,baseRefName,headRefName,headRefOid \
    | jq -r --arg f "$FILTER" '($f|split(",")|map(tonumber)) as $w
        | .[] | select(.number as $n | $w|index($n))
        | [.number,.baseRefName,.headRefName,.headRefOid]|@tsv' > "$OUT/meta.tsv"
else
  gh pr list --repo "$REPO" --author "$AUTHOR" --state open --limit 500 \
     --json number,baseRefName,headRefName,headRefOid \
    | jq -r '.[]|[.number,.baseRefName,.headRefName,.headRefOid]|@tsv' > "$OUT/meta.tsv"
fi
sort -rn -o "$OUT/meta.tsv" "$OUT/meta.tsv"
cut -f1 "$OUT/meta.tsv" > "$OUT/prs.txt"
echo "resolved $(wc -l < "$OUT/prs.txt" | tr -d ' ') PRs"

# One fetch of every head ref, so the per-PR checkouts are local and offline.
# A read loop, not mapfile: macOS ships bash 3.2, where mapfile does not exist
# and this step used to fail quietly, leaving every head pushed after the
# clone to die with "FAIL checkout N".
SPECS=()
while IFS= read -r h; do
  [ -n "$h" ] && SPECS+=("+refs/heads/$h:refs/remotes/origin/$h")
done < <(cut -f3 "$OUT/meta.tsv")
if [ ${#SPECS[@]} -gt 0 ]; then
  git -C "$REPO_DIR" fetch origin "${SPECS[@]}" >/dev/null 2>&1
fi

# Detached worktrees: a detached HEAD at the PR head OID sidesteps "branch is
# already checked out" and needs no local branches. `--scope branch` diffs
# merge-base...HEAD, which is exactly what GitHub renders, so the line numbers
# line up with the commentable diff.
for i in $(seq 1 "$WORKERS"); do
  [ -d "$OUT/wt/w$i" ] || git -C "$REPO_DIR" worktree add --detach "$OUT/wt/w$i" HEAD >/dev/null 2>&1
done

worker() {
  local slot=$1; shift
  local wt="$OUT/wt/w$slot"
  for n in "$@"; do
    if [ -s "$OUT/payloads/pr-$n.json" ]; then echo "[$slot] skip $n (done)"; continue; fi
    local oid base
    oid=$(awk -F'\t' -v n="$n" '$1==n{print $4}' "$OUT/meta.tsv")
    base=${BASE:-origin/$(awk -F'\t' -v n="$n" '$1==n{print $2}' "$OUT/meta.tsv")}
    if ! git -C "$wt" checkout -f --detach "$oid" >/dev/null 2>&1; then
      echo "[$slot] FAIL checkout $n"; continue
    fi
    echo "[$slot] start $n"
    if node "$REVIEW" --pr "$n" --repo "$REPO" --repo-dir "$wt" --base "$base" \
         --min-confidence "$MINCONF" ${FOCUS:+--focus "$FOCUS"} --dry-run \
         > "$OUT/payloads/pr-$n.json" 2> "$OUT/logs/pr-$n.log"; then
      echo "[$slot] ok $n"
    else
      echo "[$slot] FAIL $n (see $OUT/logs/pr-$n.log)"
      rm -f "$OUT/payloads/pr-$n.json"
    fi
  done
}

ALL=($(cat "$OUT/prs.txt"))
for s in $(seq 1 "$WORKERS"); do
  chunk=()
  for ((i=s-1; i<${#ALL[@]}; i+=WORKERS)); do chunk+=("${ALL[$i]}"); done
  [ ${#chunk[@]} -eq 0 ] || worker "$s" "${chunk[@]}" &
done
wait

done_n=$(find "$OUT/payloads" -name 'pr-*.json' -size +0 | wc -l | tr -d ' ')
all_n=$(wc -l < "$OUT/prs.txt" | tr -d ' ')
echo "DONE $done_n/$all_n payloads in $OUT/payloads"
[ "$done_n" = "$all_n" ] || echo "re-run to retry the missing ones (it resumes)"

# ponytail: worktrees are left in place so a re-run resumes cheaply.
# Remove them with: git -C "$REPO_DIR" worktree remove --force "$OUT/wt/wN"
