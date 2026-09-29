# P-037-X Stage 1 — canonical first-party call transport (EXPLORATORY)

> Status: **EXPLORATORY research record, research branch `research/p037-max-v1` only.**
> Track: P-037-X / P037-MAX, the capability-ceiling study of guarded ownership/effect
> summaries. Protocol frozen BEFORE this code in Own.NET-paperwork
> `paper-eval/prereg/p037-max-v1.json` (commit `69adf01`, sha256 `bbb08e3f…`).
> This is **not** a production migration, **not** a reopen of #304 (the 2026-09-28 freeze
> ruling stands unchanged), and **not** a P-037 implementation: no engine reads a guard value
> at this stage. Never merged to `main`.
>
> Base: `main` at `fb06adc` (the #381 merge). Stage commits: `702d25b` (the carrier),
> `2d2ba15` (the bridge tolerance), `4ed5eda` (the re-recorded census, controls and #380 pins),
> and the commit that carries this note and the population evidence.
>
> Evidence tags as elsewhere: `REPOSITORY FACT`, `MEASURED OBSERVATION`, `INFERENCE`.

## 1. Question

RQ-X1: how much capability returns if first-party calls are represented canonically instead
of being pre-collapsed by the frontend? Stage-1 success is **not** "B1 green". It is: the
core can SEE the call relationship without the frontend lying with unconditional
`release`/`use` semantics.

## 2. What was built (REPOSITORY FACT)

One extractor change (`frontend/roslyn/OwnSharp.Extractor/Program.cs`, +219/−1 handwritten
lines by the ledger rule) and one bridge tolerance (both engines, Python +14/−6, Rust +37/−16). No OwnIR
schema field, no new op kind, no lattice, no guard read.

**The rule, stated generically.** A statement-form invocation (`Foo(s);`, `await Foo(s);`,
`await Foo(s).ConfigureAwait(false);`, `return Foo(s);`) of a resolved, non-reduced,
ordinary first-party method that *will carry a `functions[]` record* is lowered as ONE
existing OwnIR `call` op (spec/OwnIR.md §5 — the D5.2 op the bridge already reads as a
forward edge) for every tracked handle that binds — by name, else by position, after the
value-preserving unwrap of parentheses, `!` and identity/reference casts (A2.2 G-C, mined
from #371 at `0ae8213`) — to one of the callee's owned-disposable parameters. `args` are
positional over the callee's `params[]` list. Those handles get neither the legacy handoff
`release` nor a `use` for the call, and a canonically forwarded local is not an escape. The
extractor decides nothing about `must`/`may`/`no`: the MOS reads the callee's summary
(INF-S3) and applies it (INF-A1, INF-A5).

**Record prediction.** Whether the callee will carry a record is re-derived on the callee's
own declaration with canonical emission off (a block body, a direct class member, an
owned-disposable parameter, a body that lowers to at least one op). A callee without a
record would read as extern → `unknown` and silence the caller, so such a call keeps the
legacy lowering. Record absence is never read as a value, in either direction.

**Degradation is counted, never hidden.** Every invocation into which a handle flows but
that the rule cannot carry keeps the legacy lowering and is counted on stderr
(`p037x: canonical=N degraded={reason=count,…}`): `unresolved_callee`, `reduced_extension`,
`not_ordinary_method` (delegate invoke, local function), `not_first_party`,
`callee_no_block_body` (expression-bodied, interface/abstract), `callee_not_class_member`,
`callee_no_owned_param`, `callee_unmodelled` (unmodelled construct or empty body: the R
boundary), `named_unresolved`, `ref_out`, `params_slot`, `non_owned_slot`,
`gap_in_owned_slots` (a handle past an owned slot with no handle: positional `args` cannot
express it without a filler the doors do not accept).

**The bridge tolerance (both engines).** The carrier exposed a latent hazard: a `call` op
whose argument names a handle the core never minted (a non-fresh first-party factory
result, a branch-scoped acquire) reached the core as a raw name and hard-errored with
OWN030, while a `use`/`release` of the same name has always been dropped silently. Measured
on the pinned dotnet/runtime `HttpClient.cs` (case 2). Both engines now treat an unmapped
call argument exactly like an unmapped `use`; a direct `Call` (which the core checks against
the callee's signature) with an unmapped argument applies the callee's contract per mapped
argument through the existing `$consume`/`$borrow` channel instead. Only documents that
previously hard-errored can observe the change; every existing golden and parity fixture is
unchanged (`tests/test_ownir.py` 282/282, `test_summaries_fixtures` 35/35,
`test_lowered_fixtures` 27/27, `cargo test -p own-bridge` green).

## 3. Challenge-set results (MEASURED OBSERVATION; the frozen expectations held on every row)

45 documents, Rust and Python **byte-identical on every one**, 0 OWN030.

| group | rows | baseline `fb06adc` | Stage 1 | frozen expectation |
|---|---|---|---|---|
| A: F3 pairs (4 × before/after) | 8 | silent on both sides | OWN051 advisory only, both sides | met: the guard is not read yet, so bug/safe stay undistinguished |
| A: shapes on main | 14 | 9 caller records absent since #380 | the 9 caller records **return** with OWN051; `guard-forward-bare/negated` `Outer.s` `no → may`; 5 shapes unchanged | met |
| A: B1 8 UNEXPLAINED coordinates | 8 | `no` (post-#380 legacy) | **`may` on 8/8** = A18-0's `L_canonical` (6 via the canonical call, 2 via the unwrap of `(Stream)p` / `p!`) | met |
| B: #380 family | 10 | OWN002 ×2 | OWN002 ×2 kept; OWN051 ×4 at the partial callers; `BorrowingWrapper.borrowed` `no → may`; `ForwardDynamic.forwarded` `no → may` (the pin's own "canonical call facts arrived" branch) | met (XB-1…XB-10) |
| B: gallery 07 anchor | 2 | OWN002 / silent | OWN002 / silent | met |
| C: six real cases | 6 | see §4 | see §4 | met |
| D: four conformance controls | 4 | no findings | OWN051 only; **no fabricated release, no OWN003, never consume**; `Outer.p` `no → may` | met (XD-1…XD-4) |
| D: shape controls / mined A2.2 controls / B0 probes | 11 | — | `unresolved-callee` → `unresolved_callee=1`; `record-absence-boundary` → no canonical call (expression-bodied / empty-body callees never carry a record); `ref`/`params`/unstable-owned unchanged; B0 probes: 8 canonical, 2 `callee_unmodelled` (`Probe2.Log`, whose only use of its parameter sits in a local initializer: an R-boundary callee B1 also listed) | met (XD-5…XD-9) |

The eight-row carrier result, in the words the protocol requires: **P-037-X Stage 1 moved
the eight historically UNEXPLAINED B1 coordinates from the folded legacy value to the
canonical value `may` merely by carrying the call.** It is an integration/carrier result. It
is not evidence that the historical #373 FAIL was wrong: #373 measured the production carrier
of its day, and that carrier folded these calls.

## 4. The six real cases at Stage 1 (MEASURED OBSERVATION)

| case | canonical / degraded | findings | what the carrier changed |
|---|---|---|---|
| 1 ImageHelpers.Outline | 3 / `unresolved_callee` 6, `callee_unmodelled` 1 | none | nothing at the frozen site: `Bitmap` is not a tracked disposable here (ANALYZER_SCOPE_LIMIT stands) |
| 2 HttpClient.FinishSend | 10 / `unresolved_callee` 2, `not_first_party` 1, `not_ordinary_method` 1 | none (after the bridge tolerance; OWN030 before it) | ten first-party calls now reach the MOS; none is a frozen site — the CTS is tuple-deconstructed, not a tracked handle |
| 3 EcmaAssembly.CreateModule | 1 / — | none | unchanged |
| 4 SymmetricCngTestHelpers.VerifyPersistedKey | 2 / — | OWN001 ×2 (pre-existing: `CngKey.Delete` is not modelled as a release), **OWN051 ×2 at C12/C13** | the two caller records that #380 dropped **return**; the in-branch call to a `may` callee untracks `cngKey` (INF-A5b) with the honest advisory; no OWN009 |
| 5 ArgumentSource.GetArguments | 14 / `callee_unmodelled` 1, `not_first_party` 2 | none | the public wrapper's call to the private iterator overload is `callee_unmodelled` (the iterator body carries no record: the R boundary), so the wrapper keeps the legacy `no` |
| 6 AuthHandshakeMessageHandlerTests.SendResponseAsync | 0 / — | none | unchanged (using-declared listeners, local functions) |

## 5. Population (MEASURED OBSERVATION)

The complete before/after comparison, the sealed instruments' own outputs and the hand classification
are the `population` object of the Stage 1 evidence file in Own.NET-paperwork
(`paper-eval/p037-max/stage1-canonical-calls-v1.json`); this section is its digest.

Four sealed snapshots per side (`scripts/p037_verdict_snapshot.py` rust/python, `scripts/p037_mos_snapshot.py`
corpus/repo), population commit `fb06adc` on every side, `is_evidence: true`, `dirty: false`, before at
`fb06adc`, after at `4ed5eda` (this stage's records commit). The sealed `compare` REFUSES `fb06adc → 4ed5eda`
("the measurement instrument differs between before and after"): the bridge tolerance touched `ownlang/` and
`rust/`, which the A2.0 instruments count as instrument, not treatment. That refusal is the instrument doing its
job and is recorded as such. The comparison below is an unsealed diff of the two sealed snapshots; the sealed
compare is taken instead across `fb06adc → 702d25b` (the carrier alone, a `Program.cs`-only change; sealed
snapshots taken in a detached worktree at `702d25b`, `is_evidence: true`), and the tolerance is isolated as
`702d25b → 4ed5eda` — both in the evidence file (`population.decomposition`). The sealed result for the
carrier: `--level verdict` **UNCHANGED** on both engines (137 files, no verdict moved); `--level all` 12 of 137
files MOVED on both engines, every one an OWN051 note arrival on a challenge document, declared class
EXPECTED_CARRIER_EFFECT; MOS corpus MOVED (facts 18, python 11, rust 11, after-parity 0); MOS repo MOVED
(1 document, both engines). Every number equals the unsealed `fb06adc → 4ed5eda` comparison below: the whole
population movement is the carrier's. The tolerance alone (`702d25b → 4ed5eda`): verdicts UNCHANGED on
137/137 files on both engines, 0 transfer moves, 0 record changes on either population (the repo-tree facts digest differs by exactly 183 bytes: three `DiCaptiveSample.cs` records carry an absolute `file` path, so the digest depends on where the tree sits — the mid snapshot was taken in a worktree under the scratchpad; reproduced byte-for-byte with the instrument's own launcher invocation in both trees; a pre-existing extractor quirk on `main`, recorded for the owner, not fixed here).

| population | moved | what moved | class |
|---|---|---|---|
| verdicts, 137 files, rust | 12 | OWN051 arrivals at note level, one per file; 0 error/warning-level movement; 0 exit changes | EXPECTED_CARRIER_EFFECT (INF-A5a advisory at a top-level canonical forward to a `may` callee) |
| verdicts, 137 files, python | 12 | identical to rust; rust == python on all 137 files after | same |
| which 12 | — | exactly the 8 F3 pair files and the 4 conformance controls — the challenge documents; no other corpus file moved | — |
| MOS corpus, 137 documents | 18 facts digests | 12 challenge documents + 6 real-world `ownership-handoff-{consume,use,use-transitive}/{before,after}.cs` | the 6 real-world ones are representation-only: verdicts and summaries unchanged (op-level diff, base vs head extractor: the only change is each extractor-side `release` at a first-party definite-consumer call — `Archiver.Run/RunOk → Archive`, `HandoffUse.Run → Consume`, `HandoffUseTransitive.Run → Consume → Inner`, a two-level chain — replaced by one canonical `call`; the core derives the same `must` transitively and lowers it to `$consume`: the definite handoff is derived instead of fabricated, on real corpus documents) |
| MOS corpus transfers | 6 coordinates × 2 engines | `no → may`: `GuardedNegation.Outer.s` ×2, `GuardedWrapper.Outer.s` ×2, `Guarded.Outer.p` ×2 (the mutated-guard and ref-alias controls) | L_canonical (A18-0): INF-S3 on a carried forward to a `may` callee; four are B1 UNEXPLAINED rows, two are the hostile-guard wrappers G-V4 requires to stay `may` |
| MOS corpus records | +11 per engine, 0 lost | `Fine`/`Leak` on the 8 F3 files, `Guarded.Use` on 3 controls | the records #380 dropped return (a canonical forward is not an escape) |
| MOS repo tree, 82 files | 1 document | `BorrowingWrapper.borrowed` and `ForwardDynamic.forwarded` `no → may` (rows XB-7, XB-8); +4 `GuardedConsumeSample` caller records; the other 104 records unchanged | as above |
| cross-engine | 0 | 0 disagreements on any snapshot; 0 failures; 0 status changes | — |

**Degradation over the populations (extractor counter, MEASURED).** Corpus: 28 canonical calls over 18
documents; 13 degraded — `callee_no_owned_param` ×10 on the arraypool documents (a rented array flows into a
first-party helper whose parameter is not an owned-disposable type; the rule binds owned-disposable parameters
only, so those calls keep the legacy lowering and their verdicts did not move) and `callee_no_block_body` ×3.
Repo tree: 9 canonical, 1 `callee_no_block_body`. No `unresolved_callee`, `ref_out`, `params_slot` or
`gap_in_owned_slots` degradation occurs on either population.

**Runtime and size (MEASURED, quiet machine, medians of 3).** Extractor wall-clock over the 137 corpus
documents (sequential `dotnet` launches, Release builds): base `fb06adc` 145.95 s, Stage 1 146.01 s (+0.0%);
`own-cli ownir` over the 137 facts documents: 0.30 s vs 0.31 s (noise at the timer's granularity). Facts
size: +10.46% bytes over the corpus (a canonical `call` op names its callee and signature where a `release`
or `use` named only a variable). No MOS schema change; per-record shape unchanged.


## 6. Records re-taken on the research branch (REPOSITORY FACT)

Each re-recorded file keeps its superseded record verbatim in an append-only entry that
names the Stage-1 commit and classifies the move as an EXPLORATORY P-037-X record, never as
a production baseline:

- `corpus/p037-shapes/*/expected.json` — 9 shapes (`baseline_transitions[]` id
  `p037x-stage1`; the `record: absent` assertions of #380 become `record: present` with the
  superseded absence kept); 5 shapes unchanged;
- `corpus/p036-bakeoff/*/expected.json` — the 4 controls (`remeasured[]`, findings
  `['OWN051']`, no fabricated release). The `post_a1` layer is untouched: it is the A1 acceptance
  record, `p037_controls.py --post-a1` is documented and CI-configured as expected to fail until A1
  lands, and Stage 1 is not A1. It now mismatches on all four controls (measured `['OWN051']`,
  recorded `[]`); the recorded `[]` rests on OWN051 sitting at note level (the legacy-honesty
  control's note says so) while both engines report OWN051 as a warning today — a pre-existing
  tension on `main` that belongs to A1, recorded here, not resolved here;
- `tests/test_guarded_consume.py` — the definite consumers (`Close`, `CloseInFinally`) are pinned as
  canonical `call` ops with OWN002 derived by the core (INF-S2 on the callee + A1), no longer as
  extractor-side `release` ops; the four kept streams pin exactly the OWN051 advisory (silence would
  now mean the carrier is gone; any OWN001/OWN002/OWN003/OWN009 would be a fabrication); `ForwardDynamic`
  pinned `may` (the pin's own "canonical call facts arrived" branch), `BorrowingWrapper` pinned `may`
  (frozen expectation XB-7).

## 7. Result

**Stage 1: KEEP.** The core sees the call relationship; the frontend no longer decides a
first-party call's ownership effect. Complexity: one generic extractor rule (+219/−1 lines), one
generic bridge tolerance (+51/−22 lines over two engines), no vocabulary change. What the
carrier alone buys and what it does not: every guarded caller is now honestly `may` +
OWN051 — the bug/safe twins remain undistinguished until a guard is read (Stage 2).

Findings for the owner, outside this track's authority:

1. `#304` reopen condition 1 names exactly this representation ("the legacy `body` stops
   folding first-party forwards"); whether an exploratory carrier meets it is the owner's
   call and is **not claimed** here.
2. The OWN030 hazard is latent on `main` today for a chain of two first-party factory
   calls whose first is not `fresh`; the tolerance is a candidate for a separate,
   ordinary correctness PR, independent of P-037.
3. `callee_unmodelled` on the iterator overload (case 5) and on `Probe2.Log` are the R
   boundary (§10.6) seen from the carrier side; Stage 1 does not widen the record set.
4. Three records of `frontend/roslyn/samples/DiCaptiveSample.cs` emit an absolute `file` path
   while every other record emits the path as given, so the repo-tree facts digest is
   machine-dependent by exactly those three fields (pre-existing on `main`; surfaced by the
   worktree decomposition above; not fixed here).
