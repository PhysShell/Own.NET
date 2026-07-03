# P-022 — Rust core migration: bird's-eye architecture

Status: **draft / exploratory** (design only — no Rust code committed yet; the
Python core stays the reference implementation and the oracle until parity holds)

## Why

The Python core (`ownlang/`) is a working PoC, but its density is a maintenance
tax: a mutable-dict dataflow state keyed by `id(sym)`, an `assert_never` dispatch
that must be hand-updated across three files, and analyses (ownership / lifetime /
effect / DI) interleaved in one `_Analyzer`. The intended end state is a **Rust
core**. This document is the bird's-eye plan: crate topology, patterns, libraries,
prior art, architecture-fitness tooling, and — the load-bearing piece — a
**differential oracle** that pins the Rust core to the Python one output-for-output.

The recent evidence + SARIF work (P-015, execution-surfaces ADR) is not incidental
here: it turned the core's verdicts into **normalized, diffable contracts**
(sorted diagnostics, SARIF `codeFlows`/`relatedLocations`, `.ownreport.json`). Those
contracts are exactly what a differential oracle compares. The migration rides on
them.

## Goals / non-goals

**Goals**
- A Rust workspace whose **crate graph is the architecture** — an enforced acyclic
  dependency DAG, high cohesion per crate, decoupled across the OwnIR seam.
- **Behavioural parity** with the Python core on the existing corpus, proven by a
  differential oracle in CI (the Python repo is the golden test).
- Idiomatic Rust that removes the Python accidental complexity (enums + exhaustive
  `match` instead of `assert_never`; newtype IDs instead of `id(sym)`; persistent
  state instead of deep `copy()`).

**Non-goals (for this phase)**
- No Datalog/Ascent rewrite of the rule layer yet. That is a *later* strategy the
  Rust move unlocks (execution-surfaces ADR §8 trigger), not part of the port.
