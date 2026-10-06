---
name: macos-sandbox-exec-agent-command-confinement
description: |
  Confine shell commands an AI agent runs on macOS to one directory tree with
  `sandbox-exec` (Seatbelt), for reads AND writes, with symlink escapes and
  runtime-resolved paths caught in the kernel. Use when: (1) an agent's
  "working directory" policy is only a cwd and you need a path an agent cannot
  escape by `cat /abs/path`, `ln -s ~/.ssh link`, or `d=../x; cat $d/secret`;
  (2) a textual path allow/deny guard is being called "not a sandbox" and you
  want the real thing without Docker/VMs; (3) commands under the sandbox fail
  with `shell-init: error retrieving current directory: getcwd`, `Operation
  not permitted` on `~/.gitconfig`, or a write to `/tmp` is denied although
  `/tmp` was allowed (realpath is `/private/tmp`); (4) deciding what under
  `$HOME` a git/gh/node toolchain must still read; (5) auto-approving an
  agent's in-tree writes and needing the containment that makes that sound;
  (6) `git push` must work inside the sandbox but `~/.ssh` must not be
  readable -- or `git ls-remote` hangs silently inside the profile (Homebrew's
  `credential.helper osxkeychain` waiting on a keychain prompt).
  Encodes the profile shape (allow-default + global write deny + read deny
  under /Users and /Volumes + carve-outs), the ancestor `file-read-metadata`
  rule that traversal needs, realpath everywhere, per-tenant allowances, the
  fail-closed wrapper, the argv-in-logs trap, and the live tests that prove
  it.
author: Claude Code
version: 1.1.1
date: 2026-08-28
source: Built for voitta-ai/shmobster #116 (sandbox per Slack channel), verified live on Darwin 25 against a real git worktree.
source_file: skills/macos-sandbox-exec-agent-command-confinement/SKILL.md
---

# Confine agent-run commands to a tree with macOS `sandbox-exec`

Canonical source: this file in `voitta-ai/skillz`.

## Problem

An agent host (a Slack bot, a CLI wrapper, an approval loop) has a per-tenant
"working directory", but the directory is only `cwd=` on `subprocess.run`.
Nothing stops an absolute path elsewhere, a symlink inside the tree pointing
out of it, or a path the shell resolves at runtime. A textual guard that
inspects argv tokens catches `cat ~/Secrets/x` and nothing else, and usually
says so in its own docstring. If you also want to *auto-approve* in-tree
writes (so `cp x app/index.html && git add && git commit` does not need a
human), the grant is only sound if "in tree" is enforced somewhere the shell
cannot argue with.

On macOS that somewhere is Seatbelt: `sandbox-exec -p <profile> /bin/sh -c
<command>`. It is marked deprecated in the man page and still works on Darwin
25 (macOS 26); Claude Code, Codex CLI, Gemini CLI and others use it for exactly
this.

## Trigger conditions

- You need reads and writes confined, not just writes.
- A symlink or `$VAR/path` must not be an escape.
- You are on macOS with no Docker/VM, and the toolchain (git, gh, node, python)
  must keep working inside the confinement.
- Symptoms once you start: `shell-init: error retrieving current directory:
  getcwd: cannot access parent directories: Operation not permitted`;
  `fatal: unable to access '~/.gitconfig': Operation not permitted`;
  `warning: unable to access '~/.gitignore_global'`; a write to `/tmp` denied
  even though `/tmp` is in the allow list.

## Solution

### 1. Profile shape (later rules win)

```scheme
(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath "<tree>") (subpath "<tree>.worktrees")
                   (subpath "<realpath of tempdir>") (subpath "/private/tmp")
                   (subpath "/dev")
                   (subpath "<home>/.npm") (subpath "<home>/.cache")
                   (subpath "<home>/Library/Caches"))
(deny file-read* (subpath "/Users") (subpath "/Volumes"))
(allow file-read-metadata (literal "/Users") (literal "/Users/<me>")
                          (literal "/Users/<me>/g") ...)      ; every ancestor
(allow file-read* (subpath "<tree>") (subpath "<tree>.worktrees")
                  <the write roots again>
                  (subpath "<home>/.gitconfig") (subpath "<home>/.gitignore_global")
                  (subpath "<home>/.config/gh") (subpath "<home>/.nvm")
                  (subpath "<home>/.local")
                  <per-tenant allow_read entries>)
(deny file-read* file-write* (subpath "<tree>/<excluded>"))   ; last, so it wins
```

Decisions baked into that shape:

