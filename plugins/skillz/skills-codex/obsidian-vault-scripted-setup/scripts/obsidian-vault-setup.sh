#!/usr/bin/env bash
# Register an existing directory as an Obsidian vault (macOS), pre-seed
# regex exclusions that match at any depth, and reopen Obsidian on it.
#
# Usage: obsidian-vault-setup.sh <vault-root> [extra-excluded-name ...]
#
# Quits Obsidian (it rewrites its registry on exit), backs up the registry
# next to itself, adds the root, and merges exclusions into an existing
# <root>/.obsidian/app.json rather than replacing it. Other registered vaults
# are left alone; unregister or fold nested ones as described in SKILL.md.
set -euo pipefail

ROOT="$(cd "${1:?usage: $0 <vault-root> [extra-excluded-name ...]}" && pwd)"
shift
EXTRA="$*"
CFG="$HOME/Library/Application Support/obsidian/obsidian.json"

if [ -f "$CFG" ]; then
  cp "$CFG" "$CFG.bak-$(date +%Y%m%d%H%M%S)"
fi

if pgrep -xq Obsidian; then
  osascript -e 'quit app "Obsidian"' >/dev/null
  for _ in $(seq 1 30); do
    pgrep -xq Obsidian || break
    sleep 0.5
  done
  if pgrep -xq Obsidian; then
    echo "Obsidian did not quit; aborting before touching the registry" >&2
    exit 1
  fi
fi

mkdir -p "$ROOT/.obsidian"

python3 - "$CFG" "$ROOT" "$EXTRA" <<'EOF'
import json, os, secrets, sys, time

cfg, root, extra = sys.argv[1], sys.argv[2], sys.argv[3].split()

# Registry: re-read now, add the root if missing, print the result.
data = json.load(open(cfg)) if os.path.exists(cfg) else {}
vaults = data.setdefault("vaults", {})
if not any(v.get("path") == root for v in vaults.values()):
    vaults[secrets.token_hex(8)] = {
        "path": root,
        "ts": int(time.time() * 1000),
        "open": True,
    }
os.makedirs(os.path.dirname(cfg), exist_ok=True)
json.dump(data, open(cfg, "w"))
print(json.dumps(data, indent=1))

# Exclusions: segment-anchored regexes so nested folders match too.
filters = [
    "/(^|\\/)node_modules(\\/|$)/",
    "/(^|\\/)(dist|build|target|out|bin|obj|vendor|coverage)(\\/|$)/",
    "/(^|\\/)(venv|site-packages|__pycache__)(\\/|$)/",
    "/\\.worktrees(\\/|$)/",
]
filters += ["/(^|\\/)%s(\\/|$)/" % name for name in extra]

app_path = os.path.join(root, ".obsidian", "app.json")
app = json.load(open(app_path)) if os.path.exists(app_path) else {}
current = app.setdefault("userIgnoreFilters", [])
current += [f for f in filters if f not in current]
json.dump(app, open(app_path, "w"), indent=2)
print(open(app_path).read())
EOF

open "obsidian://open?path=$ROOT"
