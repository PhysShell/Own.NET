# P-036 - Interprocedural semantic architecture

Status: **draft**

Related work:

- [P-016 - deep C# fact extraction](P-016-deep-fact-extraction.md)
- [P-022 - Rust core migration](P-022-rust-core-migration.md)
- [P-025 - obligation protocols](P-025-obligation-protocols.md)
- [`spec/Inference.md`](../../spec/Inference.md)
- [`docs/notes/interprocedural-roadmap.md`](../notes/interprocedural-roadmap.md)
- [`docs/notes/interprocedural-tz.md`](../notes/interprocedural-tz.md)
- #258 (closed) / #259 / #260: bridge contract, Rust bridge, dual-engine parity
- #278 (closed by #293, extended by #302): a release that exists syntactically
  but is not reachable — the historical motivating incident; #304 tracks the
  post-cutover summary-backed generalization
- #272 / #274: obligation protocols and protocol/effect summaries
- #275: consume-or-exit loop progress
- #122 / #146: exclusivity and publisher provenance
- #282: structured-concurrency contracts

## Decision in one paragraph

Own.NET should treat interprocedural analysis as a first-class semantic layer, not
as additional logic inside AST visitors or the OwnIR bridge. The external
versioned **OwnIR** JSON contract remains the frontend seam. It lowers into an
internal, typed, syntax-independent **OwnHIR** method representation. The
existing **OwnCFG** is the local-analysis substrate, intended to become the
MIR-equivalent control-flow representation, and should remain the execution
substrate for local dataflow. A derived call graph and
first-class **MethodSummary** artifacts carry effects across method boundaries.
A generic SCC/fixpoint summary engine composes domain-specific summaries for
ownership, obligations, progress, regions, and tasks. Diagnostics consume
ordered derivation evidence from those layers. OwnAudit remains the runtime
witness/correlation consumer; 007 remains the gate and replay consumer.

This proposal names and separates the elephant already visible in the current
code and roadmap. It does not replace the shipped MOS solver, the existing CFG,
or the P-022 parity plan. It defines the architecture those pieces should grow
into after the Rust cutover instead of allowing `own-bridge` to become the
permanent home of every future semantic.

## Motivation

Own.NET already has more than a raw AST checker:

- frontends emit versioned OwnIR facts;
- `.own` source has a parser and AST;
- `own-cfg` provides canonical intraprocedural CFG lowering;
- `own-analysis` has a worklist solver and several flow-sensitive domains;
- `ownership.py` already performs SCC condensation and bottom-up MOS inference;
- `spec/Inference.md` normatively defines the current method-ownership summaries;
- diagnostics already carry ordered Evidence and SARIF code flows.

The missing part is an explicit architectural home for the semantics between a
frontend fact and a cross-method verdict.

Today, `ownlang/ownir.py` is not merely a JSON loader. It validates facts,
normalizes identities, lowers flow operations, mints handles and RIDs, resolves
calls, infers method ownership summaries, applies branch-local behavior,
prepares DI/effect inputs, drives analyses, and maps results back to source
locations. #258 (now closed) correctly treated this as verdict-determining
behavior and specified it so that #259 can port it under a frozen contract.

That concentration was acceptable for the proof of concept. It is not an
acceptable permanent substrate for the next classes of work:

- the #278 class needs release reachability through lifecycle call chains, not a
  class-wide search for a matching `-=` or `Stop()` — the landed #293/#302
  extractor predicates are the current bounded implementation, and #304 tracks
  their summary-backed generalization;
- obligation protocols need effects to be produced in one method and discharged
  in another;
- loop progress needs callees to summarize whether they advance a controlling
  measure or exit;
- field, closure, timer, and callback escapes need stable places and heap
  identities rather than syntax-node coincidence;
- async and structured concurrency need task creation, capture, join, cancel,
  and scope effects to cross method boundaries;
- runtime correlation needs a static derivation trace with stable identities,
  not only a final warning line.

Adding each of these as another special case in the bridge would preserve the
file layout while destroying the architecture. The result would be a second
compiler hidden inside a deserializer, with more side effects than a pharma
commercial.

## Scope

This proposal defines:

1. the distinction between external OwnIR and internal semantic IR;
2. the internal method representation used by all frontends;
3. the role of the existing CFG as the MIR-equivalent local execution model;
4. call-target and call-graph representation;
5. first-class, serializable method summaries;
6. SCC/fixpoint composition of summaries;
7. domain boundaries for ownership, protocols, progress, regions, and tasks;
8. evidence and uncertainty requirements;
9. an incremental migration sequence compatible with P-022 parity;
10. acceptance criteria for the first real consumer, #304 (the #278 class,
    generalizing the landed #293/#302 predicates).

## Non-goals

This proposal does **not**:

- change verdicts before the P-022 Rust-default cutover gate (#262);
- replace Roslyn or reimplement C# semantics in Rust;
- turn OwnLang into a language users must author;
- build a complete C# compiler or a sound whole-program points-to analysis;
- require LLVM IR, MLIR, SSA, IFDS, separation logic, or Datalog in the first
  implementation;
- make `own-bridge` a generic analysis engine;
- move runtime heap analysis into Own.NET;
- move static semantics into OwnAudit;
- make 007 a checker;
- claim formal proof of arbitrary C# behavior;
- promise perfect resolution of reflection, dynamic dispatch, native callbacks,
  or third-party code without models.

The target is a compositional, evidence-producing analysis architecture with
explicit uncertainty. It is not omniscience wearing a compiler badge.

## Terminology and layer boundaries

### External OwnIR

**OwnIR** keeps its current meaning: the versioned JSON fact contract emitted by
Roslyn and future frontends. It is a wire format and compatibility seam.

OwnIR should describe what the frontend learned from the source environment:

- canonical symbols and signatures;
- source spans;
- declarations and calls;
- resource/protocol observations;
- frontend-resolved types and targets;
- explicit unknown or degraded resolution;
- language/framework-specific facts that the bridge can normalize.

OwnIR is not the solver IR. It may preserve source-level facts that are useful
for compatibility but inconvenient for analysis. It must not become a dump of
Rust implementation structs.

### OwnHIR

**OwnHIR** is the internal, typed, syntax-independent semantic representation.
It normalizes different frontend spellings into the operations the analyses
actually understand.

The name is intentionally modest. OwnHIR is not a second user language and not
another wire contract. It is an internal program model that can be constructed
from:

- OwnLang AST;
- C# OwnIR facts;
- future TypeScript/JVM facts;
- synthetic test fixtures.

A first vocabulary should include operations such as:

```text
Acquire(resource, kind)
Use(place)
Borrow(place, permission)
Transfer(place, destination)
Release(place, protocol_event)
StoreField(base, field, value)
LoadField(base, field)
AliasJoin(left, right)
ProtocolEvent(subject, protocol, event)
Call(callsite, target_set, receiver, arguments, result)
Return(value)
Throw(value)
Await(task)
SpawnTask(task, captures)
JoinTask(task)
CancelTask(task)
Barrier(kind, subject)
Progress(measure, relation)
```

The exact enum is a later spec. The architectural rule is immediate: analyses
consume normalized semantic operations, not Roslyn syntax kinds and not bridge
JSON dictionaries.

### OwnCFG

The existing **OwnCFG** is the local-analysis substrate and the *intended*
MIR-equivalent layer. Today it lowers the OwnLang AST into basic blocks with
plain successor edges — calls and returns are ordinary instructions, and the
crate still re-exports the AST for analyses the CFG does not model — so
"MIR-equivalent" is the target contract, not the current state. To serve this
architecture it must be extended to carry normalized OwnHIR operations and
explicit typed terminators:

```text
Goto
Branch
Switch
Invoke   (call terminator: normal + exceptional successors)
Return
Throw
AwaitSuspend
```

One model, stated once: lowering selects `Call` or `Invoke` deterministically
from the configured CFG profile and the available frontend facts — never from
the analysis domain. When exceptional or suspension flow is represented, the
call is lowered as `Invoke` for **all** domains; a domain that does not care
about those successors may ignore them, but it does not request a different
lowering for the same method and profile. A plain call whose exceptional flow
the profile does not represent stays an ordinary OwnHIR `Call` operation
inside a block. One method, one profile, one CFG shape — shared summaries,
serialization, and cache keys all assume it — and `Call` never appears as both
an instruction and a terminator in the same method lowering.

Normal, exceptional, and suspension edges must be distinguishable when a domain
cares about them.

This proposal does not require a separate `OwnMIR` merely to imitate compiler
naming conventions. A new layer is justified only by a semantic difference. If
OwnCFG already provides normalized linear instructions in basic blocks, calling
another copy MIR would add letters, files, and opportunities for drift while
adding no reasoning power.

### Interprocedural graph

The interprocedural graph is a derived view over methods and callsites:

- method nodes;
- callsite nodes or labelled call edges;
- candidate callees;
- return continuations;
- exceptional continuations;
- lifecycle roots and framework callbacks;
- unresolved/external targets with explicit precision.

The graph should not be the sole source of truth. Method CFGs and callsite
bindings remain canonical; the call graph and ICFG are derived and rebuildable.

### MethodSummary

A **MethodSummary** is the first-class interprocedural artifact. It records only
the behavior observable across a method boundary. Internal temporary variables
and block identities do not escape into the summary.

The existing MOS is the first summary domain, not a disposable special case.
Future domains extend the same composition architecture.

## Target architecture

```text
                    FRONTENDS

  .own source          C# / Roslyn          future TS/JVM
      |                    |                     |
  own-syntax AST       OwnIR facts           OwnIR facts
      |                    |                     |
      +--------- frontend-specific lowering ----+
                           |
                           v
                       OwnHIR
          typed places, calls, semantic operations
                           |
                           v
                       OwnCFG
       basic blocks, normal/exception/suspend edges
                           |
             +-------------+--------------+
             |                            |
             v                            v
        Local analyses              Call graph / ICFG
   ownership, loans, regions       targets, roots, SCCs
             |                            |
             +-------------+--------------+
                           v
                  MethodSummary engine
       infer, join, apply, cache, explain, serialize
                           |
          +----------------+-------------------+
          |                |                   |
          v                v                   v
    Ownership/MOS     ObligationSummary   ProgressSummary
          |                |                   |
          +----------------+-------------------+
                           |
                 later Region/Task summaries
                           |
                           v
                  Diagnostics + Evidence
                           |
                 text / SARIF / ownreport
                           |
        +------------------+------------------+
        |                                     |
        v                                     v
     OwnAudit                            007 consumers
 runtime witness/correlation        gates, replay, promotion
```

## Program identities and places

Interprocedural ownership analysis fails quickly if identity is based on source
text or object addresses. The internal representation needs stable IDs.

Recommended identity families:

```text
MethodId
TypeId
FieldId
ParameterId
LocalId
CallsiteId
AllocationSiteId
ResourceId
ProtocolInstanceId
TaskId
BlockId
```

Recommended place model:

```text
This
Parameter(method, index)
Local(method, local_id)
StaticField(field_id)
Field(base_place, field_id)
ReturnValue(callsite_id)
Allocation(allocation_site_id)
Captured(closure_or_task, place)
UnknownHeap(type_or_region)
```

The first implementation does not need a perfect heap model. It needs a model
that is better than matching variable names:

- field-sensitive for project-local fields;
- allocation-site-sensitive for resources created in analyzed code;
- receiver/type based for modeled external APIs;
- an explicit `UnknownHeap` fallback;
- no conversion of unknown identity into a silent clean result.

## Call resolution

Every callsite records both targets and resolution precision:

```text
Exact(method)
FiniteSet(methods)
External(model_key)
Unknown(reason)
```

Resolution may use:

- the Roslyn-resolved `IMethodSymbol` and canonical signature;
- static/private/sealed dispatch;
- conservative virtual/interface target sets;
- delegate targets when statically known;
- framework callback models;
- external annotations and resource model files;
- explicit unknown fallback.

A call by textual method name is a compatibility fallback, not the target
architecture. The shipped signature work in the interprocedural roadmap is the
minimum identity baseline.

## Summary domains

### Common summary envelope

Every domain-specific summary should share a common envelope:

```text
MethodSummary {
    method_id
    input_contract
    normal_exit_effect
    exceptional_exit_effect
    unresolved_calls
    precision
    dependencies
    evidence
    format_version
}
```

`dependencies` records the callee summaries and external models used to derive
the result. This makes invalidation, explanation, and differential replay
possible.

`input_contract` is not decorative: it carries the guarded-effect predicates
(see the MVP policy under the ownership summary) under which conditional
effects apply, plus the argument facts a callsite is allowed to substitute
(statically-known constants). An empty contract means the summary's effects
are unconditional.

### Ownership summary

The current MOS remains authoritative for existing behavior. Its future internal
shape may include:

```text
ParameterEffect = Plain | Borrow | BorrowMut | Consume | MayEscape | Unknown
ReturnEffect = Plain | Fresh | AliasOf(parameter) | AliasOf(receiver) | Unknown
ReceiverEffect
FieldEffects
MayAcquire
MayRelease
MustRelease
MayLeaveLive
```

The critical distinction is **may** versus **must**. A release on one branch is
not a release on all branches. Unknown is not clean.

One context-insensitive summary per method is not enough for the flagship
lifecycle case, and this proposal says so now rather than discovering it in
Phase 2. The heap-proven SectorTS shape is:

```csharp
void Teardown(bool skip)
{
    if (!skip)
        publisher.Event -= handler;   // the release
}

Teardown(true);                        // the callsite that never releases
```

An unconditional summary can say at most `MayRelease` — true and useless.
Binding `parameter[0] -> true` decides the case only if the summary preserved
the guard. The MVP policy is therefore:

```text
MVP guarded effects:
  summaries preserve guarded effects over simple boolean/null parameter
    predicates (a release/consume/protocol effect may carry
    `when <param> == <const>` / `when <param> is null | non-null`);
  callsite application substitutes statically-known constant arguments and
    resolves the guard before joining;
  any predicate outside that vocabulary degrades the effect to May/Unknown —
    never to Must, and never to silence.
```

A full symbolic executor is explicitly out of scope. But without at least this
much, the summary layer would be weaker than the landed #293/#302 extractor
predicates on the exact case that motivated it.

### Obligation summary

Obligation protocols need summaries that can create, transform, discharge, or
propagate obligations:

```text
Produces(protocol_state, subject)
Discharges(protocol_state, subject)
Transforms(from, event, to)
Requires(before_call)
Forbids(after_barrier)
Propagates(subject_mapping)
```

Example:

```text
BeginTransaction:
    produces MustEventually(CommitOrRollback, return)

Commit:
    discharges MustEventually(CommitOrRollback, receiver)
```

This is the architectural destination of P-025 and #274. It is not a second
protocol engine in the bridge.

### Progress summary

#275 needs a domain that describes whether a method advances a measure or exits:

```text
MustAdvance(measure, relation)
MayAdvance(measure, relation)
MustExit
MayExit
NoProgress
Unknown
```

At a loop back-edge, the local CFG analysis combines local mutations with callee
progress summaries. A call named `ReadNext` does not count as progress merely
because a human chose an optimistic verb.

### Region summary

Region/lifetime summaries describe captures and escapes:

```text
Escapes(parameter, destination_region)
Captures(receiver_or_parameter, owner)
ReturnsBorrowedFrom(parameter_or_receiver)
Promotes(subject, region)
```

This extends the existing lifetime/DI region reasoning without moving DI
registration extraction into the generic solver.

### Task summary

Structured-concurrency work should wait until narrower async facts are stable.
When introduced, the summary domain should include:

```text
Spawns(task, captures)
ReturnsTask(task)
Awaits(task)
Joins(task)
Detaches(task)
Cancels(task)
RequiresJoinBefore(scope_exit)
```

This is a future consumer of the architecture, not a prerequisite for the first
implementation.

## Summary inference and composition

### Local analysis

Each method is analyzed over its OwnCFG with current callee summaries as input.
A domain transfer function updates an abstract state for each instruction.
Control-flow joins use the domain lattice and preserve may/must distinctions.

### Callsite application

At a callsite, formal places are bound to actual places:

```text
callee.receiver -> caller actual receiver
callee.parameter[0] -> caller argument[0]
callee.return -> caller result place
```

The callee summary is instantiated through that binding and applied to the
caller state. This gives callsite-sensitive effects without requiring a unique
summary for every caller.

### SCC and recursion

The call graph is condensed into strongly connected components. Acyclic SCCs
are solved bottom-up. Recursive SCCs iterate summaries to a fixpoint:

```text
summary_0 = bottom or explicit unknown baseline
summary_n+1 = analyze(method, summaries_n)
stop when all summaries stabilize
```

Every domain must define a finite-height lattice or a widening strategy. The
existing ownership solver already demonstrates the SCC/fixpoint pattern; the
new architecture generalizes its home and artifacts rather than replacing its
semantics.

### Context sensitivity

Default policy:

- one context-insensitive summary per resolved method signature;
- callsite-sensitive parameter/receiver binding;
- allocation-site/resource-sensitive facts where available;
- selective specialization only when an observed false positive/negative
  justifies it.

Possible later specializations:

- receiver-type-sensitive virtual summaries;
- one-callsite sensitivity for wrapper/factory patterns;
- bounded generic instantiation keys;
- framework lifecycle contexts.

Unbounded call strings are not an MVP. Precision is useful; combinatorial
self-harm is not.

## Unknown and external calls

Unknown behavior must be visible and policy controlled.

The engine distinguishes:

1. **analyzed body**: infer a summary;
2. **trusted model**: apply a versioned external summary;
3. **finite but unresolved target set**: join candidate summaries;
4. **unknown target**: apply conservative domain defaults and record degraded
   precision;
5. **unsupported construct**: emit an advisory or explicit skip reason.

External models belong in declarative model files or dedicated framework model
modules. They do not belong as scattered name tables in analysis transfer
functions.

Optimistic and pessimistic policies may differ by check, but both consume the
same explicit `Unknown` evidence. A rule may choose not to fail CI on unknown;
it may not pretend the call was proven harmless.

## Lifecycle roots and reachability

#278 showed that intraclass syntax matching is not lifecycle reasoning (a
heap-proven leak hid behind a flag-guarded `-=` in a method callers skip). The
landed #293/#302 extractor predicates close that reported class with bounded
teardown-context and guard reasoning; they are the floor this section
generalizes, not the ceiling. A reachable-release analysis needs explicit
roots and entry contracts.

Examples of roots:

- `IDisposable.Dispose` / `IAsyncDisposable.DisposeAsync`;
- WPF `Closed`, `Unloaded`, `OnClosed`, and modeled framework teardown;
- DI scope disposal;
- application shutdown;
- test fixture teardown;
- project-declared lifecycle methods.

For each acquired obligation, the analysis should answer:

```text
Which lifecycle roots can own this resource?
Which root-to-exit paths are reachable?
Which callees are traversed?
Is release guaranteed on every required path?
Which path proves the missing release?
```

A release in a dead method, an unregistered callback, or a conditional branch
must not discharge a must-release obligation globally.

Two different theorems hide here, and the analysis must keep them apart:

```text
LifecycleEffect:
  IF a lifecycle root runs, release happens on all its required exits
  (proved by the call graph + summaries under that root)

LifecycleEnrollment:
  THIS instance actually reaches that root
  (proved by `using`, DI scope membership, a wired framework callback,
   an owner whose own teardown calls Dispose, a registered handler,
   or a framework model that guarantees the teardown)
```

Proving a perfect `Dispose()` that nothing ever calls proves nothing. A
must-release obligation is discharged only by LifecycleEffect *and*
LifecycleEnrollment together; effect without enrollment yields a degraded or
conditional verdict — never clean.

## Evidence and explanations

Every interprocedural conclusion should be explainable without reading solver
code.

Required evidence kinds:

```text
Acquire
Call
CallTarget
SummaryApplied
Branch
Return
ExceptionalReturn
Transfer
Escape
ProtocolTransition
Release
Barrier
LoopBackEdge
UnknownCall
ModelApplied
```

A #278-style finding should be able to render a witness such as:

```text
Subscription acquired at ViewModel.cs:42
Close() called from OnClosed() at ViewModel.cs:91
Close() calls Cleanup() at ViewModel.cs:96
Cleanup() reaches `return` when `_flag == false`
Unsubscribe at ViewModel.cs:121 is not reached on that path
```

The evidence graph should retain stable method/callsite/resource IDs and source
spans. Two representations, one truth: the full derivation exists once as a
**proof DAG** keyed by those stable IDs; summaries carry only compact
provenance/dependency references into it, and the diagnostic layer selects one
deterministic **displayed witness** path per finding. The derivation graph is
never duplicated into every summary, and the witness is a projection of the
DAG, not a second derivation. Diagnostic formatting is a projection. OwnAudit
may correlate those IDs
with runtime resource identities and classify the result as static-only,
runtime-only, or confirmed. OwnAudit does not recompute the static summary.

## Incrementality and caching

The IDE path is a primary P-022 motivation, so summaries must be cacheable.

A summary cache key should include at least:

```text
method body semantic hash
resolved signature
relevant frontend fact/model versions
analysis domain version
callee summary dependency hashes
configuration/profile hash
```

Two consequences of that key shape must be designed in rather than discovered
in production:

- **Recursive SCCs cache at SCC granularity.** Inside a recursive component,
  each member's callee dependency hashes include the other members, so
  per-method keys cannot be reconstructed before some entry is retrieved. The
  cacheable unit for a recursive component is the SCC itself: its key derives
  from the members' local inputs (body hashes, signatures, domain/config
  versions) plus the dependency hashes of summaries *outside* the component —
  all reconstructible bottom-up over the acyclic condensation. Per-method
  entries inside the component stay locally addressable; their cross-member
  dependency hashes are validated after loading, never used for lookup.