- **Writes: deny everything, carve back.** The tree, its sibling
  `<tree>.worktrees/` (branch worktrees live next to the repo, not under it),
  the temp dir, `/dev` (`/dev/null`, ttys), and the three caches the
  toolchain fails without (`~/.npm` for npm's `_cacache`/`_logs`, `~/.cache`,
  `~/Library/Caches`). Caches, not project data.
- **Reads: deny under `/Users` and `/Volumes`, not just `$HOME`.**
  `/Users/Shared`, other users' homes, and every mounted drive are as far
  outside the tree as `~/Documents` is, and a mounted drive is where the data
  someone did not mean to expose lives. The system roots (`/usr`,
  `/opt/homebrew`, `/Library`, `/System`, `/private/etc`) stay readable: the
  toolchain lives there and is the same for every tenant. This is the
  allow-default (blocklist) style; a deny-default allowlist is stronger but
  means enumerating every dyld cache, locale file and framework the toolchain
  touches. Know which you chose and why (see References for what allow-default
  leaves open).
- **`~/.ssh` is not a default read.** A read-only `cat ~/.ssh/id_*` is
  exactly what an auto-approve path lets through. A tenant that pushes over
  ssh lists `~/.ssh` in *its own* allowance; nobody else gets it.
- **Allowances are per tenant, never global.** A global "extra read paths"
  knob turns one tenant's ssh key into every tenant's readable file.
- **Excludes last.** The tenant's own "keep this subtree off-limits" list is
  the final rule, so it beats every allow above it.

### 2. Three mechanics you will hit

1. **Ancestor metadata.** Denying `file-read*` on `/Users` denies stat on
   `/Users/<me>` too, and `getcwd()` walks parents: the shell prints
   `shell-init: error retrieving current directory` and every relative path is
   suspect. Add `(allow file-read-metadata (literal <dir>))` for every
   directory from each allowed path up to and including the deny root. Compute
   it, do not hand-list it.
2. **realpath everything.** Seatbelt matches on the resolved vnode path. That
   is *why* symlinks cannot escape -- and why `/tmp` in a rule never matches
   (`/private/tmp` does), why `tempfile.gettempdir()` must be realpath'd, and
   why a relative entry in a tenant's exclude list must be joined to the
   tenant's cwd, not the host process's cwd, before resolving.
3. **Quote for Seatbelt.** Paths go in double quotes; escape `\` and `"`. A
   path with a quote in it must not be able to close the literal.

### 3. Wrapper: fail closed, and mind the logs

```python
def wrap(command, tenant):
    exe = shutil.which("sandbox-exec")
    if not exe:
        raise RuntimeError("sandbox-exec not found; refusing to run unconfined")
    retval = [exe, "-p", profile(tenant), "/bin/sh", "-c", command]
    return retval

subprocess.run(wrap(cmd, tenant), capture_output=True, text=True, cwd=tenant_cwd, timeout=...)
```

Never fall back to a bare shell when the sandbox is missing -- that is the
one moment the confinement matters most. And: the profile is now *in argv*.
`subprocess.TimeoutExpired.__str__` and similar quote argv, so a timeout log
line becomes a screenful; log the fact ("timed out after Ns") and the
scrubbed command, not `str(exc)`.

### 4. Git without `~/.ssh` (do not grant the key directory)

The first instinct -- "the channel that pushes needs `~/.ssh` readable" --
hands a read-only `cat ~/.ssh/id_*` to whatever auto-runs read-only
commands. ssh needs `config`, `known_hosts` (0600 by convention, and host
verification is mandatory without a tty) and a key or an agent; a mode-based
"deny 0600 files" rule breaks it on `known_hosts`. Route git over https
instead, per process, with config injected through the environment
(git >= 2.31), and let `gh` supply the token from the keychain:

```sh
GIT_TERMINAL_PROMPT=0
GIT_CONFIG_COUNT=4
GIT_CONFIG_KEY_0=url.https://github.com/.insteadOf   GIT_CONFIG_VALUE_0=git@github.com:
GIT_CONFIG_KEY_1=url.https://github.com/.insteadOf   GIT_CONFIG_VALUE_1=ssh://git@github.com/
GIT_CONFIG_KEY_2=credential.helper                   GIT_CONFIG_VALUE_2=
GIT_CONFIG_KEY_3=credential.helper                   GIT_CONFIG_VALUE_3='!gh auth git-credential'
```

Two things bite without warning:

- **The empty `credential.helper` is load-bearing.** Git runs every helper
  configured at any level, and Homebrew ships `credential.helper osxkeychain`
  in `/opt/homebrew/etc/gitconfig`. Inside the sandbox that helper hangs
  waiting on a keychain prompt, so `git ls-remote` sits until your timeout
  with no error text. The empty value resets the list; then only `gh` runs.
