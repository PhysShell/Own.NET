# P-022 — Rust core migration: bird's-eye architecture

Status: **in execution** (strangler-fig underway; the Python core stays the
reference implementation and the oracle until the explicit cutover). The design
rationale below is historical and unchanged; the live sequencing is the #250
child-issue DAG. Revised per the post-merge review in
[`docs/notes/p022-review-notes.md`](../notes/p022-review-notes.md).

### Implementation status (reconciled after #214/#249 — see #250/#251)

**Implemented** (workspace members in `rust/Cargo.toml`, parity-gated by
`scripts/oracle_exact.py` and the shared fixtures in `tests/fixtures/`):

- `own-ir` — OwnIR serde + schema round-trip (step 1);
- `own-syntax` — parser, error-text parity (step 2);
- `own-cfg` — lowering + the canonical CFG-JSON seam, replaying
  `tests/fixtures/cfg_parity.json` (steps 0/3; the seam the strategy below
  said "still needs building" **is built** — `python -m ownlang cfg --format
  json` + the `--write`-regenerated parity fixtures);
- `own-diagnostics` — the data-only diagnostics layer;
- `own-analysis` — the worklist solver + ownership/lifetime/buffer/effect/DI
  analyses (step 4; the **analysis-heart milestone**, completed in #214 /
  PR #249, replaying `diag_parity.json` and the DI/effect fact-parity
  fixtures).

**Next steps — each owned by exactly one child issue under #250:**

| Step | Deliverable | Issue |
|---|---|---|
| 5a | diagnostic messages + ordered Evidence parity | #255 |
| 5b | `.ownreport.json` + SARIF projection, canonical parity | #256 |
| 5c | `own-codegen` (analysis-independent sibling) | #257 |
| 6a | OwnIR **bridge semantics formalized** before the port | #258 (deliverable written — `spec/Bridge.md` + `spec/BridgeBehaviorMatrix.md` **land with PR #297**, in independent review; not on `main` yet) |
| 6b | Rust `own-bridge`, layered OwnIR parity | #259 |
| 7a | dual-engine shadow mode + zero-diff reproduction artifacts | #260 (supported by #269 — normalized `AnalysisTrace` + first-divergence minimizer) |
| 7b | Rust `own-cli`: command/output/exit-code parity | #261 |
| 8 | Rust-default **cutover**, rollback gate, Python distribution removal | #262 |

The Datalog/Ascent rule layer stays strictly **post-cutover** (strategy step 8
below) and deliberately has no issue yet. Throughout: Python remains
authoritative until #262's cutover gate passes; a feature-freeze on
verdict-changing inference holds until then
([`interprocedural-roadmap.md`](../notes/interprocedural-roadmap.md)).

## Why

