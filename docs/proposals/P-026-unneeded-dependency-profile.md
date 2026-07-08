# P-026 — Unneeded-dependency profile (`Own.Lean`)

- **Status:** draft — not started.
- **Depends on:** [P-001](P-001-csharp-extractor.md) (the Roslyn extractor
  seam), [P-006](P-006-di-lifetimes.md) (the DI `services[]` registration
  graph — YDN002 extends its facts with the closed generic arguments the
  existing graph collapses away, see Sketch), [P-015](P-015-configuration-surface.md)
  (severity/opt-in surface for the phase-2 heuristics). Bounded explicitly
  against [P-021](P-021-async-audit-pack.md) (`ASYNC040` already owns the
  "trivial async passthrough" case — not duplicated here) and
  [P-023](P-023-architecture-guard.md) (Own.Arch gates *forbidden* structure;
  this profile flags *provably redundant* structure — different verdict shape,
  never a build gate).

## Motivation

The `you-dont-need/You-Dont-Need` meta-list (a curated collection of
"You Might Not Need Lodash/Moment/Redux/…" write-ups) makes one real point
under all the individual takes: teams often reach for a popular dependency
because it is popular, not because the problem in front of them needs it. The
honest version of that point is not "dependencies are bad" — it is that every
dependency has to clear a bar:

```text
dependency_value > dependency_cost
```

where cost is never just install size — it is maintenance, transitive CVEs,
build complexity, onboarding, and the debugging friction of an indirection
layer nobody on the team wrote. .NET has its own instances of the same
pattern: an `AutoMapper` profile that copies five identically-named properties
and nothing else, a `MediatR` handler with exactly one implementation and no
pipeline behaviours standing in for a direct method call. The libraries are
not the problem — using them where they buy nothing is.

