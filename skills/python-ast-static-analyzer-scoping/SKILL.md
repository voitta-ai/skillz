---
name: python-ast-static-analyzer-scoping
description: |
  Build a correct Python `ast`-based static analyzer that resolves import
  aliases (`from os import system; system(...)` -> `os.system`) and
  models which AST positions execute at module-load vs are deferred
  until call time. Use when: (1) writing a linter / safety-check /
  destructive-call detector that walks `ast` and matches calls against
  rule patterns, (2) seeing false negatives because calls inside
  functions defined before later imports don't resolve, (3) seeing
  false positives because an earlier destructive call disappears after
  a later top-level rebind or re-import, (4) deciding whether to flag
  calls inside class bodies, decorators, default args, kw-only
  defaults, lambda bodies, or parameter / return annotations, (5)
  confused by `ast.NodeVisitor` walking in pre-order, breaking
  same-walk binding-table population, (6) seeing
  `python3 -c 'import os as x; x.system(...)'` (or any semicolon
  one-liner) escape alias resolution even though the multi-line
  equivalent works. Covers the six iterative correctness traps that
  surface in this order: import-alias resolution, source-order
  independence, scope-aware bindings, module-scope execution-order
  sensitivity, definition-time vs deferred positions, the PEP 563 /
  PEP 649 reason annotations should NOT be analyzed, and
  same-source-line position precision (lineno-only keying loses
  intra-line ordering when multiple statements share a line).
author: Claude Code
version: 1.1.1
date: 2026-05-13
---

# Python AST Static Analyzer: Import Resolution + Execution-Time Model

## Problem

When you build a Python static analyzer that walks `ast` and matches
function-call expressions against rule patterns (e.g. `os.system`,
`shutil.rmtree`), naive implementations get bitten by five separate
correctness traps in a predictable sequence. Each fix uncovers the
next. This skill enumerates all five, the order they surface, the
underlying cause, and the design that resolves them together.

## Context / Trigger Conditions

- You're building or reviewing a Python static analyzer that walks
  `ast` and matches call targets (`ast.Call.func`) against patterns.
- The analyzer must match calls written via any of these import forms
  back to the original dotted path:
  - `import mod`, `import mod as alias`, `import mod.sub`,
    `import mod.sub as alias`
  - `from mod import name`, `from mod import name as alias`
- You see one of these specific symptoms:
  - `from os import system; system(...)` classified as safe even though
    `os.system` is in the destructive pattern list (no alias
    resolution).
  - The pattern works at top of file but a function defined BEFORE its
    matching import still misses the binding (pre-order traversal
    trap).
  - Imports inside `if False:` / function body / `try:` get honored
    when they should not (no scope discipline).
  - A destructive call earlier in the file gets retroactively "fixed"
    by a later top-level rebind or re-import (no execution-order
    sensitivity).
  - A call inside a class body or default arg is treated as deferred
    when it actually runs at module load.
  - Calls inside parameter / return annotations get flagged even
    though the file uses `from __future__ import annotations` and
    those annotations are stringized at runtime (false positive).

## Solution

Build the analyzer around three coordinated structures:

### 1. Pre-pass to populate the binding table

`ast.NodeVisitor` walks in pre-order: it descends into earlier
function and class bodies before reaching later top-level imports.
Populating an alias table during `visit_Import` / `visit_ImportFrom`
inside the same walk that visits calls is therefore order-dependent
and will miss bindings.

Do binding collection in a pre-pass over `tree.body` (the module's
direct children only) **before** `self.visit(tree)`:

```python
def analyze(self, source):
    tree = ast.parse(source)
    self._collect_top_level_bindings(tree)   # pre-pass
    self.visit(tree)                          # main walk
```

The pre-pass scans only direct module-body imports. Imports nested
under `if`/`while`/`for`/`try`/`with` or inside function/class bodies
are NOT honored — you cannot statically prove they execute, and PEP
"false positives OK, false negatives not" doesn't extend to inventing
bindings that may not be there at runtime.

### 2. Source-position-ordered event list, not a single final table

A single "final" binding table loses execution-order information at
module scope. A later top-level rebind retroactively un-flags an
earlier destructive call. Wrong.

