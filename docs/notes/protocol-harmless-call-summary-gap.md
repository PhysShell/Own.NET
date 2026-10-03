# State protocols × effect summaries: the missing wire for harmless calls in a region

Status: **BLOCKED BY SUMMARY INFRASTRUCTURE** — a kill-first finding, no code
change. Measured at `main` = `a27a8277b40309aa56b945e73dd305ddb90e72b4`.

**Follow-up:** slice H0 (§4) landed inert — see
[`heap-effect-summaries.md`](heap-effect-summaries.md). H1 is still open.

Question: can `ProtocolLowering` let a *provably harmless* call stand inside a
state-protocol region by consuming the existing P-036/P-037 summary layer,
without weakening the fail-closed default?

    unknown / no summary                    -> refusal (as today)
    summary proves harmless                 -> allowed
    summary may mutate / escape the entity  -> refusal or verdict, never clean

Answer: **not with what exists.** The only summary the repository computes
does not carry the property, and there is no channel through which the lowering
could consult a core-side summary without an OwnIR vocabulary change. Building
the proof inside the extractor would be the typestate-only purity analyzer this
work must not create. What follows is the exact gap and the smallest slice that
closes it.

## 1. What exists

| Layer | What it summarizes | Can it prove "harmless"? |
|---|---|---|
| MOS (`ownlang/ownership.py`, `own-analysis` port), P-005 D5 | `Transfer ∈ {no, must, may, unknown}` per **disposable** parameter, plus owned-return kind | **No.** Non-disposable methods get no record; `borrow` and `borrow_mut` both seed `borrow` (`_build_skeletons`); the `escapes` axis is reserved with **no producer** (TZ D2); no heap/static/receiver effect at all |
| P-037 guarded transfer (A1 in progress; A2.1 sidecar inert) | The same `Transfer` lattice, split on one bool/null guard | **No.** A refinement of the transfer axis, not a new axis |
| P-036 `ParameterEffect = … BorrowMut \| MayEscape \| Unknown`, `FieldEffects`, region `Escapes(...)` | Named in the design (ownership/region summary sections) | Would be enough — but it is **design only**, scheduled under P-036 Phase 5 ("#122 cross-method exclusivity"), and has no producer, solver or schema |
| `ProtocolLowering.CheckBoundary.Effects` (extractor) | Writes to the protocol's *entity family* and the family methods reached, for **admission** | Not a candidate: protocol-local, blind to statics, and extending it into a general effect proof is exactly the purity-analyzer-for-typestate this work rules out |

### Kill-first probe (reproducible)

Sample API (`frontend/roslyn/protocol-samples/Api`) plus:

```csharp
public static class Helpers
{
    private static int _counter;
    private static Order? _kept;
    public static int Twice(int x) => x * 2;                 // harmless
    public static void Mutates(Order o) => o.Annotate("x");  // mutates the entity
    public static void Escapes(Order o) => _kept = o;        // escapes the entity
    public static void TouchesGlobalState() => _counter++;   // global write, no entity
}
// each inside its own Protocol.WithApproved(order, approved => { <call>; approved.Ship(); });
// plus Console.WriteLine("shipping") as the unknown external call
```

