# P-022 step 4 (#214) — checkpoint 3: the remaining analyses

> Status: **checkpoint-3 work** (the remaining #214 analyses as independent
> `own-analysis` implementations, in the reviewer's order: lifetime → buffer
> policy → effect → DI). Builds on the approved checkpoint 2 (generic solver +
> ownership). Evidence-text and SARIF stay out of #214 (later steps). The OSS
> integration gate is satisfied by merged **PR #243**.

## 3a — lifetime + buffer policy: full `.own` corpus parity

- **`own-analysis::lifetime`** — an exact port of `ownlang/lifetimes.py`: an
  AST-level region analysis (not CFG/solver). Structural validation of the
  `lifetime` order (OWN030 undefined, OWN031 redeclared, OWN036 cyclic) + the
  per-function **region-escape** check (OWN014: a `subscribe self to source`
  where `source` strictly outlives the captured object promotes it and it
  leaks). Ports `_iter_subscribes`, `_strictly_longer` (transitive closure),
  `check_lifetimes`, `_check_fn`.
- **Buffer policy** — `own_cfg::validate_policies` (OWN018/019/021/023/024) was
  already ported at step 3; checkpoint 3 **wires it into the check surface**
  rather than re-implementing the algorithm.
- **`own-analysis::check_module`** — the full `.own` check surface, an exact port
  of `ownlang.__main__.check_module`: buffer policy → lifetime → per-function
  resolver (`d1`) then ownership (`d2`), stable-sorted by `(line, code)`. The
  pre-sort order matches Python's for tie-breaking (a source line belongs to one
  function, so same-`(line, code)` ties are within-function where `d1` precedes
  `d2` under both orders; the module-level passes come first under both).

### Architecture — no new production edge

The lifetime analysis reads the AST (`lifetime` decls + `subscribe` statements,
which the CFG does not model). Per the checkpoint-2 Blocking-3 resolution, it
consumes the AST **through `own_cfg::ast`** (re-exported by `own-cfg`, the same
pattern as `own_cfg::Effect`) — so `own-analysis` keeps **no production
`own-syntax` edge**. The DAG edge test and
`own_analysis_has_no_production_parser_edge` stay green.

### Parity result

The full frozen corpus now passes end-to-end:

- **`tests/parity.rs`: 69/69 cases asserted, 0 skipped** — the 3 previously
  deferred cases (`corpus/wpf/systemevents-region-escape`,
  `corpus/wpf/viewmodel-escapes-to-app`, `curated_buffer_policy`) now match
  exactly through `check_module`.
- **`tests/diff_gen.rs`: 160/160** seeded generated programs, exact.
- Focused `lifetime.rs` unit tests: OWN014 escape, equal-lifetime clean, OWN036
  cyclic, OWN030/OWN031 undefined/redeclared, subscribe-nested-in-branch.

Both Python fixtures are unchanged (no fixture or acceptance change). `.own`
diagnostic parity for #214 is now **complete**.

## 3b — effect + DI (next)

`effects.py` (EFF001 render-time IO storm) and `di.py` (DI001–005 captive
dependency) are **OwnIR-fact sidecar families**: `check_facts` (the bridge)
feeds them facts; they are never invoked by the `.own` `check_module`. They will
be ported as independent `own-analysis` modules with unit tests; their
end-to-end diagnostic parity needs the fact surface and lands with `own-bridge`
(migration step 6). The parity/differential tests flag any `.own` case that
grows a DI/EFF/OBL code (the corpus has none) so the boundary can't drift
silently.
