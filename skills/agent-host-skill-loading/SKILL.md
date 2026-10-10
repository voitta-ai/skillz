---
name: agent-host-skill-loading
description: |
  Make a non-Claude, non-Codex agent load skillz-format `SKILL.md` files, so procedures written once reach every agent you run instead of being restated per host. Covers the two-stage disclosure that keeps the standing prompt small (menu line in the system prompt, full body behind a `load_skill` tool), the measured cost of each alternative, frontmatter parsing that survives block scalars, ordered-path precedence with shadow reporting, refresh without a restart and the turn-boundary gotcha that comes with it, and why the reload belongs behind a privilege gate even though it only reads files. Use when: (1) you have a custom agent loop (Slack bot, service, own harness) that cannot use the skills your Claude Code or Codex installs already have, (2) you are deciding how much of a skill catalog to put in a system prompt versus behind a tool, (3) your standing prompt is growing with every skill added and cheaper fallback models in a waterfall are paying for it, (4) a skill catalog is loaded but the model never invokes it, or (5) two catalogs (public plus private) define the same skill name and you need a defined winner.
author: Claude Code
version: 1.1.2
date: 2026-10-09
source: https://github.com/voitta-ai/skillz
source_file: skills/agent-host-skill-loading/SKILL.md
---

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/agent-host-skill-loading/SKILL.md`). Updates go through the repo's
> worktree + PR workflow — open an issue, branch, PR.

# agent-host-skill-loading

## Problem

A skill catalog targets specific hosts. Claude Code and Codex read
`skills/<name>/SKILL.md` natively; anything else you run — a Slack agent, a
cron worker, your own tool-calling loop — cannot. The knowledge exists, and the
agent standing in the channel with you does not have it. You end up restating
the same procedure in that agent's prompt, where it drifts from the catalog
copy.

Adding a third host is mostly a delivery question, not a parsing one. The
parsing is twenty lines. The decision that matters is **how much of the catalog
sits in the standing prompt**, because a system prompt is paid on every turn, by
every model in a fallback chain, forever.

## Format contract

A skill is a directory holding `SKILL.md`:

    ---
    name: some-skill
    description: |
      One or more sentences. Often long — written for a host that injects
      the whole thing.
    ---

    # some-skill
    ...body...

Two parsing points that bite:

- **Use a YAML parser, not a regex.** Descriptions routinely use block scalars
  (`description: |`) and run to several hundred characters over many lines. A
  `^description:\s*(.*)$` regex silently captures the empty string after the
  pipe, and you get a catalog of nameless menu entries that the model cannot
  match against anything.
- **Split on the frontmatter fence, then parse only the fence.** `text.split("---", 2)`
  gives you `["", frontmatter, body]`; feeding the whole file to the YAML parser
  fails the moment a body contains a `:` in prose, which is always.

Fall back to the directory name when `name:` is missing, and skip a file whose
frontmatter will not parse rather than failing the whole scan — one malformed
skill in a catalog of forty should not cost you the other thirty-nine.

## The delivery decision

Three options, and the cost of each is measurable before you build it. Numbers
below are from a 44-skill catalog; scale linearly.

| Approach | Standing cost | Failure mode |
|---|---|---|
| Full descriptions inline | ~25 KB | Every turn, every fallback model, pays for 44 skills to use zero or one |
| Nothing in prompt, `find_skill(query)` tool only | 0 | Never invoked — **a model cannot search for what it does not know exists** |
| Menu line per skill + `load_skill(name)` tool | ~7 KB | None material; costs one extra tool round-trip on the turns that use a skill |

Claude Code started at the first row and now bounds it. Each listed entry
(`description` plus `when_to_use`) is cut at 1,536 characters, and the whole
listing gets a budget of 1% of the model's context window. When the listing
overflows, it keeps every name but drops descriptions, starting with the
skills invoked least. That is a capped version of the third row with
usage-ranked eviction, which is worth copying if your catalog outgrows a
fixed menu cap.

The third is the one to build. Concretely:

1. **The menu** — one line per skill in the system prompt: name plus the
   *first sentence* of the description, capped (150 chars works). Not the whole
   description: catalog descriptions are written for a host that injects them
   whole, and their tail is trigger-matching material that a menu does not need.
2. **The body** — a `load_skill(name)` tool returning the `SKILL.md` in full,
   capped (20 KB; a long skill is a real thing). The model calls it when a
   request matches a menu line, then follows what it reads.

Tell the model in the menu header that the line is a label and the body has the
steps, or it will act on the one-line summary alone.

Measure yours before shipping: index the real catalog, print
`len(prompt_block())`, and read the first ten lines. If a summary is truncating
mid-word into uselessness, your cap is too tight or the descriptions lead with
boilerplate.

## Implementation sketch

```python
_INDEX = {}     # name -> {"name", "summary", "path"}
_SHADOWED = []  # (name, path) a higher-precedence path already claimed

