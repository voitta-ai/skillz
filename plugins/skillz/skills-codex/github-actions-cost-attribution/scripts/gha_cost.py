#!/usr/bin/env python3
"""Reconstruct GitHub Actions billed minutes from run/job timestamps - no billing access needed.

  gha_cost.py runs   OWNER/REPO 2026-09-01 2026-09-25          # -> runs_REPO.json
  gha_cost.py jobs   OWNER/REPO 2026-09-23 2026-09-25 [0.25]   # -> jobs/REPO/<run_id>.json (optional sample)
  gha_cost.py report OWNER/REPO 2026-09-23 2026-09-25          # tables: day, workflow, actor, job, tiny jobs
  gha_cost.py steps  OWNER/REPO 2026-09-01 2026-09-25 "Job name"  # per-step median/p90 seconds

Auth comes from the `gh` CLI. Dates are UTC days (GitHub bills in UTC). Run from a scratch directory:
files are written to the current directory.
"""
import collections
import datetime as dt
import json
import math
import os
import random
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

# List rates, USD per minute, standard 2-core runners
# (https://docs.github.com/en/billing/reference/actions-runner-pricing, checked 2026-09).
# ponytail: larger runners have their own SKUs; extend when `labels` show them.
RATE = {"arm": 0.005, "x64": 0.006}


def gh(path):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"{path}: {out.stderr.strip()[:300]}")
    retval = json.loads(out.stdout)
    return retval


def ts(s):
    retval = dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None
    return retval


def days(start, end):
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    retval = [(d0 + dt.timedelta(n)).isoformat() for n in range((d1 - d0).days + 1)]
    return retval


def cmd_runs(repo, start, end):
    # One query per UTC day: filtered run listings are search-backed and cap at 1000 results.
    # ponytail: a day with >= 1000 runs is flagged, not split; narrow it with created=<ts>..<ts> by hand.
    def day(d):
        runs, page = [], 1
        while True:
            r = gh(f"repos/{repo}/actions/runs?created={d}&per_page=100&page={page}")
            runs += r["workflow_runs"]
            if len(r["workflow_runs"]) < 100 or len(runs) >= r["total_count"]:
                break
            page += 1
        retval = (d, r["total_count"], runs)
        return retval

    allruns = {}
    with ThreadPoolExecutor(6) as ex:
        for d, total, runs in ex.map(day, days(start, end)):
            got = len({r["id"] for r in runs})
            ok = got == total and total < 1000
            print(f"{d}: total_count={total}" + ("" if ok else f"  <-- CHECK: fetched {got}"))
            allruns.update({r["id"]: r for r in runs})
    json.dump(list(allruns.values()), open(f"runs_{repo.split('/')[1]}.json", "w"))
    print(f"{len(allruns)} runs saved")


def cmd_jobs(repo, start, end, frac="1.0"):
    name = repo.split("/")[1]
    os.makedirs(f"jobs/{name}", exist_ok=True)
    sel = [r for r in json.load(open(f"runs_{name}.json")) if start <= r["created_at"][:10] <= end]
    random.seed(42)
    sel = [r for r in sel if random.random() < float(frac)]

    def fetch(r):
        p = f"jobs/{name}/{r['id']}.json"
        if os.path.exists(p):
            return None
        jobs, page = [], 1
        while True:
            # filter=all: re-run attempts are billed too.
            d = gh(f"repos/{repo}/actions/runs/{r['id']}/jobs?filter=all&per_page=100&page={page}")
            jobs += d["jobs"]
            if len(jobs) >= d["total_count"] or not d["jobs"]:
                break
            page += 1
        json.dump(jobs, open(p, "w"))
        return None

    with ThreadPoolExecutor(10) as ex:
        list(ex.map(fetch, sel))
    print(f"{len(sel)} runs' jobs cached under jobs/{name}/")


