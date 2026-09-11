"""Validate + merge subagent chunk files, save cache, Part C merge with AST, Step 4 build.
Run from project root. Idempotent."""
import glob
import json
import re
import collections
from pathlib import Path

OUT = Path('graphify-out')
VALID_FT = {'code', 'document', 'paper', 'image', 'rationale', 'concept'}
DEFAULT_SCORE = {'EXTRACTED': 1.0, 'INFERRED': 0.75, 'AMBIGUOUS': 0.2}


def norm_id(s):
    retval = re.sub(r'[^a-z0-9_]', '_', (s or '').lower()).strip('_')
    return retval


ast = json.loads((OUT / '.graphify_ast.json').read_text(encoding='utf-8'))
ast_ids = {n['id'] for n in ast['nodes']}

chunks = sorted(glob.glob(str(OUT / '.graphify_chunk_*.json')))
print(f'chunk files on disk: {len(chunks)} -> {[Path(c).name for c in chunks]}')
all_nodes, all_edges, all_hyper = [], [], []
fixes = collections.Counter()
for c in chunks:
    try:
        d = json.loads(Path(c).read_text(encoding='utf-8'))
    except Exception as e:
        print(f'  WARN {Path(c).name}: invalid JSON ({e}) - skipped')
        continue
    n, e, h = d.get('nodes', []), d.get('edges', []), d.get('hyperedges', [])
    print(f'  {Path(c).name}: {len(n)} nodes, {len(e)} edges, {len(h)} hyperedges, tokens {d.get("input_tokens",0)}/{d.get("output_tokens",0)}')
    for x in n:
        nid = norm_id(x.get('id'))
        if nid != x.get('id'):
            fixes['node_id_normalized'] += 1
            x['id'] = nid
        if x.get('file_type') not in VALID_FT:
            fixes['file_type_fixed'] += 1
            x['file_type'] = 'concept'
        if not x.get('label'):
            x['label'] = x['id']
            fixes['label_filled'] += 1
    for x in e:
        for k in ('source', 'target'):
            v = norm_id(x.get(k))
            if v != x.get(k):
                fixes['edge_id_normalized'] += 1
                x[k] = v
        conf = x.get('confidence') or 'INFERRED'
        x['confidence'] = conf
        if not isinstance(x.get('confidence_score'), (int, float)):
            x['confidence_score'] = DEFAULT_SCORE.get(conf, 0.75)
            fixes['score_filled'] += 1
        x.setdefault('weight', 1.0)
    for x in h:
        x['nodes'] = [norm_id(v) for v in x.get('nodes', [])]
    all_nodes += n
    all_edges += e
    all_hyper += h
print('fixes:', dict(fixes))

# dedup nodes by id, merging descriptions (keep longest) and first source_file
by_id = collections.OrderedDict()
dups = collections.Counter()
for x in all_nodes:
    if x['id'] in by_id:
        dups[x['id']] += 1
        cur = by_id[x['id']]
        if len(x.get('description') or '') > len(cur.get('description') or ''):
            cur['description'] = x.get('description')
        if x.get('rationale') and not cur.get('rationale'):
            cur['rationale'] = x.get('rationale')
    else:
        by_id[x['id']] = x
print(f'nodes: {len(all_nodes)} raw -> {len(by_id)} unique; cross-chunk merged ids: {len(dups)}')
print('  most merged:', dups.most_common(12))

sem_ids = set(by_id)
known = sem_ids | ast_ids
dangling = [e for e in all_edges if e['source'] not in known or e['target'] not in known]
print(f'edges: {len(all_edges)}; dangling: {len(dangling)}')
for e in dangling[:25]:
    missing = [v for v in (e['source'], e['target']) if v not in known]
    print('   drop', e['source'], '->', e['target'], e.get('relation'), 'missing', missing, '| from', e.get('source_file'))
kept_edges = [e for e in all_edges if e['source'] in known and e['target'] in known and e['source'] != e['target']]
# dedup identical (source,target,relation)
seen = set()
uniq_edges = []
for e in kept_edges:
    key = (e['source'], e['target'], e.get('relation'))
    if key in seen:
        continue
    seen.add(key)
    uniq_edges.append(e)
