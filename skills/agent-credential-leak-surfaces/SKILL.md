---
name: agent-credential-leak-surfaces
description: |
  Find and clean the places a coding agent quietly accumulates copies of your
  secrets on local disk, and stop it recurring. Use when: (1) you found a token
  in one place and need to know where else it went before rotating; (2) you are
  about to rotate a credential and want the rotation to actually be complete;
  (3) an agent echoed a secret into a session and you want to know what
  persisted it; (4) you are writing a redactor and need to know which patterns
  work and which are unwinnable; (5) periodic hygiene on a machine where an
  agent has been editing config files. Covers the seven surfaces (git remote URLs,
  agent memory stores, the agent's own file-history snapshots, MCP config
  literals, permission allowlists, tool-output caches), why prefix-grep gives
  false confidence, why keyword-adjacency regexes lose to prose, why bare
  high-entropy matching is unusable, and the fingerprint-not-echo technique.
author: Claude Code
version: 1.3.0
date: 2026-08-19
---

# Where a coding agent leaves copies of your secrets

## Problem

You rotate a leaked credential and consider it handled. But rotation only closes
the exposure you found. Around a coding agent, one secret typically exists in
**several** places you did not put it, created by machinery you never
configured, and most of which no audit covers.

Most are untracked local state. Two are not: a permission allowlist and a
project-scoped tool config both get committed routinely, which is why the
git-history audit and this one overlap rather than partition cleanly.

The failure mode is not "a secret leaked." It is **"we rotated the copy we knew
about."**

## The pattern set, defined once

Every sweep below uses the same union. Defining it once is the point: the most
common way an audit produces a false "clean" is a snippet that checks fewer
shapes than the reader assumes.

```bash
# Left-anchored so `flask-sqlalchemy` and `dask-distributed` do not match `sk-`.
SECRET_RE='(^|[^A-Za-z0-9_-])(gh[posru]_|github_pat_|glpat-|xox[baprsedc]-|xapp-|sk-(ant-|or-)?|nvapi-|AIza)[A-Za-z0-9_-]{16,}'
AWSID_RE='\b(AKIA|ASIA)[0-9A-Z]{16}\b'
PEM_RE='-----BEGIN [A-Z ]*PRIVATE KEY-----'
```

Families that are easy to leave out, and were left out of the first draft of
this very file: `github_pat_` (fine-grained PATs), `ASIA` (STS temporary keys),
`xoxc-`/`xoxd-` (browser session token and cookie -- a whole sibling skill
exists for those), `AIza` (Google), `sk-ant-`/`sk-or-`/`nvapi-`. AWS key IDs get
their own exactly-anchored pattern rather than the loose suffix, because
`AKIA[0-9A-Z]{16}` is a known fixed shape and folding it into a generic
`[A-Za-z0-9_-]{16,}` both over- and under-matches.

**Not covered here, deliberately:** the AWS *secret* access key is a bare 40-char
base64-ish string with no prefix, so it cannot be found by prefix matching at
all -- see "Bare high-entropy matching is unusable" below for why a generic
pattern for it is not workable in a transcript. `scripts/check-sensitive-terms.sh`
in this repo carries a length-and-boundary-anchored version for the narrower
case of scanning repo files.

**This is not the only copy in the repo, and that is a known problem.**
`scripts/check-sensitive-terms.sh` is the CI-enforced set,
`pre-open-source-credential-audit` carries a third. They disagree today. If you
extend this list, extend the enforced script too -- a prose union that drifts
from the gate is a false-clean generator.

## The seven surfaces

Ordered by how often they are missed, not by severity.

### 1. Credentials embedded in git remote URLs

```
https://<user>:<token>@<host>/<org>/<repo>.git
```

Lives in `.git/config`, per clone. Clone the same way ten times and there are
ten copies of the token, which then age independently of wherever you think the
canonical copy lives.

