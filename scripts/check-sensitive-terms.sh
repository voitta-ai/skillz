#!/usr/bin/env bash
#
# check-sensitive-terms.sh - pre-publish gate for the public skillz catalog.
#
# Greps the given files/dirs for content that must NEVER land in the public
# repo (per the hard rule: no account IDs, keys, client names, internal
# domains, or infra topology). Exits non-zero if anything matches, so it can
# gate a skill-promotion step or CI.
#
# The paradox this design resolves: a denylist of *client names* is itself
# sensitive and cannot be checked into the public repo. So this script ships
# only STRUCTURAL patterns (safe to be public - key/token/account-id shapes,
# private IPs, internal-domain suffixes) and reads any name-based terms from a
# PRIVATE, out-of-repo wordlist (one term per line; blank lines and lines
# starting with # are ignored). The wordlist is read from
# $SKILLZ_SENSITIVE_TERMS_FILE, defaulting to
# ~/.config/skillz/sensitive-terms.txt when that is unset.
#
# Usage:
#   scripts/check-sensitive-terms.sh <path> [<path> ...]
#   SKILLZ_SENSITIVE_TERMS_FILE=/other/list.txt \
#     scripts/check-sensitive-terms.sh skills/my-skill/
#
# Exit codes: 0 = clean, 1 = matches found, 2 = usage error or a
# SKILLZ_SENSITIVE_TERMS_FILE that was set but does not exist.
#
# bash 3.2 compatible (macOS default); no bashisms beyond 3.2.

set -u

if [ "$#" -eq 0 ]; then
  echo "usage: $0 <path> [<path> ...]" >&2
  exit 2
fi

# Structural patterns - safe to live in the public repo. Extended-regex.
# Each entry: "label|regex".
STRUCTURAL="
aws-account-id|(^|[^0-9])[0-9]{12}([^0-9]|$)
aws-access-key|AKIA[0-9A-Z]{16}
aws-secret-key|(^|[^A-Za-z0-9/+])[A-Za-z0-9/+]{40}([^A-Za-z0-9/+]|$)
slack-bot-token|xox[baprs]-[0-9A-Za-z-]{10,}
slack-app-token|xapp-[0-9]-[0-9A-Za-z-]{10,}
github-token|gh[posru]_[0-9A-Za-z]{30,}
openai-key|(^|[^A-Za-z0-9_-])sk-(proj-)?[A-Za-z0-9]{20,}
google-api-key|AIza[0-9A-Za-z_-]{30,}
private-key-block|-----BEGIN [A-Z ]*PRIVATE KEY-----
private-ip-10|(^|[^0-9])10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}
private-ip-192|(^|[^0-9])192\.168\.[0-9]{1,3}\.[0-9]{1,3}
private-ip-172|(^|[^0-9])172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3}
internal-domain|[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?\.(internal|corp|intranet)\b
"

status=0

# Set to "-i" by the wordlist pass: names are written in every casing
# (Foo, foo, FOO), so a case-sensitive term match misses most of them.
# Structural patterns stay case-SENSITIVE on purpose - AKIA, sk-, xoxb-,
# AIza are fixed-case prefixes, and -i would only add false positives.
CASE_FLAG=""

# Set to "-w" by the wordlist pass: a name is matched as a WHOLE WORD.
# Without it a short listed term matches inside unrelated longer words - an
# identifier like `labelLarge`, or an ordinary English word that happens to
# contain the name - and the gate blocks pushes that leak nothing. Structural
# patterns never get -w: they carry their own anchors and boundaries, and -w
# would break the ones that legitimately match mid-token.
WORD_FLAG=""

check_pattern() {
  label="$1"
  regex="$2"
  shift 2
  # grep -rEn over the paths; -I skips binaries. Suppress the "no match" exit.
  matches=$(grep -rEnI $CASE_FLAG $WORD_FLAG "$regex" "$@" 2>/dev/null)
  if [ -n "$matches" ]; then
    echo "SENSITIVE [$label]:" >&2
    echo "$matches" | sed 's/^/  /' >&2
    status=1
  fi
}

# 1) structural patterns
echo "$STRUCTURAL" | while IFS='|' read -r label regex; do
  [ -z "$label" ] && continue
  echo "${label}|${regex}"
done > /tmp/.skillz_structural.$$
# (piping into a while-subshell loses $status in bash 3.2; iterate via a temp file)
while IFS='|' read -r label regex; do
  [ -z "$label" ] && continue
  check_pattern "$label" "$regex" "$@"
done < /tmp/.skillz_structural.$$
rm -f /tmp/.skillz_structural.$$

# 2) optional private wordlist (client/account names etc.)
DEFAULT_TERMS_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/skillz/sensitive-terms.txt"
terms_file="${SKILLZ_SENSITIVE_TERMS_FILE:-$DEFAULT_TERMS_FILE}"

if [ -f "$terms_file" ]; then
  CASE_FLAG="-i"
  WORD_FLAG="-w"
  while IFS= read -r term; do
    case "$term" in
      ""|\#*) continue ;;
    esac
    # Case-insensitive, whole-word; the term is treated as an extended regex.
    check_pattern "private-term" "$term" "$@"
  done < "$terms_file"
  CASE_FLAG=""
  WORD_FLAG=""
elif [ -n "${SKILLZ_SENSITIVE_TERMS_FILE:-}" ]; then
  # Explicitly pointed at a file that isn't there - that is an error, not a
  # silent downgrade to structural-only.
  echo "error: SKILLZ_SENSITIVE_TERMS_FILE=$SKILLZ_SENSITIVE_TERMS_FILE does not exist" >&2
  exit 2
else
  echo "note: no name wordlist - structural checks only." >&2
  echo "      create $DEFAULT_TERMS_FILE (one term per line, # for comments)" >&2
  echo "      to also match client/employer names. Keep it OUT of this repo." >&2
fi

if [ "$status" -eq 0 ]; then
  echo "check-sensitive-terms: clean"
fi
exit "$status"