def reload():
    """Re-scan every configured path. Returns the count indexed."""
    global _INDEX, _SHADOWED
    index, shadowed = {}, []
    for raw in CONFIGURED_PATHS:              # ordered: first wins
        root = os.path.expanduser(os.path.expandvars(raw))
        for entry in sorted(os.listdir(root)):        # guard OSError
            path = os.path.join(root, entry, "SKILL.md")
            if not os.path.isfile(path):
                continue
            meta, _body = parse(path)                 # yaml.safe_load the fence
            if meta is None:
                continue
            name = str(meta.get("name") or entry).strip()
            if name in index:
                shadowed.append((name, path))         # report, never silent
                continue
            index[name] = {"name": name,
                           "summary": summarize(meta.get("description")),
                           "path": path}
    _INDEX, _SHADOWED = index, shadowed
    retval = len(_INDEX)
    return retval
```

`summarize()` is: collapse whitespace, take up to the first `". "`, cap, ellipsize.

`load(name)` re-reads the file (do not cache bodies — the point of a catalog is
that it changes) and, on a miss, returns the near matches:
`no such skill: 'worktree'. Closest: git-worktree-convention.` A bare "not
found" sends the model into retry loops on inflected guesses.

## Precedence: ordered paths, loudly

Configure **a list** of directories, not one. A private catalog and a public one
is the normal case, and the same name will eventually exist in both.

- First path that defines a name wins. Put the private/local one first so it
  shadows.
- Record every shadowed `(name, path)` and log it at boot. Silent shadowing is
  the bug you diagnose twice: someone edits a skill and the agent keeps quoting
  the other copy.
- Log **names only**. A skill body is content; boot logs are a surface you keep
  boring.

## Refresh, and the turn-boundary gotcha

Build the index at boot, and expose a `reload_skills` tool so pulling the
catalog does not need a service restart.

**The gotcha:** most loops compute the tool schema list once per turn, at the
top. If a turn *starts* with an empty index, the reload fills the index but
`load_skill` is not among that turn's tools — the model cannot use what it just
loaded until the next turn. Either document it, or (if same-turn "reload and
immediately use" matters) offer `load_skill` unconditionally and have it report
"no skills configured" when the index is empty. Rebuild the *menu* per turn
regardless, so a reload is at least visible in the same conversation.

## Gate the reload

Reading files is not a mutation, so it feels like it belongs outside your
privilege gate. Put it inside anyway: **it changes which instructions the agent
will follow.** In a shared channel, an untrusted participant who can point the
agent at a directory and reload it can author the agent's next system prompt.
Same gate as "change my configuration", not the same gate as "read a file".

The converse also needs saying, in the skill menu header and in your docs: **a
skill is instructions, not permission.** Whatever a skill tells the agent to run
still passes the exec classifier, the path policy, and the approval flow it
would have passed otherwise. A skill cannot widen scope; if it appears to, the
bug is in your gate, not in the skill.

## Zero-cost when unused

Gate both the menu and the tool on "any skills configured". An instance with no
`skills.paths` should get no `## Skills` section and no `load_skill` schema —
identical prompt bytes to before the feature existed. This is what makes the
feature safe to ship to every deployment rather than the ones that asked.

## Verify

1. Index the real catalog: count indexed, and `len(prompt_block())` — compare
   against the table above for your catalog size.
2. `load_skill` a known skill; assert a distinctive line from its body comes
   back.
3. `load_skill` a near-miss name; assert the suggestion, not a bare failure.
4. Two paths defining one name: assert the first path's body wins and the loser
   is in the shadow list.
5. Empty configuration: assert empty menu, no tool schema.
6. A turn through the real loop: assert `## Skills` is in the system prompt the
   model receives and `load_skill` is in the tool list — not just that the
   module works in isolation.

## Reference implementation

[voitta-ai/shmobster](https://github.com/voitta-ai/shmobster) `shmobster/skills.py`
(PR #75, shipped in v0.2.0) — a Slack agent as a third host for this catalog,
with the checks above in its `selfcheck.py`.

## Related

- `claude-code-plugin-update-flow` — how the two native hosts get their copies
- `claude-code-codex-plugin-parity` — the same catalog, two manifests
