---
name: personal-skills-shadow-bundle-audit
description: |
  Audit and clean up personal `~/.claude/skills/` copies that duplicate or
  shadow skills a plugin bundle also ships, so sessions stop silently running
  stale versions. Use when: (1) a skill you know was updated upstream behaves
  like an old version (e.g. it ran at 4.0.0 while the installed bundle ships
  4.1.0), (2) you are asked "can I just delete the local copy?" of a skill
  that also exists in a plugin, (3) `~/.claude/skills/` has accumulated copies
  of skills that later moved into a plugin bundle, (4) a skill appears in the
  session's skill list bare (no `plugin:` prefix) and you need to know which
  file on disk that actually is, (5) after installing or updating a bundle
  plugin you want to retire the loose per-skill installs it replaced. Key
  trap: `~/.claude/plugins/marketplaces/<mkt>/` is the fetched marketplace
  source, NOT loaded — only plugins present under `~/.claude/plugins/cache/`
  serve skills, and a bundle can turn out not installed at all, leaving the
  personal copies as the sole (stale) provider. Covers the audit commands
  (version drift table, two-way content diff against the cache copy), the
  delete / keep decision tree (byte-identical, version-behind with superseded
  wording, genuine unpushed fork), and the tar backup before any rm.
author: Claude Code
version: 1.0.0
date: 2026-08-27
source: https://github.com/voitta-ai/skillz
source_file: skills/personal-skills-shadow-bundle-audit/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/personal-skills-shadow-bundle-audit/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR.

# personal-skills-shadow-bundle-audit

## Problem

Skills often start life as loose directories under `~/.claude/skills/` and
later get collected into a plugin bundle. Nothing cleans up the loose copies.
The result, found on a real machine in one audit (2026-08-27): **38 personal
skills duplicated bundle skills, and 11 were stale copies actively driving
sessions** — one skill ran at 4.0.0 in the very session doing the audit while
the installed bundle shipped 4.1.0; another was at 1.9.0 against a bundle
1.11.0. The session had no idea: a bare skill name in the skill list looks the
same whether it loads from a current bundle or a months-old personal copy.

The failure is silent in both directions:

- **Stale shadow**: the personal copy loads, the newer bundle version (with
  fixes you may have PR'd yourself) never runs.
- **Deleted too eagerly**: "it's a duplicate, just remove it" — but if the
  bundle plugin is not actually installed, the personal copy was the ONLY
  provider, and deleting it makes the skill vanish from sessions entirely.

## The layout that decides everything

Three directories look interchangeable and are not:

| Path | What it is | Loaded into sessions? |
|---|---|---|
| `~/.claude/skills/<name>/` | loose personal skill install | yes |
| `~/.claude/plugins/marketplaces/<mkt>/` | git clone of the marketplace repo — **fetched source** | **NO** |
| `~/.claude/plugins/cache/<mkt>/<plugin>/<ver>/` | installed plugin — the copy that serves | yes |

The trap in the middle row: seeing the skill at the right version under
`marketplaces/` proves nothing. In the audited case the marketplace clone had
the current version of everything while `cache/` contained a single unrelated
plugin — the bundle was **not installed**, so all 63 of its skills were being
served exclusively by the personal copies. Check what is installed, not what
is fetched:

```bash
# Is the bundle actually installed? (cache, not marketplaces)
ls ~/.claude/plugins/cache/<mkt>/ 2>/dev/null

# Where does one specific skill resolve from?
find ~/.claude/plugins/cache -maxdepth 6 -type d -name "<skill-name>" 2>/dev/null
ls -la ~/.claude/skills/<skill-name>/ 2>/dev/null
```

If the bundle is missing, install it FIRST (`claude plugin marketplace update
<mkt> && claude plugin install <plugin>@<mkt>`), verify the skill exists under
`cache/` at a version >= the personal copy, and only then consider deleting
anything.

## Audit

Set `B` to the bundle's skills directory inside the cache (layout varies per
plugin — in skillz it is `skills-claude/`; discover it rather than guess):

```bash
B=$(dirname "$(find ~/.claude/plugins/cache/<mkt> -path "*/<any-known-skill>/SKILL.md" | head -1)")
B=$(dirname "$B")   # .../skills-claude (or .../skills)
S=~/.claude/skills
```

**1. Version drift table** — every personal skill the bundle also ships:

```bash
for d in "$S"/*/; do
  n=$(basename "$d")
  if [ -d "$B/$n" ]; then
    pv=$(awk -F': ' '/^version:/{print $2;exit}' "$d/SKILL.md" 2>/dev/null)
    bv=$(awk -F': ' '/^version:/{print $2;exit}' "$B/$n/SKILL.md" 2>/dev/null)
    printf "%-52s personal=%-8s bundle=%-8s%s\n" "$n" "${pv:-?}" "${bv:-?}" \
      "$([ "$pv" != "$bv" ] && echo '  <- DRIFT')"
  fi
done
echo "=== personal skills NOT in the bundle (keep, they are genuinely local) ==="
for d in "$S"/*/; do n=$(basename "$d"); [ -d "$B/$n" ] || echo "  $n"; done
```