- **Evidence spans are a projection, not cached truth.** A semantic body hash
  deliberately survives edits that only move code (inserting lines above an
  otherwise unchanged method), but source spans captured in cached evidence do
  not. A cache hit may reuse semantic effects and evidence *structure* (stable
  IDs and edges); the spans rendered to users are re-projected from the current
  frontend facts at diagnostic time — the same "formatting is a projection"
  rule the evidence section imposes. Equivalently: a cached span is valid only
  together with the source-map version it was minted against.

Changing a leaf method invalidates:

1. its local CFG/summary;
2. callers that depended on the changed summary;
3. affected SCC peers;
4. diagnostics whose evidence depends on changed artifacts.

It should not invalidate unrelated methods because a source file timestamp
changed. The dependency graph in each summary is therefore a correctness input,
not only a performance optimization.

## Logical module boundaries

The exact Rust crate split is an implementation decision, but the logical
boundaries are required:

### Frontend / OwnIR

Responsibilities:

- source-language semantic resolution;
- canonical symbols, signatures, spans;
- OwnIR serialization;
- explicit degradation.

Must not:

- infer ownership verdicts;
- run protocol fixpoints;
- decide CI severity.

### Bridge lowering

Responsibilities:

- validate OwnIR;
- normalize identities;
- lower facts to OwnHIR;
- report unmappable facts explicitly.

