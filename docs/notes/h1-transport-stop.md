# H1 — harmless calls in a protocol region: STOPPED at the transport

Status: **RESOLVED.** The owner approved OwnIR v2 and T0 Amendment 2 for H1; H1
landed as [`h1-proven-call.md`](h1-proven-call.md). Kept as the record of why the
version had to move. (Original status: STOP: needs an owner ruling.)
Base: `main` = `1c70e867eb408d931ae3dfffd8c0b351190f6547`, the H0 landing point
([`heap-effect-summaries.md`](heap-effect-summaries.md)).

H1 would let a provably harmless direct source call stand inside a
`[ProtocolRegion]` instead of being refused. The kill-first question was whether
a fail-loud transport for that decision exists inside the current contracts.
**It does not.** The only compliant transport bumps `OWNIR_VERSION`, and a bump
moves the frozen T0 harness identity, which only an owner amendment may do.

## 1. Why the decision needs a must-understand transport

- `ProtocolLowering` refuses in the extractor, before any fact exists.
- The H0 summary is solved in the core.
- The frontend may not solve summaries (IR6, and the rule that frontends emit facts only).

So the facts must carry an **obligation**: "this call is admitted only if the core proves `Harmless(...)`". A core that does not understand the obligation must not read it as clean.

## 2. Every fail-loud mechanism in OwnIR v1 is a version bump

| Candidate transport | Old core (v1) reads it as | Verdict |
|---|---|---|
| Optional field on `call` (`requires: harmless`) | a call to an extern with no tracked argument, i.e. **nothing**, i.e. clean | **fail-open**: rejected |
| Omit the admitted call from facts and put the obligation in a separate file or section | a valid v1 document without the call, i.e. clean | **fail-open**: rejected |
| Extractor calls the core solver before writing facts | n/a | frontend depends on and decides with the core at runtime: an architectural decision no spec makes; **STOP** condition |
| New flow op without a bump | `OwnIRError` (IR4: unknown op) | fail-loud, but violates IR3 ("add a flow op ⇒ bump"); a contract violation is not a transport |
| New resource kind without a bump | `OwnIRError` at load | same: IR3 requires a bump |
| **New flow op + `OWNIR_VERSION` 1 → 2** | `OwnIRError` twice: IR1 (version) and IR4 (op) | **the only compliant fail-loud transport** |

This is by design, not an accident: in OwnIR, "an old core fails loud" and "the vocabulary changed" are the same event (spec/OwnIR.md §2, IR1–IR4). No mandatory-capability or feature-gating mechanism exists. `fix_candidates_version` and the H0 `heap_effects_version` are additive and are ignored by the core.

## 3. Why the bump is not this change's to make

`scripts/perf_baseline.py`'s `facts` calibration generator stamps `"ownir_version": 1`. Under a v2 core:

1. **The literal must move,** or `perf-calibration-facts-current` goes red: the generator would write facts both engines refuse. This is exactly the defect Amendment 1 found.
2. **Moving it moves the T0 harness identity** (`measurement_harness_digest`, currently `1a26aa63fd5f…`), because `perf_baseline.py` is in the harness source set.
3. **The P-022 merge gate** (`scripts/step7/mergegate.py`, `p022-merge-gate.yml`) recomputes the live digest of the merged commit and requires it to equal the one T0-1 names, so the PR cannot merge green.
4. **T0 rules it out unilaterally.** "the next move is a new amendment or it is a defect" (`p022-263-t0-protocol-freeze.md`, Amendment 1). The owner also "ruled out a compatibility shim on either side", so a v2 core that still accepts v1 is not an option either.

The P-022 freeze on verdict-changing inference itself is **not** the blocker: it lifted at the Stage 3 cutover (`P-022-rust-core-migration.md`, "With the cutover complete the P-022 feature freeze on verdict-changing inference lifts"). The blocker is the T0 harness binding that a version bump drags along.

**Precedent:** Amendment 1 is this exact situation (0 → 1 for `borrow_mut`/`move`), and the owner resolved it with one literal plus a re-binding of steps 4, 5 and 6.

