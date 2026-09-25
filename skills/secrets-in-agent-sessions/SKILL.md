---
name: secrets-in-agent-sessions
description: |
  Work with credentials during a coding-agent session without writing them into
  the transcript, the tool-output cache, the permission allowlist or the logs.
  Use when: (1) a task requires fetching, comparing, rotating or installing a
  secret and an agent is doing it; (2) you are about to paste a token into a chat
  to hand it to a process or another agent; (3) a command you want to run takes a
  credential as an argument or header; (4) you need to prove a rotation happened
  without revealing either value; (5) reviewing why a secret ended up in a
  session log. Covers why one echo becomes several permanent copies, the four
  traps that leak silently (command strings in task summaries, argv, narration,
  spilled tool output), and the fingerprint / ask-the-service / env-to-file
  techniques that avoid all of them.
author: Claude Code
version: 1.1.0
date: 2026-08-14
---

# Keeping secrets out of agent sessions and logs

## Problem

A chat session with a coding agent is not ephemeral. A single secret that
appears once in a session typically ends up in **all** of:

- the session transcript on disk, often permanently
- any "remember this session" memory store, usually embedded and searchable, so
  it can resurface in a *later* session's context
- spilled tool-output files, when a result was too large to inline
- the agent's own logs
- the permission allowlist, if the approved command string contained it

So the cost of echoing a credential once is not one copy. It is several, in
places with different lifetimes, none of which are in git and most of which
nobody will ever grep.

And this is the failure mode that keeps biting: an agent handling a secret
**correctly** — fetching it from a secret manager with proper credentials, using
it once, never committing it — still leaks it, purely by narrating what it did.

## The four traps

### 1. The credential is in the command string

The most common one, because the command is *correct*:

```bash
curl -H "X-Api-Key: <value>" https://service/endpoint
```

Nothing is wrong with that command. But the command string itself gets recorded:
in the transcript, in any background-task summary, in the shell history of the
process, and in the permission allowlist if the user approves it. One real API
key reached disk this way in four separate files, none of which were the file
anyone was looking at.

**Instead:** put it in the environment and reference it, so the value never
appears in the *recorded command string*:

```bash
KEY="$(read-from-secret-store)" \
  sh -c 'curl -H "X-Api-Key: $KEY" https://service/endpoint'
```

**This fixes trap 1 but not trap 2, and the difference matters.** What gets
recorded -- transcript, task summary, allowlist -- is the unexpanded `$KEY`, so
the durable copies are gone. But the inner shell expands `$KEY` before exec'ing
curl, so the *live process* still carries the value in its argument vector for
the duration of the call.

To close both, hand the header to curl on stdin, which never touches argv:

```bash
KEY="$(read-from-secret-store)" sh -c \
  'printf "header = \"X-Api-Key: %s\"\n" "$KEY" | curl -K - https://service/endpoint'
```

A `chmod 600` file with `curl -H @file` works too. Readers will otherwise
assume the env form covers both surfaces; it covers the one that persists.

### 2. `argv` is world-readable while the process runs

Beyond logging, arguments are visible to any process that can read `/proc` or
run `ps`. A credential passed as `--token <value>` is exposed to every user on
the box for the lifetime of the call. Environment or stdin, never argv.

```bash
printf '%s' "$TOKEN" | some-tool auth --token-stdin
```

### 3. Narration

The agent explains what it just did, and the explanation contains the value:

> Fetched the API key from the secret store: `<value>`

or writes it into a summary, a plan, or a "here is what I found" note. This is
the hardest to catch because it is not a command, it is prose — and prose is
exactly what pattern-based redaction is worst at.

**Rule: state that you obtained a credential, never what it is.** "Fetched the
key (fingerprint `4ef1a0e67f`)" carries every bit of information the reader
needs.

### 4. Tool output that was not yours

A command legitimately prints a secret — `env`, a config dump, a `describe` call
on a secret resource, a verbose HTTP trace. The agent did not choose to echo it,
but the output is captured all the same, and large outputs get spilled to files
that outlive the session.

**Filter at the point of capture**, not after:

```bash
SECRET_RE='(^|[^A-Za-z0-9_-])(gh[posru]_|github_pat_|glpat-|xox[baprsedc]-|xapp-|sk-(ant-|or-)?|nvapi-|AIza)[A-Za-z0-9_-]{16,}'
AWSID_RE='\b(AKIA|ASIA)[0-9A-Z]{16}\b'
some-command | sed -E "s/$SECRET_RE|$AWSID_RE/<REDACTED>/g"
```

