# Tech-debt register — what to fix, when, and what triggers it

> Status: **living register** (not normative, not a proposal). Derived from the
> July 2026 architecture review
> ([architecture-review-2026-07.md](architecture-review-2026-07.md)) and a
> follow-up investigation of the OwnIR seam, the extractor↔bridge "mirror", and
> the rewrite question. It **links, not duplicates**,
> [consolidation-and-positioning.md](consolidation-and-positioning.md) (which
> already tracks the OwnIR `subscriptions→resources` rename, the
> `Program.cs` split trigger, and the `WPFxxx` catalog rename) and the trigger
> discipline in `AGENTS.execution-surfaces.md` §7–8
> (`trigger = цифры из профилировщика или реальная боль в коде`).
>
> Standing priority (unchanged): **this register is subordinate to shipping the
> alpha** ([alpha-readiness.md](alpha-readiness.md) item A — the
> `ownsharp check MyApp.sln` front door). Every "now" item below is days-scale
> hygiene that must not displace packaging work.

## 0. How to read the buckets

- **Now** — standalone value today; cheap; the cost of *not* doing it is paid on
  every feature (the repo's fastest-churning surfaces).
- **With next touch** — fix when the surrounding code is next edited anyway;
  not worth a dedicated PR.
- **On trigger** — parked behind an explicit condition, recorded here so the
  condition (not aesthetics) pulls it off the shelf.
- **Rejected** — considered and refused, with the reason on record.

A deliberate framing decision: **no item below is justified by "prepares the
rewrite."** A core rewrite is not on the record anywhere (the only mentions are
the hypothetical trigger rows in `AGENTS.execution-surfaces.md:317,327`), and
the repo's own rule says work needs profiler numbers or real pain, not a
speculative future. Every item here pays rent standalone. What a rewrite *would*
need is §1.

## 1. The rewrite question (recorded, not scheduled)

**Current position: no rewrite until a trigger fires.** Candidate triggers, in
the spirit of the existing trigger table:

- measured performance pain at mining scale (profiler numbers on 50+-repo runs,
  not vibes);
- Gate A/B of [incremental-computation.md](incremental-computation.md)
  (interprocedural whole-program inference, or live in-IDE feedback);
- the imperative rule code becomes unmanageable (>30–50 interdependent rules —
  the existing Datalog threshold).

**If a trigger fires, the target language is an open decision, not a default.**
Both candidates must be argued in a P-NNN proposal before any code:

- **C# core.** The strongest *packaging* case: extractor + core become one
  self-contained `dotnet tool` / Roslyn analyzer; the two-runtime install
  (.NET SDK **and** Python 3.11+) — which is exactly alpha-readiness gap A —
  disappears; the in-IDE story unblocks (`docs/howto-visual-studio.md:7-13`
  documents that the Python core is *why* there is no Roslyn analyzer today:
  an in-process analyzer would be a second checker). Multi-stack neutrality is
  **not** an argument against C#: neutrality lives in the OwnIR JSON seam, not
  in the core's implementation language (the OwnTS frontend is itself Python
  today; CodeQL's engine language is invisible to its users).