## 4. What the owner is asked to rule

**Amendment 2: `OWNIR_VERSION` 1 → 2 for the `proven_call` op.** Mirroring Amendment 1:

| Item | What moves |
|---|---|
| Instrument | one literal in `perf_baseline.py`'s `facts` generator, `1` → `2`; nothing else in the harness source set |
| Re-bound | T0 steps 4, 5, 6 (with `design_constants_blob_sha1`), to the new harness identity |
| Re-run | the instrumentation controls Amendment 1 re-ran |
| Unchanged | rules, budgets, populations, statistic, roll-ups, host predicate, retry budget |
| Not rewritten | committed evidence of past runs |

**Mechanical churn of the bump itself:** three producer stamps (`ownlang/ownir.py`, `own-ir/src/lib.rs`, `Program.cs`) and 244 committed JSON fixtures carrying `"ownir_version": 1`:

| Fixture family | Files |
|---|---:|
| summaries | 82 |
| lowered | 64 |
| verdicts | 38 |
| ownir | 22 |
| repro | 19 |
| verdict_renders | 9 |
| cli_ownir | 4 |
| `corpus/ownership-lab/h29` | 4 |
| others | 2 |

All of them are regenerated by their own `--write` tooling, never by hand.

## 5. H1 as it would be built once ruled (design, ready)

- **Extractor (`ProtocolLowering`).** Only one site changes: an invocation inside a region that touches no entity and no token. Today it reaches `OpaqueCode` and is refused.
  - If its dispatch is `direct`, decided by the **same classifier H0 uses** (shared, not copied), it lowers to `{"op": "proven_call", "site": <id>, "line": n}`.
  - Every other call is refused exactly as today, with the same text: extern, virtual, delegate, local function, constructors, getters, operators.
  - An entity-touching call keeps today's `use` + core verdict.
- **Site evidence.** Each site is a synthetic H0 record walked by the H0 producer over the call expression alone. Outer variables (the enclosing method's locals and parameters, the token) read as `heap`, so any mutation through them is a heap write, never silence.
- **Section.** The facts carry a `heap_effects` section (H0 vocabulary v1): the site records plus the records reachable from them by `direct` edges. Selecting the records is closure only, not solving; a missing record solves to Unknown.
- **Core (Python reference + Rust port, byte-parity).**
  - The section is required whenever a `proven_call` exists. Its absence, a missing site record, or a malformed section is an `OwnIRError` (refusal, exit 2).
  - The H0 solver solves the section. Each site is admitted iff its solved summary satisfies the predicate below; otherwise `OwnIRError` naming the site.
  - An admitted `proven_call` lowers to nothing: it touches no tracked resource.
- **Predicate v1 (strict)** on the site summary, and so transitively on the callee:
  - no Unknown anywhere;
  - every parameter and the receiver at most `borrow`;
  - `writes.instance`, `writes.static` and `writes.indirect` all `none`;
  - `returns` is `[]` (inert, or no alias to a parameter, the receiver or the heap).
- **Negative controls.**
  - A v1 core on v2 facts gives `OwnIRError`, on both engines.
  - A v2 core with the section removed gives `OwnIRError`.
  - A v2 core with a site record removed gives `OwnIRError`.
  - A mutant that reads Unknown as harmless must turn the suite red.
  - Python and Rust refusal texts are identical.
- **Kill fixtures.**
  - `Twice` is admitted.
  - `Mutates(order)` and `Escapes(order)` touch the entity, so they keep `use` + verdict.
  - `TouchesGlobalState()`: refusal (static write).
  - `Console.WriteLine`: refusal in the extractor, unchanged text.
  - A → B pure: admitted. A → B mutating, escaping or global: refusal.
  - A pure SCC is admitted; an SCC with mutation, escape or Unknown is refused as a whole.
- **Regression.** Protocol documents without a harmless call change only their version stamp. Their verdicts are unchanged on both CLIs.