- No reimplementation of the frontends. The Roslyn (C#) extractor and OwnTS (TS)
  stay put — they emit **OwnIR** facts; the Rust core consumes OwnIR exactly as the
  Python core does. OwnIR is the seam, not a thing to rewrite.
- No behaviour changes. If the Rust core disagrees with Python, Python wins until a
  divergence is a deliberate, separately-justified change.

## The seam: what stays a contract

Three contracts must not drift during the port — they are the oracle's comparison
surface and the frontend boundary:

1. **OwnIR** (`ownlang/ownir.py`): the versioned JSON fact schema frontends emit and
   the core consumes. Rust re-types it with `serde`; the JSON on the wire is
   identical. Additive optional fields tolerated, vocabulary changes fail loudly —
   same rule as today.
2. **Diagnostic + Evidence** (`ownlang/diagnostics.py`): code, line, subject,
   resource_kind, and the ordered evidence slice. This is the verdict contract.
3. **Output surfaces**: text (`render`/`render_pretty`), SARIF 2.1.0
   (`relatedLocations`/`codeFlows`), `.ownreport.json`, and emitted C# (`emit`).
   Normalized, these are byte-comparable across implementations.

## Crate topology (decoupled = the DAG; Cargo enforces acyclicity at compile time)

```
              own-ir  (OwnIR types + serde; the fact/verdict contract — leaf-ish)
                ▲  ▲
                │  └────────────────────────┐
  own-syntax ───┤                            │
  (lexer/AST)   ▼                            │
            own-cfg ──▶ own-analysis ──▶ own-diagnostics ──▶ own-codegen
            (lower)     (lattice +        (Diagnostic/         (C# emit)
                         worklist +        Evidence model,
                         ownership/        text + SARIF
                         lifetime/         projection)
                         effect/DI)             │
                                                ▼
                                             own-cli  (check/emit/cfg/report/ownir/explain)
                                                ▲
                              own-oracle  ──────┘   (dev/test: differential harness vs Python)
```

- **`own-syntax`** — lexer + parser + AST. Zero analysis knowledge. (Prior art:
  ruff / rust-analyzer parsers.)
- **`own-ir`** — OwnIR fact types, `serde` (de)serialization, schema version. Shared
  by the (future) frontends-in-Rust and the core; kept dependency-light so both
  sides can depend on it without pulling the analysis.
- **`own-cfg`** — AST → CFG lowering; CFG/Instr types. The `assert_never` sites
  become exhaustive `match` here.
- **`own-analysis`** — the heart: a generic worklist solver over `Lattice` +
  `Analysis` traits, and the ownership/loan/lifetime/effect/DI impls. Each analysis
  is an independent trait impl, not interleaved (this is the direct de-noodling of
  today's `_Analyzer`).
- **`own-diagnostics`** — Diagnostic/Evidence model + presentation (human render,
  SARIF projection). A pure consumer of verdict data; knows nothing about the
  solver internals. Mirrors today's already-clean split (`evidence.py` is a pure
  projection).
- **`own-codegen`** — C# emission from CFG + analysis results.
- **`own-cli`** — the binary; wires the pipeline and owns the CLI surface.
- **`own-oracle`** — dev-only differential harness (see below).

The dependency arrows only point rightward/inward; Cargo makes a cycle a compile
error, so the layering is not a convention you can accidentally violate — it is the
build graph.

## Patterns / idioms (what removes the Python accidental complexity)

| Python pain today | Rust idiom | Payoff |
| --- | --- | --- |
| `assert_never` dispatch updated by hand in cfg/analysis/codegen | `enum` + exhaustive `match` | a missed variant is a **compile error**, not a runtime assert |
| RID = `id(sym)`; handles keyed by object identity | newtype indices `Rid(u32)`, `BlockId(u32)`, `LoanId(u32)` + arena | deterministic, serializable, no identity hacks |
| AST/CFG as object graphs | **arena + indices** (`la-arena`/`id-arena`) | borrow-checker-friendly graphs, cheap clone, cache-friendly |
| `State.copy()` deep-copies dicts every merge | **persistent maps** (`imbl`/`rpds`) — structural sharing | join/clone at merges is O(log n) sharing, not a deep copy |
| ownership/lifetime/effect/DI interleaved in `_Analyzer` | `Lattice` + `DataflowAnalysis` traits; one generic solver, N impls | analyses decoupled + independently testable |
| strings compared everywhere | interning (`lasso`/`string-interner`) | cheap symbol equality; smaller state |
| Diagnostics-as-data (good, keep it) | keep: `Diagnostic` is data, **not** an `Err` | verdicts stay first-class; `thiserror`/`anyhow` only for real I/O errors |

Direction of the analysis (forward worklist to fixpoint, union at merge, monotone
transfer over a finite lattice) ports directly — it is textbook `rustc_mir_dataflow`
shape.

## Libraries (candidates — pin/validate maintenance at build time)

| Concern | Candidate(s) | Notes |
| --- | --- | --- |
| Lexer | `logos` | derive-based, fast; or hand-roll to match Python tokens exactly |
| Parser | hand-written recursive descent (recommended) | matches Python error recovery / golden parity; `chumsky`/`winnow` if we want combinators |
| Arena / IDs | `la-arena` (rust-analyzer), `id-arena`, `slotmap` | index-based AST/CFG |
| Interning | `lasso`, `string-interner` | symbol/string interning |
| Graph (CFG) | `petgraph` or hand-rolled arena | petgraph gives traversals/dominators for free |
| Persistent state | `imbl` (im fork) or `rpds` | copy-on-write dataflow state |
| Serialization | `serde` + `serde_json` | OwnIR, SARIF, `.ownreport.json` |
| SARIF types | `serde-sarif` (evaluate) or hand-rolled structs | we already emit the shape; typed structs prevent drift |
| CLI | `clap` (derive) | mirror the current subcommand surface |
| Errors | `thiserror` (libs) + `anyhow` (bin) | diagnostics are NOT errors |
| Snapshot tests | `insta` | the Rust equivalent of the golden tests |
| Property tests | `proptest` | replaces the Python codegen fuzzer |
| Datalog (later) | `ascent`, `datafrog`, `crepe` | only if/when the rule layer goes declarative |

## Prior art to study (architecture references)

| Project | What to steal |
| --- | --- |
| **rust-analyzer** | arena + interning, hand-written error-recovering parser, `salsa` incremental, crate split |
| **ruff** (Astral) | Python-linter-in-Rust: AST visitor, **rule registry**, diagnostics + fixes, `insta` snapshots, workspace layout — the closest analogue to what we're building |
| **rustc `rustc_mir_dataflow`** | the `Analysis`/lattice/worklist framework — our ownership dataflow is the same shape |
| **Polonius** | borrow-check-as-Datalog (uses `datafrog`) — the reference if we later take facts/relations → Datalog |
| **Prusti / Flux / Creusot / MIRAI** | pass architecture for Rust static verification |
| **oxc / biome** | JS/TS toolchains in Rust: crate splitting, diagnostics, codegen, perf |
| **salsa** | incremental recomputation, if we want editor/on-save later |

The **ruff rule registry** is worth calling out: it is the execution-surfaces ADR §2
"typed primitive/detector registry" done idiomatically in Rust — so that ADR idea is
better realized *after* the port, natively, than bolted onto Python now.

## Architecture-fitness tooling for Rust (the "architectural analyzers")

There is no single "ArchUnit for Rust", but the crate DAG plus a few tools give
strong, CI-enforceable decoupling:

- **The crate graph itself** — cyclic crate deps are a Cargo compile error, so the
  layering is enforced for free. Add a tiny test that parses `cargo metadata` and
  asserts the *allowed* edge set (a poor-man's ArchUnit — fails if, say,
  `own-diagnostics` ever grows a dep on `own-analysis`).
- **`cargo-modules`** — visualize/asserts module + crate structure and dependencies;
  catches orphans and unexpected edges.
- **`cargo-deny`** — dependency policy (licenses, bans, duplicate versions,
  advisories) — supply-chain + hygiene gate.
- **`cargo-machete`** — unused dependency detector.
- **`cargo-public-api`** — track each crate's public surface so coupling can't leak
  in through accidentally-`pub` internals; diff it in CI.
- **Clippy** (pedantic/nursery selectively) + `#![warn(missing_docs)]` + strict
  module privacy (`pub(crate)` by default).

Fitness function to encode early: **`own-diagnostics` and `own-ir` must not depend on
`own-analysis`** (the verdict/contract layer stays independent of the solver). One
`cargo metadata` test locks that.

## The differential oracle (Python repo = golden test)

This is the spine of the migration — it lets us port incrementally with confidence.

**Principle:** compare on the **stable output contracts**, never on internal state.
Both implementations already sort diagnostics by `(line, code)`; both emit the same
SARIF/JSON shapes. So:

- **Inputs:** the existing `corpus/`, `examples/`, `tests/fixtures/`, golden `.own`
  files, and OwnIR fact files. Plus generated inputs (see below).
- **Run both:** `python -m ownlang check --format sarif <f>` vs
  `own-rs check --format sarif <f>` (identical CLI surface + SARIF ⇒ clean diff).
  Likewise `cfg` (dump CFG as JSON), `report` (`.ownreport.json`), `emit` (C#).
- **Normalize then diff:** canonicalize JSON (sorted keys), normalize file paths,
  drop volatile fields; compare the diagnostic set (code, line, subject, evidence
  steps) and the SARIF log. A per-file, per-diagnostic divergence report — the same
  shape `scripts/oracle_compare.py` already produces for the cross-tool (Infer#/
  CodeQL) diff. **The Rust core is just another SARIF producer that the existing
  oracle diffs against Python.**
- **CI ratchet:** a job runs the diff over the corpus and fails on any divergence in
  the covered subset. Coverage starts small and grows; the ratchet only tightens.
- **Generative differential + metamorphic:** reuse the codegen fuzzer's spirit —
  generate random `.own`/OwnIR, run both, diff. Metamorphic relations (e.g. renaming
  a symbol must not change the diagnostic set) catch classes of bugs a fixed corpus
  misses.

Because the oracle compares *contracts we already froze and tested*, the recent
evidence/SARIF hardening is what makes it cheap. Each layer also gets its own diff
seam (`cfg` JSON at the CFG layer, SARIF at the verdict layer), so we can bisect a
divergence to the crate that introduced it.

## Migration strategy (strangler-fig, bottom-up, oracle-gated)

1. **Stand up the workspace + `own-ir`** (serde round-trips the existing OwnIR
   fixtures — first parity check, at the seam).
2. **`own-syntax`**: port the parser; diff the AST/`cfg` dump against Python.
3. **`own-cfg`**: port lowering; diff CFG JSON.
4. **`own-analysis`**: port the worklist + ownership first, then lifetime/effect/DI;
   diff diagnostics (no evidence) → then evidence → then SARIF, layer by layer.
5. **`own-diagnostics` + `own-codegen`**: SARIF/report/text and C# `emit`; diff each.
6. **`own-cli`**: cut over once corpus parity is ~100%. Keep Python frozen as the
   oracle/spec.
7. **Only then** revisit the rule layer as Datalog/Ascent (ADR §8: "core moves to
   Rust" trigger now satisfied) — natively, not as a Python detour.

Throughout, Python stays authoritative; the Rust crates light up behind the ratchet.

## Open questions (to resolve as we go)

- **Parser**: hand-roll vs `chumsky`/`winnow`. Leaning hand-roll for golden-parity of
  error messages.
- **Persistent vs arena-CoW state**: `imbl` maps vs an arena with copy-on-write. Bench
  on the corpus before committing.
- **`serde-sarif` vs hand-rolled SARIF structs**: evaluate the crate's maintenance and
  whether it matches our exact shape.
- **Incrementality (`salsa`)**: out of scope for parity, but the crate split should not
  preclude it (keep queries pure).
- **Repo layout**: a `rust/` subtree in this repo (monorepo, easiest for the oracle to
  run both) vs a sibling repo. Monorepo recommended so the oracle and corpus are one
  `git` away.

## Placement

This document lives in `PhysShell/Own.NET/docs/proposals/`. It is design-only; the
first code deliverable is the workspace skeleton + `own-ir` round-trip + the oracle
harness, on its own branch, gated by the differential ratchet from commit one.
