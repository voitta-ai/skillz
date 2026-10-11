---
name: claude-code-plugin-python-bootstrap
description: |
  Bootstrap Python deps from a Claude Code plugin's hook script so
  `/plugin install` is one-click on systems without those deps already
  installed. Use when: (1) building a CC plugin whose hook (PreToolUse,
  PostToolUse, etc.) runs a Python script that imports third-party
  packages (tree-sitter, openai, requests, ...), (2) `/plugin install`
  succeeds but the hook silently no-ops on fresh systems with
  ImportError, (3) users hit `externally-managed-environment` (PEP 668)
  errors on recent Debian / Homebrew Python. Covers installing into the
  plugin's own `${CLAUDE_PLUGIN_DATA}` directory (no `--user`, no
  `--break-system-packages`), marker-file caching, content-hash
  invalidation on requirements bumps, and the never-break-session
  invariant.
author: Claude Code
version: 1.2.0
date: 2026-10-09
---

# Claude Code Plugin: Bootstrap Python Deps in Hook Script

## Problem

A Claude Code plugin that ships a hook script written in Python (or a
bash wrapper that execs Python) needs its third-party deps importable.
The naive options all fail:

- **Document `pip install -r requirements.txt`**: most users won't
  read it. `/plugin install` looks like it worked. The hook silently
  no-ops on every invocation because the Python script ImportErrors
  and the wrapper exits 0 (it has to — breaking the session is worse).
- **Vendor the wheels in the repo**: ~5MB+ per platform, hostile to
  platforms you didn't pre-build for.
- **Subprocess fork to a managed venv**: 100ms+ startup per hook fire,
  unacceptable for `PreToolUse` budgets.

The right answer is to have the plugin's wrapper script bootstrap the
deps itself on first run, then cache.

## Context / Trigger Conditions

- You're writing a CC plugin whose hook entry imports non-stdlib Python.
- After `/plugin install <plugin>@<marketplace>`, the hook does
  nothing visible. If the plugin has a log, it shows
  `ImportError: No module named X` or similar.
- Users report "it installed but isn't working." You realize the deps
  aren't on their Python.
- You want to keep the never-break-session invariant: a failing
  bootstrap must still let the user's command run (Claude Code default
  prompts).

## Solution

Wrap the Python entry point in a bash script that bootstraps deps on
first run into the plugin's data directory, with a content-hash-keyed
marker file.

Claude Code exports `CLAUDE_PLUGIN_DATA` (`~/.claude/plugins/data/<id>/`)
to hook processes. It survives plugin updates, unlike
`${CLAUDE_PLUGIN_ROOT}`, which is the versioned cache directory, and it is
removed on uninstall. Codex exports the same directory as `PLUGIN_DATA`
and also sets `CLAUDE_PLUGIN_DATA` as an alias. `pip install --target`
into it touches neither the system nor the user site, so PEP 668 never
applies and no `--break-system-packages` is needed.

```bash
#!/bin/bash
# hooks/pre-tool-use.sh — Claude Code plugin hook wrapper.
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REQS="$PLUGIN_ROOT/requirements.txt"
# Fallback only for running the wrapper by hand outside a host.
DATA_DIR="${CLAUDE_PLUGIN_DATA:-${PLUGIN_DATA:-$HOME/.cache/myplugin}}"
SITE="$DATA_DIR/site-packages"
export PYTHONPATH="$SITE${PYTHONPATH:+:$PYTHONPATH}"

bootstrap_deps() {
    # Marker keyed to requirements.txt content. A dep bump invalidates
    # the marker and re-bootstraps automatically.
    local cache_dir="$DATA_DIR"
    local sha
    if command -v shasum >/dev/null 2>&1; then
        sha="$(shasum -a 256 "$REQS" 2>/dev/null | awk '{print substr($1,1,12)}')"
    elif command -v sha256sum >/dev/null 2>&1; then
        sha="$(sha256sum "$REQS" 2>/dev/null | awk '{print substr($1,1,12)}')"
    else
        sha="nohash"
    fi
    local marker="$cache_dir/deps-installed-$sha"

    # Fast path: marker exists, trust it. ~ms bash file-exists test.
    if [[ -f "$marker" ]]; then
        return 0
    fi

    mkdir -p "$cache_dir" 2>/dev/null

    # Already importable from a previous install? Record and skip pip.
    # Costs one python3 startup the first time, never again.
    if python3 -c "import mydep1, mydep2" 2>/dev/null; then
        touch "$marker"
        return 0
    fi

    # Install into the plugin's own directory. --target skips pip's
    # externally-managed check, so this works on PEP 668 Pythons
    # (recent Debian, Homebrew) without --break-system-packages.
    if python3 -m pip install --quiet --disable-pip-version-check \
            --upgrade --target "$SITE" -r "$REQS" >/dev/null 2>&1; then
        touch "$marker"
        return 0
    fi

    # Bootstrap failed. Don't mark; retry next time. Hook still execs
    # the Python entry below, which is responsible for logging the
    # ImportError somewhere the user will see.
    return 1
}

bootstrap_deps || true

exec python3 "$SCRIPT_DIR/myplugin_entry.py" --hook
```