That union is the one defined in `agent-credential-leak-surfaces` -- keep the
two in step, and read that skill for why it is shaped this way. Two properties
it took a round of review to get right: it is **left-anchored**, or it matches
`flask-sqlalchemy` and `dask-distributed` on the `sk-` branch; and AWS key ids
get their own exactly-anchored pattern rather than being folded into the generic
suffix. A filter missing `github_pat_`, `ASIA`, `xoxc-`/`xoxd-` or `AIza` passes
that whole family into the spilled output this exists to protect.

## Techniques that avoid all four

### Compare by fingerprint

Proves two values differ, or that a rotation happened, revealing neither:

```bash
fp() { printf '%s' "$1" | shasum | cut -c1-10; }
fp "$OLD_TOKEN"    # 8184916b4a
fp "$NEW_TOKEN"    # 4ef1a0e67f     -> different, therefore rotated
```

Truncate to ~10 hex chars: enough to compare, useless for reversing.

### Ask the service who the token is

To find a token in a web UI you need its identity, not its value. Nearly every
API will tell you:

```bash
r="$(mktemp)"; trap 'rm -f "$r"' EXIT
curl -s -D - -o "$r" -H "Authorization: token $T" <api>/user \
  | grep -i '^x-oauth-scopes:'          # scopes
python3 -c "import json,os;print(json.load(open(os.environ['r']))['login'])"  # account
```

Use `mktemp` and a cleanup trap rather than a fixed path. `-o /tmp/r` leaves an
authenticated API response at a predictable, world-readable location that
outlives the command, and a predictable name in a shared `/tmp` is
symlink-attackable. Spilled response bodies are their own small surface -- the
same "one secret becomes several copies" failure in miniature.

Account plus scopes plus "last used" is almost always enough to pick the right
row out of a token list. Same for chat platforms: an `auth.test`-style endpoint
returns team and bot identity.

### Test liveness without revealing anything

Rotation verification is a yes/no question:

```bash
for t in $(collect-candidates); do
  ok=$(curl -s -X POST <api>/auth.test -H "Authorization: Bearer $t" \
        | python3 -c "import json,sys;print(json.load(sys.stdin).get('ok'))")
  [ "$ok" = "True" ] && echo "STILL LIVE fp=$(fp "$t")"
done
```

Prints a fingerprint for anything still valid and nothing for the rest.

### Count and locate, never display

```bash
grep -rl  <pattern> <dir>     # which files
grep -rc  <pattern> <file>    # how many
grep -rhoE <pattern> <dir> | sort -u | wc -l    # how many DISTINCT values
```

`sort -u | wc -l` is the one that matters when auditing: eight occurrences of one
token is a very different problem from eight different tokens.

### Move a value between places without it passing through the model

To get new credentials from a shell profile into a config file, let a subshell
source the profile and a script read `os.environ` — the agent orchestrates but
never sees the values:

```bash
bash -c 'source ~/<profile> >/dev/null 2>&1; exec python3 write_config.py'
```

`write_config.py` reads `os.environ`, writes atomically (`tempfile` +
`os.replace`, preserving mode), and prints only fingerprints and "written".

### Redact before you print, if you must print at all

When output may contain secrets and you need to show *structure*:

```bash
... | sed -E 's/=.*/=<redacted>/'                    # config lines
... | sed -E 's|://[^/@]*@|://<CREDS>@|g'            # URLs with credentials
```

Leave the mask **unanchored**. A pattern written for the live assignment,
`^\s*(export\s+)?NAME=`, passes commented-out lines through untouched - and a
dotfile's `# export TOKEN=...` is exactly where a retired, possibly still-valid
token is kept. One anchored mask over a shell profile printed such a line in
full. When only the set of variables matters, print names and never lines:

```bash
grep -o -E '^[[:space:]#]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=' ~/.bash_profile
```

To ask whether two secrets are the same one, compare hashes, not values.

## Handing a secret to another process or agent

Do not paste it into the chat. That is the single highest-cost action available,
because it puts a live credential into the most-replicated surface you have, and
usually into a memory store as well.

Use a channel the agent does not read: a `chmod 600` file, the platform's own
secret store, an out-of-band message. If a value must move between machines,
move it directly, not via a transcript that both machines' agents will persist.

## When it has already happened

Assume the value is in more places than the one you found — transcript, memory
store, spilled tool output, logs, and the permission allowlist all take
independent copies with independent lifetimes.

Rotate first (it is the only step that actually revokes access), then sweep for
the **old** value. See **`agent-credential-leak-surfaces`** for where the copies
accumulate and how to clean them, including why a literal-value replacement
beats regex for cleanup.

## Related

- `agent-credential-leak-surfaces` — the forensic side: the six places copies
  accumulate, and how to find and clean them.
- `pre-open-source-credential-audit` — auditing a git repo and its history
  before making it public.
- `prevent-committing-secrets` — the commit-time gate on the other leak path: a
  pre-commit secret scanner, and the git template that puts one in every new
  repo without anyone remembering to.