```bash
# Two userinfo forms exist and BOTH leak:
#   https://user:<token>@host/...     (username + token)
#   https://<token>@host/...          (token only -- git clone accepts this)
# A pattern requiring the colon silently misses the second.
find ~ -maxdepth 8 -name config -path '*/.git/*' -print0 \
  | xargs -0 grep -lE 'url *= *https?://[^/@]+@'

`-maxdepth 8` rather than something tighter because `ghq` and GOPATH-style
layouts put a clone at `~/ghq/github.com/<org>/<repo>/.git/config`, which is
depth 6. A bound that silently drops an entire checkout convention defeats the
purpose of the sweep.

**That predicate still cannot see four real locations**, so sweep them
separately rather than assuming one `find` covers git:

```bash
grep -lE 'https?://[^/@]+@' ~/.git-credentials ~/.config/git/config 2>/dev/null
find ~ -maxdepth 8 -name '*.git' -type d -name config          # bare clones
```

- `~/.git-credentials` -- the `store` helper's plaintext file. Not under a
  `.git/` directory, and its lines have no `url = ` prefix.
- `~/.config/git/config` -- where an `insteadOf` rewrite carrying a token
  lives, and it applies to **every** repo on the machine.
- **Bare clones** (`repo.git/config`) -- the path contains `o.git/`, never the
  literal `/.git/`.
- **`--separate-git-dir` and `git worktree`** layouts, where `.git` is a *file*
  and the real config sits outside any `.git` directory.

Strip them without touching anything else:

```bash
old="$(git -C <repo> remote get-url <name>)" || exit 1
case "$old" in
  http://*|https://*)                                   # ONLY http(s)
    new="$(printf '%s' "$old" | sed -E 's|://[^/@]+@|://|')"
    [ -n "$new" ] && git -C <repo> remote set-url <name> "$new" ;;
  *) echo "not an http(s) remote, leaving alone: $old" ;;
esac
```

Use `--all` and repeat for push URLs. `git remote get-url <name>` returns only
the first *fetch* URL, and `set-url` without `--push` writes only fetch URLs --
so a token sitting in `pushurl` is **flagged by the sweep** (because `pushurl`
contains the substring `url`) and then **silently untouched by the fix**, which
exits 0 and looks like success. `git remote get-url --all <name>` and a matching
`--push` pass close it; `git config --unset` on the specific key is the blunt
alternative.

The `case` guard matters: run the bare `sed` against `ssh://git@host/o/r.git`
and it strips the required `git@`, leaving `ssh://host/o/r.git`, which then
authenticates as your local username and fails. Since the remediation below is
"use an SSH remote", an unguarded cleanup would break the very thing this
section tells you to switch to. The `[ -n "$new" ]` guard stops a failed
substitution from setting the URL to an empty string.

Then give git a real credential source, or the next person just pastes the token
back in. A token in the URL is the symptom, not the disease.

Pick the fix with care, because one of them just relocates the problem:

- **SSH remote** -- no token anywhere. Best option where keys are available.
- **A keychain-backed helper** (`osxkeychain`, `libsecret`, `gh auth setup-git`)
  -- the credential leaves the filesystem.
- **`credential.helper store`** -- writes `https://user:<token>@host` in
  cleartext to `~/.git-credentials`. That path is matched by **none** of the
  sweeps in this skill: it is not under a `.git/` directory and its lines have
  no `url = ` prefix. If you use it, add it to your sweep list explicitly.

### 2. Agent memory / session-transcript stores

Any "remember this session" feature persists prompts and replies verbatim into a
long-lived, usually embedded and searchable store. Anything you pasted, and
anything the assistant echoed back in prose, is now in it. Embedded means it can
resurface in a *later* session's context, which is a feedback loop: the secret
gets re-injected and re-persisted.

Check what your store ingests and whether it filters. Most do not.

### 3. The agent's own file-history snapshots

This is the one nobody looks at. Coding agents commonly snapshot every file they
edit so edits can be undone. Edit a config containing secrets three times and
there are three preserved generations of the then-current secrets — including
ones you already rotated and believed gone.

Symptom that gives it away: a token you rotated months ago is still on disk, in
a directory you have never opened, under an opaque filename.

