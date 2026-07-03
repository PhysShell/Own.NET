# P-022 review notes — Rust core migration + the IDE-extension trigger

> Status: **review notes** (follow-up to
> [architecture-review-2026-07.md](architecture-review-2026-07.md) and
> [tech-debt-register.md](tech-debt-register.md)). Reviewed: P-022 as merged in
> PR #166 (`docs/proposals/P-022-rust-core-migration.md`) and
> [strictness-and-fitness.md](strictness-and-fitness.md).

## Verdict

P-022 as merged is a strong proposal: the differential oracle as the spine
(exit/crash gate before any output diff; the explicit "do not reuse
`oracle_compare.py` as the parity oracle" fence; OWN050 pinned to the SARIF
seam; "CFG JSON seam is work to build, not an existing contract"),
strangler-fig bottom-up ordering, the `Diagnostic`-is-data-not-`Err` rule, and
the persistent-vs-arena question left open with a concrete bench protocol
(largest real corpus function, wall-clock **and** RSS). The perf principles
match the external playbook and the ruff/rustc precedent. The findings below
are ordered by cost-of-late-discovery.

## 1. The OwnIR *bridge* is missing from the crate topology (highest cost)

The crate map covers syntax → cfg → analysis / codegen / diagnostics / cli,
but ~900 lines of **verdict-determining** logic in today's `ownir.py` have no
named home: facts→core-AST lowering (`_lower_flow`, handle minting, localmap
kill-on-rebind), the interprocedural MOS solver (`_build_skeletons`, `solve`,
`_infer_return_skeleton`, `_infer_param_effect`), branch-local hoisting, the
BCL fresh-factory table, and `check_facts`' verdict mapping. `own-ir` is
declared "fact types + serde, dependency-light" — correct, and therefore this
logic cannot live there; `own-analysis` is the lattice/worklist — not this
either. The migration steps (§ strangler-fig) port parser, cfg, analysis,
diagnostics, codegen, cli — the bridge is never named as a port step, yet
without it the flagship path (real C# → facts → verdicts) has no Rust
implementation.

**Fix:** add an `own-bridge` (or `own-ir-lower`) crate to the DAG
(`own-ir + own-cfg → own-bridge → own-analysis` consumers), a migration step
for it (between analysis and cli), and — per the tech-debt register — write
the normative description of the inference semantics
(consume/borrow/fresh/alias/overwrite rules) *before* porting, since today it
is pinned only by `test_ownir.py` examples. Discovering this mid-port is the
expensive surprise; the OwnIR fixtures in the oracle corpus would catch the
*behavior* but not tell anyone *where the code goes*.

## 2. The IDE goal is the missing "Why" — and it changes two design points

P-022's motivation is the maintenance tax; under the repo's own trigger
discipline (`AGENTS.execution-surfaces.md` §7–8: profiler numbers or real
pain) that is the weakest possible justification. The actual trigger now on
the table — **an IDE extension** — is Gate B of
[incremental-computation.md](incremental-computation.md), i.e. a *recorded,
legitimate* trigger. Writing it into P-022's Why both squares the proposal
with the house rules and reorders the perf priorities: an IDE cares about
**keystroke latency and incrementality**, not batch throughput — which is
exactly where Rust+salsa beats "fast Python" by construction, and where the
10–100× batch numbers are the wrong metric.

Two concrete design consequences:

- **`panic = "abort"` must be per-binary, not doctrine.** Fine for `own-cli`;
  fatal for a long-lived LSP server, where one panic in one file's analysis
  takes down the whole session — and salsa's *cancellation is implemented via
  unwinding*, so an LSP binary needs `panic = "unwind"` + catch at the request
  boundary (rust-analyzer's model). Record it now so "abort in release"
  doesn't get baked into the workspace profile.
- **Error-tolerant parsing gets promoted** from nice-to-have to requirement:
  an IDE analyzes broken code on every keystroke. This strengthens the
  existing "hand-roll the parser" lean (rust-analyzer precedent) beyond the
  error-message-parity argument.

**Architecture reality-check for the IDE scenario.** For the flagship use
case (real C# in the editor), the latency chain is keystroke → Roslyn
semantic model (in-process in the IDE, already incremental) → fact extraction
→ core verdicts. The Rust core is the *cheap* half of that chain; the
extraction must run in-process on the .NET side regardless. So the realistic
extension shape is hybrid: the VS/VS Code extension hosts the (existing C#)
extraction and talks to the Rust core over the OwnIR seam (stdio or FFI) —
which is exactly the seam P-022 already freezes. Rust removes the Python
runtime from the distribution (alpha-readiness gap A closes); it does not
remove the .NET half, and no one should expect it to. For `.own` files a pure
Rust LSP is trivial and a good first slice.

## 3. `indexing_slicing = "deny"` collides with the core data structure

The perf doctrine's centerpiece is a dense `Vec<VarStates>` indexed by RID
(and flat backing arrays everywhere); the strictness block denies `v[i]`
(`indexing_slicing`), denies `unwrap_used`, and the hot path cannot afford
`.get().expect(...)` noise either. Left unresolved, the first hot loop starts
the suppress-without-looking reflex the ratchet doctrine explicitly warns
against. **Resolution to record:** arena/newtype-index access
(`la-arena`-style `arena[idx]` where the ID was minted by that arena) is
panic-free by construction — allow indexing there via a *justified,
module-scoped* `#[allow(clippy::indexing_slicing)]` on the state container,
keep the deny everywhere else. Decide it in the proposal, not in the first
PR's review thread.

## 4. Residuals from the external review of the pre-merge draft

The pasted external critique's blocker — the `own-diagnostics` arrow vs
fitness-function conflict — is **already fixed on main** (commit `60b45f9`),
and resolved the *opposite* way from the critique's suggestion: the
Diagnostic/Evidence model stays in `own-diagnostics` and `own-analysis`
depends on it. That resolution is sound (arguably better than moving verdicts
into `own-ir`, which stays pure facts). Still-standing residuals, all cheap:

- **Stale label:** the diagram still calls `own-ir` the "fact/**verdict**
  contract" while verdicts now live in `own-diagnostics`. One-word fix,
  prevents the next reader re-importing the ambiguity.
- **Span placement:** `own-diagnostics` "depends only on span/location
  primitives (`own-ir`/`own-syntax`)" — if `Span` lives in `own-syntax`, the
  presentation crate pulls the parser. Put the span type in a leaf (`own-ir`
  or a tiny `own-span`) instead.
- **Positions:** internal representation should be **byte offsets** + one
  line-index per file, line/col only at the output seam (ruff /
  rust-analyzer). Not fixed anywhere in P-022; cheap now, painful later.
- **IDs:** `Rid(u32)` → `Rid(NonZeroU32)` etc., so `Option<Id>` is free
  (niche optimization). Day-1 decision.
- **`[profile.release]` block** (lto = "thin", codegen-units = 1,
  opt-level = 3; panic per §2) is described in prose but absent as TOML.
- **Oracle cost:** don't run the Python core live on every CI pass — commit
  its outputs as golden snapshots keyed by (corpus hash, Python-core commit)
  and diff Rust against the snapshots; regenerate only when Python itself
  changes (which the proposal already treats as the exception). Otherwise CI
  time grows with corpus × Python and the ratchet gets disabled "temporarily".
- **Error-text parity:** extract parser/diagnostic message texts into shared
  fixtures asserted from both sides, or parity rests on copy-paste.
- **Enum-size ritual:** `clippy::large_enum_variant` is already in the
  default warn set (perf group) — the missing piece is the habit: audit
  `size_of::<Expr>()`/`<Instr>()` (assert in a test) whenever IR types change.

## 5. Notes on the performance playbook (the external document)

Direction confirmed; the u8-`bitflags`-over-`fixedbitset` correction, RPO
worklist scheduling, and the serde_json-I/O caveat are all right and already
in the merged P-022. Additions/corrections worth keeping:

- The 10–100× figure is a *batch CLI* number (ruff's). If the CLI on today's
  corpus is not actually CPU-bound, the visible batch win may be modest — the
  IDE latency budget (§2) is where the migration genuinely pays. Set
  expectations accordingly in any public claim.
- `#[cold]` on the diagnostic-construction paths is a good, stable-Rust hint
  (the playbook is right that `likely/unlikely` are unstable).
- `SmallVec` caveat is real; measure before sprinkling. Evidence steps and
  loans-per-owner match the small-N profile, block instruction lists may not.
- Skip the HFT residue (busy-poll, thread-per-core, lock-free) — the playbook
  itself says so; recorded here so it doesn't get cargo-culted later.

## 6. strictness-and-fitness.md

Sound doctrine (ratchet, baseline, justified allows). Two notes: (a)
`import-linter` for `ownlang` is the cheapest immediate win — the Python
import DAG is already clean (verified in the July review), so the contract
would pass on day one and prevent regressions while Python remains the
oracle; (b) ruff `select = ["ALL"]` contradicts the current deliberate
selection in `pyproject.toml` (SIM intentionally omitted because it fights
the commented branch structure) — keep the curated select, or carry the SIM
exclusion into the ALL-based config explicitly.