Must not:

- own domain-specific fixpoint semantics;
- contain the permanent MOS/protocol/progress solver;
- emit final findings except malformed/unmappable-input diagnostics.

`own-bridge` may remain the public facade during migration, but internally it
must delegate these responsibilities instead of remaining one verdict-owning
module.

### CFG

Responsibilities:

- basic blocks and terminators;
- normal/exception/suspend edges;
- local dominance/reachability helpers;
- deterministic serialization for parity/debugging.

Must not:

- know WPF policy;
- decide resource protocols;
- construct SARIF.

### Interprocedural engine

Responsibilities:

- call graph and lifecycle roots;
- SCC condensation;
- generic summary iteration;
- summary dependency tracking;
- external model lookup;
- summary dumps and traces.

Must not:

- hard-code every domain lattice;
- parse Roslyn syntax;
- render user diagnostics.

### Analysis domains

Responsibilities:

- define lattices and transfer functions;
- define summary join/apply semantics;
- produce domain-neutral derivations;
- turn proven violations into diagnostic data.

Each domain should be an independent implementation over common CFG and summary
interfaces. The current interleaving inside a single analyzer is migration debt,
not the desired design.

### Diagnostics and evidence

Responsibilities:

- stable diagnostic/evidence data model;
- human text, SARIF, ownreport projection;
- deterministic ordering;
- source-location rendering.

