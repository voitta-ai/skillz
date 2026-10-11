---
name: deployed-venv-false-pass
description: |
  Verify what a DEPLOYED Python process actually imports, when a service runs
  from its own venv while you develop in a source checkout. Use when: (1) you
  merged a change and want to confirm the running service has it, (2) a check
  like `python -c "import pkg; print(hasattr(pkg,'new_thing'))"` says True but
  the service behaves as if the change is absent, (3) a config naming a new
  option fails at runtime with "needs <old option>" or an unexpected TypeError,
  (4) you are about to ship a config change that depends on freshly merged
  code, (5) `pip install` reported success but behaviour did not change. The
  trap: `sys.path[0]` is the cwd (for `-c`/`-m`) or the script's own directory,
  so running a probe from inside the source tree imports the checkout and every
  check passes falsely, whatever interpreter you named.
author: Claude Code
version: 1.0.0
date: 2026-09-30
source: https://github.com/voitta-ai/skillz
source_file: skills/deployed-venv-false-pass/SKILL.md
---

# Verifying a deployed venv, without fooling yourself

> **Canonical source.** This skill lives at
> https://github.com/voitta-ai/skillz (`skills/deployed-venv-false-pass/SKILL.md`).

## Problem

A service runs from its own virtualenv, usually a non-editable install of a
package you also have checked out as source. The two drift: merging to the
source repo is not a deploy.

The obvious check is to import the package with the deployed interpreter and
look for the new symbol. That check is unreliable in the one situation you most
want it: **run it from inside the source checkout and it imports the checkout,
not the venv**, and reports every merged change as present.

Naming the interpreter by absolute path does not help. Neither does
`PYTHONPATH`. `sys.path[0]` wins because it is first.

## Context / Trigger conditions

- You merged a change and want to know whether the running service has it.
- A probe says the symbol exists, but the service fails as though it does not.
- A config that names a newly added option fails at runtime — commonly
  `... needs '<older option>'` from a validator that predates the change, or a
  `TypeError` about an unexpected keyword argument.
- `pip install` printed success and nothing changed. (A version-pinned install
  whose version string did not move is often a silent no-op; see Notes.)
- You are about to change a config in a way that depends on freshly merged code.

## Solution

### 1. Probe from a neutral directory

```bash
cd /tmp && <deployed-venv>/bin/python -c \
  "import <package>.<module> as m; print(m.__file__)"
```

The printed path is the answer. If it is under the venv's `site-packages`, you
are seeing the deployment. If it is under your checkout, the probe was
shadowed — discard whatever it told you and run it again from `/tmp`.

### 2. Assert on the code, not on a version

```bash
cd /tmp && <deployed-venv>/bin/python -c "
import inspect, <package>.<module> as m
print('has change:', 'new_symbol' in inspect.getsource(m.target_function))
print('signature :', inspect.signature(m.TargetClass.__init__))
"
```

A version string is not evidence: packages installed from a VCS ref commonly
keep the same version across many commits, so `pip show` can report the exact
version you expect while the code is months old.

### 3. Refresh, then re-verify the same way

```bash
<deployed-venv>/bin/pip install --no-deps --force-reinstall <path-to-checkout>
```

`--force-reinstall` because pip will otherwise decide the requirement is already
satisfied. `--no-deps` keeps the refresh to the one package. Then repeat step 2
from `/tmp` — do not assume the install worked because it exited 0.

### 4. Deploy the code before the config that needs it

A config naming a feature the deployed code lacks does not fail at load time.
It fails when that code path runs, which can be long after a human committed to
the operation — after an approval, after earlier steps have already had real,
irreversible effects. Order is: refresh the deployment, verify, then change the
config.

## Verification

You have verified the deployment when both are true, from a neutral cwd:

- `m.__file__` is inside the deployed venv's `site-packages`;
- an `inspect` assertion on the new symbol passes.

## Example

Measured, not reasoned about. A package `pkgdemo` exists only in a source tree,
and is **not** installed in the interpreter being used:

```
=== -c with cwd inside the source tree ===
  sys.path[0]: '' -> checkout            # imported the checkout
=== a SCRIPT living in the source tree, run from elsewhere ===
  sys.path[0]: '/tmp/sp-demo' -> checkout # STILL the checkout
=== neutral cwd, -c ===
  sys.path[0]: ''                         # ModuleNotFoundError: honest
=== PYTHONSAFEPATH=1, cwd inside the source tree ===
  ModuleNotFoundError: No module named 'pkgdemo'
```

The second case is the nastier one: moving your shell out of the repo is not
enough if the *probe script itself* lives in the repo, because `sys.path[0]`
then becomes the script's own directory.

## Notes

- **`sys.path[0]` differs by invocation.** `-c` and `-m` put the cwd (as `''`)
  first; a script puts the script's directory first. Both shadow
  `site-packages`, which is later on the path.
- **`PYTHONSAFEPATH=1`** (Python 3.11+, or the `-P` flag) removes that first
  entry. Setting it for a probe is a reasonable belt alongside the neutral cwd,
  and is worth setting for a service that should never import from its cwd.
- **An editable install is a different animal.** It deliberately points at a
  checkout, so "the deployment is the checkout" is correct there, and the
  question becomes *which* checkout — a worktree on a branch will still lose to
  the main checkout when cwd shadows it.
- **Service managers make this easy to miss.** launchd `WorkingDirectory`,
  systemd `WorkingDirectory` and container `WORKDIR` decide what the real
  process shadows, and that is usually not where you were standing when you
  tested.
- **Two venvs can disagree.** If more than one venv can run the code, verify the
  one the service manager actually invokes — read it out of the unit/plist
  rather than assuming.

## References

- [Python docs: `sys.path`](https://docs.python.org/3/library/sys.html#sys.path)
  — the initialisation rules for `sys.path[0]`.
- [Python docs: `PYTHONSAFEPATH`](https://docs.python.org/3/using/cmdline.html#envvar-PYTHONSAFEPATH)
- [pip: `--force-reinstall`](https://pip.pypa.io/en/stable/cli/pip_install/#cmdoption-force-reinstall)
