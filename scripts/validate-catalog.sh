#!/usr/bin/env bash
set -euo pipefail

# Validate the skillz catalog:
# 1. Every skill referenced in catalog.json has a SKILL.md at its declared path.
# 2. Every SKILL.md begins with a YAML frontmatter block containing `name:`
#    and `description:`.
# 3. Every skill directory on disk is declared in catalog.json (the reverse of
#    check 1 - an undeclared dir is invisible to install.sh, the bundle
#    plugin, and the README, so it ships as a silent no-op).
# 4. Every collection (inline in catalog.json AND in collections/*.json)
#    references known skills.
# 5. install.sh --dry-run works for: default no-arg, --collection pr-loop,
#    --skill work-on-pr, --all.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CATALOG="$ROOT/catalog.json"

if [[ ! -f "$CATALOG" ]]; then
  echo "error: $CATALOG not found" >&2
  exit 2
fi

fail=0
note() { echo "  $*"; }
err()  { echo "ERROR: $*" >&2; fail=1; }

echo "Validating catalog at $CATALOG"

# Pass the catalog by PATH, not by value. Linux caps any single argv/env
# string at MAX_ARG_STRLEN (32 pages = 131072 bytes) and raises E2BIG past it,
# while macOS has no per-string cap - so `CATALOG_JSON="$(cat ...)"` worked on
# every developer machine and died in CI the moment catalog.json crossed 128 KiB,
# with `/usr/bin/python3: Argument list too long` and exit 126. The file grows
# by roughly a kilobyte per skill, so this was a cliff the catalog was always
# going to walk off, not a property of any one PR.
CATALOG="$CATALOG" ROOT="$ROOT" python3 <<'PY'
import collections, json, os, re, sys

root = os.environ["ROOT"]
with open(os.environ["CATALOG"]) as fh:
    catalog = json.load(fh)

errors = []

skills = catalog.get("skills", [])
skill_names = set()
for s in skills:
    name = s.get("name")
    path = s.get("path")
    if not name or not path:
        errors.append(f"skill entry missing name/path: {s}")
        continue
    skill_names.add(name)
    abs_path = os.path.join(root, path)
    if not os.path.isfile(abs_path):
        errors.append(f"skill '{name}' path does not exist: {path}")
        continue
    with open(abs_path) as f:
        head = f.read(4096)
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", head, re.DOTALL)
    if not m:
        errors.append(f"skill '{name}' SKILL.md missing YAML frontmatter block")
        continue
    fm = m.group(1)
    if not re.search(r"(?m)^name\s*:", fm):
        errors.append(f"skill '{name}' frontmatter missing `name:`")
    if not re.search(r"(?m)^description\s*:", fm):
        errors.append(f"skill '{name}' frontmatter missing `description:`")

skill_hosts = {s.get("name"): s.get("hosts", []) for s in skills}

# `files` must list every non-SKILL.md file in the skill's directory. install.sh
# copies the whole directory from a local clone, but over curl it can only fetch
# what is declared here - so an undeclared sibling installs for clone users and
# silently goes missing for curl users, which is the worse of the two failures
# because nothing errors.
for s in skills:
    name, path = s.get("name"), s.get("path")
    if not name or not path:
        continue
    skill_dir = os.path.join(root, os.path.dirname(path))
    if not os.path.isdir(skill_dir):
        continue
    on_disk = set()
    for dirpath, dirnames, filenames in os.walk(skill_dir):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), skill_dir)
            if rel == "SKILL.md" or fn.endswith((".pyc", ".pyo")) or fn == ".DS_Store":
                continue
            on_disk.add(rel)
    declared = set(s.get("files", []))
    for missing in sorted(on_disk - declared):
        errors.append(
            f"skill '{name}' ships {missing} but does not declare it in "
            f"`files` - curl installs would silently omit it"
        )
    for extra in sorted(declared - on_disk):
        errors.append(
            f"skill '{name}' declares files entry '{extra}' which is not on "
            f"disk - a curl install would 404"
        )

