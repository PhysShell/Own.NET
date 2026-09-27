# MathComp applicability spike — kill-first protocol and result

> Status: **experiment run; RESULT: GO (bounded), with the MathComp-specific
> share of the value small and not yet separated from plain Rocq (§G).** §C
> was committed (`4f7ee4f`) *before* any `.v` file existed and is unchanged
> except for the appended outcome table §C.7, so the verdict is judged
> against criteria written in advance.
> Research branch only; changes no verdict, no schema, no CI gate, and does
> not touch `formal/p037-kernel/`.
>
> Evidence discipline as in `p037-formal-kernel.md`: `REPOSITORY FACT`,
> `MEASURED OBSERVATION`, `INFERENCE`, `EXTERNAL FACT` (primary source,
> cited with access date), `OWNER RULING`.

## A. Executive result

**GO: a next bounded experiment is justified. This is not "adopt MathComp".**

Evidence:

1. **Stronger than Kani, on the property Kani could not close.** K10 (the
   solver reaches the least fixpoint, and every fair chaotic schedule gives
   the same one) and G-T2a at the lfp (`C(lfp F_G) <= lfp F_C`) are proved
   for **any number of coordinates, any number of edges per coordinate, and
   any fair schedule with repeats**. Kani checks K10c and K11 only at 2
   coordinates with at most 1 edge, and the A0 note (§2) fills the rest with
   "the standard argument". The proofs also show that the `n·HEIGHT + 1`
   pass bound suffices for every `n`; `n·HEIGHT` alone does not prove (mutant R7) (§E). Every headline
   theorem is "Closed under the global context".
2. **The seam is checked, not transcribed.** Every finite operation (`join`,
   `fin`, `lower`, `collapse`, `contribute ∘ read`, `apply`: 5 to 375 rows
   each) equals the Rust kernel's on its whole domain. The rows are exported
   *by the kernel crate itself*. For the structural parts, 300 Rust solver
   traces (the traces of both `sys` and `sys.collapsed()`) are accepted by a
   *proved* certificate checker (`chain_lfp`), so Rust's answers are the
   Rocq model's least fixpoints.
3. **Non-vacuous.** 11 of 11 mutants are rejected (§F). Four of them live in
   the Rust kernel: a law-preserving wrong join, the `neg` swap forgotten,
   `step` dropping its seed, and `collapsed()` keeping masks. On the Rocq side, only the
   seam can see them, and it rejects all four.
4. **Cost is proportionate but above the ~300-LOC target.** 494 code lines
   of `.v` (186 generic solver theory, 246 model + instance, 62 seam) and a
   232-line exporter. The full check takes about 10 s. The toolchain takes
   about 10 min and 1.9 GB to install once.
5. **Small real finding.** `solve_with` on the Rust kernel returns
   `Some(x)` for an `x` that is not a fixpoint when the schedule skips a
   live coordinate. This was reproduced on the kernel. Fairness is a
   *necessary* hypothesis, and the Rocq side has a lemma witnessing that.
   A1 must enforce it (§H).
6. **MathComp-specific value is real but small.** `{ffun}`, `bigop` and
   `eqType` gave axiom-free, decidable finite states and the rank sum. The
   order hierarchy and `[forall]` gave nothing usable, and MathComp's finite
   machinery does not *compute* under `vm_compute`, so the executable seam
   is plain-Rocq style. Rocq value: demonstrated. MathComp versus plain
   Rocq: **not separated by measurement**, and that is the next gate (§I).

Kani remains the right tool for the Rust code itself, because it checks the
real functions without a transposition. This spike adds unbounded theorems
*about the algorithm* and does not replace any harness.

## B. Base

