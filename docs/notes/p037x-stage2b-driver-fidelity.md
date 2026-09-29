# P-037-X Stage 2b — driver fidelity for the frozen replay (EXPLORATORY)

> Status: **EXPLORATORY research record, research branch `research/p037-max-v1` only.**
> Track: P-037-X / P037-MAX. Pre-registered BEFORE the code in Own.NET-paperwork
> `paper-eval/p037-max/stage2b-prereg-v1.json` (commit `c8ef9c9`, sha256 `bdae34e5…`); nothing
> in Stage 2's record is re-expected. Not a production migration, not a reopen of #304 (frozen
> 2026-09-28, unchanged). Stage commits: `c419fd7` (the rules, controls, re-records, spec) and the
> one carrying this note. Evidence: `paper-eval/p037-max/stage2b-driver-fidelity-v1.json`.

## 1. Question

Stage 2 measured four NO_GUARDED_EVIDENCE boundaries that belong to the B1 **driver** — how it
decodes facts and identifies coordinates — not to the frozen vocabulary. Left in place they would
be reported as the ceiling. Stage 2b removes exactly those four, reading only present facts, so
that the vocabulary's own limit shows.

## 2. The four rules (REPOSITORY FACT; stated generically)

- **R1, the empty-sidecar leaf** (`own-guarded/src/facts.rs`): A2.1 emits `guarded_facts` only for
  a method with a relevant call or an eligible guard, so for a record whose body carries no `if`,
  `while` or `call` op the emitted sidecar would have been empty and its absence encodes
  emptiness. Such a record reads as `{calls: [], guards: []}`; any structural or call op in a
  sidecar-less body keeps the fail-closed `missing_sidecar`.
- **R2, sig-keyed identity** (`facts.rs`, `lib.rs`, `own-bridge/src/lower.rs`): a coordinate is
  keyed by the record's identity — its name, or the bridge's per-overload key `name(sig)` among
  same-name records; a sidecar call resolves its callee by `(callee, sig)`; a sig matching no record
  of that name is `callee_sig`, never a name-only fallback; the seam passes the call op's `sig`.
- **R3, the declared ordinal as a fact** (`Program.cs`, `facts.rs`, `spec/OwnIR.md`): every owned
  parameter carries `params[].ordinal`, the same integer the sidecar keys `args[].param` and
  `guards[].param` by. Additive; both doors carry it as an unknown field; both production engines
  ignore it. The reader uses it when present on every param, strictly increasing, within the sig
  arity and agreeing with A17's allowlist derivation when that exists — and refuses the map
  otherwise (control C6).
- **R4, the election seed per coordinate** (`facts.rs`, `solve.rs`): G-S1 stage 1 verbatim — the
  seed of `(M, i)` joins the guard literals that lexically enclose an ownership action on `i` or
  precede it with a literal-guarded early `return`; a guard governing nothing on `i` is walked
  unguarded; two distinct governing literals seed `Conflict` (`Uncond`, the honest join); the same
  literal twice, or two guard records on one line, stay `multi_guard` / `join_guard`.

**Implementation record.** The first R4 implementation decided "governs" by re-running the B1
walker and counting any action after a passed literal. That over-elects a guard whose branches merge
before the action: `CloseUnlessKept` and B1's `Absence.ToLeaf` regressed to `Uncond` in a first,
discarded measurement, caught by the B1 acceptance pin and the #380 fixture. It was replaced by the
two-shape lexical test before the recorded measurement, and hostile control X2B-C7 (a merging guard)
was added for exactly that defect — recorded as added after observation.

Two B1 acceptance pins move as the rules imply and are re-recorded with the rule named:
`Absence.Leaf` / `Absence.ToLeaf` are solved (R1: `Uncond(must)`; `Split(keep, no, must)` through
the id edge); `Probe.TwoIfs` answers `join_guard` where B1 answered `multi_guard` — no evidence
either way, B0 §E.6 holds. The 12 shapes whose params entries gained the ordinal field are
re-recorded (`baseline_transitions` id `p037x-stage2b`, superseded facts kept verbatim); no verdict
moved.

## 3. Results (MEASURED OBSERVATION)

52 documents (the 46 of Stage 2 plus the six extractable hostile controls), flag off / flag on /
Python. Flag off == Python byte for byte on 52/52 and == Stage 2's flag-off output on 46/46.

