#!/usr/bin/env python3
"""Compare the chart stored in a deployed Helm 3 release with an extracted chart directory.

Reads the decoded release JSON on stdin. Pipe it straight in; do not save it, it
holds the rendered manifests and the release's user-supplied values:

  kubectl -n NS get secret -l owner=helm,name=REL,status=deployed \\
      -o jsonpath='{.items[0].data.release}' | base64 -d | base64 -d | gunzip \\
    | python3 -I helm-release-chart-diff.py ./extracted/CHART

Exit 0: every compared part is byte-identical and nothing was skipped.
Exit 1: something differs.
Exit 2: nothing differs, but a part could not be compared (see COULD NOT lines).
"""
import base64
import json
import os
import sys

# Stored in their own release fields, not in chart.files; compared separately below.
SPECIAL = {"Chart.yaml", "values.yaml", "values.schema.json", "Chart.lock", "requirements.lock"}


def read_disk_files(root):
    disk = {}
    for dirpath, _, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        # Subcharts are not serialized into the release record, so there is nothing to compare them with.
        if rel_dir == "charts" or rel_dir.startswith("charts" + os.sep):
            continue
        for fn in filenames:
            rp = os.path.normpath(os.path.join(rel_dir, fn))
            if rp in SPECIAL:
                continue
            with open(os.path.join(dirpath, fn), "rb") as fh:
                disk[rp] = fh.read()
    return disk


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = sys.argv[1]
    rel = json.load(sys.stdin)
    chart = rel["chart"]
    md = chart["metadata"]
    print(f"release {rel['name']} rev {rel['version']} status {rel['info']['status']} "
          f"chart {md['name']} {md['version']}")

    live = {f["name"]: base64.b64decode(f["data"])
            for f in (chart.get("templates") or []) + (chart.get("files") or [])}
    disk = read_disk_files(root)
    same = sorted(k for k in live if k in disk and live[k] == disk[k])
    differ = sorted(k for k in live if k in disk and live[k] != disk[k])
    only_release = sorted(set(live) - set(disk))
    only_tarball = sorted(set(disk) - set(live))
    print(f"files: identical={len(same)} differ={differ} "
          f"only_in_release={only_release} only_in_tarball={only_tarball}")
    bad = bool(differ or only_release or only_tarball)
    skipped = []

    schema_path = os.path.join(root, "values.schema.json")
    live_schema = base64.b64decode(chart["schema"]) if chart.get("schema") else None
    disk_schema = None
    if os.path.exists(schema_path):
        with open(schema_path, "rb") as fh:
            disk_schema = fh.read()
    if live_schema != disk_schema:
        bad = True
        print("schema: DIFFERS")
    else:
        print("schema: identical" if disk_schema is not None else "schema: absent in both")

    try:
        import yaml
    except ImportError:
        skipped.append("default values and Chart.yaml (PyYAML is not importable)")
    else:
        with open(os.path.join(root, "values.yaml")) as fh:
            disk_values = yaml.safe_load(fh) or {}
        if disk_values != (chart.get("values") or {}):
            bad = True
            print("default values: DIFFER")
        else:
            print("default values: identical")
        with open(os.path.join(root, "Chart.yaml")) as fh:
            disk_md = yaml.safe_load(fh) or {}
        mismatched = [k for k in ("name", "version", "appVersion") if disk_md.get(k) != md.get(k)]
        if mismatched:
            bad = True
            print(f"Chart.yaml: DIFFERS in {mismatched}")
        else:
            print("Chart.yaml name/version/appVersion: identical")

    for s in skipped:
        print(f"COULD NOT compare: {s}")
    retval = 1 if bad else (2 if skipped else 0)
    print("RESULT:", {0: "IDENTICAL", 1: "DIFFERENT", 2: "INCOMPLETE"}[retval])
    return retval


if __name__ == "__main__":
    sys.exit(main())
