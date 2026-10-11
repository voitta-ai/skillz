#!/bin/bash
# Drive an Android UI over adb: read the screen as text, tap elements by their
# label, type into the focused field without leaking the value into argv.
#
#   adb-ui.sh text                  # every visible string, one per line
#   adb-ui.sh tap "Save"            # tap the element whose text contains "Save"
#   adb-ui.sh tap-nth 2 Switch      # tap the 2nd element of a class (switches, etc.)
#   adb-ui.sh type                  # read a value on stdin and type it
#   adb-ui.sh has "Stop speaking"   # exit 0 if present -- for assertions
#
# ADB may be set to a full path if adb is not on PATH.
set -u
ADB=${ADB:-adb}
DUMP=/sdcard/adb-ui.xml

# Refuse to run without exactly one device. Otherwise every query returns
# nothing, `has` reports "absent", and an unplugged cable reads as a passing
# assertion. This guard is the whole point: a negative from a check that cannot
# observe anything is not evidence.
if [ "$($ADB devices | tail -n +2 | grep -cw device)" -ne 1 ]; then
  echo "adb-ui: need exactly one attached device; got:" >&2
  $ADB devices >&2
  exit 2
fi

dump() {
  $ADB shell uiautomator dump "$DUMP" > /dev/null 2>&1
  $ADB shell cat "$DUMP"
}

# uiautomator emits text='...' (single quotes) when the value itself contains a
# double quote -- which happens whenever an app surfaces a JSON error. A
# text="..." pattern alone silently misses exactly the strings worth reading.
strings_of() {
  dump | grep -oE "text=\"[^\"]+\"|text='[^']+'" | sed -E "s/^text=.//; s/.$//"
}

bounds_for() {
  dump | tr '<' '\n' | grep -F "$1" \
    | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1
}

bounds_nth() {
  dump | tr '<' '\n' | grep -iE "$2" \
    | grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | sed -n "$1p"
}

tap_bounds() {
  local b=$1 x1 y1 x2 y2
  [ -z "$b" ] && { echo "element not found" >&2; return 1; }
  x1=$(echo "$b" | grep -oE '[0-9]+' | sed -n 1p)
  y1=$(echo "$b" | grep -oE '[0-9]+' | sed -n 2p)
  x2=$(echo "$b" | grep -oE '[0-9]+' | sed -n 3p)
  y2=$(echo "$b" | grep -oE '[0-9]+' | sed -n 4p)
  # Tap the centre rather than a remembered coordinate: layouts move between
  # builds, and a stale coordinate taps whatever moved into its place.
  $ADB shell input tap $(( (x1 + x2) / 2 )) $(( (y1 + y2) / 2 ))
}

case "${1:-}" in
  text)    strings_of ;;
  has)     strings_of | grep -qF "$2" ;;
  tap)     tap_bounds "$(bounds_for "$2")" ;;
  tap-nth) tap_bounds "$(bounds_nth "$2" "$3")" ;;
  # The value arrives on stdin and is passed to the device shell on stdin, so it
  # never appears in argv, in `ps`, or in a shell history file.
  type)    IFS= read -r v; printf '%s' "$v" | $ADB shell 'IFS= read -r x; input text "$x"' ;;
  *)       sed -n '2,12p' "$0"; exit 1 ;;
esac