# Reverse of the check above: every skill dir on disk must be declared.
# An undeclared dir is invisible to install.sh (including --all), to the
# skillz bundle plugin, and to the README table - it ships as a silent no-op,
# so the author thinks it landed and review sees a green check.
#
# Declared paths are matched rather than directory names, since a catalog
# entry's `name` and its directory need not agree.
declared_dirs = {
    os.path.normpath(os.path.dirname(s["path"]))
    for s in skills
    if s.get("path")
}
skills_root = os.path.join(root, "skills")
if os.path.isdir(skills_root):
    for entry in sorted(os.listdir(skills_root)):
        entry_path = os.path.join(skills_root, entry)
        # Plain files at the top level are left alone, so a future
        # skills/README.md describing the layout would not trip this.
        if not os.path.isdir(entry_path):
            continue
        rel = os.path.normpath(os.path.join("skills", entry))
        if not os.path.isfile(os.path.join(entry_path, "SKILL.md")):
            errors.append(
                f"'{rel}' has no SKILL.md - not a skill; remove it or add one"
            )
            continue
        if rel not in declared_dirs:
            errors.append(
                f"'{rel}' has a SKILL.md but no catalog.json entry - it will "
                f"not install; add it to catalog.json or delete the directory"
            )

# Inline collections in catalog.json
for c in catalog.get("collections", []):
    cname = c.get("name", "<unnamed>")
    for sn in c.get("skills", []):
        if sn not in skill_names:
            errors.append(f"collection '{cname}' references unknown skill '{sn}'")
    cpath = c.get("path")
    if cpath:
        abs_path = os.path.join(root, cpath)
        if not os.path.isfile(abs_path):
            errors.append(f"collection '{cname}' path does not exist: {cpath}")
        else:
            with open(abs_path) as f:
                cdata = json.load(f)
            for sn in cdata.get("skills", []):
                if sn not in skill_names:
                    errors.append(f"collection file '{cpath}' references unknown skill '{sn}'")

# Plugin assets referenced by manifests
for p in catalog.get("plugins", []):
    pname = p.get("name", "<unnamed>")
    for key in (
        "claude_manifest",
        "claude_marketplace",
        "codex_manifest",
        "codex_marketplace",
    ):
        rel = p.get(key)
        if rel and not os.path.isfile(os.path.join(root, rel)):
            errors.append(f"plugin '{pname}' missing {key}: {rel}")

    # For each host manifest (claude_manifest -> claude, codex_manifest ->
    # codex), read that manifest's own `skills` path and verify the dir it
    # points at holds exactly the host-applicable subset of the plugin's
    # declared skills. A claude-only skill must not appear in the codex
    # manifest's dir, and vice versa. Every symlink must resolve under
    # skills/.
    declared_skills = list(p.get("skills", []))
    for key, host in (("claude_manifest", "claude"), ("codex_manifest", "codex")):
        rel = p.get(key)
        if not rel or not rel.startswith("plugins/"):
            continue
        manifest_path = os.path.join(root, rel)
        if not os.path.isfile(manifest_path):
            continue  # missing-manifest already reported above
        plugin_root = os.path.dirname(os.path.dirname(rel))
        try:
            with open(manifest_path) as mf:
                manifest = json.load(mf)
        except ValueError as e:
            errors.append(f"plugin '{pname}' {key} is not valid JSON: {e}")
            continue
        skills_field = manifest.get("skills", "./skills/")
        skills_paths = (
            skills_field if isinstance(skills_field, list) else [skills_field]
        )
        # Claude Code always also scans a default skills/ dir alongside any
        # listed dir, so a leftover skills/ would re-expose every skill even
        # when the manifest points elsewhere. Guard against that.
        norm_paths = {pp.strip("./").rstrip("/") for pp in skills_paths}
        if "skills" not in norm_paths and os.path.isdir(
            os.path.join(root, plugin_root, "skills")
        ):
            errors.append(
                f"plugin '{pname}' {key} points at {skills_paths} but a "
                f"default {plugin_root}/skills/ dir still exists "
                f"(always-scanned; would re-expose skills)"
            )
        expected = {s for s in declared_skills if host in skill_hosts.get(s, [])}
        symlink_skills = set()
        for sp in skills_paths:
            skills_dir = os.path.normpath(os.path.join(root, plugin_root, sp))
            reldir = os.path.relpath(skills_dir, root)
            if not os.path.isdir(skills_dir):
                errors.append(f"plugin '{pname}' {key} skills dir missing: {reldir}")
                continue
            for entry in sorted(os.listdir(skills_dir)):
                link_path = os.path.join(skills_dir, entry)
                if not os.path.islink(link_path):
                    continue
                target = os.path.realpath(link_path)
                expected_prefix = os.path.realpath(os.path.join(root, "skills"))
                if not target.startswith(expected_prefix):
                    errors.append(
                        f"plugin '{pname}' symlink {reldir}/{entry} -> "
                        f"{target} escapes skills/"
                    )
                    continue
                if not os.path.isdir(target):
                    errors.append(
                        f"plugin '{pname}' symlink {reldir}/{entry} broken: "
                        f"{target} not a directory"
                    )
                    continue
                symlink_skills.add(entry)
        if declared_skills and symlink_skills != expected:
            missing = expected - symlink_skills
            extra = symlink_skills - expected
            if missing:
                errors.append(
                    f"plugin '{pname}' {key} dir missing symlinks for: "
                    f"{sorted(missing)}"
                )
            if extra:
                errors.append(
                    f"plugin '{pname}' {key} dir has unexpected symlinks: "
                    f"{sorted(extra)}"
                )

