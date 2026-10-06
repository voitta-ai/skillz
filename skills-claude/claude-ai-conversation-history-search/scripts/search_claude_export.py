#!/usr/bin/env python3
"""Search a claude.ai data export (conversations.json, or the .zip/.dms containing it).

Usage:
  ./search_claude_export.py <export.zip|conversations.json> <regex> [regex ...]
  ./search_claude_export.py --selftest
"""
import json
import re
import sys
import zipfile

# ponytail: walk every string in the JSON rather than modeling the schema --
# export shape has changed before and a missed key is a false negative.
CONTEXT = 220


def walk(node, path, out):
    if isinstance(node, str):
        out.append((path, node))
    elif isinstance(node, dict):
        for k, v in node.items():
            walk(v, path + [str(k)], out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, path + [str(i)], out)
    return out


def load(src):
    if src.endswith((".zip", ".dms")):
        with zipfile.ZipFile(src) as z:
            name = next(n for n in z.namelist() if n.endswith("conversations.json"))
            retval = json.loads(z.read(name))
    else:
        with open(src) as f:
            retval = json.load(f)
    return retval


def label(convo):
    name = convo.get("name") or "(untitled)"
    uuid = convo.get("uuid") or "?"
    when = convo.get("created_at") or convo.get("updated_at") or "?"
    retval = f"{name}  [{uuid}]  {when}"
    return retval


def search(data, patterns):
    pats = [re.compile(p, re.I) for p in patterns]
    convos = data if isinstance(data, list) else [data]
    hits = 0
    for convo in convos:
        shown = False
        for path, text in walk(convo, [], []):
            for pat in pats:
                for m in pat.finditer(text):
                    if not shown:
                        print("\n" + "=" * 78)
                        print(label(convo))
                        print("=" * 78)
                        shown = True
                    hits += 1
                    a = max(0, m.start() - CONTEXT)
                    b = min(len(text), m.end() + CONTEXT)
                    snippet = text[a:b].replace("\n", " ")
                    print(f"  /{'/'.join(path)}  ~{pat.pattern}~")
                    print(f"    ...{snippet}...")
                    break
    retval = hits
    return retval


def selftest():
    sample = [{
        "uuid": "abc",
        "name": "Eco matrix",
        "created_at": "2026-07-01",
        "chat_messages": [
            {"sender": "human", "content": [{"type": "text", "text": "rate Trump on Ur-Fascism"}]},
            {"sender": "assistant", "text": "nothing here about kindness"},
        ],
    }]
    found = walk(sample, [], [])
    assert any("Ur-Fascism" in t for _, t in found), "nested content blocks must be walked"
    assert any(t == "human" for _, t in found), "plain scalar fields must be walked"
    assert search(sample, ["ur-fascism"]) == 1, "case-insensitive match expected"
    assert search(sample, ["zzz-no-match"]) == 0, "no false positives"
    print("selftest ok")
    return 0


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        retval = selftest()
    elif len(sys.argv) < 3:
        print(__doc__)
        retval = 2
    else:
        data = load(sys.argv[1])
        hits = search(data, sys.argv[2:])
        print(f"\n--- {hits} hit(s) ---")
        retval = 0 if hits else 1
    return retval


if __name__ == "__main__":
    sys.exit(main())