```bash
DIR=~/.claude          # or ~/.codex, ~/.cursor, ... -- whatever your agent uses
[ -d "$DIR" ] || { echo "no such dir: $DIR" >&2; exit 1; }
grep -rlE "$SECRET_RE|$AWSID_RE|$PEM_RE" "$DIR"
```

Check the directory exists first and do **not** blanket-redirect stderr: a
mistyped or unsubstituted path makes `grep` print nothing and exit non-zero,
which with `2>/dev/null` is byte-identical to a clean sweep. A false clean from
a typo is the same outcome as a false clean from a bad regex.

Rotating without clearing these leaves the old values sitting next to the new
ones, and the next rotation adds another generation.

### 4. MCP / tool config with literal secrets

Config files that wire up tool servers often take secrets as an `env` map. It is
easy to paste the literal. Then it is a second copy that silently keeps the old
value after you rotate the "real" one — the server keeps working until the token
expires, or keeps failing long after you fixed the env var, and nobody connects
the two.

Prefer an environment reference (`"${MY_TOKEN}"`) over a literal, so there is one
copy and one place to rotate. Audit with:

```bash
SECRET_RE="$SECRET_RE" AWSID_RE="$AWSID_RE" PEM_RE="$PEM_RE" \
CONFIG=~/.claude.json python3 - <<'PY'
import json, os, re
d = json.load(open(os.path.expanduser(os.environ["CONFIG"])))
# Read the patterns from the environment rather than restating them: a quoted
# heredoc does not expand $SECRET_RE, so an inline copy here is guaranteed to
# drift the first time the union is extended.
pat = re.compile("|".join(os.environ[k] for k in ("SECRET_RE", "AWSID_RE", "PEM_RE")))
# Test strings at the TOP, not inside the dict branch: a literal reached via a
# list (args: ["--token", "<value>"]) would otherwise hit neither branch and be
# silently skipped -- and args arrays are where secrets most often sit.
def walk(n, p=""):
    if isinstance(n, str):
        if pat.search(n): print("LITERAL at %s" % p)
    elif isinstance(n, dict):
        for k, v in n.items(): walk(v, p + "." + k)
    elif isinstance(n, list):
        for i, v in enumerate(n): walk(v, p + "[%d]" % i)
walk(d)
PY
```

### 5. Permission allowlists

Agents that ask before running commands often record the **approved command
string** so they need not ask again. Approve one `curl` with a token in the
header, or one `git clone` with a token in the URL, and the credential is now
inside a permission file — which is exactly the kind of file people share or
commit, because it looks like configuration rather than a secret.

### 6. Tool-output caches and logs

Large tool results get spilled to files. Anything a command printed — including
a secret it legitimately fetched — can persist there long after the session.

### 7. Credential stores that are not files

Every sweep in this skill walks the filesystem, which means it is structurally
blind to credentials held in a **store**. A 101,691-file sweep found nothing while
the platform CLI reported an invalid token sitting in the **OS keychain** — the
value lived only there, not in the CLI's own config file.

Enumerate stores alongside files:

| Store | How to look |
|---|---|
| macOS keychain | `security find-generic-password -s '<service>'` — attributes only; add `-w` to read the value |
| Linux | `secret-tool search ...` / `libsecret`, and the GNOME/KDE wallets |
| Windows | Credential Manager (`cmdkey /list`) |
| Browsers | saved-password stores |
| Credential helpers | `gh`, `docker`, `aws`, `git credential-*` |

Two things that surprise people:

- **Reading one may need no authorisation at all.** The keychain value above piped
  straight into a hash command with **no prompt**: the item's ACL did not gate
  reads. "It is in the keychain" describes protection against *other users*, not
  against your own automation — and an agent running as you is your own
  automation.
- **The store's own CLI may refuse to clean it.** A logout command declined to run
  because an environment variable was supplying a *different, working* credential,
  and then printed, as its remedy, the command it had just refused. Unset the
  variable for that one subprocess (`env -u VAR -u VAR2 <cli> logout ...`) rather
  than disturbing the working surface.

### 7. `bashEditDiff` - the harness diffs any TRACKED file a Bash command writes