- **Rust core.** The case: Ascent/Soufflé (already the named Datalog
  candidates) and Salsa (the named IDE-incrementality candidate) are
  Rust-native; a single static binary distributes without any runtime; the
  domain (borrow checking) has its reference implementations there. The cost:
  a third language in the repo, and none of the packaging gaps close (the
  extractor stays C#, users still install two things).

**Non-negotiable guardrail either way** (from incremental-computation.md): the
new core is an *optimization, never a new decider* — it must produce
bit-identical verdicts to the Python core over the full corpus, proven by
differential testing, or "one checker" is broken.

**What is actually rewrite-durable** (the oracle a port would be built
against): `spec/` + `tests/test_spec.py` conformance, the two-layer corpus
(`corpus/` + `scripts/benchmark.py` recall/specificity over real C#), the
differential codegen fuzzer, and end-to-end golden runs (sample `.cs` →
expected diagnostics). **Not** the OwnIR fact schema — it is at version 0,
churning weekly, and would be redrawn at any seam re-cut (§3). Sharpening the
durable set is ordinary test hygiene and is already mostly built.

## 2. OwnIR: formalize, do not replace

Investigated and settled: OwnIR is a *data schema for facts at rest*, not a
language. Config/scripting languages (Starlark, Lua, CUE, Dhall) solve a
different problem (executing logic to produce data); MLIR/LLVM are
instruction-level compiler frameworks (massive cost, wrong abstraction, no
fact-interchange precedent); SCIP/LSIF are code-navigation formats; SARIF is
for *results* (already used correctly on the output side); Joern's CPG is the
closest adoptable format but demands a whole-program graph — a frontend-scale
rewrite for no analysis gain. The facts-seam we have is the industry-standard
shape: CodeQL TRAP files, Doop/Soufflé `.facts`, Polonius input relations,
Glean's versioned JSON facts, Infer's Textual `.sil`. Datalog *relations*
become the right vocabulary only if the engine ever moves to a fixpoint/Datalog
core — derivable then as an export from validated OwnIR.

The formalization stack, in order of actual protection delivered:

1. **Fail-loud unknown ops** *(now)*. `_lower_flow`'s `if/elif` chain has no
   `else` — an unknown `op` is silently dropped (`ownlang/ownir.py:1692-1836`),
   and the five structural walkers that hardcode the `if`/`while` recursion
   (`_collect_vars`, `_has_bare_return`, `_call_result_callees`,
   `_param_signals`, `_forward_targets`) share the hole. A newer extractor
   emitting a new compound op under an unbumped version would silently swallow
   nested acquires/releases — fabricated OWN001s and missed leaks while every
   hand-written fixture stays green. Add `else: raise OwnIRError(...)`.
   This single guard is worth more than any schema file.
2. **Golden facts snapshots in CI** *(now)*. Today the extractor→bridge seam is
   pinned only at the rendered-diagnostics level (~174 `grep -q` assertions);
   the `facts.json` itself is `cat`'d, never diffed. CI already has the
   `jq -S` diff machinery and its own rationale for why diagnostics-level
   diffing is insufficient (`ci.yml:1002-1019`) — apply it to the seam: snapshot
   normalized facts for the pinned samples, and feed the same goldens to
   `test_ownir.py` so the Python suite also consumes *extractor-produced*
   facts, not only hand-written ones.
3. **`spec/OwnIR.md` + `spec/ownir.schema.json`** (JSON Schema draft 2020-12,
   `ownir_version` as a `const`) *(now/short)*. Validate all
   `tests/fixtures/ownir/*.json` and the extractor's CI output against it.
   Note: the schema must encode the *deliberate* open points — unknown
   resource kinds coerce to `subscription` by documented design
   (`ownir.py:66-70`), so the resource-kind enum is open, and the schema's job
   is shape/type/enum guarantees, not vocabulary closure.
4. **A written evolution policy** *(now, one paragraph in the spec)*: additive
   optional fields do not bump `OWNIR_VERSION`; a **new op or changed op
   semantics does**. Today's policy only covers the first half, which is
   exactly the gap item 1 exploits.
5. Version single-sourcing across the three producers (`ownir.py:159`,
   `Program.cs:4360`, `ownts.py:580`) *(with next touch)* — worth doing, but
   understand what it does not protect: the dangerous case is *nobody* bumping,
   which only items 1–4 catch.
6. Reconcile or explicitly document the BCL fresh-factory asymmetry *(now,
   small)*: the extractor's `IsOwningFactory` knows the ADO.NET family
   (`ExecuteReader`/`CreateCommand`/`BeginTransaction`,
   `Program.cs:2545-2568`) and crypto `Create*` statics; the bridge's
   `_BCL_FRESH_BY_NS` (`ownir.py:1179-1199`) lists neither, despite "kept in
   lockstep" comments on both sides. Precision-safe today (the Python table is
   only consulted for first-party `call` ops), but the lockstep is
   comment-enforced and has already quietly diverged.

Later, if a Rust/C# core materializes: generate types from the same schema
(serde via typify / System.Text.Json source-gen). Protobuf/FlatBuffers only if
fact volume ever makes JSON parse time measurable — no evidence today.

## 3. The extractor↔bridge "mirror" (LowerFlowStmt / _lower_flow)

Settled by code reading: **this is not duplicated logic and does not have to be
removed.** The two sides are producer and consumer of one flow-op vocabulary —
C# lowers syntax→facts (throw-edge injection, `using`/`switch`/`do`
desugaring exist *only* there), Python lowers facts→core AST (handle minting,
MOS inference, hoisting exist *only* there). The genuine double-encodings are
three enumerable spots: the BCL fresh-factory tables (§2.6), the
`kind:"pool"` tag, and the op-vocabulary structure re-walked by the five
Python walkers (§2.1).

- **Now:** pin the contract mechanically instead of by comment — §2.1 + §2.2 +
  §2.3 cover it (~1–2 days total).
- **On trigger (P-017 multi-stack becomes real, or a core rewrite fires):**
  re-cut the seam so the *core* owns control-flow desugaring (structured
  `try`/`using`/`switch` ops with `may_throw` annotations on leaves) and the
  ~900 lines of contract inference that today live in the bridge
  (`solve`, `_infer_return_skeleton`, `_infer_param_effect`, hoisting).
  Otherwise every new frontend reimplements the exception-edge machinery per
  language. **What must stay frontend-side regardless:** everything that needs
  the `SemanticModel` — pool/factory/adopt classification, may-throw
  reasoning, escape shapes. "Dumb frontend, all semantics in core" is not
  achievable and is not the goal; the goal is *one* implementation of path
  enumeration and ownership inference.
- **Before any core rewrite (hard prerequisite):** the bridge's inference
  layer is verdict-determining and has **no normative description** — it is
  outside `spec/`, outside the schema, and pinned only by examples in
  `test_ownir.py`. Either spec it (consume/borrow/fresh/alias/overwrite rules)
  or relocate it into `ownlang/` proper first, so "the core" is coextensive
  with "what must be ported." Discovering this mid-port is the expensive
  surprise this register exists to prevent.

