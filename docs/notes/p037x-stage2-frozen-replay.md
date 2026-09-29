# P-037-X Stage 2 — the frozen P-037 replayed unchanged on canonical calls (EXPLORATORY)

> Status: **EXPLORATORY research record, research branch `research/p037-max-v1` only.**
> Track: P-037-X / P037-MAX. Protocol frozen before this code in Own.NET-paperwork
> `paper-eval/prereg/p037-max-v1.json` (commit `69adf01`). This is **not** a production
> migration and **not** a reopen of #304 (the 2026-09-28 freeze ruling stands unchanged).
> The phase-C edge `own-bridge → own-guarded` that #304's B1 lock forbids on `main` exists
> here as the experiment, behind `OWEN_P037X_GUARDED=1`; the default lowering is
> byte-identical to Stage 1. Never merged to `main`.
>
> Base: Stage 1's last commit `9e2d11c`. Stage commit: the one carrying this note.
> Evidence: Own.NET-paperwork `paper-eval/p037-max/stage2-frozen-replay-v1.json`.

## 1. Question

RQ-X2: does the frozen P-037 vocabulary — one elected guard per coordinate, positive/negative
cells over the existing transfer domain, the five edge transforms, the existing collapse, the
two consume routes — recover the historical cases once the carrier is honest? Stage-2 success
is a measurement, not "B1 green": every ON/OFF movement must fall into the three P-037 classes
(APPLICATION_REFINEMENT, SUMMARY_REFINEMENT, LEGACY_HONESTY) or be explained as a carrier
effect; UNEXPLAINED must be 0.

## 2. What was built (REPOSITORY FACT)

- `rust/crates/own-guarded` — P-037 B1's shadow driver at `92cedb7`, ported into the workspace:
  `src/facts.rs`, `src/solve.rs`, `tests/acceptance.rs` and the fixtures are **byte-identical** to
  B1; `src/lib.rs` is B1 verbatim plus a seam section (`GuardedDoc::solve`, `collapsed`,
  `apply_at`). Every lattice operation, election, edge transform, finalization and call-site
  application is `formal/p037-kernel`'s; this crate defines none. The acceptance tests pass
  unchanged (`a15_b0_probe_outcomes`, `k7_witness_on_the_adapter`, `a13_only_finalized_cells_cross_sccs`,
  `record_absence_boundary`, `wf_edge_without_a_coordinate`, `a12_bound_failure_is_no_evidence`,
  `a2_a5_edges_and_selection`, `n4_required_read_contradictory_sidecar`,
  `a14_report_is_static_dispatch_conditional`, `g13_classifiers_never_bucket`).
- `rust/crates/own-bridge/src/lower.rs` — the seam, behind `OWEN_P037X_GUARDED=1`: the kernel's
  solution is an **overlay** on the legacy MOS (a coordinate with guarded evidence contributes its
  finalized collapse — the value INF-A1 lowers where no site selects; every other coordinate keeps
  its legacy value, so absence is never read as a value), and G-A1 site selection (`contract_at`)
  is consulted wherever a call's per-argument transfer is read: the channel lowering, the
  unverified-transfer advisories, the kill sites. A `true`/object-creation argument at the callee's
  elected guard ordinal selects the positive cell, `false`/`null` the negative, anything else
  applies the collapse. With the flag off nothing runs and the lowering is byte-identical.
- `rust/crates/own-shadow/src/bin/own-guarded-report.rs` — B1's R-1 report entry point (stdin facts,
  stdout the `p037-guarded-shadow/1` report against the legacy MOS dump), run with the flag off.
- `rust/crates/own-diagnostics/tests/dag.rs` — `own-guarded → own-ir` only; `own-bridge` and
  `own-shadow` its only consumers; `p037-kernel` named by `own-guarded` only; every core crate
  ignorant (`p037x_guarded_seam_is_the_only_kernel_path`). The `main` lock that forbids
  `own-bridge → own-guarded` is deliberately **not** ported: on the research branch that edge *is*
  the experiment, and this test must never be merged as a relaxation of the lock.
- The Python reference is untouched; cross-engine parity is claimed with the flag off only.

## 3. Results (MEASURED OBSERVATION)

46 documents (the 45 of Stage 1 plus the B1 acceptance fixture), each run three ways: Rust with the
flag off, Rust with the flag on, Python. **Flag off == Python byte for byte on 46/46**, and
flag off == the Stage-1 Rust output on 45/45 (after normalizing the facts path in the header line).

