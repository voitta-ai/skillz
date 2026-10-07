#!/bin/bash
# Normalize `gradle dependencies` tree output to a sorted set of
# group:artifact:resolvedVersion, one per line.
#
# usage: classpath-set.sh [configuration]            # runs gradle itself
#        classpath-set.sh --from-file <tree.txt>     # normalizes saved output
#
# The resolved version is what matters, so the conflict-resolution form
# `1.2.3 -> 4.5.6` must normalize to 4.5.6, not 1.2.3. That single rule is why a
# hand-rolled diff of the raw tree misreports: the tree prints the REQUESTED
# version on the left.
set -euo pipefail

normalize() {
  sed -E \
    -e 's/\r$//' \
    -e 's/^[^a-zA-Z]*//' \
    -e 's/ \(n\)$//' \
    -e 's/ \(\*\)$//' \
    -e 's/ \(c\)$//' \
    |
  sed -E \
    -e 's/^([^:]+):([^:]+):([^ ]+) -> ([^ ]+).*$/\1:\2:\4/' \
    -e 's/^([^:]+):([^:]+):([^ ]+)$/\1:\2:\3/' \
    |
  grep -E '^[^:]+:[^:]+:[^:]+$' | sort -u
}

if [ "${1:-}" = "--from-file" ]; then
  normalize < "$2"
else
  ./gradlew -q dependencies --configuration "${1:-runtimeClasspath}" | normalize
fi
