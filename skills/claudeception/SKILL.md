---
name: claudeception
description: |
  Claudeception is a continuous learning system that extracts reusable knowledge from work sessions.
  Triggers: (1) /claudeception command to review session learnings, (2) "save this as a skill"
  or "extract a skill from this", (3) "what did we learn?", (4) After any task involving
  non-obvious debugging, workarounds, or trial-and-error discovery. Creates new skills, on
  either host, when valuable reusable knowledge is identified. Repeatable, broadly-useful
  procedures are promoted into the public skillz catalog via a pull request; specific
  recollections (one-off fixes, gotchas, project quirks) go to memory instead. Owns the
  **Wiring procedure** for that promotion - `catalog.json`, the bundle's per-host symlinks,
  the optional single-skill plugin, and the version bumps CI requires - which is the one
  copy both hosts follow. On Codex the same retrospective is driven by `Stop` and
  `UserPromptSubmit` hooks instead of an explicit call; that entry point is
  `continuous-learning`, which defers here for the classification and the wiring.
author: Claude Code
version: 4.2.1
date: 2026-06-14
source: https://github.com/voitta-ai/skillz
source_file: skills/claudeception/SKILL.md
upstream: https://github.com/blader/Claudeception
allowed-tools:
  - Read
  - Write
  - Edit
  - Grep
  - Glob
  - Bash
  - WebSearch
  - WebFetch
  - Skill
  - AskUserQuestion
  - TodoWrite
---

# Claudeception

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file: `skills/claudeception/SKILL.md`).
> Updates go through the repo's worktree + PR workflow - open an issue,
> branch, PR. Vendored from the upstream MIT-licensed project
> https://github.com/blader/Claudeception (see `LICENSE`).

You are Claudeception: a continuous learning system that extracts reusable knowledge from work sessions and 
codifies it into new Claude Code skills. This enables autonomous improvement over time.

## Core Principle: Skill Extraction

When working on tasks, continuously evaluate whether the current work contains extractable 
knowledge worth preserving. Not every task produces a skill—be selective about what's truly 
reusable and valuable.

## When to Extract a Skill

Extract a skill when you encounter:

1. **Non-obvious Solutions**: Debugging techniques, workarounds, or solutions that required 
   significant investigation and wouldn't be immediately apparent to someone facing the same 
   problem.

2. **Project-Specific Patterns**: Conventions, configurations, or architectural decisions 
   specific to this codebase that aren't documented elsewhere.

3. **Tool Integration Knowledge**: How to properly use a specific tool, library, or API in 
   ways that documentation doesn't cover well.

4. **Error Resolution**: Specific error messages and their actual root causes/fixes, 
   especially when the error message is misleading.

5. **Workflow Optimizations**: Multi-step processes that can be streamlined or patterns 
   that make common tasks more efficient.

## Skill Quality Criteria

Before extracting, verify the knowledge meets these criteria:

- **Reusable**: Will this help with future tasks? (Not just this one instance)
- **Non-trivial**: Is this knowledge that requires discovery, not just documentation lookup?
- **Specific**: Can you describe the exact trigger conditions and solution?
- **Verified**: Has this solution actually worked, not just theoretically?

## Extraction Process

### Step 1: Identify the Knowledge

Analyze what was learned:
- What was the problem or task?
- What was non-obvious about the solution?
- What would someone need to know to solve this faster next time?
- What are the exact trigger conditions (error messages, symptoms, contexts)?

### Step 2: Research Best Practices (When Appropriate)

Before creating the skill, search the web for current information when:

**Always search for:**
- Technology-specific best practices (frameworks, libraries, tools)
- Current documentation or API changes
- Common patterns or solutions for similar problems
- Known gotchas or pitfalls in the problem domain
- Alternative approaches or solutions

**When to search:**
- The topic involves specific technologies, frameworks, or tools
- You're uncertain about current best practices
- The solution might have changed after January 2025 (knowledge cutoff)
- There might be official documentation or community standards
- You want to verify your understanding is current

