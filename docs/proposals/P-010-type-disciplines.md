# P-010 — Richer type disciplines (`Own.Types`)

- **Status:** draft (horizon)
- **Depends on:** `spec/OwnCore.md` (the ownership/affine core and its fact
  vocabulary), `spec/Lifetimes.md`; relates to P-005 (`IDisposable` typestate —
  the first concrete protocol), P-006 (DI lifetimes — a region contract, not a
  protocol), P-007 (ArrayPool/Span borrow-view — the pooled-buffer instance),
  P-008 (effects — the `use !Db` half of a signature), and P-017 (multi-stack
  frontends — where `Own.Types` facts travel beyond C#). See `docs/ROADMAP.md`
  for where this sits in the strategy.

## Motivation

> **Own.Types is not trying to make C# pretty. Own.Types makes domain lies
> mechanically harder to write.**

The guiding heuristic: types aren't only about the *shape* of data
(`string`/`int`/`User`). They can encode validity, access rights, state,
dimension, order of operations, effects, protocol, ownership, even proofs. If a
bug arises because *"this value was in the wrong state / not validated / used in
the wrong place / called in the wrong order"*, it is a candidate for a smarter
type — one that makes the bad program unrepresentable instead of merely
unit-tested.

C# gives you the shape dimension and almost nothing else. The two dimensions it
lacks are exactly the interesting ones: **what a value MEANS** (`ProductId` is
not `DeclarationId`, even though both are `string`) and **what STATE it is in**
(a `Report` that is `Draft` cannot be exported). The usual C# coping mechanism —
make everything `string` / `int` / `Guid` / `Dictionary<string, object>` — is not
flexibility. It is homeless JSON pretending to be architecture.

`Own.Types` adds those dimensions as an **external static-contract layer** over
existing C#: an analyzer / source generator / `.own` spec that checks the
discipline, without rewriting the code into a new language. This is the move that
turns Own.NET from "a borrow checker for C#" into "an external static contract
layer for C#/.NET that adds ownership, typestate, effects, capabilities, and
domain types" — while the DSL stays a spec/model/contract language and pointedly
refuses to become a second C# people write business logic in.

## Map of the five pillars

```text
Own.Types
├─ Semantic primitives           — what a value MEANS
│  ├─ newtype / branded types
│  ├─ constrained (refinement) types
│  ├─ units / quantities
│  └─ strongly typed IDs
│
├─ Algebraic domain modeling     — what a value CAN BE
│  ├─ discriminated unions
│  ├─ exhaustive matching
│  ├─ Option
│  └─ Result / error unions
│
├─ State/lifetime discipline     — what STATE a value is in
│  ├─ typestate
│  ├─ owned/borrowed/must-dispose
│  ├─ event subscription lifetime
│  ├─ pooled buffer lifecycle
│  └─ ValueTask/single-use constraints
│
├─ Tooling                       — how the discipline is enforced
│  ├─ source generators
│  ├─ Roslyn analyzers
│  ├─ code fixes
│  ├─ generated docs
│  └─ OwnIR facts
│
└─ Future                        — horizon, not committed
   ├─ .own DSL
   ├─ F# generator/backend
   ├─ interop analyzers
   └─ multi-language frontends
```

The first four pillars share one restraint: brands, refinements, units, unions,
and protocols all lower to plain structs/records plus smart constructors — the
*discipline* is enforced by analyzer, not by a second type checker that could
drift from the affine core (the project's standing meta-irony).

## Scope

### 1. Semantic primitives — what a value means

1. **Branded / opaque types.** Distinguish `ProductId`, `DeclarationId`, `Email`
   though all are `string` underneath, so `GetProduct(declarationId)` is a
   diagnostic, not a 2 a.m. incident. DSL: `brand ProductId : string;`. C#:
   `[OwnBrand("ProductId")]` on a `readonly record struct` plus a smart
   constructor; the analyzer enforces that the wrapped value only enters through
   it. (Mechanically these are phantom types — see the deferred catalog.)

2. **Refinement types** — "int, but valid":
   `refinement Port : int where value >= 1 && value <= 65535;`,
   `refinement NonEmptyString : string where !String.IsNullOrWhiteSpace(value);`,
   `Age = int where 0 <= value <= 130`, `Percentage = number where 0..100`. This
   replaces the scattered `if (age < 0) throw` rituals with one declared
   predicate. The C# imitation today is value objects + smart constructors; we
   make it **declarative and analyzer-checked** so the predicate lives in one
   place and the type system, not code review, enforces the boundary.

3. **Units of measure**, à la F# `[<Measure>]`: `unit kg; unit usd; unit kzt;` so
   `metres + seconds` and `usd + kg` are compile errors. For money, currency,
   tax rates, and physical quantities — the domains where a silent unit mix-up
   is a financial bug, not a rounding one.

4. **Strongly typed IDs.** Not a new mechanism — the single most-applied
   *instance* of branded types, called out because it is the pattern developers
   reach for first: `brand OrderId : Guid; brand CustomerId : Guid;` so
   `GetOrder(customerId)` is caught even though both brands share the same
   underlying `Guid`. The analyzer's job here is narrower than general branding:
   catch **argument-order transposition** at call sites where two branded IDs of
   the same underlying type are adjacent parameters — the concrete bug this
   pillar exists to kill.

### 2. Algebraic domain modeling — what a value can be

5. **Discriminated unions.** A closed set of shapes a value can take:
   `union Shape { Circle(radius: float); Rect(w: float, h: float); }`. Lowers to
   a sealed hierarchy (or a source-generated closed struct union) that cannot be
   extended from outside the declaration — the analyzer, not `sealed` alone,
   enforces closedness across partial classes and other-assembly subclassing
   attempts.

6. **Exhaustive matching.** C#'s `switch` over a non-`enum` type has no
   exhaustiveness check at all, and even enum switches only get an ignorable
   `CS8509` warning. Own.Types promotes this to a hard diagnostic tied to the
   `union` declaration: every `switch`/pattern match over a branded union must
   cover every case or an explicit `default`/discard, and a new case added to
   the union must break every non-exhaustive match site at compile time, not at
   3 a.m. in production.

7. **`Option`.** Replaces the gap nullable reference types leave open (nothing
   stops a `string?` from silently meaning "not yet loaded" *and* "deliberately
   absent" *and* "error", all at once). `Option<T>` is a two-state union
   (`Some`/`None`); the analyzer flags unmatched `.Value` access the same way it
   flags a non-exhaustive union match — this pillar is a specialization of #6,
   not a separate mechanism.

8. **`Result` / error unions.** `Result<T, E>` as the alternative to
   exceptions-as-control-flow for expected failure. Two enforcement angles: (a)
   the exhaustiveness rule from #6 — a `Result` must be matched on both `Ok` and
   `Error`, not just unwrapped; (b) an "unobserved result" diagnostic, structurally
   the same shape as an unawaited `Task` — a `Result` that is constructed and
   never matched or propagated is silently swallowed failure.

Pillar 2's four items are one mechanism wearing three hats: a closed-shape
declaration plus an exhaustiveness check. `Option` and `Result` are simply the
one- and two-error-case unions developers reach for constantly enough to name
directly, rather than making every call site spell out a bespoke `union`.

### 3. State/lifetime discipline — what state a value is in

9. **Typestate / protocols.** Encode object state in the type so methods can
   only be called in a valid order:

   ```text
   protocol Report {
     state Draft; state Validated; state Built;
     validate: Draft     -> Validated;
     build:    Validated -> Built;
     export:   Built      -> File use !Log;
   }
   ```

   Examples: `Connection<Closed|Open>`, `Transaction<Started|Committed|RolledBack>`,
   `Json<Raw|Parsed|Validated>` (you cannot save unvalidated JSON). This composes
   directly with the ownership/affine core: a transition can **consume self**, so
   `commit: Started -> Committed` consuming `tx` makes a subsequent `rollback(tx)`
   reject — rollback-after-commit is not a runtime guard, it is a use-after-move.
   Typestate is also the generalization that subsumes **session types** (typed
   message-ordering protocols) as the special case where the object is a channel.

10. **Owned / borrowed / must-dispose.** Already built as a standalone
    diagnostic in [P-005](P-005-idisposable-ownership.md) — Own.NET already
    treats `IDisposable` as typestate C# lacks. This pillar's job is *not* to
    duplicate P-005's checker; it is to surface the same ownership verdict as a
    **type-level marker** in the signature a developer reads (`Owned<T>`,
    `Borrowed<T>`, `[OwnMustDispose]`) so the discipline is visible at the call
    site, not only in an analyzer squiggle.

11. **Event subscription lifetime.** Already covered as a resource-lifetime
    profile in P-004 (WPF) and P-006 (DI lifetime, where a subscription is one
    captive-dependency shape). Own.Types' angle: a typed subscription handle
    that is itself a two-state protocol (`Active -> Disposed`, unsubscribe
    consumes self), so double-unsubscribe and use-after-unsubscribe fall out of
    the same typestate mechanism as #9, instead of a bespoke `SUB0xx` rule.

12. **Pooled buffer lifecycle.** Already covered in
    [P-007](P-007-arraypool-span.md) (ArrayPool/Span borrow-view). Own.Types'
    angle: model a rented buffer as `Buffer<Rented|Returned>` — a two-state
    protocol exactly like #9 — so "view survives `Return`" is reported through
    the general typestate/use-after-move path rather than a parallel
    pool-specific engine.

13. **`ValueTask`/single-use constraints.** A well-known .NET footgun:
    `ValueTask` must be awaited (or converted) exactly once, and never both
    stored and awaited. Structurally this is a **single-transition protocol**
    (`Pending -> Awaited`; awaiting twice, or awaiting after `.AsTask()`, is
    use-after-move) — the same affine "consume once" mechanism as #9, applied to
    a BCL type Own.NET does not own and cannot annotate at the source, so the
    marker has to live at the call site (`[OwnSingleUse]` on the
    producing member, or an analyzer-only rule with no DSL declaration).

Pillars 10–13 are **not** new checkers to build — they are existing or
near-existing lifetime facts (P-004/005/006/007) reframed as instances of the
two general Own.Types mechanisms (ownership marker, typestate protocol). The
payoff of doing this pillar at all is *unification*: one mental model
(protocol state, consume-on-transition) instead of four bespoke rule families.

### 4. Tooling — how the discipline is enforced

14. **Source generators.** Emit the boilerplate a brand/refinement/union
    declaration implies — smart constructors, equality, `ToString`, exhaustive
    `Match`/`Switch` helper methods — so the discipline costs one declaration,
    not hand-written ceremony per type.

15. **Roslyn analyzers.** The enforcement side for every pillar above: brand-
    boundary violations (#1), predicate bypass (#2), unit mismatch (#3),
    non-exhaustive match (#6), unobserved `Result` (#8), invalid protocol
    transition / use-after-transition (#9, #11–#13).

16. **Code fixes.** A matching quick-fix per analyzer: insert the missing
    `switch` arm stub for a non-exhaustive match, wrap a raw literal in its
    brand's smart constructor, insert the missing `Dispose`/transition call.
    Diagnostics without a code fix push the discipline back onto the developer
    manually re-deriving the fix; that is the gap this item exists to close.

17. **Generated docs.** Render the `.own` declarations (brand / refinement /
    union / protocol) into human-readable reference pages, the same way
    `spec/Diagnostics.md` is the single source of truth for `OWN` codes today —
    one declaration, read by the compiler *and* the wiki, so the contract and
    its documentation cannot drift apart.

18. **OwnIR facts.** The seam every pillar above lowers through: new OwnIR fact
    kinds (`brand`, `refinement`, `union`, `protocol-state`) alongside the
    existing resource/ownership facts in `spec/OwnIR.md`, so any frontend —
    today's Roslyn C# extractor, tomorrow's OwnTS/OwnJava/OwnKotlin (P-017) —
    emits and consumes the same domain-type vocabulary without re-deriving it
    per language.

The combined picture — domain types, refinements, unions, resources, protocol
state, and effects in one signature set:

```text
brand ProductId : string;
brand OrderId : Guid; brand CustomerId : Guid;
refinement NonEmptyString : string where !String.IsNullOrWhiteSpace(value);
unit usd;
union PaymentResult { Approved(txId: string); Declined(reason: string); }
resource Db; resource ArrayPool<T>;

protocol Report {
  state Draft; state Validated; state Built;
  validate: Draft     -> Validated;
  build:    Validated -> Built;
  export:   Built      -> File use !Log;
}

fn CalculateTotal(order: Order) -> Money pure;
fn LoadOrder(id: ProductId) -> Order use Db;
fn Charge(customer: CustomerId, amount: usd) -> PaymentResult use Db;
fn RenderReport(report: Report<Validated>) -> File use !ArrayPool<byte>, !Log;
```

## Future (horizon, not committed)

Distinct from the deferred catalog below: these are things Own.Types plausibly
grows *into*, not type-theory tempo it is refusing.

- **`.own` DSL.** Today's brand/refinement/union/protocol snippets are sketch
  syntax inside this proposal, not a ratified grammar. Graduating this pillar
  means these constructs get a real entry in `spec/Grammar.md`, with the same
  test-pinned discipline as every other DSL construct.
- **F# generator/backend.** F#'s discriminated unions, units of measure, and
  records are a structural match for pillars 1–2 — a codegen backend that lowers
  `.own` declarations to *idiomatic F#* (real DUs, real `[<Measure>]`) instead of
  a C# analyzer shim, for teams that can host an F# core project inside a C#
  solution and want the compiler itself enforcing the discipline.
- **Interop analyzers.** Once an F# backend exists, the boundary itself needs
  checking: a value crossing from a real F# DU into the C#-side shim
  representation must stay branded and exhaustive across the language edge, not
  just within one language.
- **Multi-language frontends.** Ties directly to
  [P-017](P-017-multi-stack-frontends.md) — Own.Types facts (#1–#13) become one
  more fact family the OwnTS/OwnJVM frontends emit over the same OwnIR seam
  (#18) the ownership facts already use.

## Non-goals

Refuse the boil-the-ocean version. The first move is explicitly **not** dependent
types, GADTs, or higher-kinded types — that way lies a tower of type-level
arithmetic (башня type-level арифметики) where you wanted to write a function and
end up proving 2 + 2 = 4. The DSL must not become a new general-purpose language;
it stays a spec/model/contract layer. No new runtime, no rewriting the codebase —
brands, refinements, and unions lower to plain structs/records and smart
constructors, and the discipline is enforced by analyzer, not by a parallel type
checker that drifts from the core (the project's standing meta-irony).
Algebraic domain modeling (pillar 2) gets the same restraint: exhaustive matching
is enforcement of *existing* C# `switch`/pattern-match syntax, not a new
pattern-matching language grafted on top of it. `[OwnIgnore("reason")]` remains
the escape hatch.

## Deferred catalog

Surveyed and explicitly **not** first — recorded so the ideas aren't lost:

- **Dependent types** (`Vector<int, 3>` — length in the type;
  `dot: Vector<float, N> -> Vector<float, N> -> float`). Maximum strictness,
  maximum cognitive cost. Idris / Agda / Coq / Lean / F*. Not a contract layer; a
  proof obligation.
- **GADTs** (typed AST: `Expr<Int>` / `Expr<Bool>`,
  `Add: Expr<Int> -> Expr<Int> -> Expr<Int>`). Only if a typed AST / DSL /
  query-builder need appears — relevant to the Snipper / Reactor / AST-transform
  ideas, not before.
- **Phantom types** — already in scope, as the underlying mechanism behind
  brands (pillar 1, including strongly typed IDs).
- **Higher-kinded types** (abstract over `F<_>`: Functor / Monad). Do not touch:
  assembling a spaceship out of `IEnumerable`, `Task`, and pain.
- **Row types** ("an object with at least these fields"), **existential types**
  ("there is some hidden `T`" — plugin/handler systems, heterogeneous
  collections), **intersection `A & B`** / **union `A | B`** types (the
  type-theory *union*, distinct from pillar 2's closed-shape `union`
  declaration), and **gradual typing** (strict + dynamic mixed; the risk is
  `any` spreading until the type system is a decorative quality sticker).
- **Modal types** (`Html<Trusted|Untrusted>`, `Sql<Untrusted|Parameterized>`,
  `sanitize: Html<Untrusted> -> Html<Trusted>`) and **indexed types**
  (`Buffer<Initialized|Uninitialized>`, `Password<PlainText|Hash>`, pipeline
  stages) — both for trust zones, escaping, and lifecycle. These overlap heavily
  with branded + typestate, so they may fall out for free once those two land.

Priority, most-applied → academic tail: **branded/opaque · units of measure ·
typestate · refinement · discriminated unions/exhaustive matching · effect types
(P-008) · session types · phantom**, then **dependent / GADT / HKT** as the
cognitively expensive end.

## Open questions

1. **Surface:** analyzer-only (annotate C# in place) vs `.own` spec + source
   generator vs both. Brands, refinements, and unions want a generator (smart
   constructors, exhaustive-match helpers); typestate wants the analyzer + the
   affine core.
2. **Where do brands live** relative to P-006 capabilities — is a capability just
   a branded, non-`Copy` resource token, or its own kind?
3. **Refinement strength:** syntactic predicate enforced at the constructor
   boundary (cheap, sound-by-construction) vs flow-checked refinement (needs the
   verification backend, P-002). v0 should be the former.
4. **Typestate ↔ ownership seam:** confirm transitions express consume-self
   through the *existing* affine facts, so `commit` then `rollback` is reported as
   use-after-move by the one core — no second mechanism. Pillar 3's items 10–13
   are the concrete test of this seam: each must reduce to it, not spawn a
   parallel one.
5. Do **modal/indexed** types ever need their own surface, or are they always
   reducible to brand + typestate in practice?
6. **Diagnostic prefix.** `DI`, `EFF`, and `OBL` are established per-pillar
   families (see `ownlang/diagnostics.py`). Does Own.Types reserve `TYP0xx` the
   same way, or fold into core `OWN` codes with a `[type: …]` kind tag mirroring
   the existing `[resource: …]` tag? Reserving `TYP` now avoids repeating the
   `WPFxxx`-catalog-vs-emitted-code confusion recorded in
   `docs/notes/consolidation-and-positioning.md`.
7. Do discriminated-union exhaustiveness (#6) and `Option`/`Result` unwrap-safety
   (#7, #8) stay one analyzer rule family or split into separate rules sharing
   only the source-generator scaffolding?