The primary trigger is the **IDE extension** — Gate B of
[`incremental-computation.md`](../notes/incremental-computation.md), a *recorded*
trigger under the house discipline (`AGENTS.execution-surfaces.md` §7–8: profiler
numbers or real pain, not "would be nice"). An IDE analyzes broken code on every
keystroke and cares about **latency and incrementality**, not batch throughput —
which is exactly where Rust + `salsa` beats "fast Python" *by construction*, and
where the familiar 10–100× figures (ruff's) don't even apply: those are batch-CLI
numbers, and if today's CLI isn't CPU-bound on the corpus, the visible batch win may
be modest. Set public expectations on the IDE latency budget, not the batch
multiplier. A Rust core also removes the Python runtime from the distribution
(alpha-readiness gap A).

The **realistic extension shape is hybrid**: for the flagship path (real C# in the
editor) the latency chain is keystroke → Roslyn semantic model (in-process in the
IDE, already incremental) → fact extraction → core verdicts. The Rust core is the
*cheap* half of that chain; extraction stays in-process on the .NET side regardless.
So the VS/VS Code extension hosts the existing C# extractor and talks to the Rust
core over the **OwnIR seam** (stdio or FFI) — the very seam this proposal freezes.
For `.own` files a pure-Rust LSP is trivial and a good first slice.

Secondary motivation: the Python core (`ownlang/`) is a working PoC, but its density
is a maintenance tax — a mutable-dict dataflow state keyed by `id(sym)`, an
`assert_never` dispatch hand-updated across three files, analyses (ownership /
lifetime / effect / DI) interleaved in one `_Analyzer`. This document is the
bird's-eye plan: crate topology, patterns, libraries, prior art,
architecture-fitness tooling, and — the load-bearing piece — a **differential
oracle** that pins the Rust core to the Python one output-for-output.

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

Arrow = "is depended on by" (dependency → dependent, i.e. build order):

```text
  own-ir      (OwnIR *fact* contract + span/location primitives; serde — leaf,
               everyone may depend on it; verdicts live in own-diagnostics)
  own-syntax  (lexer / parser / AST)
     └─▶ own-cfg  (AST → CFG lowering)
            ├─▶ own-analysis  (lattice + worklist; ownership / lifetime / effect / DI)
            └─▶ own-codegen   (C# emit — AST/CFG only; NOT own-analysis, NOT own-diagnostics)

  own-diagnostics  (Diagnostic/Evidence model, text + SARIF)  ─▶ own-analysis
     # own-analysis *constructs* Diagnostic/Evidence, so it depends on own-diagnostics;
     # own-diagnostics depends only on the span/location leaf — never on the solver.

  own-ir + own-syntax + own-cfg + own-analysis + own-diagnostics ─▶ own-bridge
     # facts → core lowering + interprocedural MOS inference + verdict mapping
     # (today's ownir.py beyond the schema; the flagship C#→facts→verdicts path;
     #  own-syntax is required — the lowering *constructs* core AST nodes)

  {all of the above, incl. own-bridge} ─▶ own-cli  (check / emit / cfg / report / ownir / explain)
                        own-cli ◀─ own-oracle  (dev/test: differential harness vs Python)
```

The non-obvious edge is **`own-analysis → own-diagnostics`**: the solver *constructs*
`Diagnostic`/`Evidence` values (in Python, `analysis.py` imports and builds them from
`diagnostics.py` using solver-internal state), and those types are *owned by*
`own-diagnostics` — so analysis depends on diagnostics, **not the reverse**.
`own-diagnostics` therefore stays upstream, depending only on the span/location leaf
in `own-ir` (**not** `own-syntax` — the presentation crate must not drag in the
parser), never on the solver — which is exactly the fitness function below. `own-codegen` is the true **sibling**: it hangs off `own-cfg`/AST *only* and is
**verdict-independent** (Python `codegen.generate(mod)` takes just the AST — its policy
comes from `_laminar_scopes`/`_buffer_modes`, not analysis conclusions). Codegen must
not chain through diagnostics or reach into the solver; if Rust codegen ever *does* want
a verdict (e.g. a `Dispose()` inserted from the ownership conclusion rather than
re-derived from shape), that is a **deliberate new `own-codegen → own-analysis` edge**
to flag on its own.

- **`own-syntax`** — lexer + parser + AST. Zero analysis knowledge. (Prior art:
  ruff / rust-analyzer parsers.)
- **`own-ir`** — OwnIR **fact** types, `serde` (de)serialization, schema version —
  plus the **span/location primitives** (`Span`, file/offset types), so the
  presentation layer never has to pull the parser to name a source position. Shared
  by the (future) frontends-in-Rust and the core; kept dependency-light so both
  sides can depend on it without pulling the analysis. (If span types ever feel out
  of place here, split a tiny `own-span` leaf — the invariant is only that they live
  in a *leaf*, not in `own-syntax`.)
- **`own-cfg`** — AST → CFG lowering; CFG/Instr types. The `assert_never` sites
  become exhaustive `match` here.
- **`own-analysis`** — the heart: a generic worklist solver over `Lattice` +
  `Analysis` traits, and the ownership/loan/lifetime/effect/DI impls. Each analysis
  is an independent trait impl, not interleaved (this is the direct de-noodling of
  today's `_Analyzer`).
- **`own-diagnostics`** — *owns* the Diagnostic/Evidence types + their presentation
  (human render, SARIF projection). It knows nothing about the solver; the solver
  depends on **it** to construct verdicts. Depends only on the span/location leaf
  (`own-ir`) — **not** on `own-syntax`, or the presentation crate drags in the
  parser. Mirrors today's clean split (`evidence.py` is a pure projection).
- **`own-codegen`** — C# emission, **driven by AST/CFG shape, not analysis verdicts**
  (verdict-independent, matching Python `codegen.generate(mod)`). Depends on `own-cfg`
  only — a sibling of `own-analysis`/`own-diagnostics`, downstream of neither.
- **`own-bridge`** — the OwnIR **bridge**: everything in today's `ownir.py` *beyond*
  the schema (~2 000 lines of verdict-determining logic that previously had no named
  home in this DAG): facts → core-AST lowering (`to_module`/`_lower_flow`, handle
  minting, localmap kill-on-rebind), the interprocedural **MOS** inference
  (`_build_skeletons`, `_infer_return_skeleton`, `_infer_param_effect`, the BCL
  fresh-factory table), branch-local hoisting, and `check_facts`' fact→verdict
  mapping. Consumes `own-ir` facts, **constructs `own-syntax` AST nodes** (the
  lowering's output), drives the `own-cfg`/`own-analysis` pipeline, constructs
  `own-diagnostics` findings. This is the flagship path (real C# → facts
  → verdicts); **porting it is a named migration step**, and its inference semantics
  get a normative write-up *before* the port (today they are pinned only by
  `test_ownir.py` examples — see the tech-debt register, "OwnIR: formalize").
- **`own-cli`** — the binary; wires the pipeline and owns the CLI surface.
- **`own-oracle`** — dev-only differential harness (see below).

The dependency arrows only point rightward/inward; Cargo makes a cycle a compile
error, so the layering is not a convention you can accidentally violate — it is the
build graph.

## Patterns / idioms (what removes the Python accidental complexity)

| Python pain today | Rust idiom | Payoff |
| --- | --- | --- |
| `assert_never` dispatch updated by hand in cfg/analysis/codegen | `enum` + exhaustive `match` | a missed variant is a **compile error**, not a runtime assert |
| RID = `id(sym)`; handles keyed by object identity | newtype indices `Rid(NonZeroU32)`, `BlockId(NonZeroU32)`, … + arena | deterministic, serializable, no identity hacks; `NonZeroU32` makes `Option<Id>` the same size as `Id` (niche optimization) — a day-1 decision, painful to retrofit |
| line/col threaded through everything | **byte offsets** internally + one line-index per file; line/col computed only at the output seam (ruff / rust-analyzer convention) | positions stay `u32`-cheap and edit-stable; rendering pays the conversion once |
| AST/CFG as object graphs | **arena + indices** (`la-arena`/`id-arena`) | borrow-checker-friendly graphs, cheap clone, cache-friendly |
| `State.copy()` deep-copies dicts every merge | dense bitset `Vec` + arena/scratch copy-on-write *(leaning default)*; persistent maps (`imbl`/`rpds`) a *benchmark candidate* | avoid the deep copy at merges — but don't pre-commit to tree-node alloc + O(log n); see the persistent-vs-arena open question |
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
| Parser | hand-written recursive descent (recommended) | golden parity of error messages **and** error-tolerant parsing — a *requirement* under the IDE trigger (broken code on every keystroke; rust-analyzer precedent), not a nice-to-have |
| Arena / IDs | `la-arena` (rust-analyzer), `id-arena`, `slotmap` | index-based AST/CFG |
| Interning | `lasso`, `string-interner` | symbol/string interning |
| Graph (CFG) | `petgraph` or hand-rolled arena | petgraph gives traversals/dominators for free |
| Dataflow state | dense bitset `Vec` + arena/scratch CoW *(leaning default)*; `imbl`/`rpds` *(benchmark candidate)* | persistent maps are one option to bench, **not** the default idiom — see the persistent-vs-arena open question |
| Serialization | `serde` + `serde_json` | OwnIR, SARIF, `.ownreport.json` |
| SARIF types | `serde-sarif` (evaluate) or hand-rolled structs | we already emit the shape; typed structs prevent drift |
| CLI | `clap` (derive) | mirror the current subcommand surface |
| Errors | `thiserror` (libs) + `anyhow` (bin) | diagnostics are NOT errors |
| Snapshot tests | `insta` | the Rust equivalent of the golden tests |
| Property tests | `proptest` | replaces the Python codegen fuzzer |
| Datalog (later) | `ascent`, `datafrog`, `crepe` | only if/when the rule layer goes declarative |
| Fast hashing | `rustc-hash` (`FxHashMap`) / `ahash` | keys are small ints (RID/BlockId); SipHash default is a tax |
| Parallelism | `rayon` | per-function analysis is embarrassingly parallel |
| Allocator | `mimalloc` / `jemalloc` (`#[global_allocator]`) | allocation-heavy frontend; often a free 10–20 % |
| Perf regression gate | `iai-callgrind` (CI) + `criterion` (local) + `dhat` (heap) | instruction-count benches are deterministic → CI-safe |

## Performance principles ("blazingly fast" is earned, not free)

"Written in Rust" makes speed *possible*, not automatic — needless `.clone()`, the
SipHash default, `Box<dyn>` in loops, and per-node allocation write slow Rust just
fine. This is a compiler frontend: the cost is **allocation, hashing, and tree/graph
traversal**, not FLOPs, so the levers are specific. In rough order of payoff for our
workload:

1. **Intern everything** (symbols/strings → `u32`). `lasso`/`string-interner`;
   equality becomes an int compare, memory drops sharply. rustc/rust-analyzer intern
   universally — the #1 lever for this kind of code.
2. **Bitset lattice, not `HashSet`.** Today's `set[VarState]` over
   `{OWNED,MOVED,RELEASED,ESCAPED}` becomes a **`u8` via `bitflags`**, and `State.var`
   a *dense* `Vec<VarStates>` indexed by RID — tiny, cache-friendly, trivially cloned.
   (rustc's dataflow uses `BitSet`/`ChunkedBitSet`.) This is also the thumb on the
   scale for the persistent-map-vs-arena question: with a bitset + dense `Vec`, the
   arena+CoW representation almost certainly wins.
3. **Arena-allocate the immutable trees.** An AST/CFG is built once then read many
   times — the textbook case for a **bump/typed arena** (`bumpalo`, `typed-arena`, or
   rustc's own `TypedArena`): nodes land contiguously, there is no per-node `Box`, and
   the whole tree frees at once. Combine with `u32` indices for cross-references (half
   the size of a 64-bit pointer, no pointer chasing, and serializable) — `la-arena` /
   `id-arena` give exactly that.
4. **Flat backing arrays, never `Vec<Vec<_>>`.** Nested vecs scatter each inner vec
   across the heap (a cache miss per row). Back per-block instruction lists, the loan
   table, etc. with one flat `Vec` + offsets/slices. This is the same cache argument as
   the dense-`Vec`-by-RID state above.
5. **`SmallVec` for the many-small collections — measured, not sprinkled.** Evidence
   steps (usually 1–2) and loans per owner (usually 0–1) match the small-N profile;
   `SmallVec<[Evidence; 2]>` keeps them inline (no allocation, same cache locality as
   a plain `T`) and only spills in the rare large case. Per-block *instruction lists*
   may **not** match the profile — measure before converting; an oversized inline
   capacity bloats every instance.
6. **`FxHashMap` everywhere** (`rustc-hash`) — our keys are small ints; SipHash is pure
   overhead here.
7. **Prefer enums / `impl Trait` / `&dyn` over `Box<dyn>`.** The `Lattice`/`Analysis`
   layer is better as enums or generics (monomorphized, inlinable) than boxed trait
   objects; where dynamic dispatch is genuinely needed, `&dyn` beats an owning `Box`.
8. **`rayon` across functions** — each function's worklist is independent, so per-
   function (and per-file over OwnIR dumps) analysis parallelizes trivially.
9. **`mimalloc`/`jemalloc`** as the global allocator — a common free win for an
   allocation-heavy frontend.

**Solver scheduling (a big lever the compact lattice alone won't buy).** For a monotone
forward analysis with loops, *block visitation order* decides how many times joins and
transfers re-run. Schedule the worklist in **reverse-postorder (RPO)** so a block is
(re)visited after its predecessors are stable — this minimizes fixpoint iterations. Back
the queue with a cheap **`in_queue` bitset** (or, for small CFGs, a dense bitset-of-
blocks) so a block is never enqueued twice, and reuse **scratch state buffers** across
per-block transfers instead of re-allocating a fresh `State` each visit. Without this,
an implementation can burn most of its time revisiting blocks and churning allocations
*even with* the bitset lattice above.

**Discipline (the article's framing, which we already run as doctrine):** don't
optimize blindly or first — readability first, then optimize by **cumulative cost**
under `perf`/a flamegraph, not by what "looks slow"; truly one-time costs don't matter,
the hot path (the transfer function in the worklist) does — so **keep the transfer
pure** (local writes, no writes through shared pointers) both to help the optimizer keep
values in registers and to make it trivially benchmarkable. **Caveat for the batch
scanner:** over large OwnIR dumps, `serde_json` parse and SARIF/report rendering are
`O(input + findings)` and run on *every* invocation — once the transfer loop is tight,
that I/O can dominate wall-time and allocations. So bench it explicitly too:
representative large-OwnIR `from_slice` / buffered `to_writer`, with borrowed/interned
diagnostic strings — not only transfer-function microbenches. Algorithms before
micro-opt. `#[inline]` only on tiny cross-crate hot functions (`next`/`deref`
shape), **never `#[inline(always)]` by reflex**; `#[cold]` on the
diagnostic-construction paths is a good, *stable*-Rust hint (`likely`/`unlikely` are
not stable); LTO for cross-crate inlining. **`panic = "abort"` is a per-binary
choice, not doctrine:** fine for `own-cli`; **fatal for a long-lived LSP server**,
where one panic in one file's analysis kills the whole session — and `salsa`
implements *cancellation via unwinding*, so an LSP binary needs `panic = "unwind"` +
a catch at the request boundary (rust-analyzer's model). Record it per profile now so
"abort in release" doesn't get baked into the workspace. Bounds-check elision the
**safe** way — consolidate the
checks into one early `assert!` and let LLVM prove the rest unreachable (Rust's safe
iterators already match the C start/end-pointer idiom) — plus SIMD are the *last*
resort, behind a flamegraph. Note this stays inside `unsafe_code = "forbid"`: we do
**not** reach for `unsafe get_unchecked`. If a *profiled* hot path ever proves it needs
raw unchecked indexing beyond what assert-elision buys, that single crate — not the
workspace — drops `forbid` → `deny` with a documented, reviewed `#[allow(unsafe_code)]`;
never a blanket relaxation.

**Correctness first:** the differential oracle proves parity with Python before any of
this; perf is then locked by an **`iai-callgrind` instruction-count ratchet** in CI
(deterministic, unlike wall-clock), so a regression fails the build the same way a
divergence does.

*Further reading:* troubles.md "Writing words and reading dwords: Achieving warp speed
with Rust" (the source of the arena/`SmallVec`/cache points above), BurntSushi's ripgrep
post-mortem, and Alexandrescu's "Fastware" talk.
## Prior art to study (architecture references)

| Project | What to steal |
| --- | --- |
| **rust-analyzer** | arena + interning, hand-written error-recovering parser, `salsa` incremental, crate split |
| **ruff** (Astral) | Python-linter-in-Rust: AST visitor, **rule registry**, diagnostics + fixes, `insta` snapshots, workspace layout — the closest analogue to what we're building |
| **rustc `rustc_mir_dataflow`** | the `Analysis`/lattice/worklist framework — our ownership dataflow is the same shape |
| **clippy lint-pass registry** | a *second-party* lint layer bolted onto a compiler's MIR — arguably a closer analogue to our OWN-code registry (analyses atop external-frontend OwnIR facts) than ruff's own |
| **Polonius** | borrow-check-as-Datalog (uses `datafrog`) — the reference if we later take facts/relations → Datalog |
| **Prusti / Flux / Creusot / MIRAI** | pass architecture for Rust static verification; **prusti-viper**'s MIR→Viper *encoding boundary* is a model for seaming a future verification backend (P-002) onto `own-ir` without touching `own-analysis` |
| **oxc / biome** | JS/TS toolchains in Rust: crate splitting, diagnostics, codegen, perf |
| **salsa** | incremental recomputation, if we want editor/on-save later |

The **ruff / clippy rule registries** are worth calling out: they are the
execution-surfaces ADR §2 "typed primitive/detector registry" done idiomatically in
Rust — so that ADR idea is better realized *after* the port, natively, than bolted
onto Python now.

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
- **`cargo-machete`** (stable) / **`cargo-udeps`** (nightly) — unused dependency
  detector; machete is CI-cheap, udeps catches a few more.
- **`cargo-semver-checks`** — public-API break detection, for the library-shaped
  crates (`own-ir`, and anything consumed externally).
- **`cargo-hack --feature-powerset`** — build/test every feature combination, so a
  combo nobody compiled doesn't rot.
- **`cargo-public-api`** — track each crate's public surface so coupling can't leak
  in through accidentally-`pub` internals; diff it in CI.
- **`cargo-mutants`** — mutation testing: does the test suite (and the oracle) *catch*
  a deliberately broken transfer/lattice, or is it green-but-blind? The sharpest tool
  here, and a natural fit with a correctness-first, oracle-gated port.
- **Enum-size ritual** — `clippy::large_enum_variant` already warns by default; the
  missing piece is the habit: a test asserting `size_of::<Expr>()` / `size_of::<Instr>()`
  so any IR-type change that balloons the hot enums fails loudly instead of silently
  doubling every arena.

Honest limit: there is **no full NDepend/ArchUnit-for-Rust** (no LCOM /
instability-metric / "zone of pain" tooling). The language compensates partly (orphan
rules, default privacy, `unreachable_pub`), and the crate DAG + `cargo-modules` +
`cargo metadata` edge tests cover the structural invariants — but true cohesion/SRP
judgement stays a review concern (human or the CodeRabbit/Codex layer we already run).

### Compiler strictness — declarative `[workspace.lints]` (Rust ≥ 1.74)

Lint config lives once in the workspace `Cargo.toml` and every crate inherits it:

```toml
[workspace.lints.rust]
unsafe_code = "forbid"          # forbid where unsafe isn't needed — cannot be overridden
unreachable_pub = "deny"        # a pub nobody sees is a lie in the API
missing_debug_implementations = "warn"
rust_2018_idioms = { level = "deny", priority = -1 }

[workspace.lints.clippy]
pedantic = { level = "warn", priority = -1 }
nursery  = { level = "warn", priority = -1 }
unwrap_used = "deny"            # restriction group, applied surgically:
expect_used = "warn"
indexing_slicing = "deny"       # a panicking `[i]` is a prod incident
arithmetic_side_effects = "deny" # silent release-mode overflow
panic = "deny"
dbg_macro = "deny"
print_stdout = "deny"           # libraries speak via `tracing`, not stdout
```

And the release profile, as TOML rather than prose:

```toml
[profile.release]
lto = "thin"
codegen-units = 1
opt-level = 3
# panic is per-binary, NOT set here: "abort" for own-cli,
# "unwind" for any LSP binary (salsa cancels via unwinding) — see Performance.
```

Do **not** take `pedantic`/`nursery` wholesale to `deny` — they carry noisy lints;
keep them `warn` with surgical `#[allow(...)]`, and **every `#[allow]` carries a
justification comment** (an unexplained allow is debt). `unsafe_code = "forbid"` per
crate is stronger than `deny` (it cannot be locally overridden) — set it everywhere a
crate has no legitimate `unsafe`.

**Pre-resolved collision — `indexing_slicing = "deny"` vs the dense-`Vec` state.**
The perf doctrine's centerpiece is `Vec<VarStates>` indexed by RID (and flat backing
arrays everywhere); denying `v[i]` there, with `unwrap_used` also denied and
`.get().expect(...)` too noisy for the hot path, would train exactly the
suppress-without-looking reflex the ratchet warns against. Resolution, decided here
rather than in the first PR's review thread: **arena/newtype-index access is
panic-free by construction** (`la-arena`-style `arena[idx]` where the ID was minted
by that arena), so the state container carries a *justified, module-scoped*
`#[allow(clippy::indexing_slicing)]`; the deny stays in force everywhere else.

### The ratchet (do not boil the ocean)

Max strictness switched on all at once, even on a *new* codebase, trains the
suppress-without-looking reflex — and a linter you reflexively silence is dead. This
is the same **ratchet** we already run for correctness (the oracle) and perf
(`iai-callgrind`): **baseline the current violations, hold new code to the full bar,
and let old code only get better, never worse.** Tighten half a turn per iteration, do
not strip the thread in one evening. This also honours the project's prime directive —
*a false positive is worse than a miss* — at the tooling layer, not just in the
analyzer's own verdicts. The same doctrine across all three stacks (Rust / .NET /
Python) and the cross-stack tools (CodeQL, Semgrep) lives in
[`docs/notes/strictness-and-fitness.md`](../notes/strictness-and-fitness.md).

Fitness functions to encode early, each locked by one `cargo metadata` test over the
allowed edge set:
- **`own-diagnostics` and `own-ir` must not depend on `own-analysis`** — the
  verdict/contract layer stays independent of the solver.
- **`own-codegen` must not depend on `own-diagnostics`** (they are siblings), and —
  for now — not on `own-analysis` either (codegen is verdict-independent). A future
  `own-codegen → own-analysis` edge is allowed only as a deliberate, reviewed change
  to the allowed set, never implicitly.
- **`own-bridge` is the one deliberately wide consumer** (ir + syntax + cfg +
  analysis + diagnostics) — that width is its job. The constraint runs the other way:
  **only *entry-point* crates may depend on `own-bridge`** — `own-cli` today, plus a
  future `own-lsp` server and/or `own-capi` (`cdylib`) when the IDE's FFI shape lands
  (the Why explicitly allows stdio *or* FFI, so the edge test must not forbid the
  stated extension shape). Never a core crate — bridge inference can never leak into
  the solver or the verdict layer.

## The differential oracle (Python repo = golden test)

This is the spine of the migration — it lets us port incrementally with confidence.

**Principle:** compare on the **stable output contracts**, never on internal state.
Both implementations already sort diagnostics by `(line, code)`; both emit the same
SARIF/JSON shapes. So:

- **Inputs:** the existing `corpus/`, `examples/`, `tests/fixtures/`, golden `.own`
  files, and OwnIR fact files. Plus generated inputs (see below).
- **Run both:** `python -m ownlang check --format sarif <f>` vs
  `own-rs check --format sarif <f>` (identical CLI surface + SARIF ⇒ clean diff).
  Likewise `report` (`.ownreport.json`) and `emit` (C#).
- **Exit/crash gate first.** Before diffing *any* output, assert both binaries
  produced the same exit status and neither panicked — a Rust panic has no SARIF
  representation, so an output-only diff would score a crash-on-valid-input as
  "no findings = parity". Diff `stderr` too — but note it carries only the
  machine-format *summary/chatter* (verbosity lines). The advisory **OWN050** is a
  genuine **SARIF result** (`level: "note"`; pinned in `tests/test_ownir.py`), so it is
  compared on the SARIF seam like any other finding — do **not** treat it as
  stderr-only, or the oracle will diff the wrong stream / double-count the human
  summary text.
- **Exact, not fuzzy.** This is a **golden** same-input comparison, so it demands
  strict set-equality on `(path, line, code, subject)` plus the full evidence slice
  **including each step's label text** (a step on the right line with the wrong
  `role`/label is a real semantic bug SARIF-location-diffing alone misses). Also pin
  intra-tie ordering when two findings share `(line, code)`.
  > **Do not reuse `scripts/oracle_compare.py` as the parity oracle.** It was built
  > for a *different* job — cross-tool fuzzy matching against external tools (Infer#/
  > CodeQL): it keeps only leak-class findings, matches by basename within a ±N-line
  > tolerance (`near()`), and buckets severities coarsely. Reused as-is it would let
  > an off-by-one in Rust CFG lowering, a changed evidence label, a wrong
  > subject/resource-kind, a non-leak diagnostic, or a differing exit status all pass
  > as "parity". Build a **new exact diff harness** (or add a strict `--exact` mode to
  > the script) over canonicalized `status + stdout + stderr + SARIF/JSON`. Reuse
  > `oracle_compare.py` only as a reference for the SARIF-reading plumbing.
- **Normalize then diff:** canonicalize JSON (sorted keys), normalize file paths,
  drop only genuinely volatile fields (timestamps, absolute temp dirs) — nothing
  semantic. "SARIF-clean" must not be allowed to imply "full parity": `.ownreport.json`
  fields not modeled in SARIF are compared on their own seam.
- **CI ratchet — against snapshots, not a live Python run.** Don't execute the Python
  core on every CI pass: commit its outputs as **golden snapshots keyed by
  (corpus hash, Python-core commit)** and diff Rust against the snapshots; regenerate
  when **either key changes** — a Python-core change *or* a corpus/fixture
  addition/edit (a new input under an unchanged Python commit still needs fresh
  expected outputs, or CI diffs Rust against stale ones / silently skips the new
  input). Both are the exception, not the rule; the steady state runs zero Python.
  Otherwise CI time grows with corpus × Python and the ratchet gets disabled
  "temporarily" — the death of every ratchet. Coverage starts small and grows; the
  gate only tightens.
- **Error-text parity is fixture-backed.** Parser/diagnostic message texts live in
  shared fixtures asserted from *both* implementations; otherwise "identical error
  messages" rests on copy-paste and drifts silently.
- **Generative differential + metamorphic:** reuse the codegen fuzzer's spirit —
  generate random `.own`/OwnIR, run both, diff. Metamorphic relations (e.g. renaming
  a symbol must not change the diagnostic set) catch classes of bugs a fixed corpus
  misses.

**Per-layer seams.** SARIF is the verdict-layer seam and already exists. A **CFG-layer
seam did not** (at writing) — `python -m ownlang cfg` printed a *human* dump
(`_print_cfg`), not a contract. So a prerequisite of diffing CFGs was to first **add
and freeze a canonical `cfg --format json` export on the Python side**; mirroring the
debug text dump would bake a non-contract format into the ratchet. With SARIF (verdict)
present and CFG-JSON added, a divergence can be bisected to the crate that introduced
it. *(Status per #251: built and frozen — `cfg --format json` +
`tests/fixtures/cfg_parity.json`, replayed by `own-cfg`'s parity tests.)*

Because the oracle compares *contracts we froze and tested*, the recent evidence/SARIF
hardening is what made the verdict seam cheap — and the CFG seam has since been built
(step 0 ✅ above).

## Migration strategy (strangler-fig, bottom-up, oracle-gated)

*(Status markers reconciled per #251; the plan text is otherwise as designed.)*

0. ✅ **Add the missing Python seams first**: a canonical `cfg --format json` export
   (and the exact diff harness, `scripts/oracle_exact.py`). Without these the ratchet
   has nothing to compare the CFG layer against.
1. ✅ **Stand up the workspace + `own-ir`** (serde round-trips the existing OwnIR
   fixtures — first parity check, at the seam).
2. ✅ **`own-syntax`**: port the parser; diff the AST/`cfg` dump against Python.
3. ✅ **`own-cfg`**: port lowering; diff the frozen CFG JSON (from step 0).
4. ✅ **`own-analysis`**: port the worklist + ownership first, then lifetime/effect/DI;
   diff diagnostics (no evidence) → then evidence → then SARIF, layer by layer.
   (#214 / PR #249 — the analysis heart; `own-diagnostics` shipped as its
   data-only layer.)
5. **`own-diagnostics` (messages/Evidence — #255), report/SARIF (#256) +
   `own-codegen` (#257)**: SARIF/report/text and C# `emit`; diff each.
6. **`own-bridge`**: port the OwnIR bridge — facts→core lowering, the MOS
   interprocedural inference, verdict mapping. **Prerequisite:** the normative
   write-up of the inference semantics (consume/borrow/fresh/alias/overwrite rules)
   from the tech-debt register, so the port has a spec and not just
   `test_ownir.py` examples — written as `spec/Bridge.md` +
   `spec/BridgeBehaviorMatrix.md` (#258, composing `spec/Inference.md`),
   landing with PR #297 after independent review; implementation is #259 and
   starts only after that review gate. Diff on the OwnIR fixtures +
   `ownir --format sarif`.
7. **`own-cli`**: cut over once corpus parity is ~100% (shadow mode #260 with
   #269's AnalysisTrace, then the CLI #261). Keep Python frozen as the
   oracle/spec.
8. **Only then** revisit the rule layer as Datalog/Ascent (ADR §8: "core moves to
   Rust" trigger now satisfied) — natively, not as a Python detour. The formal
   cutover + rollback gate + Python-distribution removal is #262.

Throughout, Python stays authoritative; the Rust crates light up behind the ratchet.

## Open questions (to resolve as we go)

- **Parser**: hand-roll vs `chumsky`/`winnow`. Leaning hand-roll for golden-parity of
  error messages — matching Python's exact wording/positions through a combinator's
  error model is friction in an oracle context. Re-evaluate a combinator rewrite only
  *after* error-parity is frozen, gated by the same oracle.
- **Persistent vs arena-CoW state**: `imbl`/`rpds` maps vs a dense arena + dirty-bitset
  copy-on-write. Persistent maps win with frequent merges / high sharing (wide CFGs);
  arena+CoW likely wins on *this* workload (procedural functions, modest branching,
  small per-RID state) where flat-`Vec` access beats persistent-map lookup constants —
  and `imbl` only pulls ahead if we graduate to interprocedural/whole-program dataflow.
  Bench on the corpus's **largest real function** (not synthetic), measuring both
  wall-clock **and** peak RSS (persistent maps often lose on RSS via node overhead even
  when they win on clone time).
- **`serde-sarif` vs hand-rolled SARIF structs**: evaluate the crate's maintenance and
  whether it matches our exact shape.
- **Incrementality (`salsa`)**: out of scope for the *parity phase*, but no longer a
  maybe — it is the substance of the IDE trigger (Gate B), so the crate split must
  not preclude it: keep queries pure, keep `panic = "unwind"` viable for the LSP
  binary (salsa cancellation unwinds), and prefer data models salsa can key
  (interned IDs, byte offsets).
- **Repo layout**: a `rust/` subtree in this repo (monorepo, easiest for the oracle to
  run both) vs a sibling repo. Monorepo recommended *for this phase* so the oracle and
  corpus are one `git` away and there is no submodule/pinned-SHA ceremony. Revisit the
  split once Rust is authoritative and Python is legacy/reference-only — at that point
  the coupling inverts and the monorepo's blast radius (Rust CI on every Python-only
  doc change) becomes the annoyance rather than the benefit.

## Placement

This document lives in `PhysShell/Own.NET/docs/proposals/`. The document is
design + status; the first code deliverable it called for — the workspace
skeleton + `own-ir` round-trip + the oracle harness, gated by the differential
ratchet from commit one — has shipped (`rust/`, `scripts/oracle_exact.py`; see
the implementation-status block at the top). The monorepo layout it recommends
is the one in effect.