**When to skip searching:**
- Project-specific internal patterns unique to this codebase
- Solutions that are clearly context-specific and wouldn't be documented
- Generic programming concepts that are stable and well-understood
- Time-sensitive situations where the skill needs to be created immediately

**Search strategy:**
```
1. Search for official documentation: "[technology] [feature] official docs 2026"
2. Search for best practices: "[technology] [problem] best practices 2026"
3. Search for common issues: "[technology] [error message] solution 2026"
4. Review top results and incorporate relevant information
5. Always cite sources in a "References" section of the skill
```

**Example searches:**
- "Next.js getServerSideProps error handling best practices 2026"
- "Claude Code skill description semantic matching 2026"
- "React useEffect cleanup patterns official docs 2026"

**Integration with skill content:**
- Add a "References" section at the end of the skill with source URLs
- Incorporate best practices into the "Solution" section
- Include warnings about deprecated patterns in the "Notes" section
- Mention official recommendations where applicable

### Step 3: Structure the Skill

Create a new skill with this structure:

```markdown
---
name: [descriptive-kebab-case-name]
description: |
  [Precise description including: (1) exact use cases, (2) trigger conditions like 
  specific error messages or symptoms, (3) what problem this solves. Be specific 
  enough that semantic matching will surface this skill when relevant.]
author: [original-author or "Claude Code"]
version: 1.0.0
date: [YYYY-MM-DD]
---

# [Skill Name]

## Problem
[Clear description of the problem this skill addresses]

## Context / Trigger Conditions  
[When should this skill be used? Include exact error messages, symptoms, or scenarios]

## Solution
[Step-by-step solution or knowledge to apply]

## Verification
[How to verify the solution worked]

## Example
[Concrete example of applying this skill]

## Notes
[Any caveats, edge cases, or related considerations]

## References
[Optional: Links to official documentation, articles, or resources that informed this skill]
```

### Step 4: Write Effective Descriptions

The description field is critical for skill discovery. Include:

- **Specific symptoms**: Exact error messages, unexpected behaviors
- **Context markers**: Framework names, file types, tool names
- **Action phrases**: "Use when...", "Helps with...", "Solves..."

Example of a good description:
```
description: |
  Fix for "ENOENT: no such file or directory" errors when running npm scripts 
  in monorepos. Use when: (1) npm run fails with ENOENT in a workspace, 
  (2) paths work in root but not in packages, (3) symlinked dependencies 
  cause resolution failures. Covers node_modules resolution in Lerna, 
  Turborepo, and npm workspaces.
```

### Step 5: Classify, then save

One classification, asked once: **is this a repeatable procedure, or a specific
recollection?**

- **Repeatable procedure** — a multi-step method with judgment calls; the agent *does*
  something the same way next time (e.g. a PR loop, a migration, a publish flow). This
  is a **skill**. Continue below.
- **Specific recollection** — a single cause->fix, an API gotcha, a config detail, a
  project quirk; the agent *recalls* something. This is **memory, not a skill.** Do NOT
  mint a `SKILL.md`. Write it as a memory file using the host's memory conventions (one
  fact per file, with `name`/`description` frontmatter) and stop. **Most session
  learnings are memory, not skills.**

This classification is shared with `continuous-learning`, the Codex-hook-driven
form of the same retrospective. Both must answer identically for the same
learning; a divergence is a defect in one of them, not a host difference.

For a **skill**, decide where it lives:

1. **Project-specific** — only meaningful inside this one codebase. Save to
   `.claude/skills/[name]/SKILL.md`.
2. **User-wide** — useful to this user across projects, but tied to their
   machine/accounts/private context. Save to `~/.claude/skills/[name]/SKILL.md`.
3. **Useful at large** — generic, reusable, nothing secret or machine-specific. Save it
   user-wide AND **promote it to the public skillz catalog** (see below).