| row | expectation (frozen in the 2b prereg) | measured with the flag on | held |
|---|---|---|---|
| F3 pairs, B1 36 rows, XD-1…9, XB-1/2/3/7/8/9/10 | unchanged from Stage 2 | unchanged (B1 36/36 EQUAL; controls OWN051 only, never consume) | yes |
| XB-4 GuardedForwardFalse | clean: `Close = Uncond(must)` (R1), `MaybeForward = Split(forward, must, no)`, `false` → borrow | clean; the #380 fixture now reports exactly its two true OWN002 | **yes** |
| XB-5 / XB-6 | OWN002 unchanged, now through `Uncond(must)` on the leaves | OWN002; `Close`, `CloseInFinally` EQUAL `uncond [must, must]` | yes |
| XC-6 SendResponseAsync.listener | `Split(stopListenerAfterResponse, must, no)` as a summary; no site selects | `split(3) [must, no]`, EQUAL; verdict unchanged | yes |
| XC-2 FinishSend.cts / .response | `Split(disposeCts, must, no)` / `Uncond(no)`, no site selects | `.cts = split(2) [must, no]` EQUAL; `.response` NGE `callee_unresolved` (an unresolved forward: the XD-4 limitation); verdict unchanged | cts yes; response recorded |
| XC-4 VerifyPersistedKey.key | `Split(disposeKey, must, no)`; C12/C13 select the negative cell | **NGE `no_body_op`** (§4) | **no** |
| XC-1 / XC-3 / XC-5 | unchanged | unchanged (case 1's overloads are coordinates now and answer `opaque_slot`) | yes |
| corpus, flag on vs off | the same 8 F3 documents; UNEXPLAINED 0 | the same 8; not one finding differs from Stage 2; summary EQUAL 32 (Stage 2: 14), NGE 8 (26); application EQUAL 16 (6), NGE 50 (60) | yes |
| hostile controls C1–C7 | as frozen | C1 NGE stays (OWN051, never consume); C2 NGE stays; C3 the guarded caller selects, the consumer consumes, the record-less overload's call is `callee_sig`; C4 Conflict → plain + OWN051, never consume; C5 and C7 Split on the governing guard alone; C6 the ordinal map refused | 7/7 |
| mutants M1–M4 | each turns its control red | M1 → C1, C2; M2 → C3; M3 → C4; M4 → C5, C7; the pristine reader green afterwards | 4/4 |

## 4. Where it stops now (MEASURED + INFERENCE)

`VerifyPersistedKey(CngKey, …).key` has an identity (R2) and an ordinal (R3) and then fails B1 A15:
the sidecar records the delegate invocation `cngKeyAlgFunc(key)` (form `initializer`, line 79) but
the legacy body carries **no op for `key` on that line**. A probe over six initializer forms shows
the cause: the legacy lowering emits `use` for a tracked handle passed to a non-canonical call in
statement form and nothing at all in a local-declaration or `using` initializer (invocation or object
creation alike). That is precisely the prereg's own conditional for XC-4 ("the delegate-invocation
argument must lower as use/borrow"). The vocabulary would express `Split(disposeKey, must, no)`; the
carrier does not show the argument. The same gap is why case 2's `GetXxxAsyncCore.request` is
`no_body_op`. It is a carrier gap, generic (any language has declaration initializers), and the next
rung: a pre-registered sub-stage 2c.

Driver rules that remain and are **not** pursued: B1 A15's refusal of any sidecar call carrying an
opaque argument (`opaque_slot`, case 1's overloads — case 1 is SHAPE_ONLY regardless), and the
legacy-honest treatment of an unresolved callee (`callee_unresolved` / `callee_external`: the
XD-4 limitation, deliberate).

## 5. Result

**Stage 2b: KEEP.** Four rules that read only present facts — body ops, `sig`, a declared-ordinal
fact, G-S1's own seed — at the cost of one additive schema field and a small reader change lift the
driver off the ceiling: XB-4 recovered, XC-2 and XC-6 form their guarded summaries, 18 more corpus
coordinates solved, zero verdict movement on the population, every control intact. Not claimed:
that XC-4 is recovered (it is not), that #304 is reopened, or parity with the flag on.
