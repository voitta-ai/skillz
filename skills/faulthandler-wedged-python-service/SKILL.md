---
name: faulthandler-wedged-python-service
description: |
  Diagnose and recover a long-running Python service (a Slack Socket Mode bot, a
  queue worker, any daemon) that stops doing work while the PROCESS stays alive --
  so the supervisor's health check sees it as healthy and never restarts it. Use
  when: (1) a daemon goes silent -- no new log lines, no events handled -- but
  `ps` shows it running at ~0% CPU in state S; (2) a KeepAlive/launchd/systemd
  supervisor never restarts it because the process did not exit; (3) you need to
  know WHERE it is stuck without attaching a debugger; (4) you added
  `faulthandler.register(SIGUSR1, ...)` and `kill -USR1 <pid>` silently KILLS the
  process instead of dumping; (5) a wedge that "wasn't an issue a few days ago"
  is now frequent. Covers the faulthandler SIGUSR1 thread dump, the chain=False
  gotcha, how to read the dump (half-open socket vs frozen interpreter vs
  deadlock), an out-of-process heartbeat as the recovery net, and the host-
  pressure angle behind a sudden increase in frequency.
author: Claude Code
version: 1.0.0
date: 2026-10-05
source: https://github.com/voitta-ai/skillz
source_file: skills/faulthandler-wedged-python-service/SKILL.md
---

# Finding where a deaf-but-alive Python service is stuck

> **Canonical source.** This skill lives in the repo at
> https://github.com/voitta-ai/skillz (file:
> `skills/faulthandler-wedged-python-service/SKILL.md`).


## Problem

A daemon stops doing its job -- a Slack Socket Mode bot stops answering, a worker
stops draining its queue -- but the process never exits. `ps` shows it alive at
~0% CPU. The supervisor (`launchd` KeepAlive, `systemd`, a container restart
policy) only restarts on exit, so it sees a healthy service and does nothing. A
human notices minutes or hours later and restarts it by hand. You need to see
WHERE it is stuck, live, without a debugger -- and ideally recover it
automatically next time.

## Context / Trigger Conditions

- No new log lines for a long stretch, while the process is up at ~0% CPU (S, not
  R or U).
- The supervisor's liveness check is "did the process exit", which a wedge
  defeats.
- You cannot easily attach `gdb`/`py-spy` (not installed, or no time), or you want
  a signal you can fire any time.

## Solution

### 1. Arm faulthandler on a signal -- with chain=False

At startup:

```python
import faulthandler, signal
faulthandler.enable()  # dump on a fatal signal (crash), too
# chain=False is load-bearing -- see the gotcha below.
faulthandler.register(signal.SIGUSR1, all_threads=True, chain=False)
```

Then, when it wedges:

```bash
kill -USR1 <pid>   # dumps a traceback for EVERY thread to stderr
```

The dump goes to the process's stderr -- i.e. wherever the supervisor sends it
(a `.err.log`, `journalctl`, `docker logs`). It does not interrupt the process.

### 2. THE GOTCHA: chain=True makes the dump kill the process

`SIGUSR1`'s default disposition is to **terminate** the process.
`faulthandler.register(sig, chain=True)` dumps the stacks and then **calls the
previous handler** -- which, if you never installed one, is the default
(terminate). So `chain=True` turns your diagnostic `kill -USR1` into a kill: you
get the dump, then the process dies and the supervisor restarts it. That looks
like "the dump crashed it". Use **`chain=False`** so it dumps and continues,
which is the whole point when you want to observe a wedged-but-running process.
(`faulthandler.enable()` still chains genuinely fatal signals; that is about
crashes, not this.)

### 3. Read the dump

Match the stuck thread's stack to the failure:

- A receive loop blocked in **`ssl.read` / `socket.recv`** = a half-open
  connection: the peer went away without a FIN/RST, there is no read timeout, so
  `recv()` blocks forever. The fix is a socket read timeout + reconnect, or a
  liveness check on ping/pong freshness.
- A worker thread on **`queue.get`** with an empty queue = idle consumer
  (normal) -- look elsewhere.
- Several threads waiting on the **same lock** = a deadlock; the holder's stack
  shows where.
- If a dedicated **heartbeat thread is still running** (see below), the
  interpreter is alive and scheduling threads -- so it is a socket/delivery wedge,
  not a freeze.

### 4. Recover automatically: an out-of-process heartbeat

An in-process watchdog thread cannot catch a *frozen interpreter* -- it freezes
too. Put the liveness check OUTSIDE the process:

```python
# a daemon thread, deliberately dumb: its value is that it STOPS when the
# interpreter freezes.
def _beat(path, interval=15):
    while True:
        try:
            open(path, "w").write(str(int(time.time())))
        except OSError:
            pass
        time.sleep(interval)
```

An external job (cron, a `launchd`/`systemd` timer) restarts the service when the
file's mtime goes stale. This beats "the log went quiet", which false-positives
on a legitimately idle service -- the heartbeat advances on a timer, not on
traffic.

**Caveat:** the heartbeat only catches a FULL freeze. A half-open-socket wedge
leaves the interpreter (and the heartbeat) alive while event delivery is dead, so
the heartbeat stays fresh and will NOT catch it. For that case the reliable
signal is the connection's own ping/pong freshness (a stable session that stops
ponging is dead), or a socket read timeout -- not the heartbeat.

## "It got more frequent lately": look at host pressure

A wedge that was rare and is now frequent is often not a code change but the HOST.
Under memory pressure (check `vm.swapusage` / `vm_stat` pageouts) or high load,
the daemon's threads get paged out or starved, miss keepalive/ping deadlines, and
the peer drops the connection -- half-open. A common cause on a dev machine: a
per-use container leak -- an MCP server or helper launched with `docker run` and
no `--rm` accumulates one container per invocation, each burning a few % CPU
forever. `docker ps` sorted by age/image, and `docker stats --no-stream`, expose
the pile; stopping the leaked ones frees the CPU that was starving your service.
Fix the launcher to use `--rm` (or reuse one container) so it does not recur.

## Verification

- `kill -USR1 <pid>` prints a per-thread dump to stderr AND the process keeps
  running (prove it: the heartbeat file keeps advancing, or the next log line
  appears).
- The stuck thread's stack names the blocking call.
- After the external restarter is in place, a wedged/frozen process is
  re-launched within the staleness window with no human in the loop.

## Notes

- `all_threads=True` is essential: the main thread is often fine and the stuck
  one is a background worker.
- On macOS, `time.monotonic()` does not advance while the host is asleep, so a
  watchdog that measures only monotonic time cannot tell a sleep/suspend from a
  healthy gap; compare against wall-clock to detect a suspend.
- faulthandler is stdlib since Python 3.3; no dependency.

## References

- faulthandler: https://docs.python.org/3/library/faulthandler.html
- signal default dispositions (SIGUSR1 terminates): https://man7.org/linux/man-pages/man7/signal.7.html
