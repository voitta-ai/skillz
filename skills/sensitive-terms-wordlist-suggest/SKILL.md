---
name: sensitive-terms-wordlist-suggest
description: |
  End-of-session (or on-demand) scan that suggests names to add to the private
  sensitive-terms wordlist that the check-sensitive-terms.sh name gate reads. Use
  when: (1) a session touched client, employer, product or person names, or
  internal hostnames, and you are about to push to or publish from a public repo;
  (2) the user asks "what should go on my wordlist?" or to "refresh the
  sensitive-terms list"; (3) a name leaked to a public repo even though the gate
  ran, because the name was never on the list; (4) a session is wrapping up and
  touched both private and public repos. Suggests only: it never writes the
  wordlist, never prints its existing contents, and never posts candidates
  anywhere. Ships scripts/suggest-terms.py, which reads agent transcripts (Claude
  Code and Codex JSONL), a git commit range, and saved PR/issue bodies, and
  prints a ranked local report with pointers and a one-line append command.
author: Claude Code
version: 1.0.0
date: 2026-10-08
source: https://github.com/voitta-ai/skillz
source_file: skills/sensitive-terms-wordlist-suggest/SKILL.md
---

# Suggest names for the private sensitive-terms wordlist

> Canonical source: [voitta-ai/skillz](https://github.com/voitta-ai/skillz) -
> `skills/sensitive-terms-wordlist-suggest/SKILL.md`.

## Problem

The name half of the sensitive-term gate (`scripts/check-sensitive-terms.sh`)
catches only names that are already on the private wordlist. The list lags
reality: names that first appear during a session (a new client, a staging
hostname) are not on it yet, so the gate passes them and they reach the public
repo. The leaks come from names nobody has listed yet, not from names someone
forgot to type.

This skill closes that gap from the other side. At the end of a session it lists
names the session produced that look private and are not on the list. The user
decides which to add.

## Guardrails

- **Suggest only.** Never append to the wordlist yourself. Show the report and
  the append command; the user runs it (or tells you which entries to append).
- **Keep the report local.** Never paste candidates into a PR, issue, commit,
  Slack message or any other published place. A candidate list is exactly the
  sensitive data the gate exists to protect.
- **Never print the existing list.** The script only uses it to filter.

## Procedure

1. Locate what the session produced:
   - Claude Code transcript: `ls -t ~/.claude/projects/<project-slug>/*.jsonl | head -1`
     (the slug is the working directory with `/` replaced by `-`).
   - Codex transcript: the newest `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`.
   - Commits made in the session: a range such as `origin/master..HEAD`, or
     `<sha-before-session>..HEAD` in each repo the session committed to.
   - PR and issue bodies, release notes: they are usually already in the
     transcript as tool-call inputs. If some were written outside it, save them to
     files, for example `gh pr view <n> --json body --jq .body > /tmp/pr.txt`.
2. Run the scanner (`SKILL_DIR` is this skill's directory):

   ```bash
   python3 "$SKILL_DIR/scripts/suggest-terms.py" \
     --transcript <session.jsonl> \
     --repo <repo> --git-range origin/master..HEAD \
     [<saved-body.txt> ...]
   ```

   `--transcript` and `--git-range` can repeat; `--repo` applies to every range.
   `--top N` changes the cap of 25.
3. Show the user the report as-is. Each row is a count, the term, the spellings
   seen, and up to three places it appeared (`file:line (tool_use Bash)`,
   `commit <sha> <file>`). The last line is a `printf ... >> <wordlist>` command
   with every candidate; the user deletes the ones that are public before
   running it.
4. Outcomes the script reports, and what to do:
   - `no new candidates`: say so; nothing to add.
   - `warning: no wordlist found at <path>`: say so explicitly. The gate is
     running structural-only on this machine, which is how the leaks this skill
     exists for happened. Suggest creating the file there (outside every repo).

## What counts as a candidate

- **Capitalized words and CamelCase identifiers** (`Zorblax`, `ZorblaxThing`)
  unless every camel hump is an ordinary word in the system dictionary
  (`/usr/share/dict/words`, with simple plural and tense endings stripped). So
  `PullRequest` and `Covers` are dropped and `ZorblaxThing` is kept.
- **Hostnames** with a real TLD, reported as the registrable domain
  (`staging.zorblaxlabs.net` -> `zorblaxlabs.net`). Filenames like `SKILL.md`
  are not hostnames.
- **Dropped:** a built-in set of well-known public names and domains (GitHub,
  Slack, AWS, `github.com`, ...; `PUBLIC_NAMES` and `PUBLIC_DOMAINS` in the
  script; extend them in place when a public name keeps resurfacing), and
  anything already on the list.
- **Already on the list** is decided by a whole-word, case-insensitive match of
  each list entry against the candidate and its spellings. A short list entry
  that only sits inside a longer word (`ella` in `umbrella` or `labelLarge`)
  does not count as a match, so it neither hides a real candidate nor raises a
  false one.

Ranking is by number of occurrences. It is a review aid, not a classifier:
expect some public names and code identifiers in the list (an exception class,
a voice name, a docs domain). The dictionary also contains many first names and
place names, so a client named after one is filtered out; skim the session for
those by hand when it matters.

## Verification

Run it on a fixture before trusting it on a new machine:

```bash
d=$(mktemp -d)
printf '%s\n' '{"type":"user","message":{"content":"Deploy Zorblax to staging.zorblaxlabs.net; ask Quuxtron; check the umbrella labelLarge style"}}' > "$d/s.jsonl"
printf 'quuxtron\nella\n' > "$d/list.txt"
SKILLZ_SENSITIVE_TERMS_FILE="$d/list.txt" python3 "$SKILL_DIR/scripts/suggest-terms.py" --transcript "$d/s.jsonl"
```

Expected: `zorblax` and `zorblaxlabs.net` are suggested; `quuxtron` (on the
list), `umbrella` and `labelLarge` (ordinary words that contain the listed
`ella`) are not.

## Notes

- The wordlist path is the gate's: `$SKILLZ_SENSITIVE_TERMS_FILE`, else
  `${XDG_CONFIG_HOME:-~/.config}/skillz/sensitive-terms.txt`.
- Transcript lines are walked as JSON: every string value is scanned except
  identifier and blob fields (`uuid`, `signature`, `encrypted_content`, image
  `data`, ...), so the same code reads Claude Code and Codex logs.
- Without a system dictionary (minimal Linux images) the script warns and
  ordinary words are no longer filtered, so the report gets long.