In the Python entry, wrap the import in try/except and silently exit on
ImportError (after logging to a known location so the user can diagnose):

```python
try:
    import mydep1, mydep2
except ImportError as e:
    _log("import-error", str(e))  # write to $CLAUDE_PLUGIN_DATA/log
    sys.exit(0)  # never break the session
```

## Verification

1. Remove the marker and the installed deps:
   `rm -rf ~/.claude/plugins/data/<id>/deps-installed-* ~/.claude/plugins/data/<id>/site-packages`.
2. Make sure the host Python does not already have them
   (`python3 -c "import mydep1"` fails).
3. Fire the hook (manually pipe a payload to the wrapper):
   `echo '{}' | CLAUDE_PLUGIN_DATA=~/.claude/plugins/data/<id> hooks/pre-tool-use.sh`.
4. Expect: deps install (~1-3s), marker appears, hook emits its normal
   output. Second invocation: instant (marker hot path).

## Notes

- **Don't install into the system or user site.** System-wide needs
  sudo, and `--user` / `--break-system-packages` writes into a Python
  the user owns and may break it. `--target "$CLAUDE_PLUGIN_DATA/..."`
  keeps the deps private to the plugin and gone on uninstall.
- **Don't shell out to `pip install` without the marker.** Every hook
  fire would take 1-3s probing/installing.
- **The marker MUST be content-keyed**, not just present/absent.
  Otherwise a requirements bump goes unnoticed and users keep running
  the old code.
- **Never put the marker or deps under the plugin dir.**
  `${CLAUDE_PLUGIN_ROOT}` is a per-version cache directory, so every
  update starts from an empty one. `${CLAUDE_PLUGIN_DATA}` is the
  directory the host keeps across updates.
- **Document the force-refresh path** in your README:
  `rm -rf ~/.claude/plugins/data/<id>/deps-installed-*` for users who
  switch Python versions. `<id>` is the plugin identifier with every
  character other than a letter, digit, `_` or `-` replaced by `-`.
- **Test the failure path.** Run the wrapper with `python3` aliased to
  something that ImportErrors and verify the hook exits 0 cleanly
  without breaking Claude Code's flow.

## Example

A plugin implementing this exact pattern uses a `hooks/pre-tool-use.sh`
entry point plus a `requirements.txt`-content-hash marker. The plugin
ships with tree-sitter + tree-sitter-bash deps that get bootstrapped on
the first Bash invocation after install.

## References

- [Claude Code plugin docs](https://code.claude.com/docs/en/plugins)
- [PEP 668: externally-managed-environment](https://peps.python.org/pep-0668/)

## Related

- `claude-code-plugin-from-existing-repo` — turning the repo into a plugin in
  the first place. This skill is the fix for the hook that comes with it.
- `claude-code-codex-plugin-parity` — Codex runs the same `hooks.json`, so a
  hook that bootstraps its own deps ports without change; the manifest around
  it does not.
- `claude-code-plugin-update-flow` — where an installed plugin's hook actually
  runs from, which is the path your bootstrap has to be correct relative to.