Extractor at `a27a827` (`--flow-locals`): exit **2**, refusals at
`Twice`, `TouchesGlobalState`, `Console.WriteLine` ("runs code with no stated
contract"). `Mutates(order)` / `Escapes(order)` are not refused: the entity
argument lowers as `use order`, and the core rejects it with a verdict. So the
fail-closed contract holds today, and the one case the slice wants to open
(`Twice`) is refused for the right reason: nothing proves it harmless.

The same helpers run through the MOS layer (`ownsharp-extract … --flow-locals`
then `python -m ownlang summaries`), with disposable twins added because MOS
sees nothing else:

| Method | MOS summary |
|---|---|
| `Twice(int)`, `Mutates(Order)`, `Escapes(Order)`, `TouchesGlobalState()` | **no record** (no disposable) |
| `ReadsStream(Stream s) { var n = s.Length; }` | **no record** |
| `WritesStream(Stream s) { s.WriteByte(1); }` | `transfer: no` |
| `EscapesStream(Stream s) { _keptStream = s; }` | `transfer: no` |

A writer and an escaper solve to the same value a reader would. Using MOS as
the proof would allow `EscapesStream`-shaped calls into a region and call them
clean. **MOS cannot be the proof, by construction**: `no` means "ownership did
not leave the caller", not "nothing was touched".

## 2. Why the decision cannot simply move into the core

The summaries are solved in the core, from facts; the refusal happens in the
extractor, before any fact exists. Deferring the decision means lowering the
region call as something the core must check. The OwnIR rules close both
spellings at v1 (spec/OwnIR.md §2, IR3/IR4):

- a new op (`opaque_call`, say) is a flow-op vocabulary change — **version bump**;
- a plain `call` with an additive `requires: harmless` field changes what `call`
  means inside `borrow_mut`; a core that does not read the field (or reads it
  before the summary domain exists) sees a call to an extern with no tracked
  argument — i.e. **nothing** — and `TouchesGlobalState` becomes clean. That is
  fail-open, which the additive rule exists to forbid.

So two things are missing, and the second is not this work's to decide.

## 3. The missing contract

    ProtocolLowering (or the core on its behalf) needs, per call site in a region:

      callee  — resolved, first-party source, statically bound
                (non-virtual, or sealed / devirtualized; else Unknown)
        -> solved HeapEffectSummary  (a P-036 summary domain, SCC fixpoint,
                                      Unknown absorbing, Python + Rust parity)
        -> Harmless(callee) :=
             every parameter    ∈ {Plain, Borrow}      (no BorrowMut, no MayEscape)
           ∧ receiver           ∈ {none, Borrow}
           ∧ FieldEffects.write = ∅                    (no static, field, array-element
                                                        or ref/out write, transitively)
           ∧ return is not AliasOf(parameter | heap) unless its type is inert
           ∧ closed: no Unknown / extern / unresolved-virtual callee in the closure
        absent summary or any Unknown -> refusal, exactly as today

Notes on the predicate:

- It is a property of **all** parameters, not just disposable ones, and of
  **statics** — the `Backdoor.AnnotateLast()` shape (R9) reaches the entity with no
  argument at all. A call is never allowed because it "does not take the entity".
- Reads are allowed (an exclusive region forbids change, not observation); a read
  that *yields* an entity-typed value is still caught by the lowering's
  exclusivity-by-type rule on the call's result.
- Arguments keep today's lowering: an entity-typed argument is still a `use` of
  the entity (a verdict), whatever the summary says. The summary only replaces
  the *refusal* of a call that touched nothing visible.

## 4. Minimal next slice

**H0 — heap-effect summary domain, inert.** No verdict change, no OwnIR bump.
Precedent: P-037 A2.1 ("emit the guarded-fact sidecar from the Roslyn
extractor, validated and inert").

1. Extractor: an additive optional sidecar of per-method **local** heap-effect
   evidence for source methods — writes to statics / fields / array elements /
   ref-out params, stores of a parameter into the heap, direct callees (with
   `virtual`/extern flagged). Facts only (IR6): no solving in C#.
2. Core (Python reference + Rust port): a second domain in the summary envelope,
   solved by the same SCC condensation as MOS, `Unknown` absorbing; serialized in
   `own summaries` under its own key so the MOS parity artifact is untouched.
3. Acceptance — the probe above as fixtures: `Twice` → harmless;
   `Mutates` → `BorrowMut(0)`; `Escapes` → `MayEscape(0)` + static write;
   `TouchesGlobalState` → static write; `Console.WriteLine` → Unknown; a
   recursive pure pair → harmless; a pure helper calling an unknown → Unknown.
   Python/Rust parity fixture; `tests/run_tests.py`; Rust fmt/clippy/tests.
   Nothing reads the domain yet, so every existing verdict and refusal is
   byte-identical.

**H1 — the wire (needs an owner ruling first).** Region calls with no visible
entity touch lower to a must-understand construct instead of a refusal; the core
applies `Harmless(callee)` and emits a refusal-equivalent error otherwise. This
is verdict-changing (a refusal becomes clean) and needs one of: an OwnIR v2 op,
or an explicitly ruled exception to IR3 — both outside this task's limits. Until
H1, `refused/R9_opaque_call_inside_region` and the probe's `Twice` case stay
refused.

## 5. Untouched

OwnIR version, the token/region model, the trust boundary, OWN053, T0/perf, the
DB-side known gaps, the unknown-call fail-closed default, and the P-022 / P-037
freezes and amendments: this note changes no code and no fixture.