def load(repo, start, end):
    name = repo.split("/")[1]
    runs = {r["id"]: r for r in json.load(open(f"runs_{name}.json")) if start <= r["created_at"][:10] <= end}
    default = gh(f"repos/{repo}")["default_branch"]
    rows, skipped, missing = [], collections.Counter(), 0
    for rid, r in runs.items():
        p = f"jobs/{name}/{rid}.json"
        if not os.path.exists(p):
            missing += 1
            continue
        for j in json.load(open(p)):
            s, c = ts(j.get("started_at")), ts(j.get("completed_at"))
            secs = (c - s).total_seconds() if s and c else 0
            if secs <= 0:
                skipped[f"zero-duration:{j.get('conclusion')}"] += 1
                continue
            if not j.get("runner_name"):
                # Never got a runner: budget refusal ("An Actions budget is preventing further use")
                # or cancelled while queued. Not billed.
                skipped[f"no-runner:{j.get('conclusion')}"] += 1
                continue
            if j.get("runner_group_name") not in (None, "", "GitHub Actions"):
                skipped["self-hosted"] += 1
                continue
            arch = "arm" if any("arm" in label for label in j.get("labels") or []) else "x64"
            mins = math.ceil(secs / 60)  # GitHub rounds each job up to the whole minute
            rows.append(dict(
                run=rid, wf=r["name"], event=r["event"], day=r["created_at"][:10],
                branch="default" if r["head_branch"] == default else "branch/PR",
                actor=(r.get("triggering_actor") or r.get("actor") or {}).get("login"),
                job=j["name"], concl=j.get("conclusion"), arch=arch, secs=secs, mins=mins,
                usd=mins * RATE[arch], steps=j.get("steps") or []))
    retval = (runs, rows, skipped, missing)
    return retval


def table(rows, key, title, top=25):
    mins, usd = collections.Counter(), collections.defaultdict(float)
    runs = collections.defaultdict(set)
    for x in rows:
        k = key(x)
        mins[k] += x["mins"]
        usd[k] += x["usd"]
        runs[k].add(x["run"])
    tot = sum(usd.values()) or 1.0
    print(f"\n--- {title}  (total {sum(mins.values())} billed min, ${tot:.2f})")
    for k in sorted(usd, key=lambda k: -usd[k])[:top]:
        print(f"  ${usd[k]:7.2f} {mins[k]:6d}m {100 * usd[k] / tot:5.1f}%  runs={len(runs[k]):4d}  "
              f"avg/run={mins[k] / len(runs[k]):5.1f}m  {k}")


def cmd_report(repo, start, end):
    runs, rows, skipped, missing = load(repo, start, end)
    print(f"==== {repo} {start}..{end}: runs={len(runs)} missing_job_files={missing} "
          f"billed_jobs={len(rows)} not_billed={dict(skipped)}")
    table(rows, lambda x: x["day"], "by day", 60)
    table(rows, lambda x: (x["wf"], x["event"], x["branch"]), "by workflow / event / branch")
    table(rows, lambda x: x["actor"], "by triggering actor", 10)
    table(rows, lambda x: (x["wf"], x["job"][:50], x["arch"]), "by job")
    by_job = collections.defaultdict(list)
    for x in rows:
        by_job[(x["wf"], x["job"][:50])].append(x)
    print("\n--- sub-minute jobs (each billed as >= 1 min)")
    for k, v in sorted(by_job.items(), key=lambda kv: -len(kv[1])):
        med = sorted(x["secs"] for x in v)[len(v) // 2]
        if med < 60:
            print(f"  n={len(v):4d} median={med:4.0f}s billed={sum(x['mins'] for x in v):5d}m "
                  f"actual={sum(x['secs'] for x in v) / 60:6.0f}m  {k}")


def cmd_steps(repo, start, end, job):
    _, rows, _, _ = load(repo, start, end)
    agg = collections.defaultdict(list)
    n = 0
    for x in rows:
        if x["job"] != job or x["concl"] != "success":
            continue
        n += 1
        for s in x["steps"]:
            a, b = ts(s.get("started_at")), ts(s.get("completed_at"))
            if a and b:
                agg[s["name"]].append((b - a).total_seconds())
    print(f"{job}: {n} successful runs; median / p90 seconds per step")
    for name, v in sorted(agg.items(), key=lambda kv: -sorted(kv[1])[len(kv[1]) // 2]):
        v.sort()
        print(f"  med={v[len(v) // 2]:6.0f}s p90={v[int(len(v) * 0.9)]:6.0f}s n={len(v):4d}  {name[:80]}")


if __name__ == "__main__":
    cmds = {"runs": cmd_runs, "jobs": cmd_jobs, "report": cmd_report, "steps": cmd_steps}
    if len(sys.argv) < 5 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]](*sys.argv[2:])
