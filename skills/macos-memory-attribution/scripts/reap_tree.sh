#!/bin/bash
# Capture a process tree now, signal it later, and only touch processes that still match the capture
# (pid + start time + command), so a reused PID is never hit.
#   reap_tree.sh capture '<ERE matching the ROOT processes args>' <file>
#       file gets pid|rootpid|lstart|command for each root and every descendant. This script and its own parents are excluded.
#   reap_tree.sh alive <file>                       count captured processes still alive and unchanged
#   reap_tree.sh signal <TERM|KILL|...> <file> [skip-ERE]
#       send the signal to alive, unchanged captured processes; commands matching skip-ERE are left alone
#       (pass 'docker run' so a killed docker client does not orphan its container: use TERM for those)
# Typical order: ask the owner to shut down cleanly, wait ~6 s, `alive`, `signal TERM`, wait ~8 s, `alive`, then `signal KILL`.
MODE="$1"

same_as_capture() {
  # args: pid lstart command ; succeeds if the live process still has that start time and command
  cur=$(ps -o lstart=,command= -p "$1" 2>/dev/null)
  if [ -z "$cur" ]; then
    return 1
  fi
  curls=$(echo "$cur" | awk '{ print $1 " " $2 " " $3 " " $4 " " $5 }')
  curcmd=$(echo "$cur" | awk '{ c = ""; for (i = 6; i <= NF; i++) c = c (i > 6 ? " " : "") $i; print c }')
  if [ "$curls" = "$2" ] && [ "$curcmd" = "$3" ]; then
    return 0
  fi
  return 1
}

if [ "$MODE" = "capture" ]; then
  RE="$2"
  OUT="$3"
  ps -axo pid=,ppid=,lstart=,command= | awk -v re="$RE" -v me="$$" '
  {
    pid = $1; ppid[pid] = $2
    ls[pid] = $3 " " $4 " " $5 " " $6 " " $7
    c = ""
    for (i = 8; i <= NF; i++) c = c (i > 8 ? " " : "") $i
    cmd[pid] = c
    order[++n] = pid
  }
  END {
    for (i = 1; i <= n; i++) {
      p = order[i]
      if (cmd[p] ~ re && cmd[p] !~ /reap_tree\.sh/ && p != me) root[p] = 1
    }
    for (i = 1; i <= n; i++) {
      p = order[i]; r = p; d = 0; found = 0
      while (d < 60) {
        if (r in root) { found = 1; break }
        if (!(r in ppid) || ppid[r] <= 1) break
        r = ppid[r]; d++
      }
      if (found && cmd[p] !~ /reap_tree\.sh/) print p "|" r "|" ls[p] "|" cmd[p]
    }
  }' > "$OUT"
  echo "captured $(wc -l < "$OUT" | tr -d ' ') processes into $OUT"
  exit 0
fi

FILE="$2"
if [ "$MODE" = "alive" ]; then
  n=0
  while IFS='|' read -r pid root ls cmd; do
    if same_as_capture "$pid" "$ls" "$cmd"; then
      n=$((n + 1))
    fi
  done < "$FILE"
  echo "$n"
  exit 0
fi

if [ "$MODE" = "signal" ]; then
  SIG="$2"
  FILE="$3"
  SKIP="$4"
  n=0
  while IFS='|' read -r pid root ls cmd; do
    if ! same_as_capture "$pid" "$ls" "$cmd"; then
      continue
    fi
    if [ -n "$SKIP" ] && echo "$cmd" | grep -E -q "$SKIP"; then
      continue
    fi
    if kill "-$SIG" "$pid" 2>/dev/null; then
      n=$((n + 1))
    fi
  done < "$FILE"
  echo "signalled $n"
  exit 0
fi

echo "usage: reap_tree.sh capture <root-ERE> <file> | alive <file> | signal <SIG> <file> [skip-ERE]"
exit 1
