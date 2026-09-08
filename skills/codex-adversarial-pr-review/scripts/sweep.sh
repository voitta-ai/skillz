#!/bin/bash
#
# sweep.sh -- review the PRs that are waiting on you, across hosts and repos.
#
# For each --author [host:]login (host defaults to github.com) the queue is:
#   pending   open PRs by that login with a pending review request for you
#   followup  open PRs by that login you already reviewed, where the author has
#             commented on the PR or replied in a review thread since your last
#             review (--followup-on-push: a new head counts too - agents rebase
#             everything, so that alone re-queues most of a backlog)
# The queue is grouped by repo, batch-review.sh runs per repo (dry-run payloads
# on disk), and post-batch.sh posts them behind its staleness screen. Nothing
# is posted until `sweep.sh post`.
#
# Usage:
#   sweep.sh list   --out DIR --author [host:]login [--author ...] [--followup-on-push]
#   sweep.sh review --out DIR --author [host:]login [--author ...] [--followup-on-push] \
#                   [--clone-root DIR ...] [--workers N] [--min-confidence 0.75]
#   sweep.sh post   --out DIR [--dry-run] [--approve-clean]
#
# Layout under DIR:
#   queue.tsv                host <TAB> owner/name <TAB> number <TAB> login <TAB> pending|followup <TAB> requested|reply|push
#   candidates.tsv           the reviewed-by set before probing (debugging aid)
#   <host>/<owner>__<name>/  one batch-review.sh --out per repo (payloads/, posted/, stale/)
#   clones/<host>/<owner>/<name>/  checkouts made here when no --clone-root has one
#
# This is a batch tool: the queue is routinely dozens of PRs, so enumeration
# spends nothing on a candidate untouched since your review and at most four
# calls on one that was (three without --followup-on-push), probes 8-wide. macOS bash 3.2
# compatible: no mapfile, no associative arrays.
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export GH_PAGER=cat

# Text handed to Codex for a follow-up round. ponytail: one fixed sentence;
# feed it your previous review body and the author's replies if this proves
# too blunt.
FOLLOWUP_FOCUS="Follow-up round: this reviewer already posted an adversarial review on this PR and the author has since pushed and/or replied. Review the current diff on its merits; do not re-raise anything the current code already handles; say what is still open."

# _probe host repo number login updatedAt me
# Prints a followup queue line when the author acted after the current user's
# last review on the PR: commented or replied in a thread (reason "reply"), or
# - only with SWEEP_FOLLOWUP_ON_PUSH=1 - pushed a new head ("push"). Prints
# nothing otherwise. Runs under xargs.
probe() {
  [ $# -ge 6 ] || return 0
  local host=$1 repo=$2 n=$3 login=$4 updated=$5 me=$6 last last_at last_sha head kind why=""
  last=$(GH_HOST=$host gh api "repos/$repo/pulls/$n/reviews?per_page=100" \
    --jq "[.[]|select(.user.login==\"$me\" and .submitted_at!=null)]|sort_by(.submitted_at)|last|if .==null then empty else .submitted_at+\" \"+.commit_id end" 2>/dev/null)
  [ -n "$last" ] || return 0
  last_at=${last%% *}; last_sha=${last##* }
  # updatedAt came free with the search: untouched since the review means
  # nothing to look at, and this is where most candidates stop.
  [ "$updated" \> "$last_at" ] || return 0
  for kind in issues pulls; do
    [ "$(GH_HOST=$host gh api "repos/$repo/$kind/$n/comments?since=$last_at&per_page=100" \
          --jq "[.[]|select(.user.login==\"$login\")]|length")" = 0 ] || { why=reply; break; }
  done
  if [ -z "$why" ] && [ "${SWEEP_FOLLOWUP_ON_PUSH:-0}" = 1 ]; then
    head=$(GH_HOST=$host gh api "repos/$repo/pulls/$n" --jq .head.sha)
    [ "$head" = "$last_sha" ] || why=push
  fi
  [ -n "$why" ] && printf '%s\t%s\t%s\t%s\tfollowup\t%s\n' "$host" "$repo" "$n" "$login" "$why"
  return 0
}

MODE=review; OUT=""; AUTHORS=""; ROOTS=(); WORKERS=3; MINCONF=0.75; POSTFLAGS=""; PROBES=8
case "${1:-}" in list|review|post|_probe) MODE=$1; shift;; esac
if [ "$MODE" = _probe ]; then probe "$@"; exit 0; fi
while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT=$2; shift 2;;
    --author) AUTHORS="$AUTHORS $2"; shift 2;;
    --clone-root) ROOTS+=("$2"); shift 2;;
    --workers) WORKERS=$2; shift 2;;
    --min-confidence) MINCONF=$2; shift 2;;
    --dry-run|--approve-clean) POSTFLAGS="$POSTFLAGS $1"; shift;;
    --followup-on-push) export SWEEP_FOLLOWUP_ON_PUSH=1; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