The trap is that "you don't need X" is trivially easy to turn into an
opinionated hot-take generator (see the source list's own "You Might Not Need
TypeScript" entry) that flags a library's mere presence. That is exactly the
kind of noisy, ungrounded quality gate this project's other proposals
deliberately reject (see P-023's "no SOLID detector" stance). So the scope
here is narrower and stricter than the inspiration:

> **Own.Lean never passes judgment on a library. It flags one call site at a
> time, only when the code at that site proves the abstraction added nothing
> — and the moment any real customization is visible, it stays silent.**

## Scope

### MVP — deterministic, evidence-only

| Code | Finding | Evidence required | Suggestion |
|------|---------|--------------------|------------|
| `YDN001` | `AutoMapper` `CreateMap<TSrc,TDest>()` (or `Profile`-declared map) that is a pure 1:1 copy | every public writable member of `TDest` has an exact-name, assignable-type public readable counterpart on `TSrc`; **no** `.ForMember`/`.Ignore`/`.ConvertUsing`/custom value resolver/`.ReverseMap`; member count within a configurable bound (default 10) | replace with an explicit object initializer or a mapping constructor |
| `YDN002` | `MediatR` `IRequestHandler<TReq[,TResp]>` resolved via `ISender`/`IMediator` with exactly one registered implementation and zero registered `IPipelineBehavior<,>` (open or closed) anywhere in the DI graph | needs the DI registration graph's generic arguments preserved per `IRequestHandler<TReq[,TResp]>` registration (see Sketch — today's graph collapses these) | inject the handler directly instead of dispatching through the mediator |

`YDN001` is structurally the same shape already used for `DI001` (P-006): read
a graph the extractor already builds, compare cardinalities and declared
customization, emit a verdict only when the customization set is empty.
`YDN002` needs the same shape but over a graph the extractor does not yet
build in the needed resolution — see Sketch. Neither rule inspects call-site
*style* — only the declared shape of the mapping/registration.

### Phase 2 — heuristic, report-only, opt-in via P-015

| Code | Finding | Confidence |
|------|---------|------------|
| `YDN010` | A DI-registered service with exactly one registration across the whole solution, not exposed as a public extension point, and never re-registered in a test project | heuristic — a real single-impl service and a "this interface is pure ceremony" service look identical without knowing intent; ships as report-only or not at all |

This tier stays report-only, never a build gate, and is the honest limit of
what this profile should attempt — see Non-goals for the parts of the "You
Don't Need" list that were deliberately left out rather than downgraded to
Phase 2.

## Non-goals

- **No library blocklist.** "Don't use Lodash/Axios/Moment" has no .NET
  analogue that would be evidence rather than opinion, and even in spirit,
  Own.Lean does not ship a list of disfavoured packages. Every finding names a
  specific call site and the specific evidence at it.
- **No "replace the ORM with hand-written SQL" suggestion.** Whether a
  hand-rolled query beats an ORM call depends on performance requirements this
  tool cannot observe statically. Not evidence-based; not built.
- **No reflection → source-generator suggestion.** There is no oracle for
  "this reflection could have been codegen'd" short of writing the generator —
  guesswork, not a finding.
- **No JSON → MessagePack/binary-format suggestion.** A wire-format choice
  depends on external constraints (interop, human-readability requirements)
  invisible to static analysis.
- **No reimplementation of existing Roslyn/FxCop LINQ micro-optimizations**
  (`.Where(p).Count()` → `.Count(p)` and siblings — already `CA1826`/`CA1827`/
  `CA1828`/`CA1829`). Own.NET's differentiator is checks nobody else runs, not
  a third copy of a rule two analyzers already ship.
- **No build-blocking severity, ever, for this family.** Every `YDN###` is
  info/warning and never wired into the P-023 architecture-guard ratchet. A
  false positive here costs a reviewer one comment, not a red PR.
- **No bundle-size / transitive-CVE / dependency-count scoring.** That is a
  supply-chain audit tool (NuGet advisory scanning, dependency-graph size),
  a different project; if ever pursued it is its own proposal, not folded in
  here.
- **No hostility to AutoMapper or MediatR as libraries.** Both are legitimate
  the moment they are used for what they are for — custom resolvers, cross-
  cutting pipeline behaviours, polymorphic dispatch over many handlers.
  `YDN001`/`YDN002` are silent the instant any of that evidence appears.

## Sketch

```text
C# source --[Roslyn extractor]--> mapping-profile facts (YDN001)
                              \-> services[] graph, extended with closed generic args (YDN002)
                                              |
                                     [core: same Python seam]
                                              |
                                    YDN### verdicts --> SARIF + markdown
```

`YDN001` needs one new extractor fact family: for each `CreateMap<TSrc,TDest>`
call (or `Profile`-declared map), emit the two member lists plus whichever
customization calls (`.ForMember`, `.Ignore`, `.ConvertUsing`, `.ReverseMap`)
appear in the same fluent chain.

`YDN002` is **not** a free ride on the existing P-006 `services[]` graph, and
the MVP scope above was wrong to claim otherwise (caught in review): the
extractor's `DiTypeName` helper
(`frontend/roslyn/OwnSharp.Extractor/Program.cs`) deliberately reduces a
generic registration to its rightmost identifier — `IRequestHandler<Foo,Bar>`
and `IRequestHandler<Baz,Qux>` both become the bare `IRequestHandler` — because
P-006's captive-lifetime checks never needed to distinguish closed generic
arguments. `YDN002` does need that distinction: counting "implementations of
*this* `TReq[,TResp]`" from an identifier-only graph would silently count
every unrelated handler in the solution as the same bucket the moment a
project has more than one MediatR request. The fix is a small, additive
extractor change — preserve the closed type-argument pair (and the
`IPipelineBehavior<,>` type arguments, open or closed) alongside the existing
service/impl identifiers when the generic is one of the MediatR marker
interfaces — not a reinterpretation of the current collapsed facts.

## Open questions

1. Where does the "still trivial" member-count bound for `YDN001` live —
   hardcoded default, or a P-015 per-project knob? Leaning: a default with a
   P-015 override, consistent with how severity is already configured
   elsewhere.
2. Does `YDN002` also need to inspect the handler body for inline cross-
   cutting code (logging/validation) that a pipeline behaviour would normally
   own, or is DI-graph evidence (impl count + behaviour count) sufficient on
   its own? Needs a trial against a real MediatR-using corpus sample.
3. Naming/positioning: a standalone `Own.Lean` family, or a phase-4 "ceremony"
   tier under `Own.Arch` (P-023)? Leaning: standalone — P-023 gates *forbidden*
   structure (a graph-edge violation); this profile flags *provably redundant*
   structure (an indirection with zero customization). The verdict shapes
   differ (a gate vs. a suggestion), which argues for keeping them separate
   families sharing only the extractor seam.
4. Prefix: following the `ASYNC`/`ARCH`/`OBL` precedent of a family-specific
   code rather than overloading `OWN###` — `YDN###` as proposed above, unless
   a shorter/clearer prefix surfaces during naming review.
