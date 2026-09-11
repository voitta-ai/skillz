---
name: graphify-doc-corpus-canonical-ids
description: |
  Run /graphify on a document-heavy corpus (markdown reports, CSV data, JSON scan
  fragments) that is ABOUT a fixed set of real-world entities (services, systems,
  investigation objectives, technologies) without the graph fragmenting into
  per-file ghost duplicates. Use when: (1) graphify detect reports fewer files than
  the folder holds and the missing ones are .csv (graphifyy 0.8.x has no CSV
  support -- silently skipped, same failure class as .tf), (2) the Gemini backend
  returns ~0.5 nodes per file with filename-stub labels on a markdown corpus
  (failed_chunks=0, stub ratio > 0.5, most files produce nothing) and you fall back
  to Claude subagents, (3) the same service or concept appears in many files, so the
  skill's {parent_dir}_{stem}_{entity} id rule would mint one node per file per
  concept and fan-in questions ("who calls X") come back empty, (4) after merging,
  clustering yields dozens of 7-node communities made of JSON keys (repo, language,
  outbound_calls, notes) from data .json files, (5) the rebuild after pruning
  prints "WARNING: new graph has N nodes but existing graph.json has M. Refusing to
  overwrite" (export.to_json needs force=True), (6) you are about to run a
  semantic-id remap script written for code corpora on subagent output that used
  canonical concept ids -- do not, its fallback rewrites them to per-file ids.
  Covers the canonical shared-id prompt addendum, directory-grouped chunking with
  paired files, a validate+merge script with dangling-edge and AST-overlap checks,
  alias-merge of coined id variants, JSON-key pruning, and the forced export.
author: Claude Code
version: 1.0.0
date: 2026-09-10
---

# graphify on a document corpus: canonical shared ids across subagent chunks

## Problem

The `/graphify` skill's node-id rule (`{parent_dir}_{stem}_{entity}`, matched to
the AST extractor) is right for code symbols and wrong for a corpus of documents
that all describe the same real-world things. On an architecture-analysis repo
(29 md reports, 21 JSON scan fragments, 8 py scripts, 6 csv tables about ~25
microservices and 5 investigation objectives) a literal reading of the rule
produces one `<config-service>` node per file that mentions it, so the graph
cannot answer "which services call the config service" -- the single most
valuable question in the corpus.

Four more silent failures stack on top: `.csv` files never reach detect; the Gemini
backend produces stub output on prose (not only on terraform); the AST extractor
turns every top-level key of a data `.json` file into a node, which then dominates
clustering; and the export refuses to write a graph that got smaller.

## Context / Trigger Conditions

- Corpus is mostly `.md` / `.csv` / data `.json`, describing a bounded entity set.
- `detect` total_files < `find . -name '*.csv' | wc -l` + md + py.
- Gemini pass: `nodes/files < 1`, labels equal to filenames, `files with >=1 node`
  far below the file count, `failed_chunks=0`.
- After a chunked subagent pass: many near-duplicate ids for the same entity across
  chunks, or an AST-overlap of ~0 with hundreds of "semantic" nodes.
- After merge: communities of size 7 whose members are the top-level keys of one
  JSON file each.
- `to_json` prints `Refusing to overwrite` after you dropped nodes.

## Solution

1. **Patch detect for CSV.** Add the CSVs that carry findings (inventories, edge
   tables, cost tables) to `files.document` in `graphify-out/.graphify_detect.json`
   and bump `total_files` / `total_words`. Skip per-day time series and superseded
   backups; they add tokens, not knowledge.

2. **Run the Gemini pass, then gate it.** `extract_corpus_parallel([Path(...)],
   backend='gemini', root=Path.cwd())`. Compute `stub_ratio` and files-covered. On
   prose this backend gave 35 nodes for 64 files (stub 0.57, 22 files covered):
   discard and fall back to `general-purpose` subagents.

3. **Chunk by directory, pairing raw and derived files.** Put each entity's raw
   fragment (`_fragments/<x>.json`) in the same chunk as the document built from it
   (`<x>/dependencies.md`) so the pair yields one node set, and keep the dense
   reports in small chunks (8 files) so they get real attention. 64 files -> 5
   chunks.