[ -n "$OUT" ] || { echo "--out DIR is required" >&2; exit 2; }
[ "$MODE" = post ] || [ -n "$AUTHORS" ] || { echo "pass at least one --author [host:]login" >&2; exit 2; }

sub_dir() { echo "$OUT/$1/${2//\//__}"; }

# Local checkout for owner/name: <clone-root>/<name> for the first root that
# has one, else a clone under $OUT/clones.
clone_dir() {
  local host=$1 repo=$2 name=${2##*/} r d
  for r in ${ROOTS[@]+"${ROOTS[@]}"}; do
    [ -d "$r/$name/.git" ] && { echo "$r/$name"; return; }
  done
  d="$OUT/clones/$host/$repo"
  [ -d "$d/.git" ] || git clone -q "https://$host/$repo.git" "$d" >&2
  echo "$d"
}

enumerate() {
  mkdir -p "$OUT"
  : > "$OUT/queue.tsv"; : > "$OUT/candidates.tsv"
  local spec host login me
  for spec in $AUTHORS; do
    case "$spec" in *:*) host=${spec%%:*}; login=${spec#*:};; *) host=github.com; login=$spec;; esac
    me=$(GH_HOST=$host gh api user --jq .login)
    GH_HOST=$host gh search prs --review-requested=@me --author "$login" --state open \
        --limit 300 --json number,repository --jq '.[]|[.repository.nameWithOwner,.number]|@tsv' \
      | awk -F'\t' -v h="$host" -v a="$login" '{print h"\t"$1"\t"$2"\t"a"\tpending\trequested"}' >> "$OUT/queue.tsv"
    GH_HOST=$host gh search prs --reviewed-by=@me --author "$login" --state open \
        --limit 300 --json number,repository,updatedAt \
        --jq '.[]|[.repository.nameWithOwner,.number,.updatedAt]|@tsv' \
      | awk -F'\t' -v h="$host" -v a="$login" -v m="$me" '{print h"\t"$1"\t"$2"\t"a"\t"$3"\t"m}' >> "$OUT/candidates.tsv"
  done
  # A candidate that is already pending needs no probe.
  awk -F'\t' 'NR==FNR {seen[$1 FS $2 FS $3]=1; next} !($1 FS $2 FS $3 in seen)' \
      "$OUT/queue.tsv" "$OUT/candidates.tsv" \
    | xargs -P "$PROBES" -L 1 "$HERE/sweep.sh" _probe >> "$OUT/queue.tsv"
  sort -u -o "$OUT/queue.tsv" "$OUT/queue.tsv"
  echo "queue: $(wc -l < "$OUT/queue.tsv" | tr -d ' ') PRs ($(cut -f6 "$OUT/queue.tsv" | sort | uniq -c | awk '{printf "%s%s %s", (NR>1?", ":""), $1, $2}'))" >&2
}

# One batch-review.sh run per (repo, class); follow-ups carry the extra focus.
review() {
  cut -f1,2 "$OUT/queue.tsv" | sort -u | while IFS=$'\t' read -r host repo; do
    local dir sub cls prs focus
    dir=$(clone_dir "$host" "$repo"); sub=$(sub_dir "$host" "$repo")
    for cls in pending followup; do
      prs=$(awk -F'\t' -v h="$host" -v r="$repo" -v c="$cls" '$1==h && $2==r && $5==c {print $3}' "$OUT/queue.tsv" \
              | sort -rn | tr '\n' ' ')
      [ -n "$prs" ] || continue
      echo "== $host $repo [$cls]: $prs"
      focus=""; [ "$cls" = followup ] && focus=$FOLLOWUP_FOCUS
      GH_HOST=$host "$HERE/batch-review.sh" --repo "$repo" --repo-dir "$dir" --out "$sub" \
        --prs "$prs" --workers "$WORKERS" --min-confidence "$MINCONF" ${focus:+--focus "$focus"}
    done
  done
}

post() {
  [ -s "$OUT/queue.tsv" ] || { echo "no queue.tsv in $OUT; run review first" >&2; exit 2; }
  cut -f1,2 "$OUT/queue.tsv" | sort -u | while IFS=$'\t' read -r host repo; do
    local sub; sub=$(sub_dir "$host" "$repo")
    [ -d "$sub/payloads" ] || continue
    echo "== $host $repo"
    GH_HOST=$host "$HERE/post-batch.sh" --repo "$repo" --out "$sub" $POSTFLAGS
  done
}

case "$MODE" in
  list) enumerate; cat "$OUT/queue.tsv";;
  review) enumerate; review;;
  post) post;;
esac