| group | expectation (frozen) | measured with the flag on | held |
|---|---|---|---|
| F3 pairs S1–S4 before | OWN001 at the acquire (the `no` cell is selected: the obligation stays with the caller) | OWN001 ×1 each, OWN051 gone | 4/4 |
| F3 pairs S1–S4 after | clean, no advisory (the `must` cell is selected) | clean | 4/4 |
| B1 36 comparable coordinates | class EQUAL on 36/36 | EQUAL 36/36 (cells as B1 recorded them) | yes |
| XB-1 GuardFalse / XB-2 GuardTrue / XB-3 EarlyReturnKept | clean | clean (neg→borrow; pos→consume; pos of `Split(keep, no, must)`→borrow) | 3/3 |
| XB-4 GuardedForwardFalse | clean | **OWN051 stays**: `MaybeForward → Close` is NO_GUARDED_EVIDENCE `via:missing_sidecar` (§4) | no |
| XB-5 / XB-6 definite handoffs | OWN002 unchanged | OWN002 — through the seam's legacy fallback (`Close`, `CloseInFinally` have no sidecar), not through `Uncond(must)` | 2/2 (mechanism differs) |
| XB-7 BorrowingWrapper.borrowed | `no` | `Uncond(no)`, SUMMARY_REFINEMENT | yes |
| XB-8 ForwardDynamic.forwarded | `Split(dispose, must, no)` through the id edge, collapse `may` unselected | `split(1)` `[must, no]`, EQUAL, unselected site `plain` | yes |
| XB-9 / XB-10 gallery 07 | OWN002 / silent | OWN002 / silent | 2/2 |
| XD-1…XD-4 conformance controls | no findings beyond OWN051; never consume, never OWN003 | OWN051 only on all four; the hostile guards are `Uncond(may)` or NGE | 4/4 |
| XD-5…XD-9 shape controls, A2.2 controls, B0 probes | OWN051 only / unchanged / NGE at the record boundary | as expected (B0 probes: exactly B0's §E.6 outcomes) | yes |
| shapes on main / A2.2 shapes | (no per-shape Stage-2 expectation; fact census) | 4 shapes move OWN051 → OWN001, 1 → clean, `arg-raw-facts` 3×OWN051 → clean; every move an APPLICATION_REFINEMENT whose verdict is the fixture's real semantics (`Inner(r, true)` under `if (!keep) s.Dispose()` keeps the resource and the caller never disposes it) | — |
| six real cases | see §4 | no verdict moved; summaries: case 3 `CreateModule = Split(1)[no, must]` EQUAL; cases 1, 2, 4, 5, 6 NGE for driver reasons (§4) | XC-1/3/5 as predicted; XC-2/4/6 not recovered |
| 137-file corpus, flag on vs off | movement classified into the three classes; UNEXPLAINED 0 | 8 documents moved — exactly the F3 files — all APPLICATION_REFINEMENT; class totals summary EQUAL 14 / NGE 26, application APPLICATION_REFINEMENT 8 / EQUAL 6 / NGE 60; **UNEXPLAINED 0** | yes |

What became green **merely because the carrier was fixed** (explicit list, as the protocol requires):
the 8 B1 UNEXPLAINED coordinates (EQUAL because Stage 1 moved their legacy side to `may`), the caller
records that returned at Stage 1, and XB-5/XB-6 (the core derived `must` from the canonical call at
Stage 1; the kernel adds nothing there today). What is green **because a cell was selected**: the eight
F3 verdicts, XB-1/2/3, XB-7, and the shape/raw-arg refinements above.

## 4. Where the frozen replay stops, and why it is the driver (MEASURED + INFERENCE)

Every NO_GUARDED_EVIDENCE that blocked a frozen expectation is a property of the B1 **driver** (how it
decodes facts and identifies coordinates), not of the vocabulary:

1. **A straight-line leaf has no sidecar.** A2.1 emits `guarded_facts` only for a method with a
   relevant call or an eligible guard; `Close(Stream s) { s.Dispose(); }` carries a record but no
   sidecar, and the driver fails closed (`missing_sidecar`; its own acceptance test pins
   `Leaf → missing_sidecar`, `ToLeaf → via:missing_sidecar`). XB-4's `MaybeForward = Split(forward,
   must, no)` is expressible by the kernel and blocked by this boundary.
2. **Coordinates are keyed by name.** Two overloads (`VerifyPersistedKey`, `SavePNG/SaveJPEG/SaveGIF`)
   answer `overloaded`, although every record carries `sig`.
3. **The ordinal map is an allowlist (A17).** A params-list index maps to a declared ordinal only when
   every other declared type is in a fixed non-disposable list; `Func<…>`, `TcpListener`,
   `TextWriter`… are not, so cases 2, 4, 5, 6 answer `ordinal_map` / `caller_ordinal_map`.
4. **Election is per function.** Two eligible guards in one function answer `multi_guard`
   (`FinishSend`: `responseContentTelemetryStarted` governs telemetry, `disposeCts` governs
   `cts.Dispose()`), whereas G-S1 seeds the election **per coordinate** from the guards lexically
   governing an action on that parameter ("zero literals seed None"), under which `cts` elects
   `One(disposeCts)` and `response` elects `None`.

Leaving these in place would report the driver as the ceiling. They are removed in a pre-registered
sub-stage (2b, `paper-eval/p037-max/stage2b-prereg-v1.json`: expectations frozen before the code),
reading only present facts — body ops, `sig`, a declared-ordinal fact, G-S1's own seed rule — with a
hostile control for each, so that the vocabulary's own limit shows. Nothing in this record is re-expected.

## 5. Result

**Stage 2: KEEP.** The frozen vocabulary, replayed unchanged, buys real capability — the bug/safe twins
are distinguished on every historical pair and on real fixture semantics, the controls never consume —
at the cost of one ported crate and a ~120-line opt-in seam; zero new guard forms, transforms, lattice
or transfer values; UNEXPLAINED 0 on the corpus; the default path byte-identical. The wording the protocol
requires: *P-037-X later recovered 8/8 F3 pairs and 36/36 B1 coordinates on the canonical carrier after
exploratory extensions.* It is not a claim that #304 is reopened or that the historical #373 FAIL was wrong.