- **The operator's `~/.gitconfig` may carry the opposite rewrite**
  (`url.ssh://git@github.com/.insteadOf https://github.com/`, common for
  people who push over ssh). The env entries win, so the https URL survives;
  verify with `GIT_TRACE=1` that the transport is `http.c`, not `ssh`.

`gh` keeps its token in the keychain, which seatbelt does not restrict, so
`gh auth git-credential get` works inside the profile. Check
`~/.config/gh/hosts.yml` does not contain `oauth_token:` -- on a host with no
keychain `gh` writes the token there, and then that file is the secret.
Verified: `git ls-remote` and an authenticated `git push --dry-run` inside the
profile with `~/.ssh` fully denied.

Same rule for AWS: `~/.aws/credentials` holds every profile's keys, so do not
grant it; give a tenant its keys through its own environment.

### 5. CI without macOS

Stub the wrapper to `["/bin/sh", "-c", command]` when `shutil.which
("sandbox-exec")` is empty, so a Linux CI still exercises the exec path;
assert the *profile text* everywhere (pure function) and the kernel's answer
only where the kernel is macOS.

## Verification

Run these under the profile; every denial must be `Operation not permitted`,
not silence:

```sh
echo x > f && cat f                       # in-tree write: ok
touch ~/.probe                            # write outside: denied
ln -s ~ link && touch link/.probe         # symlink out of the tree: denied
ls ~ ; ls /Users/Shared ; ls /Volumes     # reads outside: denied
d=secret; cat $d/x                        # runtime-resolved excluded path: denied
git status ; gh --version ; node --version # toolchain still runs
echo ok > /tmp/probe                      # temp dir writable (via /private/tmp)
```

If the symlink test is *allowed*, you gave the rule `/tmp` or another
un-resolved path and it silently never matched.

## Example

A Slack agent with one policy per channel `{"cwd": "~/g/projects/app",
"exclude": ["~/g/OneDrive"], "allow_read": ["~/.ssh"]}` builds one profile
per channel from that policy. A YOLT-unsafe `cd ~/g/projects/app.worktrees/
feat && cp /tmp/x app/index.html && git add app/index.html && git commit`
then runs without a human card, because the only place it can write is the
tree; `touch ~/g/projects/other/x` from the same channel is `Operation not
permitted`; and a channel without `allow_read: ["~/.ssh"]` cannot `cat` the
key even though the command is read-only.

## Notes

- Not contained: the network. `git push`, `gh`, `aws`, `curl -X POST` are
  external effects; keep them behind whatever approval you have.
- `(allow default)` also leaves process-exec, mach lookups and IPC open;
  published escapes of allow-default agent sandboxes use exactly those. If
  the threat model includes a hostile model rather than a careless one,
  move to deny-default and pay the enumeration cost.
- `file-write*` covers create/unlink/rename/mode; a single deny is enough.
- Apple's documentation for the profile language is the `.sb` files under
  `/System/Library/Sandbox/Profiles/` and `/usr/share/sandbox/`; read those
  for operation names.

## References

- [Sandboxing an AI Harness on macOS](https://alejandromp.com/development/blog/sandboxing-an-ai-harness-on-macos/) -- allow-default vs deny-default profile styles for agent harnesses.
- [Escaping Antigravity's Allow-Default Seatbelt](https://www.pillar.security/blog/escaping-antigravitys-allow-default-seatbelt) -- what an allow-default profile leaves open.
- [agent-seatbelt-sandbox](https://github.com/michaelneale/agent-seatbelt-sandbox) -- Seatbelt to stop data egress from agents.
- [gemini-cli #22832: strict macOS sandboxing using a Seatbelt allowlist](https://github.com/google-gemini/gemini-cli/pull/22832) -- a deny-default implementation and the enumeration it needs.
- [HackTricks: macOS Sandbox](https://hacktricks.wiki/en/macos-hardening/macos-security-and-privilege-escalation/macos-security-protections/macos-sandbox/index.html) -- profile language reference and system profile locations.

## Related

- `agent-credential-leak-surfaces` — what the agent reaches when nothing
  confines it. That skill enumerates the six local surfaces holding copies of
  your secrets; this one is the kernel-level answer to most of them, and its
  read-deny list is only correct if you know what those surfaces are.
- `secrets-in-agent-sessions` — the same problem upstream: how a credential
  ends up somewhere an agent-run command can read it at all.
- `git-worktree-convention` — the sibling-worktree layout that makes "one tree"
  a well-defined boundary. A profile written against a nested or ad-hoc
  worktree path confines something other than what you meant.
- `parallel-agent-session-collisions` — the social version of the same
  boundary: a session writing into a tree that is not its own. This confines it
  mechanically; that one covers the case where the write was legitimate and the
  claim was not.