| item | value |
|---|---|
| branch | `claude/mathcomp-ownnet-spike-911fbt` (the session's designated research branch; plays the role of `research/mathcomp-ownnet-spike`) |
| base | `origin/main` at `23e32038231b5ac8398204afb35bafc115bc3bfe` (merge of #363, P-037 A2.1), fetched at the start of the spike |
| platform | Ubuntu 24.04.4, x86_64, 4 cores, 15 GiB RAM (cloud container) |
| Rocq / MathComp | `rocq-core` 9.2.0, `rocq-mathcomp-boot` + `rocq-mathcomp-order` 2.6.0 (tag `mathcomp-2.6.0` = `7cde45afa55ead3410e17081d9ab4bdd53def3e7`), Hierarchy Builder 1.10.3, rocq-elpi 3.5.1 / elpi 3.7.3, OCaml 4.14.2 (opam 2.1.5) |
| install | `opam switch create rocq-spike ocaml-base-compiler.4.14.2`; `opam repo add rocq-released https://rocq-prover.org/opam/released`; `opam install rocq-core.9.2.0 rocq-mathcomp-boot.2.6.0 rocq-mathcomp-order.2.6.0`. MEASURED: rocq-core + elpi + HB 173 s, MathComp boot + order 214 s, the OCaml switch a few minutes more; 1.9 GB. Here GitHub archive tarballs were 403 through the sandbox proxy, so MathComp was pinned from a `git clone` of the tag (`opam pin add -k path`) — an environment artefact, not a packaging problem |
| build / check | `formal/mathcomp-spike/check.sh` (regenerates `RustTables.v`, compiles all, prints the assumption audit): ≈ 10 s wall |
| Rust baseline | `cargo test --release` in `formal/p037-kernel`: 37 passed, 24.5 s (MEASURED here); Kani figures quoted from `p037-formal-kernel.md` §3 (Kani not re-run here) |

### B.1 External facts that shaped the decisions (EXTERNAL FACT, accessed 2026-09-27)

| source | what it confirms |
|---|---|
| [MathComp 2.6.0 release announcement](https://discourse.rocq-prover.org/t/mathcomp-2-6-0-released/3086) (Rocq Discourse, 2026-08-18) | 2.6.0 is compatible with Rocq 9.0 to 9.3+rc1, with opam/nix/docker packages. It adds `ring_tactic`/`field_tactic`, removes `Global Set SsrOldRewriteGoalsOrder`, and renames `fingroup` to `finite-group` and `character` to `group-representation` |
| [Rocq 9.2.0 release](https://rocq-prover.org/releases/9.2.0) / [announcement](https://discourse.rocq-prover.org/t/rocq-9-2-0-released/3013) (2026-03-30) | latest stable Rocq, available on opam (`rocq-core=9.2.0`). The opam `rocq-prover` meta-package was only at 9.0.0 in the repository here (MEASURED), so `rocq-core` is pinned directly |
| [Rocq docs: using opam](https://rocq-prover.org/docs/using-opam) | the `rocq-released` repository URL and `opam install` flow |
| [MathComp CHANGELOG](https://github.com/math-comp/math-comp/blob/master/CHANGELOG.md) / [INSTALL.md](https://github.com/math-comp/math-comp/blob/master/INSTALL.md) | 2.5.0 split `mathcomp-ssreflect` into `mathcomp-boot` and `mathcomp-order` (`preorder.v` + `order.v`); the make-based install needs Hierarchy Builder. `all_boot` is deprecated in 2.6.0 in favour of `boot` (MEASURED: deprecation warning) |
| MathComp 2.6.0 sources (`order/order.v`, `boot/finset.v`, `boot/fintype.v`) | `order.v` has `JoinSemilattice`/`BJoinSemilattice` and the factories `Le_isPOrder`, `POrder_Join_isSemilattice`, `hasBottom`. The product order on `T1 * T2` comes from `DefaultProdOrder`. There is **no** order instance for `{ffun I -> L}` and **no** general fixpoint/Kleene theory; `finset`'s `fixset` covers only `{set T}` |


PR #276 (proof-carrying findings) is unmerged and is **not** a dependency.

## C. Kill-first protocol (written before any proof code)

### C.1 What must be true for this work to be worth anything

- **N1 — strength.** At least one real P-037 invariant gets a machine-checked
  statement that is *strictly more general or stronger* than what
  `cargo test` + Kani already check (§D). A theorem over the same finite,
  bounded domain Kani already covers does **not** count.
- **N2 — no second semantics.** The proof model is tied to the Rust kernel
  by a *checked* seam (something that fails when the two diverge), not by
  "we transcribed it carefully".
- **N3 — trusted base.** The trusted boundary after the spike is stated
  precisely and is not larger than before, except for the prover kernel
  itself (declared).
- **N4 — maintenance.** Proof + model stay small (budget below), build in a
  pinned toolchain with one command, and check in seconds, not minutes.
- **N5 — a path to value.** There is a concrete answer to "what can Own.NET
  now guarantee that it could not before": a reusable theorem, a checked
  law, a stronger oracle, or a spec bug found. "A green `.v`" is not one.

### C.2 Independent necessary conditions and their cheap falsifiers

| # | necessary condition | cheap falsifier (decided in advance) |
|---|---|---|
| G0 | a minimal pinned Rocq + MathComp build is reproducible here | install fails, or needs non-pinned / unpublished packages → **KILL** |
| C1 | modelling `Transfer` (5 constructors) + decidable equality + finite enumeration is cheap | > ~40 lines of infrastructure before the first law is stated → **KILL signal** |
| C2 | the existing join/order laws are cheap to prove | if the laws need bespoke tactics or > ~30 lines → **bad signal** |
| C3 | a theorem stronger than Kani exists and is provable in budget | if the only provable statements enumerate the same finite domain Kani already covers (K1–K9), MathComp adds nothing → **KILL for N1** |
| C4 | the proof talks about the real P-037 definitions | if no checked correspondence to `formal/p037-kernel/src/lib.rs` can be made for the finite operations, and nothing but hand-transcription ties the structural ones → **weak / KILL for N2** |
| C5 | tooling cost stays proportionate | if most of the spike's time goes into package/build plumbing → **KILL** |
| C6 | no frontend needed | if the theorem says nothing useful without formalizing Roslyn/CFG/G-V4 → **KILL for current use** |
| C7 | MathComp-specific value | if the same PoC is as short in plain Rocq, record "MathComp: no demonstrated incremental value" (not a KILL of Rocq) |
| C8 | non-vacuity | if a deliberately broken join / unsafe application / non-monotone split transform still checks → the theorem is vacuous → **KILL** |

### C.3 Hard KILL (stop, no "one more day")

1. no minimal reproducible MathComp build;
2. the micro-model needs a disproportionate bespoke framework;
3. no theorem stronger than repeating an existing Kani exhaustive/symbolic check;
4. the link to production semantics is entirely manual and drift destroys the result;
5. after the first PoC there is no concrete answer to "what does Own.NET get";
6. no visible incremental benefit of MathComp over plain Rocq — this kills
   the *MathComp* hypothesis specifically, not necessarily Rocq.

KILL is a normal, successful outcome of this spike.

### C.4 Budget

Before the first kill gate: no production code, no verdicts, no OwnIR
schema, no blocking CI, no C#, no Roslyn, not all of P-037, no general
verification framework. First meaningful PoC ≈ 100–300 LOC of proof/model;
exceeding it must be justified in §E; ~1500 lines of plumbing is a KILL
signal, not a heroic effort.

### C.5 Which theorem, decided in advance, and why

The existing baseline (§D) already covers every *finite, value-level* law
(K1–K9, K12, K13) exhaustively **and** symbolically. Re-proving those in
Rocq cannot satisfy N1 (falsifier C3), so Candidate A (Transfer laws) is
used only as the cheap toolchain/ergonomics gate (C1/C2).

The **gap** in the baseline is exactly where Kani is bounded and the A0
note itself falls back to paper (REPOSITORY FACT,
`docs/notes/p037-formal-kernel.md` §2–§3, §7):

- K10b (least fixpoint) is checked at 3 coordinates / ≤ 2 edges; K10c
  (chaotic = Jacobi) only at **2 coordinates / ≤ 1 edge**; "order
  independence of the lfp follows from the inductive facts by the standard
  argument" — the unbounded claim is a paper argument;
- K11 (G-T2a lax simulation at the lfp) is checked only at **2 coordinates
  / ≤ 1 edge**; §7 names the unbounded `∀ S: C(lfp F_G(S)) ≤ lfp F_C(C(S))`
  as the A2 prover candidate ("Verus, deferred");
- the solver's pass bound `MAX_COORDS × HEIGHT + 1` is justified in a doc
  comment, not checked for arbitrary `n`.

So the chosen first theorem is **Candidate D combined with the G-T2a
lift**, stated generically and then instantiated on the P-037 definitions:

> for any finite coordinate set of any size, any number of edges per
> coordinate, any monotone step on a join-semilattice with a bounded strict
> rank: Jacobi iteration from `⊥` reaches the least fixpoint within
> `n·h + 1` passes; every fair chaotic schedule reaches the same fixpoint
> within the same bound; and a one-step lax simulation lifts to the lfps.
> Instantiated: K10 (both solvers) and K11/G-T2a for P-037 systems of
> unbounded size.

Candidate B (product lattice inheritance) falls out as a lemma of the
instance; Candidate C (K6) is re-proved only as the carrier of the
unsafe-application negative control.

### C.6 Drift seam, decided in advance

The finite operations (`join`, `fin`, `collapse`, `read`, `contribute`,
`lower`, `apply`) are total functions over enumerable domains, so they can be
pinned **extensionally**: a small exporter links `p037-kernel` as a path
dependency and prints their full truth tables as a Rocq file; Rocq then
proves that its own definitions equal those tables on the whole domain. The
structural parts (`step`, the solvers) cannot be pinned by a table; they get
differential vectors (Rust solver outputs re-checked by computation in
Rocq) and are otherwise declared hand-transposed.


### C.7 Outcome (appended after the experiment; C.1–C.6 above are unchanged)

| # | necessary condition | observation | result |
|---|---|---|---|
| G0 | reproducible pinned build | Rocq 9.2.0 + MathComp 2.6.0 installed in about 10 min. Everything checks in about 10 s. The only hitch was the sandbox proxy (archive 403), worked around by pinning the tag commit | PASS |
| C1 | cheap `Transfer` + dec. eq + enumeration | 6 lines per enumerated type (bijection with `'I_k` + `Finite.copy`) × 2, `Equality.copy` 4 lines × 3 others. Pitfall: `inord` blocks `vm_compute` (opaque `idP`), so literal `Ordinal`s are needed | PASS (≈ 35 lines of boilerplate across 5 enums) |
| C2 | laws cheap | `tjoinC/A/xx` are one line each by case analysis. Cells inherit them from the base laws in 4 one-liners (Candidate B) | PASS |
| C3 | a theorem stronger than Kani | K10 (Jacobi and fair chaotic), the pass bound and G-T2a at the lfp are proved for unbounded `n`, edges and schedules. Kani: n ≤ 3/2, edges ≤ 2/1 (§D) | PASS |
| C4 | checked correspondence to the Rust kernel | finite ops: exhaustive extensional equality. `step`/`collapsed`: 300 traces checked by the proved `chain_lfp`. Four kernel mutants caught (§F). Residual: structural code is sampled, not proved equal (§E.4) | PASS (with a declared residual) |
| C5 | tooling cost proportionate | a one-time 10-min install. Most time went into proofs, not plumbing. One detour of about 30 min into MathComp computability (below) | PASS |
| C6 | no frontend needed | none needed: the theorems sit entirely on the verified side of the A0 trusted-input boundary, and they need **no** `well_formed` hypothesis | PASS |
| C7 | MathComp-specific value | used: `{ffun}` (axiom-free extensional equality + `eqType` on states, which `jacobi`'s `F x == x` needs), `bigop` (rank sum), `ssrnat`/`seq` lemma library. Not usable: `[forall]`/`card`/`enum`/`{ffun}` under `vm_compute` (locked), and the order hierarchy for states. No plain-Rocq port was measured | **INCONCLUSIVE**, so it becomes the next gate |
| C8 | non-vacuity | 11/11 mutants rejected, plus a proved counterexample for an unfair schedule | PASS |

Hard-KILL rules 1–5: none fired. Rule 6 (no visible MathComp increment) is
**not settled**. There is some increment (§G), but it was not measured
against a plain-Rocq port, so the verdict is GO for Rocq and the MathComp
question is carried into §I instead of being declared answered.

## D. Existing baseline

REPOSITORY FACT (`formal/p037-kernel/src/`), Kani numbers from
`p037-formal-kernel.md` §3. `cargo test` was re-run here: 37 passed, 24.5 s.

| property | Rust model | `cargo test` twin | Kani harness (bound) | what Rocq/MathComp could add | done here |
|---|---|---|---|---|---|
| K1 `Transfer`/`Cells` join laws, partial order | `Transfer::join/leq`, `Cells::join` | exhaustive | `k1_*` (all values) | nothing: the domain is 5 / 25 values | re-proved as the toolchain gate only (C2) |
| K2 `Election` laws | `Election::join` | exhaustive | all values | nothing | no |
| K3 read/mask monotone; read ≤ collapse | `read`, `contribute` | exhaustive | all values | nothing (finite) | used as finite lemmas (by computation) |
| K4 import monotone, not a morphism | `import` | exhaustive | all values | nothing | no |
| K5 collapse monotone + morphism | `Cells::collapse` | exhaustive | all values | nothing | used as a finite lemma |
| K6/K7 G-A2 floor, no fabricated consume | `apply`, `lower` | exhaustive | all values | nothing (finite) | K6 re-proved as the carrier of mutant R3 only |
| K8/K9/K12/K13 | various | exhaustive / pins | all values or small n | nothing | no |
| **K10a** `step` monotone | `System::step` | via K10 | n = 3, ≤ 2 edges, symbolic state | any n, any edge count | **yes** (`step_mono`) |
| **K10b** Jacobi = least fixpoint, terminates | `lfp_jacobi`, `max_passes` | n ≤ 2 exhaustive + 20 000 random n = 3 | n = 3, ≤ 2 edges (300 s) | any n; pass bound `n·h+1` for every n; least **pre**-fixpoint | **yes** (`jacobi_is_lfp`, `k10_jacobi`, `k10_least`) |
| **K10c** chaotic = Jacobi | `lfp_chaotic` | permutations + 1 repeating schedule | **n = 2, ≤ 1 edge**, schedule length 3 (240 s) | any n, any fair schedule of any length | **yes** (`chaotic_is_lfp`, `k10_chaotic`) |
| K10e election pre-solver | `ElectionSystem::step` | exhaustive twins | as K10 | the same generic theorem applies once K4 and a rank are supplied | not instantiated (§I) |
| **K11** G-T2a at the lfp | `System::collapsed` | n ≤ 2 + random | **n = 2, ≤ 1 edge** (73 s) | any n, any edges | **yes** (`gt2a_one_step`, `gt2a_lfp`) |
| K11b G-T2b vs today | `System::today` | n ≤ 2 + random | n = 2, ≤ 1 edge | possible (needs `today` + class-3 disjunction) | no |

## E. PoC

### E.1 Model

- `Lfp.v` is generic, with no P-037 content. It takes an `eqType L` with
  `join`/`bot`, the four laws, and a rank `L -> nat` that is strictly
  monotone and bounded by `h`. The coordinate set is any `finType I`, the
  state is `{ffun I -> L}`, and the order is pointwise. The Rust loops are
  transcribed literally: `jacobi fuel x` ("next = F x; if next == x return
  x"), and `chaotic sched fuel x` (per-update write-if-changed plus a pass
  change flag).
- `P037.v` holds the kernel's `Transfer`, `Cells` (a product), `read`,
  `contribute`, `step`, `collapsed`, `lower` and `apply`. It uses unbounded
  `edges : I -> seq edge`, where Rust has `[Option<Edge>; 2]`. `Shape` drops
  the guard index; the exporter asserts that `apply` does not depend on it.

### E.2 Theorems (all Qed, all "Closed under the global context")

| theorem | statement | Kani counterpart |
|---|---|---|
| `jacobi_is_lfp` / `k10_jacobi` | `jacobi F (n·h+1) ⊥ = Some (lfp F)` for every monotone `F` / every P-037 system on any `finType` | K10b at n = 3 |
| `lfp_least` / `k10_least` | `lfp F` ≤ every **pre**-fixpoint `y` (`F y ≤ y`) | K10b "below every fixpoint" |
| `chaotic_is_lfp` / `k10_chaotic` | for every schedule covering all coordinates (repeats allowed, any length) the Rust chaotic loop returns `Some (lfp F)` within the same `n·h+1` passes | K10c at n = 2, ≤ 1 edge |
| `lax_simulation_lfp` | `α ⊥ = ⊥` ∧ `α (F x) ≤ G (α x)` ∧ `G` monotone ⇒ `α (lfp F) ≤ lfp G` (α need not be monotone) | none (paper argument, P-037 §7.2) |
| `gt2a_one_step`, `gt2a_lfp` | `C(F_G(X)) ≤ F_C(C(X))`, hence `C(lfp F_G) ≤ C(lfp F_C)` at every coordinate: exactly K11's `gv.collapse().leq(tv.collapse())`, for unbounded SCCs | K11 at n = 2, ≤ 1 edge |
| `unfair_schedule_returns_bot`, `lfp_above_seed` | an empty schedule returns `⊥`, while the lfp is ≥ every seed: fairness is necessary | the harness *assumes* it |
| `chain_lfp` | a trace `⊥ → x₁ → … → x_k` accepted by `chain_ok` (each step is Rocq's `step`, and `x_k` is a fixpoint) ends at the lfp | none |
| `k10_rust_bound` | for `'I_3`, `rust_max_passes_cells` (exported from Rust: 19) passes suffice | the doc-comment argument in `max_passes` |

No `well_formed` hypothesis appears anywhere. The solver facts hold for
*every* system, so they do not depend on the frontend's G-L1/G-S5/G-V4
guarantees (INFERENCE: this narrows what those guarantees must protect to
the value-level claims K6/K7/K11b).

### E.3 Why this theorem

This is where the baseline had a real gap. Kani's bound and the A0 note's
"standard argument" meet here, and the A0 note (§7) itself names these two
statements as the prover candidates ("Verus later"). The finite laws were
rejected as targets up front (C3).

### E.4 Size, cost, trusted base

| item | measure |
|---|---|
| `Lfp.v` | 186 code lines (110 proof-script lines) |
| `P037.v` | 246 code lines (76 proof-script); about 35 of them are enum boilerplate forced by computability (C1), about 40 are the application layer that only carries mutant R3 |
| `Correspondence.v` | 62 code lines |
| total `.v` | **494 code lines**, above the ~300 target. The overshoot is the chaotic-loop model (≈ 60 lines, which Kani covers only at n = 2) and the certificate seam (≈ 60 lines). Neither is plumbing, and nothing approaches the 1500-line KILL signal |
| exporter / mutant runner | 232 lines of Rust / 116 lines of Python (not proof) |
| check time | Lfp 1.4 s, P037 1.9 s, RustTables 3.1 s, Correspondence 2.3 s; the whole `check.sh` ≈ 10 s |
| trusted | the Rocq kernel, **including the bytecode VM**, because the finite facts and the seam are `vm_compute` proofs; the exporter's printing (≈ 60 lines of `match`); and the claim that the exporter's random systems are representative. **Not** trusted: MathComp, HB and elpi, whose output the kernel re-checks |
| residual drift | the finite operations are pinned exactly. `step`/`collapsed` are pinned on 300 random well-formed SCCs (n ≤ 3, ≤ 2 edges; the Rust arrays cannot express more). A Rust change that only shows up outside the sample would pass. Also, `System::today`, `import` and `Election` are not modelled |

### E.5 A MathComp computability pitfall (MEASURED)

`[forall x : T, P x]`, `#|T|`, `enum T` and `[ffun ...]` did **not** reduce
under `vm_compute`, including on a finType with a hand-written explicit
enumeration: `card`/`enum` are `locked`. `inord` does not reduce either,
because `insub` goes through the opaque `idP`. So every *decided-by-computation*
fact is stated with `all` over explicit lists, and `step` takes a plain
function so that the seam can execute it. The proofs keep `{ffun}`. This
split is the main reason the executable half of the spike looks like plain
Rocq.


## F. Negative controls

`python3 formal/mathcomp-spike/mutants/run_mutants.py`. Each mutant copies
both crates to a temp tree, applies one mutation, regenerates the tables and
re-checks. MEASURED: **11/11 KILLED**, about 65 s.

| id | mutation | rejected by |
|---|---|---|
| R1 | non-commutative join (`no ⊔ must = must`, `must ⊔ no = may`) | `tjoinC` |
| R2 | law-preserving wrong join ("must wins") | `crank_ok`: `no < must` breaks the strict height of G-L3 |
| R3 | unsafe application: select or collapse the **unfinalized** cells (A0 F2) | `k6_ok`, a fabricated `consume` from `(must, ⊥)` |
| R4 | dynamic split: the `neg` orientation depends on the state | `contrib_mono_ok` (non-monotone, so no lfp theorem applies) |
| R5 | fabricated must: `const-pos` reads `⊥` as `must` | `contrib_mono_ok` |
| R6 | chaotic theorem with the fairness hypothesis weakened to `true` | `chaotic_is_lfp` does not prove. `unfair_schedule_returns_bot` is the semantic witness |
| R7 | Jacobi bound `n·h` instead of `n·h+1` | `jacobi_is_lfp` does not prove |
| D1 | **kernel**: "must wins" join | `tables_match_rust` |
| D2 | **kernel**: `collapsed()` keeps branch masks | `vectors_match_rust` (structural: no table could see it) |
| D3 | **kernel**: `step()` drops the seed | `vectors_match_rust` |
| D4 | **kernel**: `neg` transform forgets the swap | `tables_match_rust` |

The D-mutants show that the seam catches drift in the direction that
matters: the Rust kernel changing under an unchanged proof.


## G. MathComp vs alternatives

| | `cargo test` twins | Kani | plain Rocq (INFERENCE, not built) | Rocq + MathComp (this spike) |
|---|---|---|---|---|
| strength of claim | executes the real code on samples or exhaustively | proof about the real code, **bounded** (n ≤ 3/2) | unbounded proof about a model | same as plain Rocq |
| generality | fixed instances | fixed bounds | parametric in `L`, `I`, edges, schedule | same, plus `finType`-generic `I` for free |
| coupling to implementation | none needed (is the code) | none needed (is the code) | needs a seam | seam built: tables + certified traces |
| trusted base | rustc + test oracle | CBMC + Kani encoding | Rocq kernel (+VM for computation) | same + nothing (MathComp is re-checked) |
| maintenance burden | lowest | harness engineering (A0 §2: five rewrites for tractability) | proofs break on model changes | same, plus MathComp version churn (2.5 split packages, 2.6 renamed files and changed rewrite order) |
| run cost | 24.5 s | 13.6 min (22 harnesses) | seconds | ≈ 10 s |
| tooling cost | none | `cargo kani setup` | opam + `rocq-core` (not measured separately) | + HB + elpi + MathComp (≈ 10 min total, 1.9 GB) |
| drift risk | none | none | high without the seam | low for finite ops, sampled for structural ones |

What MathComp specifically contributed (MEASURED by what the proofs use):

- `{ffun I -> L}` gives extensional equality **without the functional
  extensionality axiom**, plus decidable `==` on states, which `jacobi`
  needs. Plain Rocq would need funext or a list/vector state with its own
  lemmas.
- `bigop` gives `\sum_i rank (x i)`, and `bigD1`, `leq_sum` and
  `sum_nat_const` make the finite-height argument a few lines.
- The `ssrnat`/`seq`/`eqtype` libraries: `allP`, `eqVneq`, `leq_ltn_trans`,
  `last_map`, …
- The ssreflect *tactic language* is **not** MathComp value: it ships with
  Rocq's Corelib.

What it did not contribute:

- the order hierarchy. `OrderProbe.v` makes `transfer` a
  `bJoinSemilattice` in about 9 lines, and `transfer * transfer` then gets
  the product order and `leU2`/`joinC` for free. But the solver's state
  space `{ffun I -> L}` has no order, and there is no Kleene theory, so the
  6 hand-written order lemmas stay.
- computation: the finite machinery is locked (§E.5).
- Hierarchy Builder: used only to register instances.

Verdict line, as §C.3 asks: **Rocq: useful (demonstrated). MathComp:
incremental value present but small, and not measured against a plain-Rocq
port. Kani remains the better trade-off for anything finite or bounded,
which covers most of K1–K13.**


## H. Practical value for Own.NET

What can now be guaranteed that could not be before:

1. **The P-037 solver is correct for SCCs of any size.** This matters
   because A1's production engine will not have `MAX_COORDS = 3`. Jacobi and
   every fair chaotic order return the least fixpoint, and `n·HEIGHT + 1`
   passes always suffice, so the Rust `None` branch is unreachable for
   monotone steps. Before, this held for n ≤ 3/2 plus a paper argument.
2. **G-T2a holds for SCCs of any size.** This is the contract P-037 §7 and
   A0.5 settled on, now proved rather than bounded-checked.
3. **The solver facts need no `well_formed`.** They are independent of
   G-V4 and the other frontend guarantees, which narrows the trusted-input
   boundary of A0 §5 to the value-level claims.
4. **A certificate checker exists.** `chain_lfp` turns *any* solver's
   emitted Jacobi trace into a proved statement that the result is the
   model's lfp. This is the solver-level analogue of the "replayable
   derivation over canonical facts" idea in the unmerged P-035 draft
   (PR #276), and is noted as related work only.
5. **A concrete A1 obligation (finding).** The kernel's
   `solve_with`/`lfp_chaotic` returns `Some(x)` for a non-fixpoint when the
   schedule misses a live coordinate. Reproduced with a 2-coordinate SCC:
   `solve_with(&sys, &[0])` gives coordinate 1 as `⊥`, where `solve` gives
   `no`, and `solve_with(&sys, &[])` gives all `⊥`. After finalization that
   yields `no` → `borrow`: the obligation stays with the caller, so the
   result is a silent under-approximation rather than a fabricated
   `consume`. The A1 kernel should derive the schedule from the SCC or
   assert coverage. The Kani harness only *assumes* it.

What it does **not** give: anything about Roslyn, CFG, guard eligibility or
the honesty of seeds (unchanged trusted boundary); anything about
`System::today`/G-T2b, the election pre-solver, or a verdict.


## I. Next kill-gate

**One experiment. Budget: ≤ 1 working day, ≤ 300 new `.v` lines.**

Port `Lfp.v` plus the `P037.v` instance to **plain Rocq 9.2** (Corelib +
ssreflect tactics + `rocq-stdlib` if needed, no MathComp). Keep the same
theorems, the same seam and the same mutants. At the same time, instantiate
the generic theorem on the election pre-solver (K10e: needs K4's
monotonicity and a rank).

- **KILL MathComp** if the plain port is axiom-free and at most ~30 % larger:
  keep Rocq, drop MathComp/HB/elpi, which shortens install by the HB + elpi + MathComp share (≈ 4–7 min)
  and removes the version churn.
- **Keep MathComp** (boot only; never `order`/HB-heavy) if the port needs
  `funext`/`proof_irrelevance` or grows by more than ~30 %.
- **KILL both** if the election instance needs a new framework instead of
  one instantiation. That would mean the generic layer is not reusable.

Not in scope for that gate: CI wiring, G-T2b, A1 integration.