The one nobody looks for, because nothing the agent typed contains the secret.

When a Bash command modifies a **git-tracked** file, the harness records a
before/after diff into the session transcript at
`toolUseResult.bashEditDiff.files[].hunks[].lines`, and renders it in the
terminal. Observed 2026-09-30: `mkcert -cert-file … -key-file …` into a repo
that tracks its certs put **both** the old committed key and the newly generated
key into the transcript in full - 25 base64 lines removed, 25 added.

Three properties make it its own surface:

- **The command is clean.** The leak is the harness reacting to the write, so
  scanning what the agent typed finds nothing.
- **It is not in `message.content`.** Verified: the marker is absent there and
  present only under `toolUseResult`, so a scan of model-visible content misses
  it entirely.
- **Tracked-ness is the trigger.** The same command writing an ignored path
  produces no diff. A repo whose README says certs are git-ignored, but whose
  `.gitignore` has no such rule, is the exact shape that produces this.

**Scan it line by line.** `bashEditDiff` stores each diff line as a separate
JSON array element, so a PEM header and its body are **never adjacent** in the
raw text. A scan looking for a header followed by base64 in one string reports
"no body" and is wrong. Walk `hunks[].lines` element by element.

**Remediating it has three constraints, all verified:**

- **The agent cannot scrub its own transcript.** An in-place rewrite is refused
  as session-transcript tampering, and printing even a key prefix or length is
  refused as credential materialization. The scrub is user-run, not agent-run.
- **Rotate outside the session.** Regenerating the key from inside - including
  via `!` - is another Bash write, and gets diffed again.
- **Untrack without checking out.** A worktree checkout re-materializes the key.
  Build the removal commit on a temporary index instead:

  ```bash
  GIT_INDEX_FILE=$tmp git read-tree $BASE
  GIT_INDEX_FILE=$tmp git update-index --force-remove <secret paths>
  GIT_INDEX_FILE=$tmp git write-tree        # then commit-tree -p $BASE
  ```

  Review it with `git diff --name-status` only - a full diff prints the deleted
  key back out.

  **And diff it against a freshly fetched base before pushing.**
  `update-index --cacheinfo` takes WHOLE-FILE blobs from the working tree, so if
  the base moved since that tree was cut, the commit silently reverts every
  upstream edit to those files. Observed: a 4-line edit landed as **+4/-23**,
  because upstream had added 23 lines to the same file. It was caught only by
  `--stat` before the push.

  So: `git fetch` first, confirm
  `git diff --stat origin/<base> <new-branch>` shows only the intended lines,
  and for a file that moved upstream build the blob with
  `git merge-file -p <upstream> <old-base> <ours>` - its exit code is the
  conflict count, and 0 gave a clean +4.

The scrub itself: for each line containing `"bashEditDiff"`, `json.loads` it,
`toolUseResult.pop("bashEditDiff")`, re-serialize only changed lines, and write
back with `open("r+b")` + `seek(0)` + `write` + `truncate` so the inode survives
and the live session keeps appending. Run it while the session is idle; abort
before writing on any parse failure.

**Distinguishing a real leak from a marker mention.** Scanning `~/.claude` for
private-key markers also hits other sessions' transcripts that merely discuss
them. Match the **exact lines** of the real key, not the header.

## Five lessons about detection, learned the hard way

Four failure modes, and the thing that actually works.

### Prefix-grep gives false confidence

Sweeping for one token shape finds one token shape. A sweep for `gh[posru]_`
across a machine came back "clean" while an API key, a chat bot token and an
app-level token sat untouched in the same files.

**Sweep for the union of shapes, not the one you are chasing** -- `$SECRET_RE`,
`$AWSID_RE` and `$PEM_RE` as defined at the top. Every snippet here consumes
those variables rather than restating them, including the Python one, which has
to import them through the environment because a quoted heredoc will not expand
them. That detail is the whole point: the first draft of this file restated the
union inline "just there", which is precisely how a partial regex drifts out of
sync with the documented set and produces a false clean.

### Prefix-anchored patterns need a LEFT boundary