## 4. Register

### Now (standalone value; days-scale; ordered by protection-per-effort)

| # | Item | Where | Why now |
|---|------|-------|---------|
| N1 | `else: raise` on unknown flow ops (+ the five walkers) | `ownlang/ownir.py:1692-1836` | Silent fact-swallowing → fabricated/missed verdicts (§2.1) |
| N2 | Auto-discovery in the test runner | `tests/run_tests.py:1144-1149` | 25-term hand-rolled `or`; a forgotten `rc` silently stops gating |
| N3 | Golden facts snapshots in CI + feed to `test_ownir.py` | `ci.yml` wpf-extractor job | The seam is never diffed at the facts level (§2.2) |
| N4 | `spec/OwnIR.md` + JSON Schema + evolution policy | new; `ownir.py:1-97` is the source | §2.3–2.4 |
| N5 | DI001–005 + EFF001 into `spec/` + `Diagnostics.md` + `test_spec.py` | `ownlang/di.py`, `effects.py` | Second-largest analyzer has zero normative governance |
| N6 | Diagnostic `Code` enum (replace bare string literals) | `ownlang/diagnostics.py:243` + emit sites | New codes land weekly; a typo'd code silently renders `""` |
| N7 | Split `ownir.py` → `ownir/{render,load,lower,inference,check}` | `ownlang/ownir.py` (2430 lines) | Fastest-accreting file in the repo; `check_facts` grows a branch per resource kind; deferring = paying the god-file tax on every feature |
| N8 | Dedicated syntax-error code (stop filing `ParseError` as OWN020) | `ownlang/__main__.py:80` | Miscategorized as "unsupported construct" |
| N9 | Bare `assert` on the loan invariant → raise | `ownlang/analysis.py:200-203` | Stripped under `python -O`; silent wrong answer if block-scoping is ever relaxed |
| N10 | Reconcile/document BCL table asymmetry | `Program.cs:2545-2568` vs `ownir.py:1179-1199` | Lockstep already quietly diverged (§2.6) |

### With next touch

| Item | Do it when |
|------|-----------|
| `di.py`: one parameterized graph walk instead of five copies; `kw_only=True` on `Service` | next DI feature (DI006+ or P-006 open questions) |
| `buffers.branches()` / `codegen._buffer_lowering` single mode→backend table | next buffer/codegen work |
| `emit_*` template placeholder validation; drop the `or 'cond'` literal | next codegen work |
| Version literal single-sourcing across three producers | next OwnIR-schema-touching PR (per consolidation note: fold with the `subscriptions→resources` rename) |
| Move the 900-line wpf-extractor grep job into a Python golden test | next time it breaks on a message rewording (it will) |
| CI: composite action for the 3× duplicated framework-refs block; remove dev-branch push sentinels | next workflow edit |

### On trigger (parked; the trigger pulls it, not aesthetics)

| Item | Trigger | Candidate |
|------|---------|-----------|
| Core rewrite (language decision per §1) | profiler numbers at mining scale, Gate A/B, or the >30–50-rule threshold | C# (packaging case) vs Rust (Ascent/Salsa case) — P-NNN required |
| Seam re-cut: control-flow desugaring + bridge inference → core | P-017 goes real, or the rewrite fires | §3 |
| `cfg.py` three-pass split (resolver / typecheck / lowering); `Symbol` freeze; typed `check_module` | `cfg.py` starts churning again, or the rewrite fires | low churn today; contained blast radius |
| `Program.cs` decomposition by concern | merge pain (already recorded in consolidation-and-positioning.md) | EventSubscriptions / DisposableFields / ArrayPool / DiGraph / FlowLowering / ProjectResolution / Cli |
| Datalog core | existing trigger-table row | Ascent / Soufflé |
| Incrementality | Gate B (IDE) | Salsa |
| Protobuf/FlatBuffers for OwnIR | measured JSON parse cost | typify/schemars codegen path first |

### Rejected (on the record)

- **Replace OwnIR with an existing language/format** — Starlark/CUE/Dhall
  (config/scripting, wrong domain), MLIR/LLVM (instruction-level, massive
  cost), SCIP/LSIF (code navigation), CPG/Joern (whole-program graph for no
  analysis gain). The facts-seam shape is already the industry standard (§2).
- **Lowering fully in the extractor** — the "second checker" the charter
  forbids (`ownir.py:5-7`, ROADMAP "One checker").
- **Runtime `released?` flags in codegen** — already rejected in README; if we
  don't trust the static result we don't ship it.

## 5. What changed vs the July review's sequencing

The review's recommendation list keyed several items to "during the rewrite."
This register corrects that: with no rewrite on the record, "during the
rewrite" resolves to "never" for the highest-churn surfaces. The `ownir.py`
split (N7) and the `Code` enum (N6) move to **now**; `cfg.py`/`Symbol`/
`check_module` stay parked (genuinely low churn). The OwnIR formalization is
re-scoped from "schema + version single-sourcing" to the protection stack in
§2 (fail-loud ops first, schema third, version constant last).
