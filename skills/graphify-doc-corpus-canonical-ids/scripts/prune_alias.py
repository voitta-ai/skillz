"""Post-merge hygiene for graphify extraction on data-heavy corpora.

1. Alias-merge coined id variants (optional graphify-out/.graphify_aliases.json: {"variant_id": "canonical_id"}).
2. Drop AST nodes that are just top-level JSON keys of data .json files (keep the file-level node).
Rewrites graphify-out/.graphify_semantic.json and .graphify_extract.json in place. Re-run Step 4 afterwards
with to_json(..., force=True) because the node count shrinks.
"""
import json
from pathlib import Path

OUT = Path('graphify-out')
ALIAS_FILE = OUT / '.graphify_aliases.json'
ALIAS = json.loads(ALIAS_FILE.read_text(encoding='utf-8')) if ALIAS_FILE.exists() else {}

ast = json.loads((OUT / '.graphify_ast.json').read_text(encoding='utf-8'))
ast_json_key_ids = set()
for n in ast['nodes']:
    sf = n.get('source_file') or ''
    if sf.endswith('.json') and n.get('label') != Path(sf).name:
        ast_json_key_ids.add(n['id'])
print(f'aliases: {len(ALIAS)}; AST json-key nodes to drop: {len(ast_json_key_ids)}')


def fix(doc, drop):
    nodes = []
    seen = set()
    for n in doc['nodes']:
        nid = ALIAS.get(n['id'], n['id'])
        if nid in drop:
            continue
        if nid in seen:
            for m in nodes:
                if m['id'] == nid and len(n.get('description') or '') > len(m.get('description') or ''):
                    m['description'] = n['description']
            continue
        seen.add(nid)
        n = dict(n)
        n['id'] = nid
        nodes.append(n)
    edges = []
    ek = set()
    for e in doc['edges']:
        s, t = ALIAS.get(e['source'], e['source']), ALIAS.get(e['target'], e['target'])
        if s in drop or t in drop or s == t or s not in seen or t not in seen:
            continue
        key = (s, t, e.get('relation'))
        if key in ek:
            continue
        ek.add(key)
        e = dict(e)
        e['source'], e['target'] = s, t
        edges.append(e)
    hyper = []
    for h in doc.get('hyperedges', []):
        h = dict(h)
        h['nodes'] = [ALIAS.get(x, x) for x in h['nodes'] if ALIAS.get(x, x) in seen]
        if len(h['nodes']) >= 3:
            hyper.append(h)
    retval = {**doc, 'nodes': nodes, 'edges': edges, 'hyperedges': hyper}
    return retval


for name in ('.graphify_semantic.json', '.graphify_extract.json'):
    p = OUT / name
    if not p.exists():
        continue
    d = json.loads(p.read_text(encoding='utf-8'))
    before = (len(d['nodes']), len(d['edges']))
    d2 = fix(d, ast_json_key_ids)
    p.write_text(json.dumps(d2, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'{name}: nodes {before[0]} -> {len(d2["nodes"])}, edges {before[1]} -> {len(d2["edges"])}, hyperedges {len(d2["hyperedges"])}')