print(f'edges kept: {len(uniq_edges)} (dropped {len(kept_edges)-len(uniq_edges)} exact dups, {len(dangling)} dangling)')
hyper_ok = []
for h in all_hyper:
    miss = [v for v in h['nodes'] if v not in known]
    if miss:
        print('   hyperedge', h.get('id'), 'missing', miss)
        h['nodes'] = [v for v in h['nodes'] if v in known]
    if len(h['nodes']) >= 3:
        hyper_ok.append(h)
print(f'hyperedges kept: {len(hyper_ok)} / {len(all_hyper)}')

overlap = sem_ids & ast_ids
touch_ast = sum(1 for e in uniq_edges if e['source'] in ast_ids or e['target'] in ast_ids)
print(f'AST overlap: {len(overlap)} semantic ids coincide with AST ids; {touch_ast} semantic edges touch AST nodes')
print('canonical ids by prefix:')
for pref in ('svc_', 'ext_', 'aws_', 'tech_', 'objective_'):
    ids = sorted(i for i in sem_ids if i.startswith(pref))
    print(f'  {pref} ({len(ids)}):', ', '.join(ids))
print('relation dist:', collections.Counter(e.get('relation') for e in uniq_edges).most_common())
print('confidence dist:', collections.Counter(e.get('confidence') for e in uniq_edges).most_common())
print('file_type dist:', collections.Counter(n.get('file_type') for n in by_id.values()).most_common())
covered = {n.get('source_file') for n in by_id.values()}
detect = json.loads((OUT / '.graphify_detect.json').read_text(encoding='utf-8'))
root = detect['scan_root'].rstrip('/') + '/'
all_files = [f[len(root):] for g in detect['files'].values() for f in g]
uncovered = [f for f in all_files if f not in covered]
print(f'files with >=1 semantic node: {len(all_files)-len(uncovered)} / {len(all_files)}; uncovered: {uncovered}')

tot_in = sum(json.loads(Path(c).read_text(encoding='utf-8')).get('input_tokens', 0) for c in chunks)
tot_out = sum(json.loads(Path(c).read_text(encoding='utf-8')).get('output_tokens', 0) for c in chunks)
new = {'nodes': list(by_id.values()), 'edges': uniq_edges, 'hyperedges': hyper_ok, 'input_tokens': tot_in, 'output_tokens': tot_out}
(OUT / '.graphify_semantic_new.json').write_text(json.dumps(new, indent=2, ensure_ascii=False), encoding='utf-8')

# --- save cache
from graphify.cache import save_semantic_cache
saved = save_semantic_cache(new['nodes'], new['edges'], new['hyperedges'])
print(f'cache: saved {saved} files')

# --- merge cached + new (cached is empty on this run, keep skill structure)
cached = json.loads((OUT / '.graphify_cached.json').read_text(encoding='utf-8')) if (OUT / '.graphify_cached.json').exists() else {'nodes': [], 'edges': [], 'hyperedges': []}
seen_n = set()
sem_nodes = []
for n in cached['nodes'] + new['nodes']:
    if n['id'] not in seen_n:
        seen_n.add(n['id'])
        sem_nodes.append(n)
semantic = {'nodes': sem_nodes, 'edges': cached['edges'] + new['edges'], 'hyperedges': cached.get('hyperedges', []) + new['hyperedges'],
            'input_tokens': tot_in, 'output_tokens': tot_out}
(OUT / '.graphify_semantic.json').write_text(json.dumps(semantic, indent=2, ensure_ascii=False), encoding='utf-8')

# --- Part C: merge AST + semantic
seen_c = {n['id'] for n in ast['nodes']}
merged_nodes = list(ast['nodes'])
for n in semantic['nodes']:
    if n['id'] not in seen_c:
        merged_nodes.append(n)
        seen_c.add(n['id'])
    else:
        # AST node wins on identity; carry semantic description over
        for m in merged_nodes:
            if m['id'] == n['id']:
                if n.get('description') and not m.get('description'):
                    m['description'] = n['description']
                break
merged = {'nodes': merged_nodes, 'edges': ast['edges'] + semantic['edges'], 'hyperedges': semantic['hyperedges'],
          'input_tokens': tot_in, 'output_tokens': tot_out}
(OUT / '.graphify_extract.json').write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding='utf-8')
print(f'Merged: {len(merged_nodes)} nodes, {len(merged["edges"])} edges ({len(ast["nodes"])} AST + {len(semantic["nodes"])} semantic)')
