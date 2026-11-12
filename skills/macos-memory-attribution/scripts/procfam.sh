#!/bin/bash
# Print "pid<TAB>family" for every process. Read-only.
# Family = executable basename. For interpreters and launchers (node, python, java, npm, uv, ...)
# the first non-flag argument is appended, so "node mcp-server-a" and "node app.js" differ;
# for npm/npx/uv the second non-flag argument is appended too ("npm exec server-a").
TMP="${TMPDIR:-/tmp}/procfam.$$"
ps -axo pid=,comm= > "$TMP.comm"
ps -axo pid=,args= > "$TMP.args"
awk '
FNR == NR { pid = $1; sub(/^[ ]*[0-9]+[ ]+/, ""); comm[pid] = $0; next }
{
  pid = $1
  a = $0
  sub(/^[ ]*[0-9]+[ ]+/, "", a)
  n = split(comm[pid], p, "/")
  base = p[n]
  fam = base
  if (base ~ /^[0-9]+(\.[0-9]+)+$/ && n > 1) fam = p[n - 1] "/" base
  if (base ~ /^(node|python|python3|python3\.[0-9]+|java|ruby|perl|bash|sh|zsh|uv|npm|npx)$/) {
    want = (base ~ /^(npm|npx|uv)$/) ? 2 : 1
    m = split(a, t, " ")
    got = 0
    for (i = 2; i <= m && got < want; i++) {
      if (t[i] !~ /^-/) {
        k = split(t[i], q, "/")
        fam = fam " " q[k]
        got++
      }
    }
  }
  printf "%s\t%s\n", pid, fam
}' "$TMP.comm" "$TMP.args"
rm -f "$TMP.comm" "$TMP.args"