For **memory**, the same reach choice is just *where the markdown lives/syncs*:
project-local memory, a user's cross-machine **git-backed vault**, or a team's shared
vault. Sharing memory is a location, not a promotion to the skills catalog.

Include supporting scripts in a `scripts/` subdirectory if the skill benefits from
executable helpers.

## Promotion to the Shared Catalog

Only a **repeatable procedure that is useful at large** gets promoted. Specifics — even
widely useful ones — are memory; share them via a git-backed vault, not the skills
catalog.

There is intentionally **no private skills repo.** A private *procedure* would need a
sizable org with proprietary process (YAGNI today); private *specifics* belong in a
private memory vault. If a genuinely proprietary, repeatable procedure ever appears,
add a private skillz repo at that point — don't pre-build one.

Promotion target: **`voitta-ai/skillz`** (local clone `~/g/git.voitta/skillz`, default
branch `master`).

**Hard rule:** the public repo must NEVER contain account IDs, client/customer names,
domains, or infra topology. Genericize to placeholders (`<account-id>`, `<domain>`,
`<project>`) — the *technique* is what's reusable. If a procedure can't be genericized
without losing its meaning, it isn't "useful at large": keep it user-wide, and route any
specifics to a private vault.

### Wiring procedure

**Zeroth step - consider handing off.** If this session's actual work is
not the skills repo and `ListAgents` shows exactly one live session that
is working it, do not run this procedure here: author the `skills/NAME/`
content only, push branch `add-skill-NAME`, and message that session to do
the rest - the registry files are a one-writer surface. The full contract
(both sides, and when NOT to hand off) is the `skill-capture-pr-handoff`
skill; the procedure below remains the fallback when no such peer exists,
and the landing side's checklist when one does.

Let `REPO` = `~/g/git.voitta/skillz`, `NAME` = the skill's kebab-case name. (If the clone
is missing, clone it first. Always branch from `master`.)

1. **Land the content**: copy the skill into `REPO/skills/NAME/` (at minimum `SKILL.md`;
   include `scripts/`, `resources/` if present). Keep any upstream `LICENSE` for a
   vendored third-party skill (MIT etc. require retaining the notice).
2. **Register in `catalog.json`**: add a `skills` entry
   (`{ "name", "path": "skills/NAME/SKILL.md", "hosts": [...], "summary": "..." }`) and
   add `NAME` to the `skillz` bundle plugin's `skills` list.

   **Insert the entry as text; never round-trip the file through a JSON
   load/dump.** `catalog.json` is deliberately unsorted, so re-serializing it
   sorts and re-indents everything: observed twice in one day, turning a ~25-line
   addition into diffs of +1157 and +1591/-1370 lines of pure reordering, which
   buries the actual change and conflicts with every other open skill PR. Same
   for both `marketplace.json` files. If a rebase leaves these files conflicted,
   `python3 scripts/merge-skill-registry.py` resolves them correctly *and* undoes
   an earlier round-trip, since it takes the base file wholesale and re-splices
   only the entries the branch adds.
3. **Symlink into the bundle, once per host.** The bundle keeps a separate
   directory per host and the symlinks must match the `hosts` declared in step 2:

   ```bash
   ln -s ../../../skills/NAME REPO/plugins/skillz/skills-claude/NAME   # if hosts has "claude"
   ln -s ../../../skills/NAME REPO/plugins/skillz/skills-codex/NAME    # if hosts has "codex"
   ```

   There is no `plugins/skillz/skills/` and there must not be: Claude Code
   always *also* scans a default `skills/` dir alongside whatever the manifest
   names, so a stray one would re-expose every skill to both hosts.
   `validate-catalog.sh` fails on it by name.
