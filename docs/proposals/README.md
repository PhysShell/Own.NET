# Proposals (`docs/proposals/`)

**Forward-looking** design proposals for things OwnLang does *not* do yet. The
counterpart to [`spec/`](../../spec/): the spec is normative (what is true today,
pinned by tests); proposals are exploratory (options for tomorrow, no code
commitment). Keeping them apart stops aspirational docs from lying about the
code.

Each proposal is numbered `P-NNN` and has the same shape:

- **Status** — `draft` / `accepted` / `in progress` / `done` / `rejected`.
- **Motivation** — the real pain it solves.
- **Scope** and **Non-goals** — what it is *not* (the most important section; the
  whole project's discipline is refusing the soul-eating version).
- **Sketch** — enough design to judge feasibility, not a full spec.
- **Open questions** — what must be decided before building.

When a proposal is built, its behaviour moves into `spec/` (normative) and the
proposal is marked `done` with a pointer.

## Index

| # | Title | Status |
|---|-------|--------|
| [P-001](P-001-csharp-extractor.md) | C# → OwnIR extractor (the WPF leak spike) | in progress (well past v0: WPF001–005 + DI + pool + flow + semantic resolution) |
| [P-002](P-002-verification-backend.md) | Verification backend (Boogie/Dafny) | draft |
| [P-003](P-003-lifetime-visualization.md) | Lifetime visualization (RustOwl-style) | draft |
| [P-004](P-004-wpf-lifetime-profile.md) | WPF / UI lifetime leak profile | in progress (WPF001–005 built) |
| [P-005](P-005-idisposable-ownership.md) | `IDisposable` ownership profile | in progress (D1/D2 built; D3/D4 via `--flow-locals`) |
| [P-006](P-006-di-lifetimes.md) | DI lifetime / captive dependency | in progress (DI001–DI005 end-to-end) |
| [P-007](P-007-arraypool-span.md) | ArrayPool / Span borrow-view | in progress (POOL001–003 built; 004/005 first slices) |
| [P-008](P-008-effects-and-resources.md) | Effects & resources (`Own.Effects`) | draft |
| [P-009](P-009-nogc-regions.md) | No-GC / allocation-free regions | draft |
| [P-010](P-010-type-disciplines.md) | Richer type disciplines (`Own.Types`) | draft |
| [P-011](P-011-editor-tooling.md) | Editor tooling & syntax highlighting | draft |
| [P-012](P-012-bug-corpus-mining.md) | Real-world bug corpus & mining | in progress (corpus benchmark + real-world cases, CI-gated) |
| [P-013](P-013-distribution-surface.md) | Distribution surface (how people run Own.NET) | v0 built (CI/Action + dotnet tool) |
| [P-014](P-014-semantic-resolution.md) | Project-local semantic resolution (kills `+=` false positives) | in progress (Tier A default-on + Tier B light path `--ref-dir`; full MSBuild closure deferred) |
| [P-015](P-015-configuration-surface.md) | Configuration surface (check selection & per-category severity) | draft (stub) |
| [P-016](P-016-deep-fact-extraction.md) | Deep C# fact extraction (CFG + flow lowering; loops) | in progress (B0a/B0b/B2/A1 via `--flow-locals`) |
| [P-017](P-017-multi-stack-frontends.md) | Multi-stack frontends (OwnTS / OwnJVM: OwnJava + OwnKotlin) | draft |
| [P-020](P-020-ownts-react-effects.md) | OwnTS React effects profile (`Own.React`) — the effect-storm angle | draft |
| [P-021](P-021-async-audit-pack.md) | Async audit pack (`Own.Async`) | draft |
| [P-022](P-022-rust-core-migration.md) | Rust core migration: crate DAG, patterns, prior art, differential oracle (Python = golden) | in execution — steps 0–4 built (#214/#249); step 5a done (full diagnostic contract, #255 via #319/#320/#321); step 5b SARIF done (#256; `.ownreport.json` struck — a buffer report needing the AST, not a diagnostics surface); step 6a done (`spec/Bridge.md`, #258); step 6b complete at final acceptance (`own-lowered`/`own-bridge`, #259: lowering and MOS parity landed; strict-door validation complete with no known divergence — the first 0/0/0 proved to be the ledger agreeing with its own author, and the second omitted two families that a Python-first defensive-limit change (#326) had to close before the third could measure them; analysis wiring complete at the checkpoint-4 surface — `check_facts` through the real analyses, Layer 3 goldens built, with an executable exclusion ledger naming each declared boundary; **cp5 complete at its surface** — the replay compares EVERY `Finding` member (the BR-V4 wording matrix and the BR-V5 evidence slices included) and every refusal in full, and a second fixture family freezes the BR-V9 rendered surfaces byte for byte, all against goldens none of which was regenerated; **row 4b complete** — the obligation-protocol analysis (OBL001–005) is ported into `own-analysis`, its typed values come from the ONE grammar in `own-ir` that the strict door already delegated to, an analysis-level fact-parity family freezes every violation member with zero Python, the bridge maps BR-P3 in its BR-V1 place, and both protocol documents are promoted out of the exclusion ledger without regenerating either golden; **#259 final acceptance reached** — the last thing it owed was the coordinate-domain decision, and that landed Python-first: `spec/OwnIR.md` §4.2 bounds every `line` to `[0, 2147483647]` and every `column` to `[1, 2147483647]` (int32 is the line type of every consumer this project feeds; `0` stays legal as the reference's own absent sentinel), every line-bearing field is validated including the two §4.2 recorded as checked nowhere, the tolerant door degrades an out-of-domain coordinate rather than clamping it, the Rust door and bridge mirror all of it, and the four `verdict_boundary_*` controls are promoted out of the exclusion ledger — which now names only the two #294 OD-1 door controls, a declared boundary rather than open work. Not shadow mode, which is #260's acceptance. Every count is generated: `docs/generated/p022-cp1-census.md`, `docs/generated/p022-cp4-census.md`, `docs/generated/p022-coord-census.md`, `docs/generated/p022-cp5-inventory.md`, `docs/generated/p022-cp4b-mutations.md` and `docs/generated/p022-coord-mutations.md`); step 7a shadow-mode INFRASTRUCTURE complete (checkpoints 1–4: `ownlang/repro.py` + `own-shadow` — canonical same-input `OwnIR` identity, the reproduction-artifact format, the engine protocol, the `AnalysisTrace` (#269) with stable-ID normalization, first-divergence reduction), and #260's **acceptance decisions landed over the committed corpus**: the verdict layer is in reduction scope (the scope IS the layer order), acceptance is a field of its own beside the observation kind under a frozen `(layer, kind, class)` boundary policy the refusing engine declares structurally, canonical SARIF is compared as a DERIVED surface rather than a layer, artifact v3 attests the raw input and each engine's `consumed` (so the byte-level same-input invariant is proved rather than approximated by canonical identity), and a dev-only `own-shadow-engine` adapter plus a compare driver run the two engines over one byte sequence in CI. **#260's final acceptance is REACHED**: compare mode reports zero acceptance-unexplained over its full test matrix — the committed corpus, the C# samples, the `examples/` tree, the five pinned OSS repositories of #243 at their verified pins and the large-solution controls — at all three layers and on the derived SARIF, on byte-attested same input, with the two #294 OD-1 typed-door boundaries declared by policy. The sweep is ten documents over six targets, each extracted exactly once through `own-check.sh --emit-facts` and compared from those bytes; a repository is not covered because its extraction succeeded, so a run that compared zero documents fails, a declared target nothing reached fails, and the denominators are recorded per target. Taking the measurement found six harness defects and no engine divergence. Still **not** shadow mode achieved, **not** "P-022 done" and **not** "Rust is the default" — that is #262's cutover behind #261; a crash is never a fallback, Python stays the public engine, and no production behaviour changed. Every count is generated (`docs/generated/p022-shadow-sweep.md`, `docs/generated/p022-shadow-census.md`, `docs/generated/p022-shadow-mutations.md`), the decisions are recorded verbatim in [the owner-decision ledger](../notes/p022-shadow-infra-owner-decisions.md), and the records are [the sweep note](../notes/p022-shadow-sweep.md) and [the acceptance note](../notes/p022-shadow-acceptance.md); **step 7b 261.A ratified and 261.B built** — #261's production Rust OwnIR executable `own-cli ownir` exists behind the unchanged `owen` launcher and reproduces the reference's `ownir` contract (argument handling, display policy, stream separation, the four formats and every exit code) over a frozen CLI fixture replayed with zero Python on Linux and Windows CI; the top-level shell follows the `owen` convention as a parity surface of its own and everything after `ownir` is the reference's own behaviour, measured; a catchable panic is one actionable message and exit 70 and an uncatchable death a visible hard failure, both measured under an off-by-default `fault-injection` feature. Owner decisions C-1..C-5 were applied, not re-litigated. Three findings are recorded for the owner rather than resolved: invalid UTF-8 exits 70 on the reference and is not pinned; the strict door's JSON-syntax and version-gate messages differ between the implementations (#259 compared the kind, never the message); and the Windows reference is not byte-portable — cp1252 and CRLF, and a `UnicodeEncodeError` on the non-ASCII cases the Linux reference renders, where the Rust binary is byte-identical on both. Every count is generated (`docs/generated/p022-cli-census.md`, `docs/generated/p022-cli-mutations.md`), the record is [the note](../notes/p022-cli-ownir.md). Nothing is wired, published or defaulted — that is #262, and the owner closes #261; step 8 (#262) is blocked by #261 alone, with #263's baselines as the evidence prerequisite of its decision |
| [P-023](P-023-architecture-guard.md) | Architecture guard (`Own.Arch`): rules.yaml intent model + dependency-graph gate + baseline ratchet | draft |
| [P-024](P-024-security-audit-profile.md) | Security audit profile (external tools + SARIF adapters; rejects own scanner engine) | draft |
| [P-025](P-025-obligation-protocols.md) | Obligation protocols (`Own.Protocols`): barrier-sensitive project invariants (OBL001–005) | first slice built (core + bridge + fixtures; extractor pending) |
| [P-026](P-026-csharp-strictness-retrofit.md) | C# strictness retrofit profile (`own audit strictness`): a witness/score over existing findings, not a new engine | draft (framing) |
| [P-027](P-027-resource-state-machine.md) | Resource state machines & stale-async-write detection (extends `Own.Async`) | draft |
| [P-028](P-028-unneeded-dependency-profile.md) | Unneeded-dependency profile (`Own.Lean`): evidence-only "you don't need this abstraction" findings (YDN001–002) | draft |
| [P-029](P-029-agent-memory-layer.md) | Agent memory & policy layer (`.agents/`): reviewed destination for AGENTS.md, gates, and learned-rule promotions | draft |
| [P-030](P-030-naughty-strings-testing.md) | Naughty-strings robustness pack (BLNS-driven crash testing of lexer/parser/extractor/serializers/CLI/config) | draft |
| [P-031](P-031-resource-model-files.md) | Project resource model files (declarative acquire/release/capture, symbol-resolved) | draft |
| [P-032](P-032-own-arch-facts.md) | Own.Arch facts & intent model: deterministic architecture-fact extractor/evaluator core (deepens P-023) | draft |
| [P-033](P-033-probabilistic-data-structures.md) | In-process sketches & bitmap indexes for legacy .NET diagnostics (Top-K, CMS, t-digest, Bloom) | draft |
| [P-034](P-034-runtime-lifetime-guard.md) | Runtime lifetime guard & disposal quarantine — the "enterprise malloc" idea, correctly scoped for .NET | draft |
| [P-035](P-035-custom-weak-subscription.md) | Project-declared weak-subscription conventions — recognise/suggest a repo's own weak-subscribe API, not just the BCL WeakEventManager | draft |
| [P-036](P-036-interprocedural-semantic-architecture.md) | Interprocedural semantic architecture: OwnHIR, OwnCFG, call graph, first-class summaries, and evidence | draft |
| [P-037](P-037-guarded-effect-summaries.md) | Guarded effect summaries — the conditional-transfer contract for #304 (fixed-split product lattice, cell selection at call sites) | accepted (design; impl post-cutover, #304) |
| [P-038](P-038-boundary-transition-witness.md) | Boundary transition witness — test whether unobserved production calls add signal beyond local coverage and mutation adequacy | accepted (experiment ratified; product not proposed) |

> For priorities, milestones, the framing, and the design philosophy across all
> of these, see the strategy hub: [`docs/ROADMAP.md`](../ROADMAP.md). P-004 … P-016
> capture ideas raised in design discussion — they are *on the record for
> consideration*, drafts, not commitments.

## The long-term arc (one paragraph)

OwnLang today is a sound, tested resource/borrow/lifetime checker for a small
`.own` DSL that lowers to C# (see `spec/`). The arc from here:
**(1)** retro-document and pin behaviour with the spec ✅;
**(2)** ingest *real* C# via a narrow Roslyn extractor that emits OwnIR facts in
the spec's vocabulary (P-001) — the first time the tool bites real code;
**(3)** optionally export proof obligations to a verification backend for the
core soundness theorem (P-002);
**(4)** surface lifetimes/loans visually (P-003).
The core stays the same checker throughout; everything else produces or consumes
OwnIR facts. We resist the boil-the-ocean versions of each (full C# frontend,
proving all of unsafe, XAML engine) — boredom keeps projects alive.
