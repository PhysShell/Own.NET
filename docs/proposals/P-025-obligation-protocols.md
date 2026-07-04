# P-025 — Obligation protocols (`Own.Protocols`) — barrier-sensitive project invariants

- **Status:** first slice built (core + bridge + spec + fixtures, `OBL001–005`
  end-to-end over hand-written facts); the Roslyn extractor slice is designed
  below but **not** implemented (this sandbox has no dotnet; extractor work is
  CI-validated).
- **Built:** [`ownlang/obligations.py`](../../ownlang/obligations.py) (the
  path-sensitive checker), the `protocols[]` / `protocol_functions[]` OwnIR
  blocks ([spec/OwnIR.md §8](../../spec/OwnIR.md)), the `OBL001–OBL005` codes,
  [`tests/test_obligations.py`](../../tests/test_obligations.py) (64 checks),
  and the `protocol_isloaded_*` killer-demo fixtures.
- **Depends on:** [spec/OwnIR.md](../../spec/OwnIR.md) (the facts seam),
  [P-016](P-016-deep-fact-extraction.md) (the flow lowering the extractor slice
  reuses), [P-006](P-006-di-lifetimes.md)/[P-020](P-020-ownts-react-effects.md)
  (the sidecar-analysis precedent this copies).
- **Relation to [P-010](P-010-type-disciplines.md):** P-010's `protocol` blocks
  are *typestate on an object across its lifetime* (state machines, consume-self
  transitions on the affine core). P-025 is deliberately smaller: *temporal
  obligations inside a method*, checked against project-declared barriers. P-010
  can later subsume these rules; nothing here blocks it.

## Motivation — the invariant the type system cannot know

A legacy WPF method breaks its own invariant on purpose, briefly:

```csharp
IsLoaded = false;          // the document tree is now inconsistent — on purpose
RebuildIndexes();
if (hasWarnings)
    OnPropertyChanged(nameof(Document));   // ← published the broken object
IsLoaded = true;
OnPropertyChanged(nameof(Document));       // this one is fine
```

`IsLoaded = false` is not a bug; **publishing the object while the flag is
down** is. No general checker can know that `IsLoaded` means "the document is
consistent", that `PropertyChanged("Document")` hands the object to bindings
*right now*, or that `PropertyChanged("Progress")` is harmless meanwhile. That
knowledge is project-specific. Existing tools stop exactly here: analyzers know
universal protocols (dispose your `IDisposable`, unsubscribe your event);
NDepend/CodeQL can query structure but have no barrier-sensitive obligation
model; typestate research languages don't speak legacy C#. The niche is real:
**barrier-sensitive, project-specific obligation checking for code review** —
and the OwnAudit STS corpus already shows the shape in the wild (17k
INPC findings, 8 recorded `IsLoaded` findings, `BrokerDataClasses` as the
subscription-leak epicenter).

The same three verbs cover the whole family:

```text
IsLoaded=false            must become true      before PropertyChanged(Document)
_suppressNotifications    must be restored      before return/throw
BeginUpdate               must meet EndUpdate   before Refresh / method exit
SuspendCalculation        must be resumed       before results are published
```

## The model — obligation / barrier / require-closed-before

One protocol = three matchers and a scope (the full shape and its normative
semantics live in [spec/OwnIR.md §8](../../spec/OwnIR.md)):

- **opens** — the event that creates the obligation (`IsLoaded = false`, or a
  call: `BeginUpdate()`);
- **closes** — the event that discharges it;
- **barriers** — events it must not cross while open: configured calls (with an
  optional distinguished-argument set, so `OnPropertyChanged` can be unsafe for
  `Document` but allowed for `Progress`) plus, by default, every method exit
  (`return`, `throw`, falling off the end — the OWN001 shape).

The checker ([`ownlang/obligations.py`](../../ownlang/obligations.py)) walks the
method's ordered event tree path-sensitively; the obligation state is a set over
{OPEN, CLOSED} joined by union at merges, so **definite vs maybe** falls out of
the lattice exactly as OWN002 vs OWN009 do. Loops are solved to a local fixpoint
and emit once. Findings carry the ordered evidence slice — *opened here → barrier
fired here → closed only here, after the barrier* — which SARIF renders as a
click-through `codeFlows` trace.

| Code | Meaning |
|------|---------|
| OBL001 | obligation still open when a barrier fires (every path) |
| OBL002 | obligation may still be open at a barrier (some path) |
| OBL003 | obligation not closed before the method exits (every path) |
| OBL004 | obligation may not be closed before an exit (some path) |
| OBL005 | advisory: a protocol's scope matched no reported method (dead rule) |

## Precision policy (the standing red line, applied here)

False positives kill this feature faster than any competitor — a rule that
cries on every `IsLoaded=false` gets switched off like a smoke alarm that hates
toast. Three normative rules (all tested):

1. **Never invent.** An opaque write to a tracked flag (`IsLoaded = Compute()`)
   may *discharge* an open obligation (state gains CLOSED → the crossing
   degrades to a *maybe*) but never *creates* one.
2. **Unnamed calls are neutral.** A call the protocol doesn't mention neither
   discharges nor crosses. A callee that flips the flag internally is invisible
   in v1 — that is the phase-3 interprocedural slice, not a v1 guess.
