# P-036 - Interprocedural semantic architecture

Status: **draft**

Related work:

- [P-016 - deep C# fact extraction](P-016-deep-fact-extraction.md)
- [P-022 - Rust core migration](P-022-rust-core-migration.md)
- [P-025 - obligation protocols](P-025-obligation-protocols.md)
- [`spec/Inference.md`](../../spec/Inference.md)
- [`docs/notes/interprocedural-roadmap.md`](../notes/interprocedural-roadmap.md)
- [`docs/notes/interprocedural-tz.md`](../notes/interprocedural-tz.md)
- #258 / #259 / #260: bridge contract, Rust bridge, dual-engine parity
- #278: a release that exists syntactically but is not reachable
- #272 / #274: obligation protocols and protocol/effect summaries
- #275: consume-or-exit loop progress
- #122 / #146: exclusivity and publisher provenance
- #282: structured-concurrency contracts

## Decision in one paragraph

Own.NET should treat interprocedural analysis as a first-class semantic layer, not
as additional logic inside AST visitors or the OwnIR bridge. The external
versioned **OwnIR** JSON contract remains the frontend seam. It lowers into an
internal, typed, syntax-independent **OwnHIR** method representation. The
existing **OwnCFG** is the MIR-equivalent control-flow representation and should
remain the execution substrate for local dataflow. A derived call graph and
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
locations. #258 correctly treats this as verdict-determining behavior that must
be specified before #259 ports it.

That concentration was acceptable for the proof of concept. It is not an
acceptable permanent substrate for the next classes of work:

- #278 needs release reachability through lifecycle call chains, not a class-wide
  search for a matching `-=` or `Stop()`;
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
10. acceptance criteria for the first real consumer, #278.

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

The existing **OwnCFG** is the MIR-equivalent layer. It should represent each
method as basic blocks containing OwnHIR operations and explicit terminators:

```text
Goto
Branch
Switch
Call
Return
Throw
AwaitSuspend
```

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

#278 shows that intraclass syntax matching is not lifecycle reasoning. A
reachable-release analysis needs explicit roots and entry contracts.

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
spans. Diagnostic formatting is a projection. OwnAudit may correlate those IDs
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

### Phase 0 - documentation and parity freeze

Timing: before #262.

- Land this proposal as architecture direction only.
- Finish #258 and merge the normative current bridge contract.
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

### Phase 2 - #278 as the first feature consumer

Implement lifecycle-root reachability and must-release composition for event
subscriptions and timers.

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

Acceptance:

- class-wide existence of release no longer discharges an obligation;
- the finding contains a call/branch witness;
- no regression in current clean anchors;
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
7. How much field sensitivity is required for the first #278 slice?
8. How are callback registration and delegate target sets represented without
   pretending reflection is statically resolved?
9. Which dependency hashes are sufficient for IDE summary invalidation?
10. Which post-cutover issue owns the structural seam, and which issue owns the
    first #278 feature consumer?

## Acceptance criteria for this proposal

This proposal is accepted when maintainers agree on the following decisions:

- OwnIR remains the external fact contract, not the permanent solver IR;
- an internal normalized semantic representation is required;
- OwnCFG is the MIR-equivalent local analysis representation;
- interprocedural behavior is expressed through first-class method summaries;
- summaries are inferred/composed through a generic SCC/fixpoint engine;
- bridge lowering, analysis, diagnostics, OwnAudit, and 007 have the boundaries
  described above;
- no verdict-changing implementation begins before the P-022 parity/cutover
  discipline permits it;
- #278 is the preferred first production consumer because it is a confirmed
  soundness hole that syntax-only release existence cannot solve.

Acceptance of the architecture is not acceptance of every future domain. Each
new summary axis still requires its own issue, fixtures, precision policy, and
measured consumer.