**2. Back up, then classify content** — whole-directory diff plus a check for
files the personal copy has that the bundle lacks:

```bash
BK=/tmp/skills-backup-$(date +%Y%m%d-%H%M%S)   # or your session scratchpad
mkdir -p "$BK"
for d in "$S"/*/; do
  n=$(basename "$d"); [ -d "$B/$n" ] || continue
  extra=$(cd "$d" && find . -type f | sort | comm -23 - <(cd "$B/$n" && find . -type f | sort) | tr '\n' ' ')
  same=$(diff -rq "$d" "$B/$n" >/dev/null 2>&1 && echo IDENTICAL || echo differs)
  printf "%-52s %-10s %s\n" "$n" "$same" "${extra:+EXTRA-FILES: $extra}"
  cp -R "$d" "$BK/$n"
done
tar -C "$(dirname "$BK")" -czf "$BK.tgz" "$(basename "$BK")"
```

**3. For the `differs` rows, count personal-only content** (lines in the
personal SKILL.md absent from the bundle's, ignoring the version/date
frontmatter that always differs):

```bash
for d in "$S"/*/; do
  n=$(basename "$d"); [ -d "$B/$n" ] || continue
  diff -rq "$d" "$B/$n" >/dev/null 2>&1 && continue
  uniq=$(comm -23 <(grep -vE '^(version|date):' "$d/SKILL.md" | sed '/^$/d' | sort -u) \
                  <(grep -vE '^(version|date):' "$B/$n/SKILL.md" | sed '/^$/d' | sort -u) | wc -l | tr -d ' ')
  if [ "$uniq" -eq 0 ]; then v="SAFE - bundle is superset"; else v="INSPECT - $uniq personal-only lines"; fi
  printf "%-52s %5s  %s\n" "$n" "$uniq" "$v"
done
```

**4. Read the personal-only lines** for each INSPECT row before deciding:

```bash
comm -23 <(grep -vE '^(version|date):' "$S/$n/SKILL.md" | sed '/^$/d' | sort -u) \
         <(grep -vE '^(version|date):' "$B/$n/SKILL.md" | sed '/^$/d' | sort -u) | head -30
```

## Decision tree

For each personal copy the bundle also ships:

- **Byte-identical** (`diff -rq` clean) → delete. Pure redundancy.
- **Version-behind AND personal-only lines are superseded wording** — the
  bundle rephrased or replaced them (you can find the newer wording covering
  the same point in the bundle copy) → delete. In the audited run this held
  for every version-behind skill checked: the "unique" lines were old
  phrasings the newer bundle version had rewritten, e.g. a worktree path
  convention the upstream repo had since fixed. Verify per-skill; do not
  assume.
- **Same version but content differs, or personal-only lines that are NEW
  material** (a section, a pattern, a recovery procedure the bundle has
  nowhere) → this is a **genuine unpushed fork**, not a duplicate. Keep it,
  and open a PR contributing the delta upstream; delete only after that
  merges and the updated bundle is installed. The audited run found 2 of
  these among 38 — same version string as the bundle, ~28 new lines each.
  The same-version-but-differing shape is exactly what unpushed local edits
  look like; it is the one category where deletion destroys work.

Then delete with an explicit keep-list, never a bare glob:

```bash
KEEP="<fork-skill-1> <fork-skill-2>"
del=0
for d in "$S"/*/; do
  n=$(basename "$d"); [ -d "$B/$n" ] || continue
  case " $KEEP " in *" $n "*) echo "KEPT  $n"; continue ;; esac
  rm -rf "$d" && del=$((del+1))
done
echo "deleted: $del"; ls "$S"
```

## Verification

- Skills genuinely local (not in the bundle) are untouched — the `[ -d
  "$B/$n" ] || continue` guard is what protects them; re-list them after.
- In a NEW session, the skill list still shows the affected skills (now via
  the plugin) and a version-sensitive one behaves like the bundle version.
  The current session's list was assembled at startup and will not reflect
  the deletions.
- The backup tarball exists and lists all deleted names:
  `tar -tzf "$BK.tgz" | cut -d/ -f2 | sort -u`.

## Notes

- **Check for `.git` before deleting.** One personal copy in the audited run
  was itself a git clone (of the upstream project it was vendored from); its
  `.git` history went with the `rm`. Content survived upstream, but run
  `ls -d "$S"/*/.git` first and think before deleting any hit.
- Version-drift direction matters: personal AHEAD of bundle means either the
  bundle plugin needs `claude plugin update`, or the personal copy carries an
  unreleased edit — treat as the fork case, not the stale case.
- After the cleanup, new skill work should land in the repo behind the bundle
  (worktree + PR), not back into `~/.claude/skills/` — that is how the drift
  started.

## Related

- `claude-code-plugin-update-flow` — owns the marketplaces-vs-cache layout in
  detail and how a plugin update actually lands in `cache/`; this skill only
  uses that layout to answer "which copy is serving".
- `claude-code-plugin-from-existing-repo` — how skills get bundled into a
  plugin in the first place.
