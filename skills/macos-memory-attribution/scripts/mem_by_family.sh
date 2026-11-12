#!/bin/bash
# Sum top's CMPRS (compressed + swapped, LOGICAL size) and MEM by process family, then reconcile with vm_stat. Read-only.
# usage: mem_by_family.sh [rows, default 20]
# Columns: CMPRS_MiB  MEM_MiB  process_count  family     (first row is the total)
ROWS="${1:-20}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="${TMPDIR:-/tmp}/mbf.$$"
top -l 1 -stats pid,mem,cmprs -n 5000 2>/dev/null | awk '/^PID/ { go = 1; next } go && NF >= 3 { print $1, $2, $3 }' > "$TMP.top"
bash "$HERE/procfam.sh" > "$TMP.fam"
awk '
function mib(s,   u, v) {
  sub(/[+-]$/, "", s)
  u = substr(s, length(s)); v = s; gsub(/[^0-9.]/, "", v); v = v + 0
  if (u == "G") return v * 1024
  if (u == "M") return v
  if (u == "K") return v / 1024
  if (u == "B") return v / 1048576
  return v
}
FNR == NR { mem[$1] = mib($2); cm[$1] = mib($3); next }
{
  split($0, a, "\t")
  if (a[1] in cm) {
    c[a[2]] += cm[a[1]]; m[a[2]] += mem[a[1]]; k[a[2]]++
    tc += cm[a[1]]; tm += mem[a[1]]; tk++
  }
}
END {
  for (f in c) printf "%9.0f %9.0f %5d  %s\n", c[f], m[f], k[f], f
  printf "%9.0f %9.0f %5d  TOTAL\n", tc, tm, tk
}' "$TMP.top" "$TMP.fam" | sort -rn | head -n "$((ROWS + 1))"
rm -f "$TMP.top" "$TMP.fam"

echo "--- reconcile: top CMPRS total should be close to vm_stat pages stored in compressor ---"
PAGE=$(vm_stat | awk '/page size of/ { print $8 }')
STORED=$(vm_stat | awk '/Pages stored in compressor/ { gsub(/[^0-9]/, "", $NF); print $NF }')
SWAP=$(sysctl -n vm.swapusage)
awk -v s="$STORED" -v p="$PAGE" 'BEGIN { printf "vm_stat stored in compressor: %.0f MiB (%d pages of %d bytes)\n", s * p / 1048576, s, p }'
echo "swap: $SWAP"