4. **Single-skill plugin — required.** It is what lets someone install this one
   skill without the bundle, and `validate-catalog.sh` now ERRORS on a skill
   that ships only inside the bundle. Mirror an existing `plugins/<name>/`:
   both `.claude-plugin` and `.codex-plugin` manifests plus a `skills/NAME`
   symlink (single-skill plugins use a plain `skills/` dir — the split above
   is the bundle's problem, not theirs), and add a `catalog.json` `plugins`
   entry. The new plugin starts at `1.0.0`.
5. **README row.** Add one to the README catalog table. The bundle's
   marketplace description does not enumerate skills, so the two
   `marketplace.json` files need an edit **only if** step 4 produced a plugin —
   in which case add its entry to *both* of them, since a plugin advertised on
   one host and not the other is installable on one host only.
6. **Bump versions. CI fails the PR without this.** A version is the install
   cache key, so leaving one unchanged means no install ever re-extracts and
   every user silently keeps the old copy:
   - `plugins/skillz/.claude-plugin/plugin.json` **and** its `.codex-plugin`
     twin must both advance past master's, and must equal each other.
   - Every plugin whose content the diff touches bumps too. A plugin you just
     created starts at `1.0.0` and needs nothing further.
   - Editing an *existing* skill also bumps that `SKILL.md`'s own frontmatter
     `version:`, which is separate from the packaging version.

   `python3 scripts/check-plugin-version-bumps.py origin/master` is the same
   check CI runs, and it reads the working tree, so run it before committing.
7. **Validate**: run `REPO/scripts/validate-catalog.sh`; fix until it prints `OK`.
8. **Branch, commit, PR**: from `master`, branch `add-skill-NAME`, commit, push, open a
   PR with `gh pr create`. The PR is the review gate — do **not** self-merge; report the
   URL and ask for review.

Verify each git/`gh` step's output; if validation or push fails, stop and report rather
than forcing through.

## Retrospective Mode

When `/claudeception` is invoked at the end of a session:

1. **Review the Session**: Analyze the conversation history for extractable knowledge
2. **Identify Candidates**: List potential skills with brief justifications
3. **Prioritize**: Focus on the highest-value, most reusable knowledge
4. **Extract**: Create skills for the top candidates (typically 1-3 per session)
5. **Summarize**: Report what skills were created and why

## Self-Reflection Prompts

Use these prompts during work to identify extraction opportunities:

- "What did I just learn that wasn't obvious before starting?"
- "If I faced this exact problem again, what would I wish I knew?"
- "What error message or symptom led me here, and what was the actual cause?"
- "Is this pattern specific to this project, or would it help in similar projects?"
- "What would I tell a colleague who hits this same issue?"

## Memory Consolidation

When extracting skills, also consider:

1. **Combining Related Knowledge**: If multiple related discoveries were made, consider 
   whether they belong in one comprehensive skill or separate focused skills.

2. **Updating Existing Skills**: Check if an existing skill should be updated rather than 
   creating a new one.

3. **Cross-Referencing**: Note relationships between skills in their documentation.

## Quality Gates

Before finalizing a skill, verify:

- [ ] Description contains specific trigger conditions
- [ ] Solution has been verified to work
- [ ] Content is specific enough to be actionable
- [ ] Content is general enough to be reusable
- [ ] No sensitive information (credentials, internal URLs) is included
- [ ] Skill doesn't duplicate existing documentation or skills
- [ ] Web research conducted when appropriate (for technology-specific topics)
- [ ] References section included if web sources were consulted
- [ ] Current best practices (post-2025) incorporated when relevant

## Anti-Patterns to Avoid

- **Over-extraction**: Not every task deserves a skill. Mundane solutions don't need preservation.
- **Vague descriptions**: "Helps with React problems" won't surface when needed.
- **Unverified solutions**: Only extract what actually worked.
- **Documentation duplication**: Don't recreate official docs; link to them and add what's missing.
- **Stale knowledge**: Mark skills with versions and dates; knowledge can become outdated.

## Skill Lifecycle

Skills should evolve:

1. **Creation**: Initial extraction with documented verification
2. **Refinement**: Update based on additional use cases or edge cases discovered
3. **Deprecation**: Mark as deprecated when underlying tools/patterns change
4. **Archival**: Remove or archive skills that are no longer relevant

## Example: Complete Extraction Flow

**Scenario**: While debugging a Next.js app, you discover that `getServerSideProps` errors
aren't showing in the browser console because they're server-side, and the actual error is
in the terminal.

**Step 1 - Identify the Knowledge**:
- Problem: Server-side errors don't appear in browser console
- Non-obvious aspect: Expected behavior for server-side code in Next.js
- Trigger: Generic error page with empty browser console

**Step 2 - Research Best Practices**:
Search: "Next.js getServerSideProps error handling best practices 2026"
- Found official docs on error handling
- Discovered recommended patterns for try-catch in data fetching
- Learned about error boundaries for server components

**Step 3-5 - Structure and Save**:

**Extraction**:

```markdown
---
name: nextjs-server-side-error-debugging
description: |
  Debug getServerSideProps and getStaticProps errors in Next.js. Use when: 
  (1) Page shows generic error but browser console is empty, (2) API routes 
  return 500 with no details, (3) Server-side code fails silently. Check 
  terminal/server logs instead of browser for actual error messages.
author: Claude Code
version: 1.0.0
date: 2024-01-15
---

# Next.js Server-Side Error Debugging

## Problem
Server-side errors in Next.js don't appear in the browser console, making 
debugging frustrating when you're looking in the wrong place.

## Context / Trigger Conditions
- Page displays "Internal Server Error" or custom error page
- Browser console shows no errors
- Using getServerSideProps, getStaticProps, or API routes
- Error only occurs on navigation/refresh, not on client-side transitions

## Solution
1. Check the terminal where `npm run dev` is running—errors appear there
2. For production, check server logs (Vercel dashboard, CloudWatch, etc.)
3. Add try-catch with console.error in server-side functions for clarity
4. Use Next.js error handling: return `{ notFound: true }` or `{ redirect: {...} }` 
   instead of throwing

## Verification
After checking terminal, you should see the actual stack trace with file 
and line numbers.

## Notes
- This applies to all server-side code in Next.js, not just data fetching
- In development, Next.js sometimes shows a modal with partial error info
- The `next.config.js` option `reactStrictMode` can cause double-execution
  that makes debugging confusing

## References
- [Next.js Data Fetching: getServerSideProps](https://nextjs.org/docs/pages/building-your-application/data-fetching/get-server-side-props)
- [Next.js Error Handling](https://nextjs.org/docs/pages/building-your-application/routing/error-handling)
```

## Integration with Workflow

### Automatic Trigger Conditions

Invoke this skill immediately after completing a task when ANY of these apply:

1. **Non-obvious debugging**: The solution required >10 minutes of investigation and
   wasn't found in documentation
2. **Error resolution**: Fixed an error where the error message was misleading or the
   root cause wasn't obvious
3. **Workaround discovery**: Found a workaround for a tool/framework limitation that
   required experimentation
4. **Configuration insight**: Discovered project-specific setup that differs from
   standard patterns
5. **Trial-and-error success**: Tried multiple approaches before finding what worked

### Explicit Invocation

Also invoke when:
- User runs `/claudeception` to review the session
- User says "save this as a skill" or similar
- User asks "what did we learn?"

### Self-Check After Each Task

After completing any significant task, ask yourself:
- "Did I just spend meaningful time investigating something?"
- "Would future-me benefit from having this documented?"
- "Was the solution non-obvious from documentation alone?"

If yes to any, invoke this skill immediately.

Remember: The goal is continuous, autonomous improvement. Every valuable discovery
should have the opportunity to benefit future work sessions.

## Related

- `continuous-learning` — the same retrospective driven by Codex `Stop` and
  `UserPromptSubmit` hooks instead of an explicit invocation. The trigger
  differs; the rules do not. It defers to the **Wiring procedure** above for
  anything promoted to `voitta-ai/skillz`, so that section is the single copy
  and this file owns it.
- `agent-host-skill-loading` — reaching a third host that has neither of the
  above, by loading `SKILL.md` files directly.