# A skill that ships inside a hooked plugin stays out of the bundle. Installing
# both is the common case (only the plugin carries the hooks), and it exposes
# the same skill twice, namespaced by plugin - `/skillz:tamarian` next to
# `/tamarian:tamarian` - with the bundle copy the lesser half, since the hooks
# that make the skill persist or fire ship only with its plugin. Hooks are
# detected from the manifests themselves (an inline `hooks` key, or a
# hooks/hooks.json beside them), so a plugin that grows hooks later trips this
# without any catalog edit.
bundle_skills = set()
for p in catalog.get("plugins", []):
    if p.get("name") == "skillz":
        bundle_skills = set(p.get("skills", []))
for p in catalog.get("plugins", []):
    pname = p.get("name", "<unnamed>")
    if pname == "skillz":
        continue
    hooked = False
    for key in ("claude_manifest", "codex_manifest"):
        rel = p.get(key)
        if not rel:
            continue
        manifest_path = os.path.join(root, rel)
        plugin_root = os.path.dirname(os.path.dirname(manifest_path))
        if os.path.isfile(os.path.join(plugin_root, "hooks", "hooks.json")):
            hooked = True
        try:
            with open(manifest_path) as mf:
                if "hooks" in json.load(mf):
                    hooked = True
        except (OSError, ValueError):
            continue  # missing or invalid manifest is reported above
    if not hooked:
        continue
    for sn in p.get("skills", []):
        if sn in bundle_skills:
            errors.append(
                f"skill '{sn}' ships in hooked plugin '{pname}' and is also "
                f"listed in the skillz bundle - remove it from the bundle "
                f"(installing both exposes it twice; only the plugin has the "
                f"hooks)"
            )

# The two root marketplace.json files are what a host actually reads for
# `/plugin install <name>@skillz`, and nothing above has looked at them. Two
# failures have already shipped green past this script: both files sat on a
# branch as invalid JSON full of unresolved conflict markers, and both went on
# advertising 19 plugins whose directories had been deleted in #91 when those
# skills moved to skillz-memory - a quarter of the marketplace resolving to
# nothing, with no error anywhere.
#
# Parsing them is the check. `source` must resolve to a real directory, and
# every plugin dir on disk must be advertised (an unadvertised one is
# uninstallable by name, the silent inverse of the same drift).
plugin_dirs = set()
plugins_root = os.path.join(root, "plugins")
if os.path.isdir(plugins_root):
    plugin_dirs = {
        d for d in os.listdir(plugins_root)
        if os.path.isdir(os.path.join(plugins_root, d))
    }