Must not:

- rerun analysis;
- infer missing call targets;
- mutate summaries.

## Repository responsibility boundary

### Own.NET

Own.NET owns:

- OwnIR, OwnHIR, OwnCFG;
- call graph and summary semantics;
- static ownership/protocol/progress/region/task domains;
- diagnostic derivations;
- static uncertainty.

### OwnAudit

OwnAudit owns:

- runtime acquisition/release witnesses;
- heap retention and lifecycle observations;
- static/runtime correlation;
- confirmed/static-only/runtime-only buckets;
- audit aggregation and remediation workflow.

OwnAudit consumes Own.NET artifacts. It does not become the second static
checker.

### 007

007 owns:

- execution gates;
- artifact capture;
- replay and promotion;
- policy over evidence completeness;
- orchestration across repositories.

007 consumes reports and evidence. It does not infer ownership or protocol
summaries.

## Migration plan

### Who owns the bridge boundary, when

P-022/#259 deliberately place lowering, MOS inference, and callsite
application inside `own-bridge`, mirroring `ownir.py` for byte-parity. This
proposal calls that concentration migration debt. Both are right — at
different times — and a reader acting on only one of the two documents will
re-architect the wrong period:

| period | authoritative boundary |
|---|---|
| until Rust parity + cutover (#262) | #258/#259: MOS and lowering live in `own-bridge`, byte-parity with `ownir.py`; no seam moves |
| after cutover | a dedicated extraction slice per this proposal: `own-bridge` validates/lowers only; the generic interproc engine moves out (open question 2) |
| invariant across both | the OwnIR wire schema, verdicts, and parity artifacts do not change as part of the seam move |

### Phase 0 - documentation and parity freeze

Timing: before #262.

- Land this proposal as architecture direction only.
- #258 is closed: `spec/Bridge.md` and its behavior matrix are the merged
  normative bridge contract — keep them current as the parity baseline.
- Preserve the verdict-changing inference freeze.
- Add no new summary axis in only one engine.
- Treat current summary dumps and diagnostics as parity artifacts.

Acceptance:

- no production behavior change;
- no oracle drift;
- no new crate required merely to land the proposal.

### Phase 1 - internal seam after Rust bridge parity

Timing: after #259/#260 are stable, ideally after #262.

- Introduce an explicit internal method/operation representation, whether named
  `OwnHIR` in code or represented by equivalent Rust types.
- Make bridge lowering produce that representation.
- Move generic call graph/SCC/summary orchestration out of bridge-specific logic.
- Preserve existing MOS behavior exactly.
- Emit deterministic method-summary and call-graph dumps.

Acceptance:

- Python/Rust or old/new shadow comparison remains zero-diff;
- `own-bridge` validation/lowering is testable independently from analysis;
- MOS can be implemented and tested without reading OwnIR JSON dictionaries;
- every summary records dependencies and precision.

### Phase 2 - summary-backed lifecycle release reachability (#304)

Implement lifecycle-root reachability and must-release composition for event
subscriptions and timers.

The historical motivator, #278, is **closed**: PR #293 landed the bounded
extractor predicates (teardown context, parameter guards, symbol-based helper
reachability), and PR #302 extended the same invariant to WPF002 `Stop()`.
The landed #293/#302 extractor predicates are the current bounded
implementation and the regression floor. The first post-cutover consumer of
P-036 — tracked as #304 — will replace or generalize them with CFG-backed,
summary-composed lifecycle reasoning; #278 stays the motivating incident, not
a reusable implementation issue.

Required fixtures:

1. matching `-=` in a reachable teardown path on every exit: clean;
2. matching `-=` behind a flag: finding with branch witness;
3. matching `-=` in an uncalled method: finding with unreachable-release
   evidence;
4. helper method that always unsubscribes: clean through summary application;
5. helper that may unsubscribe: finding/advisory according to rule policy;
6. virtual/external cleanup target: explicit degraded precision;
7. exceptional exit bypassing cleanup: finding with exceptional path;
8. runtime-correlated SectorTS scenario: static-only becomes confirmed when the
   runtime identity matches.

Fixtures 1-3 are already caught (or deliberately kept silent) by the landed
#293/#302 predicates and enter this phase as regression anchors; fixtures 4-8
are the genuinely new summary-backed capability.

Acceptance:

- class-wide existence of release no longer discharges an obligation (landed
  behavior — must not regress);
- the finding contains a call/branch witness;
- no regression in current clean anchors or in the #293/#302 caught set;
- helper release is proven through summary application, not extractor-side
  symbol fixpoints;
- runtime correlation uses stable static identities;
- no rule-specific traversal duplicates the generic summary engine.

### Phase 3 - obligation summaries

- Extend the common summary envelope with protocol production/discharge.
- Use P-025/#272 as the intraprocedural foundation.
- Implement #274 across helper methods and barriers.
- Keep protocol automata declarative and domain-owned.

Acceptance:

- an obligation produced in method A and discharged in method B is recognized;
- discharge on only some callee exits remains `may`, not `must`;
- external model uncertainty is visible.

### Phase 4 - progress summaries

- Implement #275 with local loop CFG and callee `ProgressSummary`.
- Support consume-or-exit witnesses.
- Keep numeric reasoning narrow and monotonic.

Acceptance:

- helper calls can prove progress;
- helper calls can prove no progress;
- unknown progress remains explicit;
- recursive helper SCCs converge.

### Phase 5 - selective heap, region, and task expansion

Triggered by real consumers:

- #122 for cross-method exclusivity;
- #146 for caller-to-callee publisher provenance;
- field/closure/timer escape findings;
- #282 after Own.Async facts stabilize.

This phase may introduce field-sensitive heap facts, reverse propagation, or
selective context sensitivity. It must be driven by a concrete false negative or
accepted rule, not by a desire to collect fashionable analysis acronyms.

## Testing strategy

Every new interprocedural feature requires four levels of tests.

### Summary unit tests

Input:

- a normalized method body and callee summaries.

Assert:

- exact summary lattice value;
- precision and unknown reasons;
- dependency set;
- deterministic serialization.

### Callsite composition tests

Assert:

- formal-to-actual binding;
- receiver and field identity;
- normal versus exceptional effects;
- alias/fresh/consume propagation;
- multi-target joins.

### End-to-end OwnIR tests

Assert:

- frontend facts lower correctly;
- final diagnostics and ordered evidence;
- no hidden dependence on dictionary order;
- exact parity artifacts during migration.

### Negative mutation tests

Starting from a clean fixture, mutate one semantic condition:

- move release behind a branch;
- move release into an uncalled helper;
- replace `-=` with `+=`;
- insert an early return;
- change the released receiver;
- remove `finally`;
- make the call target external/unknown;
- remove loop progress.

The mutation must produce the intended diagnostic or explicit uncertainty.
Positive tests show the tool does not obstruct code. Negative tests show it
actually detects the bug.

## Architecture fitness checks

The repository should eventually enforce:

- bridge lowering does not import domain analysis implementations;
- diagnostics does not depend on solver internals;
- frontend crates do not depend on analysis;
- analysis consumes OwnHIR/OwnCFG, not OwnIR JSON maps;
- call graph and summary dumps are deterministic;
- unknown targets cannot be serialized as clean exact targets;
- summary format versions fail loudly on incompatible changes;
- every diagnostic evidence edge references valid stable IDs;
- old/new or Python/Rust shadow modes emit zero unexplained summary diffs during
  migration.

These are architecture checks, not style preferences. Without them the bridge
will slowly reabsorb the solver because that is always the shortest local path
and the worst global one.

## Prior art and chosen posture

Relevant models:

- Infer: compositional procedure summaries and SCC/fixpoint reasoning;
- CodeQL: separation of source syntax from semantic/dataflow representations and
  explicit library models;
- Roslyn: authoritative C# semantic model and per-body CFG;
- IFDS/IDE frameworks: useful later for finite distributive domains such as
  taint-like obligation propagation;
- separation logic/bi-abduction: useful prior art for heap ownership, but too
  large a prerequisite for the first slices;
- MLIR/LLVM analysis frameworks: useful implementation references, not a suitable
  source-level C# semantic substrate for Own.NET.

Chosen posture:

1. Roslyn remains the C# semantic authority.
2. OwnIR remains the versioned frontend seam.
3. OwnHIR normalizes semantics inside the core.
4. OwnCFG remains the local dataflow substrate.
5. Method summaries are the unit of interprocedural composition.
6. A generic SCC/fixpoint engine hosts domain summaries.
7. Unknown behavior is explicit.
8. Evidence is produced with the verdict.
9. Advanced frameworks are introduced only when a measured analysis need
   justifies them.

## Open questions

1. Should the internal type be named `OwnHIR`, `MethodIR`, or `SemanticProgram` in
   code? The semantic boundary matters more than the acronym.
2. Does the generic interprocedural engine belong inside `own-analysis` or in a
   new `own-interproc` crate after cutover?
3. Which summary data is part of a stable debug/parity format versus an internal
   cache format?
4. What is the canonical `MethodId` for generics, explicit interface methods,
   local functions, and lambdas?
5. Which WPF/DI lifecycle roots are built in, and which are project-declared?
6. What conservative policy should each rule use for unknown external calls?
7. How much field sensitivity is required for the first #304 slice?
8. How are callback registration and delegate target sets represented without
   pretending reflection is statically resolved?
9. Which dependency hashes are sufficient for IDE summary invalidation?
10. Which post-cutover issue owns the structural seam? (The first feature
    consumer — summary-backed lifecycle release reachability — is tracked as
    #304.)

## Acceptance criteria for this proposal

This proposal is accepted when maintainers agree on the following decisions:

- OwnIR remains the external fact contract, not the permanent solver IR;
- an internal normalized semantic representation is required;
- OwnCFG is the local-analysis substrate to be extended into the
  MIR-equivalent representation (OwnHIR operations + typed terminators);
- interprocedural behavior is expressed through first-class method summaries;
- summaries are inferred/composed through a generic SCC/fixpoint engine;
- bridge lowering, analysis, diagnostics, OwnAudit, and 007 have the boundaries
  described above;
- no verdict-changing implementation begins before the P-022 parity/cutover
  discipline permits it;
- summary-backed lifecycle release reachability (#304) is the preferred first
  production consumer: it generalizes the landed #293/#302 predicates on the
  confirmed soundness class (#278) that syntax-only release existence could
  not solve.

Acceptance of the architecture is not acceptance of every future domain. Each
new summary axis still requires its own issue, fixtures, precision policy, and
measured consumer.
