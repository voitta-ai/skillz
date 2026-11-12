#!/bin/bash
# Sum the "page table" row of footprint over every process footprint can read (your own), by family,
# and compare with the kernel's VM_KERN_MEMORY_PTE tag from zprint. Read-only; takes about a minute.
# usage: pagetables_by_family.sh [rows, default 15]
ROWS="${1:-15}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="${TMPDIR:-/tmp}/ptf.$$"

ps -axo pid= > "$TMP.pids"
one() {
  pid="$1"
  v=$(footprint -f bytes "$pid" 2>/dev/null | awk '/page table/ { x = $1; gsub(/[^0-9]/, "", x); print x; exit }')
  echo "$pid ${v:-NA}"
}
export -f one
xargs -P 4 -n 1 bash -c 'one "$0"' < "$TMP.pids" > "$TMP.pt" 2>/dev/null
bash "$HERE/procfam.sh" > "$TMP.fam"

echo "cols: page-table MiB | readable/total processes | average MiB | family"
awk '
FNR == NR { pt[$1] = $2; next }
{
  split($0, a, "\t")
  n[a[2]]++
  if ((a[1] in pt) && pt[a[1]] != "NA") { s[a[2]] += pt[a[1]]; r[a[2]]++; tot += pt[a[1]]; tr++ }
}
END {
  for (f in n) printf "%9.0f MiB  %4d / %4d  avg %6.2f  %s\n", s[f] / 1048576, r[f], n[f], (r[f] ? s[f] / r[f] / 1048576 : 0), f
  printf "%9.0f MiB  %4d readable  TOTAL (unreadable processes are not counted: need root)\n", tot / 1048576, tr
}' "$TMP.pt" "$TMP.fam" | sort -rn | head -n "$((ROWS + 1))"
rm -f "$TMP.pids" "$TMP.pt" "$TMP.fam"

echo "--- kernel view (zprint works without root; zone sizes show 0K without root) ---"
zprint 2>/dev/null | awk '/VM_KERN_MEMORY_PTE|VM_KERN_COUNT_WIRED[ ]/ { v = $NF; sub(/K$/, "", v); printf "%-28s %9.0f MiB\n", $1, v / 1024 }'