A pattern anchored only on the prefix matches the prefix **wherever it occurs**,
including inside a longer string. Sweeping `gh[pousr]_[A-Za-z0-9]{20,}` over an
agent tree returned nine distinct "credentials"; **eight were junk** — the literal
`ghu_`/`ghs_` sequence occurring by chance inside base64url blobs (session ids,
content hashes), whose alphabet contains `_` and `-`. Across 100k files that is
expected, not remarkable.

Two cheap diagnostics, neither of which needs the value:

- **Length.** Providers issue fixed-length tokens. The junk matches were 24–39
  characters against a real length of exactly 40. A wrong length is a wrong match.
- **Adjacent character class.** Print the class of the byte immediately before and
  after the match. A real token is delimited by a quote, space, `=` or `:`;
  **alphanumeric on the left means you are inside a bigger string.** In the sweep
  above, all eight junk hits had an alphanumeric predecessor and the one real hit
  was quote-delimited on both sides.

Fix the pattern with an explicit left boundary — `(?<![A-Za-z0-9])` — and enforce
the provider's exact length. Otherwise the false-positive tax lands on every
future sweep, and a genuinely clean result is indistinguishable from a dirty one.

### Keyword-adjacency regexes lose to prose

The obvious redaction rule is *a secret-ish word, a delimiter, then the value*:

```
(api[_-]?key|secret|token|password)\s*[=:]\s*["']?([A-Za-z0-9/+=_-]{16,})
```

One real 64-char key appeared **fourteen times in one document in eight
phrasings**, and that pattern caught four of them. The misses:

| written as | why it missed |
|---|---|
| `API key: \`<value>\`` | **`api[_-]?key` cannot match `API key`** -- `[_-]?` matches an underscore, a hyphen, or nothing, never a space. This alone defeats it; the missing backtick in `["']?` would defeat it a second time |
| `API key value: \`<value>\`` | same space, plus a word between the name and the delimiter |
| `Fetched API key from Secrets Manager: <value>` | same space, plus several words (this one does reach the `secret` alternative via "Secrets Manager") |
| `**API key**: <value>` | same space, plus markdown emphasis between name and delimiter |
| `Authorization: <value>` | "Authorization" was not in the keyword list at all |
| `API key \`<value>\`` | same space, and no delimiter either |

The space is the finding, and it is easy to misdiagnose: four of these six look
like punctuation problems and are actually a keyword problem. A fix that adds
backticks and allows intervening words still misses rows 1, 2 and 4 until
`api[_-]?key` becomes `api[_ -]?key`. Verified by running both versions.

Widening to allow intervening text then broke other things (see below). **Do not
try to win this.** For cleaning a known leak, do a **literal replacement of the
known value** — exact, complete, no regex. Save patterns for *prevention at
ingest*, where a miss costs one leak rather than the whole cleanup.

### Bare high-entropy matching is unusable

The tempting fix for the above is to match the value shape alone — say
`[0-9a-f]{32,}`. It does not survive contact with a real transcript, because
**64-hex strings are everywhere and almost none are secrets**: container image
digests (`sha256:…`), object-store canonical user ids, avatar hashes, diff
anchors, trace ids. Raising the bound to exclude 40-char SHA-1 does not help,
since the collisions are at 64.

### What does work: keyword adjacency plus a value-shape guard

Keep the adjacency requirement, add backticks to the quote class, allow a short
run of **letters and spaces only** between the name and the delimiter, and then
reject captures that are *names* rather than values:

```python
# Order matters: anything that IS a known credential shape must win before the
# name-shaped tests run.
_KNOWN_SECRET = re.compile(
    r"^(gh[posru]_|github_pat_|glpat-|xox[baprsedc]-|xapp-|sk-|nvapi-|AIza)"
    r"|^(AKIA|ASIA)[0-9A-Z]{16}$")

_IDENTIFIER_SHAPES = (
    # Unreachable with the capture class above, which excludes `$` -- so a
    # `$VAR` value is never captured in the first place. Kept because a wider
    # capture class is a natural extension and this is the guard it would need.
    re.compile(r"^\$"),                            # $ENV_REFERENCE
    re.compile(r"^[A-Z][A-Z0-9_]*$"),              # ENV_VAR_NAME
    re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)+$"),  # kebab-or-snake resource name
)

def is_identifier(v):
    if _KNOWN_SECRET.search(v):
        return False
    retval = any(p.search(v) for p in _IDENTIFIER_SHAPES)
    return retval
```

