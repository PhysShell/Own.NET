# MathComp applicability spike — kill-first protocol and result

> Status: **PROTOCOL FROZEN, experiment not yet run.** This commit
> pre-registers the necessary conditions, falsifiers, KILL rules and budget
> *before* any `.v` file exists, so the verdict in §A is judged against
> criteria written in advance, not against an impression formed afterwards.
> Research branch only; changes no verdict, no schema, no CI gate, and does
> not touch `formal/p037-kernel/`.
>
> Evidence discipline as in `p037-formal-kernel.md`: `REPOSITORY FACT`,
> `MEASURED OBSERVATION`, `INFERENCE`, `EXTERNAL FACT` (primary source,
> cited with access date), `OWNER RULING`.

## A. Executive result

_Filled after the experiment._

## B. Base

| item | value |
|---|---|
| branch | `claude/mathcomp-ownnet-spike-911fbt` (the session's designated research branch; plays the role of `research/mathcomp-ownnet-spike`) |
| base | `origin/main` at `23e32038231b5ac8398204afb35bafc115bc3bfe` (merge of #363, P-037 A2.1), fetched at the start of the spike |
| platform | Ubuntu 24.04.4, x86_64, 4 cores, 15 GiB RAM (cloud container) |
| Rocq / MathComp | _filled after Gate 0_ |

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

## D. Existing baseline

_Filled from `formal/p037-kernel/` before the PoC._

## E. PoC

_Filled after the experiment._

## F. Negative controls

_Filled after the experiment._

## G. MathComp vs alternatives

_Filled after the experiment._

## H. Practical value for Own.NET

_Filled after the experiment._

## I. Next kill-gate

_Only if GO._