4. **Give every subagent the same canonical-id addendum.** Prepend to the skill's
   prompt template a section that overrides the id rule for cross-cutting kinds and
   enumerates the allowed ids verbatim:
   - services `svc_<repo_short_name>` (one node per service regardless of region or
     deployment variants; sub-services described, not split),
   - external hosts `ext_<host_with_dots_as_underscores>`,
   - infra/tech `aws_<thing>` / `tech_<thing>` with a seed list,
   - objectives `objective_<n>_<slug>` with `file_type: rationale`,
   - everything else (findings, code symbols, document nodes) keeps the standard
     `{parent_dir}_{stem}_{entity}` rule, and data-JSON file nodes reuse the AST's
     `{parent_dir}_{stem}` id.
   Tell agents to emit the node for every canonical id they reference so nothing
   dangles, to add a one-sentence `description` (numbers included) and a `rationale`
   attr, and to write with the Write tool to an absolute chunk path and reply with a
   one-line count (keeps the JSON out of the parent context).
   Relation guidance that worked: service->service sync call = `calls`; data-plane
   (stream / cache / object store) = `shares_data_with`; doc->entity = `references`;
   finding->objective = `rationale_for`; alternatives = `conceptually_related_to`.

5. **Validate + merge with `scripts/merge_chunks.py`** (run from the project root
   after all chunk files exist). It normalises ids, fixes invalid `file_type`, fills
   missing `confidence_score`, dedups nodes across chunks (longest description wins),
   drops dangling and duplicate edges, reports AST-id overlap, prints every
   `svc_/ext_/aws_/tech_/objective_` id so variants are visible, saves the semantic
   cache, and performs the Part C merge into `.graphify_extract.json`. Do NOT run a
   code-corpus id-remap script here: one that matches only AST files sends every
   concept node from a `.md` to its fallback and turns it back into
   `<dir>_<stem>_<entity>`.

6. **Alias + prune with `scripts/prune_alias.py`.** Write coined variants to
   `graphify-out/.graphify_aliases.json` (e.g. `aws_kinesis_stream_events_prod`
   -> `aws_kinesis_stream_events`) and run it; it also drops AST nodes from `.json`
   files whose label is not the filename (the JSON-key noise) and rewires
   edges/hyperedges.

7. **Rebuild with a forced export.** Re-run Step 4, but call
   `to_json(G, communities, 'graphify-out/graph.json', force=True)` -- the default
   refuses when the node count dropped. Then label communities, `graphify export
   html`, benchmark, manifest, cleanup as usual.

## Verification

From the run this was extracted from (graphifyy 0.8.31):
- merge: 5 chunks, 524 raw -> 358 unique nodes, 76 ids merged across chunks
  (each shared service and objective id seen in 4 chunks), 1,547 -> 1,439 edges,
  0 dangling, 68 semantic ids coincide with AST ids, 64/64 files covered.
- prune: 120 JSON-key nodes dropped, 483 -> 359 nodes, communities 21 -> 9, every
  remaining community is a real topic.
- god nodes are the objectives, the shared services and the platform components --
  not file hubs.

## Example

Prompt excerpt that made ids converge across five parallel agents:

```
A. Cross-cutting canonical ids -- use these EXACT ids, never the per-file format:
1. Services: svc_<canonical>. Allowed ids: svc_api, svc_worker, svc_config_server,
   svc_identity, ... One node per service regardless of region.
   Emit the node for every service you reference so no edge dangles.
4. Objectives -- exactly: objective_1_<slug>, objective_2_<slug>, ...
   file_type "rationale". finding -> objective = rationale_for.
B. Everything else: {parent_dir}_{stem}_{entity}; `.../_fragments/api.json` ->
   fragments_api (this id already exists from the AST extractor -- reuse it).
```

## Notes

- Subagent token usage is not surfaced by idle notifications, so `cost.json` can only
  record the (discarded) Gemini spend; say so in the report instead of guessing.
- `graphify benchmark` reports ~1.0x on a 20-30k-word corpus; the value is
  navigability, not compression. Do not treat that as a failed run.
- `god_nodes()` excludes nodes whose `source_file` is empty or has no extension,
  not nodes with `file_type: concept` -- keep `source_file` populated on canonical
  nodes or they vanish from the report.
- 8-20 files per chunk worked; above ~25 files per chunk extraction quality drops.
- Sibling gotcha skills in the same family cover the terraform detect gap, the
  stub-ratio gate and an AST-id remap script for CODE corpora, and the need to pass
  `Path` objects to the Gemini entry point.

## References

- graphifyy on PyPI (0.8.31 at time of writing): https://pypi.org/project/graphifyy/
- `/graphify` skill Step 3 Part B prompt template, which this addendum extends.