for rel, host_dir in (
    (".claude-plugin/marketplace.json", ".claude-plugin"),
    (".codex-plugin/marketplace.json", ".codex-plugin"),
):
    abs_path = os.path.join(root, rel)
    if not os.path.isfile(abs_path):
        errors.append(f"marketplace file missing: {rel}")
        continue
    try:
        with open(abs_path) as mf:
            market = json.load(mf)
    except ValueError as e:
        errors.append(f"'{rel}' is not valid JSON: {e}")
        continue

    # A marketplace is per host, so what belongs in it is exactly the plugins
    # that carry THAT host's manifest. Not every plugin is dual-host:
    # continuous-learning and codex-continuous-learning are Codex-only and have
    # no .claude-plugin/plugin.json, yet the Claude marketplace advertised both.
    installable_here = {
        d for d in plugin_dirs
        if os.path.isfile(os.path.join(plugins_root, d, host_dir, "plugin.json"))
    }

    advertised = set()
    for entry in market.get("plugins", []):
        ename = entry.get("name")
        source = entry.get("source")
        if not ename or not source:
            errors.append(f"'{rel}' entry missing name/source: {entry}")
            continue
        advertised.add(ename)
        src_dir = os.path.normpath(os.path.join(root, source.lstrip("./")))
        if not os.path.isdir(src_dir):
            errors.append(
                f"'{rel}' advertises '{ename}' but its source "
                f"{source} is not a directory - the install would 404"
            )
        elif not os.path.isfile(os.path.join(src_dir, host_dir, "plugin.json")):
            errors.append(
                f"'{rel}' advertises '{ename}' but {source}{host_dir}/"
                f"plugin.json does not exist - it is not installable on this "
                f"host"
            )
    for unadvertised in sorted(installable_here - advertised):
        errors.append(
            f"plugins/{unadvertised}/ has a {host_dir}/plugin.json but "
            f"'{rel}' does not advertise it - it cannot be installed by name"
        )


# ---------------------------------------------------------------------------
# Cross-reference and coverage gate (issue #222).
#
# Every condition below was at 100% (or zero) before this was written, which is
# the only reason it can block rather than report. These are the #207 overhaul's
# hand findings made recurring: nothing else notices when the next skill arrives
# wired to only half the places it has to appear.
# ---------------------------------------------------------------------------

# The heading is load-bearing, not cosmetic. A checker keyed on `## Related`
# silently SKIPS a file that says `## Related skills` and reports green - which
# is how three references that resolve nowhere survived until the five variant
# spellings were normalised. The variant is therefore an error in its own right.
#
# Inside the section, only a bullet's LEADING backticked token is a reference.
# Backticks later in the bullet are prose - config values, CLI flags, package
# names - and scanning all of them reproduces the ~80% false-positive rate that
# made whole-body scanning useless. With this rule no allowlist is needed.
REF_RE = re.compile(r"(?m)^[-*] +`([a-z0-9][a-z0-9-]{3,})`")
SECTION_RE = re.compile(r"(?ms)^## Related\s*\n(.*?)(?=\n##\s|\Z)")