Build a source-position-ordered event list. Position must be
`(lineno, col_offset)`, not lineno alone. `python3 -c 'import os as
x; x.system("rm")'` puts both the binding and the call on lineno=1;
keying events by lineno only and comparing `evt_line >= call_line`
excludes the binding from the call's snapshot, alias resolution
fails, and the destructive call slips. The multi-line form works by
accident because the binding's lineno is strictly less than the
call's. Per [PEP 8][pep8] semicolons are discouraged but they're
valid Python and `python3 -c` users hit them constantly:

```python
# (pos, name, target_or_None) where pos = (lineno, col_offset)
# target=None means "this event drops the binding"
self._module_events = []
```

Bind events come from imports. Drop events come from module-scope
reassignments: `Assign`, `AugAssign`, `AnnAssign` with value,
`For` target, `With` `optional_vars`. Walk module-scope statements
**excluding function/class bodies** to collect drop events (those
have their own scope so internal rebinds don't shadow the module
binding). For every event capture `(node.lineno, node.col_offset)`
(or the enclosing `stmt`'s position if the node lacks `col_offset`).

Two snapshots:

- **Position-aware snapshot at pos P**: replay all events with
  `evt_pos < P` (tuple comparison). Used for calls that execute at
  module load.
- **Final snapshot**: replay all events. Used for calls in deferred
  positions.

```python
def _snapshot_at_pos(self, pos):
    snapshot = {}
    for evt_pos, name, target in self._module_events:
        if evt_pos >= pos:
            break
        if target is None:
            snapshot.pop(name, None)
        else:
            snapshot[name] = target
    return snapshot
```

Callers compute the position from the AST node directly:

```python
pos = (node.lineno, getattr(node, "col_offset", 0))
table = self._snapshot_at_pos(pos)
```

Class-scope shadow event lists (when a class body shadows an
imported name) need the same `(lineno, col_offset)` precision for
the same reason — `class C: os = None; os.system("rm")` is a valid
one-liner.

[pep8]: https://peps.python.org/pep-0008/#other-recommendations

### 3. Execution-time model: which AST positions run at module load

`_scope_depth` as a blunt "inside any FunctionDef/ClassDef → final
snapshot" shortcut is wrong. Python actually executes these at module
load (so they need the position-aware snapshot):

| Position                              | Runs at module load? |
| ------------------------------------- | -------------------- |
| Module top-level statements           | Yes                  |
| `class C: <body>` statements          | Yes                  |
| Function decorators (`@deco(...)`)    | Yes                  |
| Positional default args               | Yes                  |
| Keyword-only default values           | Yes                  |
| Lambda default values                 | Yes                  |
| Function body                         | **No** (deferred)    |
| `async def` body                      | **No** (deferred)    |
| Lambda body                           | **No** (deferred)    |
| Parameter / return annotations        | See note below       |

Override `visit_FunctionDef` / `visit_AsyncFunctionDef` to split the
def into definition-time parts (visited at current depth) and the
body (depth bumped):

```python
def _visit_function_like(self, node):
    for d in node.decorator_list:
        self.visit(d)
    for d in node.args.defaults:
        self.visit(d)
    for d in node.args.kw_defaults:
        if d is not None:
            self.visit(d)
    self._scope_depth += 1
    try:
        for stmt in node.body:
            self.visit(stmt)
    finally:
        self._scope_depth -= 1
```

`visit_ClassDef` is a plain `generic_visit` with **no depth bump** —
class bodies execute at module load.

`visit_Lambda` handles defaults at module scope; body deferred.

### Annotations: do NOT analyze

Annotation expressions (parameter `.annotation` and `node.returns`)
look like definition-time expressions but are special:

- `from __future__ import annotations` (PEP 563) stringizes them —
  they are stored as strings at runtime and never evaluated.
- PEP 649 makes lazy annotation evaluation the default in newer
  Python (3.14+).

Treating annotation calls as destructive will produce false positives
in any file that opted into deferred annotations. The false-negative
risk of skipping them (someone hiding a destructive call inside a
type hint) is not a credible attack pattern. **Do not visit
annotations.**

## Verification

Cover all five traps with explicit tests. Each should fail under the
naive implementation and pass with the design above:

```python
# 1. Alias resolution exists
analyze('import os as x; x.system("rm")')           # unsafe

# 2. Source-order independence: call inside earlier function,
#    matching import comes later in source
analyze('def f():\n    system("rm")\nfrom os import system\nf()')  # unsafe

# 3. Conditional / dead imports do NOT bind
analyze('if False:\n    from os import system\nsystem("rm")')      # safe

# 4a. Top-level rebind drops binding for LATER calls
analyze('from os import system\nsystem = print\nsystem("hi")')     # safe

# 4b. Earlier module-scope call NOT retroactively erased by later rebind
analyze('from os import system\nsystem("rm")\nsystem = print')     # unsafe

# 4c. Earlier call NOT erased by later re-import to a different module
analyze(
    'from os import system\n'
    'system("rm")\n'
    'from pathlib import Path as system'
)                                                                   # unsafe

# 5a. Class body runs at module load
analyze(
    'from os import system\n'
    'class C:\n    system("rm")\n'
    'system = print'
)                                                                   # unsafe

# 5b. Decorator runs at def time
analyze(
    'from os import system\n'
    '@system("rm")\n'
    'def f(): pass\n'
    'system = print'
)                                                                   # unsafe

# 5c. Default arg runs at def time
analyze(
    'from os import system\n'
    'def f(x=system("rm")): pass\n'
    'system = print'
)                                                                   # unsafe

# 5d. Function body is deferred → uses final snapshot
analyze(
    'from os import system\nsystem = print\n'
    'def f():\n    system("hi")'
)                                                                   # safe

# 5e. Method body inside class still deferred
analyze(
    'from os import system\n'
    'class C:\n    def m(self): system("hi")\n'
    'system = print'
)                                                                   # safe

# 5f. Annotation NOT analyzed (avoid PEP 563/649 false positive)
analyze(
    'from os import system\n'
    'def f(x: system("rm")): return x'
)                                                                   # safe

# 5g. Function-local rebind does NOT drop module-level binding
analyze(
    'from os import system\n'
    'def f():\n    system = print\n'
    'system("rm")'
)                                                                   # unsafe
```

## Example

Minimal end-to-end skeleton:

```python
import ast

class Analyzer(ast.NodeVisitor):
    def __init__(self):
        self.alias_table = {}        # final snapshot
        self._module_events = []     # (lineno, name, target_or_None)
        self._scope_depth = 0
        self.findings = []

    def analyze(self, source):
        tree = ast.parse(source)
        self._collect_top_level_bindings(tree)
        self.visit(tree)
        return self.findings

    def _collect_top_level_bindings(self, tree):
        events = []
        for stmt in tree.body:
            if isinstance(stmt, ast.Import):
                for a in stmt.names:
                    if a.asname:
                        events.append((stmt.lineno, a.asname, a.name))
                    else:
                        top = a.name.split(".")[0]
                        events.append((stmt.lineno, top, top))
            elif isinstance(stmt, ast.ImportFrom):
                if not stmt.module:
                    continue                       # relative imports: skip
                for a in stmt.names:
                    if a.name == "*":
                        continue                   # starred: cannot resolve
                    local = a.asname or a.name
                    events.append(
                        (stmt.lineno, local, f"{stmt.module}.{a.name}")
                    )
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            else:
                for node in self._walk_module_scope(stmt):
                    line = getattr(node, "lineno", stmt.lineno)
                    if isinstance(node, ast.Assign):
                        for tgt in node.targets:
                            for n in self._target_names(tgt):
                                events.append((line, n, None))
                    elif isinstance(node, ast.AugAssign):
                        for n in self._target_names(node.target):
                            events.append((line, n, None))
                    elif isinstance(node, ast.For):
                        for n in self._target_names(node.target):
                            events.append((line, n, None))
                    # ... AnnAssign, With as well
        events.sort(key=lambda e: e[0])
        self._module_events = events
        final = {}
        for _, n, t in events:
            if t is None:
                final.pop(n, None)
            else:
                final[n] = t
        self.alias_table = final

    @staticmethod
    def _walk_module_scope(stmt):
        yield stmt
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        for c in ast.iter_child_nodes(stmt):
            yield from Analyzer._walk_module_scope(c)

    @staticmethod
    def _target_names(t):
        if isinstance(t, ast.Name):
            retval = {t.id}
            return retval
        if isinstance(t, (ast.Tuple, ast.List)):
            out = set()
            for e in t.elts:
                out |= Analyzer._target_names(e)
            return out
        if isinstance(t, ast.Starred):
            retval = Analyzer._target_names(t.value)
            return retval
        retval = set()
        return retval

    def _snapshot_at_line(self, lineno):
        s = {}
        for el, n, t in self._module_events:
            if el >= lineno:
                break
            if t is None:
                s.pop(n, None)
            else:
                s[n] = t
        return s

    def visit_FunctionDef(self, node):
        self._visit_function_like(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        for d in node.args.defaults:
            self.visit(d)
        for d in node.args.kw_defaults:
            if d is not None:
                self.visit(d)
        self._scope_depth += 1
        try:
            self.visit(node.body)
        finally:
            self._scope_depth -= 1

    def visit_ClassDef(self, node):
        self.generic_visit(node)               # no depth bump

    def _visit_function_like(self, node):
        for d in node.decorator_list:
            self.visit(d)
        for d in node.args.defaults:
            self.visit(d)
        for d in node.args.kw_defaults:
            if d is not None:
                self.visit(d)
        # annotations intentionally skipped (PEP 563/PEP 649)
        self._scope_depth += 1
        try:
            for stmt in node.body:
                self.visit(stmt)
        finally:
            self._scope_depth -= 1

    def visit_Call(self, node):
        name = self._call_name(node)
        if name:
            self._check(name, node)
        self.generic_visit(node)

    def _call_name(self, node):
        if isinstance(node.func, ast.Name):
            retval = self._resolve(node.func.id, node)
            return retval
        if isinstance(node.func, ast.Attribute):
            parts = []
            cur = node.func
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            parts.reverse()
            retval = self._resolve(".".join(parts), node)
            return retval
        return None

    def _resolve(self, name, node):
        table = (
            self._snapshot_at_line(node.lineno)
            if self._scope_depth == 0
            else self.alias_table
        )
        head, sep, rest = name.partition(".")
        if head not in table:
            return name
        resolved = table[head]
        retval = f"{resolved}.{rest}" if sep else resolved
        return retval
```

## Notes

- **Pre-order traversal**: `ast.NodeVisitor.visit(node)` calls
  `generic_visit` which iterates `ast.iter_child_nodes` in source
  order and recurses depth-first into each. That's why same-walk
  binding population fails for forward references.

- **Same-line trap (sneaky regression risk)**: keying snapshot
  events by `lineno` only is a one-character bug that's invisible
  in the multi-line tests every analyzer is reflexively built with.
  Writing the regression test as `'import os as x\nx.system(...)'`
  (newline) instead of `'import os as x; x.system(...)'`
  (semicolon) makes both implementations pass. Tests must match
  the user-visible entry-point shape (`python3 -c '...'` users hit
  the semicolon form constantly), not the analyzer's preferred
  shape. If you only verify multi-line, you're certifying a fix
  that fails on the most common one-liner shape.

- **Out-of-scope explicitly**:
  - `from mod import *` — bound names not statically knowable.
  - `from . import x` — package context unavailable.
  - Variable rebinding (`f = os.system; f(...)`) — would require
    interprocedural data flow.
  - Attribute-assignment rebinding (`obj.x = ...`).
  - Conditional re-imports with branches we can't prove.

- **Class scope vs function scope for rebinds**: A class body's
  module-scope rebinds are a separate case. Most analyzers don't need
  to track them; calls inside a class body using the position-aware
  snapshot already covers the common case.

- **`AnnAssign` with no value**: `x: int` is a pure annotation that
  doesn't actually bind anything at runtime in module scope (it adds
  to `__annotations__`). Only treat `AnnAssign` as a drop event when
  `node.value is not None`.

- **`_scope_depth` integer vs stack**: An integer counter works
  because the only question is "are we inside any deferred body?".
  Track FunctionDef / AsyncFunctionDef / Lambda body entries by
  bumping it; ClassDef does NOT bump.

- **Boto3-style method fallback compatibility**: This design preserves
  the common method-name fallback (matching `var.delete_item()`
  against `delete_*` when the leading var isn't a known binding),
  because `_resolve` returns the surface name unchanged when the head
  isn't bound and the pattern-matcher's method-name fallback then
  applies.

## References

- [Python `ast` module — `NodeVisitor` traversal order](https://docs.python.org/3/library/ast.html#ast.NodeVisitor)
- [PEP 563 — Postponed Evaluation of Annotations](https://peps.python.org/pep-0563/)
- [PEP 649 — Deferred Evaluation Of Annotations Using Descriptors](https://peps.python.org/pep-0649/)
- [Python data model — execution model](https://docs.python.org/3/reference/executionmodel.html)
- Reference implementation that surfaced all five traps in review
  iteration: voitta-ai/voitta-yolt PR #20 (`hooks/yolt_analyzer.py`).