**Check the credential shapes first, or the guard eats real secrets.** Two
failures that a naive version has by construction:

- An AWS key id is `AKIA` followed by 16 uppercase alphanumerics -- i.e. it is
  `[A-Z0-9]{20}` end to end, so it matches the `ENV_VAR_NAME` test and **every**
  AWS key id is silently exempted. A 100% false-negative rate for a family this
  file lists as mandatory.
- A lowercase UUID (`8-4-4-4-12` hex groups) matches the kebab test, so
  UUID-shaped API keys and client secrets are exempted too.

Writing that first bullet is itself an example of the problem: spelling out a
full example key id trips this repo's own pre-publish gate, because a structural
scanner cannot tell an illustration from a live credential. Describe the shape
instead of instantiating it.

Without that guard the redactor eats `MY_SERVICE_API_KEY`, `some-service-auth-token-dev`
and `$SOME_TOKEN` — protecting nothing while making the stored text useless.
Allowing punctuation in the intervening run also matches things like
`| token | POST /oauth2/token (grant_type=` and redacts a URL.

Validate a redactor by running it over a **large real corpus** and reading every
line it changes. A run over ~730k lines that changes 8 lines, all genuine, is
evidence. A run that changes 300 lines is a bug.

## Do not let the cleanup become another copy

An agent investigating a leak must never print the values it finds, or the
investigation itself lands the secret in the session transcript (surface 2) and
the tool-output cache and logs (surface 6) — plus surface 3, if it writes its
findings to a file the agent then snapshots.

The short version: compare by **fingerprint** (`printf '%s' "$T" | shasum | cut -c1-10`),
identify a token by **asking the service who it is** rather than by reading it,
and count with `grep -c` / `grep -l` so no value reaches scrollback.

See **`secrets-in-agent-sessions`** for the full set of techniques and the traps
that put secrets into transcripts in the first place.

## Prevention

- **One copy.** Environment references in config, never literals. A second copy
  is a future stale credential.
- **No tokens in git remotes.** Credential helper or SSH.
- **Redact at ingest** in anything that persists sessions. Structured token
  prefixes are reliable; prose-shaped assignments are best-effort. Both beat
  nothing.
- **Never paste a secret into an agent session** to hand it to another process.
  Move it out-of-band; the transcript is a permanent store.
- **After rotating, sweep for the OLD value** across all seven surfaces. If it is
  still on disk, the rotation is not finished.
- **Mode the config that holds the references.** Shell profiles and their whole
  backup family are frequently `0644` inside a `0755` home. That is only a nit
  until you ask *who else is on the box*: package managers create unprivileged
  **build accounts** (MacPorts' `macports`, Homebrew and Nix equivalents) whose
  entire purpose is to run third-party `configure`/`make` as a non-root user. Any
  install therefore executes upstream build scripts under an account that can read
  every world-readable file in your home — including the profile holding your
  tokens. `chmod 600` the profile family; it does not affect sourcing.

## Related

- `pre-open-source-credential-audit` — auditing a git repo and its **history**
  before making it public. Mostly disjoint from this skill, but **not entirely**:
  permission allowlists (surface 5) and project-scoped tool configs (surface 4)
  do get committed, and a secret in git history survives any amount of local
  sweeping. Run both before publishing a repo.
- `secrets-in-agent-sessions` — the behavioural counterpart: not creating these
  copies in the first place. **Merge-order note:** that skill ships in a sibling
  PR; if this one lands first the reference resolves only once both are in.
- `prevent-committing-secrets` — the gate on the one surface that is versioned
  and shared with everyone: a pre-commit secret scanner, so the value never
  reaches history to begin with.
