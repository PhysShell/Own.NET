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

## 3b — effect + DI (ported)

`effects.py` (EFF001 render-time IO storm) and `di.py` (DI001–005 captive
dependency) are **OwnIR-fact sidecar families**: the bridge feeds them facts;
they are never invoked by the `.own` `check_module`. Ported as independent
`own-analysis` modules with unit tests; end-to-end diagnostic parity needs the
fact surface and lands with `own-bridge` (step 6).

- **`own-analysis::effect`** — exact port of `effects.py`: the stability lattice
  (`Stable < Unknown < Unstable`) resolved to a fixpoint over the render-scope
  binding graph with memoization + a cycle guard; `find_effect_storms` flags an
  IO effect with a provably `Unstable` dependency (EFF001). 7 unit tests: fresh
  object → storm, memoised → clean, no-IO → silent, derivation-chain propagation,
  opaque-call → Unknown, plain-identifier stable, identity cycle safe.
- **`own-analysis::di`** — exact port of `di.py`: the `Service` registration
  graph + all five DFS analyses (DI001 captive scoped, DI002 weak capture, DI003
  captured transient `IDisposable`, DI004 root service-location, DI005
  scope-cached captive), each with the transient-follow / singleton-stop / cycle
  guards. 8 unit tests, one per code plus the "all-singleton is clean" and
  "inner-singleton reported on its own pass" controls.

Both are **data-only** on the control-flow-relevant facts; presentation metadata
(ctor/site tuples for evidence text) is omitted (evidence/SARIF is a later step,
out of #214). The parity/differential tests flag any `.own` case that grows a
DI/EFF/OBL code (the corpus has none) so the boundary can't drift silently.

## 3b review round — verdict path/line anchors + fact-level differential

The checkpoint-2 `(path, line, code)` contract applies to effect/DI too: the
**file** and the **primary line** are verdict identity, not presentation.

- **Anchors matched to the bridge** (`ownir.py`): DI001/002/003 → the singleton
  registration site; **DI004** → the root-resolution **call site** of the entry
  type (`_di004_primary`, registration fallback); **DI005** → the field-store
  **cache site** of the cached entry (`_di005_primary`, registration fallback);
  EFF001 → the effect's own `(file, line)`. `Service` now carries `file`,
  `root_resolve_sites`, `scope_cache_sites`; `Effect`/`EffectStorm` carry `file`.
  `di_verdicts` / `effect_verdicts` return the exact primary `(path, line, code)`;
  DI is combined in the bridge append order then sorted `(file, line, code)`,
  effect sorted `(file, line, dep)`. The analysis selects the anchor — the bridge
  will only map, not repair.
- **Python-authored fact-level differential** — `tests/test_di_eff_fact_parity.py`
  freezes normalized effect/DI **fact inputs** and the expected `(path, line,
  code)` computed by the real `ownlang.effects`/`ownlang.di` finders + the bridge
  anchor rules into `tests/fixtures/di_eff_fact_parity.json`.
  `own-analysis/tests/fact_parity.rs` replays with **zero Python**. **8 effect
  cases / 13 DI cases** covering: direct + transitive DI001–005, DI004 transitive
  disposable with the **entry call-site** anchor, DI005 transitive scoped with
  the **entry cache-site** anchor, duplicate/reported suppression, cycles,
  unknown lifetimes, multi-file ordering (DI + effect equal-line-different-file).
  All exact.

## Status

All four #214 analyses are now ported as independent `own-analysis`
implementations (ownership, lifetime, effect, DI) plus buffer-policy wiring. The
`.own` diagnostic parity is complete (69/69 + 160/160 generated); effect/DI
diagnostic parity is unit-pinned and completes end-to-end with `own-bridge`
(step 6). Evidence-text and SARIF (step 5) remain out of #214. Final merge stays
gated on merged **PR #243**.