3. **Scope is the throttle.** `scope.methods` restricts a rule to named
   methods; the MVP posture is *one protocol, one method, one historical bug*.
   A scoped rule matching nothing is surfaced (OBL005), not silently dead.

## Why this shape (decisions on the record)

- **Sidecar analysis, not new core instructions.** `di.py`/`effects.py` set the
  pattern: a fact family + a small core analysis routed via `check_facts`. The
  alternative (new `Instr` variants in `cfg.py`) touches the frozen
  `cfg_json.py` oracle seam, `codegen.py`, the grammar, and the Rust mirror —
  all for no v1 gain. Revisit when protocols need loans/RID interplay.
- **Additive OwnIR blocks, no version bump.** `services` and `effects` landed
  additively at v0; `protocols`/`protocol_functions` follow the same IR3 rule.
  An older core ignores them; their internal vocabularies (`ev`, matcher
  `kind`) are fail-loud per IR4 and version *with the blocks*.
- **Rules are data, not a language.** The chat-derived requirement is explicit:
  nobody wants to learn OwnLang — including its author. Protocols are declared
  as JSON facts (later: generated from attributes/inference and *approved*, see
  the roadmap), never hand-written `.own`. OwnLang stays what Own.NET
  understands, not what users write.
- **Messages are line-free.** OwnAudit fingerprints findings on
  (path, rule, message) for the baseline ratchet and the FP-judge overlay; a
  line number in the message would break both on every unrelated edit. Lines
  live in the evidence slice.

## The extractor slice (designed, not built — needs CI/dotnet)

`OwnSharp.Extractor` already collects everything required; the slice is
emission, not analysis (one checker: the extractor reports, the core decides):

1. **Events.** Extend the P-016 flow lowering (`LowerFlowStmt`/`EmitFlowExpr`,
   with its `onReturn`/`onThrow` continuation threading, so `finally` and
   exceptional paths come sound for free) to emit `protocol_functions[].events`
   for methods in some protocol's scope: member assigns with literal boolean
   RHS (`AssignedFieldName`/`ThisFieldName` already normalize the LHS; a
   non-literal RHS emits an opaque assign with no `value`), self-calls with a
   `nameof(X)`/string-literal first argument as `{"ev":"call","arg":"X"}`
   (`SelfCallName` already recognizes the receiver), and `return`/`throw`.
   Scope-gating keeps the facts file small and the honest-skip discipline
   (`methods_skipped_unmodelled`) carries over.
2. **Rules.** A project file (e.g. `.own-protocols.json`, schema =
   `$defs/protocol`) merged into the facts by `own-check.sh` — configuration
   travels with the repo, not the tool invocation.
3. **CI.** A `samples/LoadingProtocolSample.cs` + grep assertions in the
   `wpf-extractor` job, and a corpus case once real-world instances are mined
   (the OwnAudit STS stand is the natural first target).

## Roadmap (each phase lands only after the previous one holds on real code)

1. **v1 (this slice):** core + bridge + fixtures. Killer demo:
   `python -m ownlang ownir tests/fixtures/ownir/protocol_isloaded_violation.facts.json`
   → `OBL001` at `BigDocumentViewModel.cs:241` with the three-hop path.
2. **Extractor emission** (above) — the same demo on real C#.
3. **Interprocedural obligations:** per-method summaries
   (`mayOpen/mustClose/mayCross` per protocol) on the MOS/SCC channel of
   [`ownership.py`](../../ownlang/ownership.py), so `ApplyWarnings()` that
   notifies internally stops being invisible. Same tier ladder as D5
   (inferred → curated → annotation).
4. **Authoring surfaces:** `[OwnProtocol]`-style C# attributes and/or inferred
   candidate protocols ("in 27 places `IsLoaded=false` … `true` precedes the
   Document notify; 2 places violate — adopt this rule?") emitted as *suggested*
   config a human approves and commits.
5. **Consumption:** OwnAudit picks OBL findings up as canonical finding records
   (SARIF evidence/codeFlows already flow through `report/sarif.py`; register
   the category for severity mapping and the runtime correlator), and the
   diff-aware baseline gate makes them review-time signals ("fail only new
   violations").

## Non-goals

- **Not a general temporal-logic engine.** No LTL, no arbitrary predicates, no
  cross-object protocols. Three verbs and a scope; the moment a rule needs a
  formula, it is a P-010/P-002 customer.
- **Not typestate.** No per-object state machines, no consume-self transitions,
  no aliasing of obligation carriers (the protocol tracks *the method's own*
  flags/calls; `this`-aliasing is out of scope for v1 by construction, and the
  RID machinery exists when that changes).
- **Not a DSL for people to write.** Facts in, findings out. Any future
  human-facing surface is attributes or approved generated config.
- **Not on by default anywhere.** No built-in protocol ships with the tool; an
  empty `protocols[]` means the analysis does not exist for that repo.

## Open questions

1. **`await` as a barrier.** During an `await` the broken state is observable
   by the UI thread; is that a barrier by default, opt-in
   (`{"kind": "await"}` in `barriers`), or a per-protocol flag? (The extractor
   currently skips most async bodies anyway — honest-skip.)
2. **Cross-member protocols** (open in `BeginLoad`, close in `OnLoaded`): needs
   obligation state on the *component*, not the method — the RID model fits,
   but the facts shape does not yet.
3. **Suggested-protocol mining:** does inference live in the core (over
   `protocol_functions` without rules) or in OwnAudit (over the corpus)?