for entry in skills:
    name, path = entry.get("name"), entry.get("path")
    if not name or not path:
        continue
    abs_path = os.path.join(root, path)
    if not os.path.isfile(abs_path):
        continue
    with open(abs_path) as f:
        body = f.read()

    for variant in re.findall(r"(?m)^##+ +Related\b.*$", body):
        if variant.strip() != "## Related":
            errors.append(
                f"skill '{name}' uses heading '{variant.strip()}' - the "
                f"canonical heading is '## Related', and a variant is skipped "
                f"by every checker that keys on it"
            )

    section = SECTION_RE.search(body)
    if not section:
        continue
    for ref in sorted(set(REF_RE.findall(section.group(1)))):
        if ref not in skill_names:
            errors.append(
                f"skill '{name}' has a Related entry `{ref}` that is not a "
                f"skill in this catalog - if it lives in a private catalog or "
                f"skillz-memory the reader cannot resolve it either, so say "
                f"where it lives or state the technique instead"
            )

# Every skill needs its own plugin, or it is installable only as part of the
# bundle and `/plugin install <name>@skillz` 404s. 15 skills were in that state
# before #263, and the gap is invisible without this check because the bundle
# keeps working.
for entry in skills:
    name = entry.get("name")
    if name and not os.path.isdir(os.path.join(root, "plugins", name)):
        errors.append(
            f"skill '{name}' has no plugins/{name}/ directory - it ships only "
            f"inside the bundle and cannot be installed by name"
        )

# The README catalog table is the human index. A missing row makes a skill
# undiscoverable to anyone not reading catalog.json; a duplicated row is the
# quieter failure, since nothing looks wrong at the point of insertion (master
# carried one row three times).
readme_path = os.path.join(root, "README.md")
if os.path.isfile(readme_path):
    with open(readme_path) as f:
        readme_text = f.read()
    for entry in skills:
        name = entry.get("name")
        if name and f"/{name}/SKILL.md" not in readme_text:
            errors.append(f"skill '{name}' has no README catalog row")
    rows = [ln for ln in readme_text.splitlines() if ln.startswith("| [")]
    for row, count in collections.Counter(rows).items():
        if count > 1:
            errors.append(
                f"README catalog row appears {count} times: {row[:70]}..."
            )

# The inverse of the hooked-plugin rule above. That check catches a hooked skill
# wrongly IN the bundle; this catches an ordinary skill wrongly OUT of it, which
# is the direction that happens by default - a new skill gets its own plugin and
# nobody remembers the bundle. Two skills were in exactly that state when this
# was written, shipping standalone-only while bundle users never saw them.
hooked_skills = set()
for p in catalog.get("plugins", []):
    if p.get("name") == "skillz":
        continue
    for key in ("claude_manifest", "codex_manifest"):
        rel = p.get(key)
        if not rel:
            continue
        manifest_path = os.path.join(root, rel)
        plugin_root = os.path.dirname(os.path.dirname(manifest_path))
        hooked_here = os.path.isfile(
            os.path.join(plugin_root, "hooks", "hooks.json")
        )
        if not hooked_here:
            try:
                with open(manifest_path) as mf:
                    hooked_here = "hooks" in json.load(mf)
            except (OSError, ValueError):
                hooked_here = False
        if hooked_here:
            hooked_skills.update(p.get("skills", []))

for entry in skills:
    name = entry.get("name")
    if not name or name in hooked_skills or name in bundle_skills:
        continue
    errors.append(
        f"skill '{name}' ships no hooks but is missing from the skillz "
        f"bundle's skill list - bundle users never get it"
    )

if errors:
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)

print("catalog OK: %d skill(s), %d collection(s), %d plugin(s)" % (
    len(skills),
    len(catalog.get("collections", [])),
    len(catalog.get("plugins", [])),
))
PY

note "running install.sh --dry-run smoke tests"
"$ROOT/install.sh" --dry-run --target codex >/dev/null \
  || err "default no-arg dry-run failed"
"$ROOT/install.sh" --dry-run --target codex --collection pr-loop >/dev/null \
  || err "--collection pr-loop dry-run failed"
"$ROOT/install.sh" --dry-run --target codex --skill work-on-pr >/dev/null \
  || err "--skill work-on-pr dry-run failed"
"$ROOT/install.sh" --dry-run --target codex --all >/dev/null \
  || err "--all dry-run failed"

if (( fail )); then
  exit 1
fi

echo "OK"
