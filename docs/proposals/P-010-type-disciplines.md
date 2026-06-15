# P-010 — Richer type disciplines (`Own.Types`)

- **Status:** draft (horizon)
- **Depends on:** `spec/OwnCore.md` (the ownership/affine core and its fact
  vocabulary), `spec/Lifetimes.md`; relates to P-006 (capability/lifetime — where
  branded `resource`/capability types are held), P-008 (effects — the `use !Db`
  half of a signature), and P-005 (IDisposable typestate — the first concrete
  protocol). See `docs/ROADMAP.md` for where this sits in the strategy.

## Motivation

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

`Own.Types` adds those two dimensions as an **external static-contract layer**
over existing C#: an analyzer / source generator / `.own` spec that checks the
discipline, without rewriting the code into a new language. This is the move that
turns Own.NET from "a borrow checker for C#" into "an external static contract
layer for C#/.NET that adds ownership, typestate, effects, capabilities, and
domain types" — while the DSL stays a spec/model/contract language and pointedly
refuses to become a second C# people write business logic in.

## Scope

The four most-applied disciplines, in priority order. Each has a `.own`
declaration and a checked C# imitation; none requires a runtime.

1. **Branded / opaque types.** Distinguish `ProductId`, `DeclarationId`, `Email`
   though all are `string` underneath, so `GetProduct(declarationId)` is a
   diagnostic, not a 2 a.m. incident. DSL: `brand ProductId : string;`. C#:
   `[OwnBrand("ProductId")]` on a `readonly record struct` plus a smart
   constructor; the analyzer enforces that the wrapped value only enters through
   it. (Mechanically these are phantom types — see the catalog.)

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

4. **Typestate / protocols.** Encode object state in the type so methods can only
   be called in a valid order:

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

The combined picture — domain types, refinements, resources, protocol state, and
effects in one signature set:

```text
brand ProductId : string;
refinement NonEmptyString : string where !String.IsNullOrWhiteSpace(value);
resource Db; resource ArrayPool<T>;

protocol Report {
  state Draft; state Validated; state Built;
  validate: Draft     -> Validated;
  build:    Validated -> Built;
  export:   Built      -> File use !Log;
}

fn CalculateTotal(order: Order) -> Money pure;
fn LoadOrder(id: ProductId) -> Order use Db;
fn RenderReport(report: Report<Validated>) -> File use !ArrayPool<byte>, !Log;
```

## Non-goals

Refuse the boil-the-ocean version. The first move is explicitly **not** dependent
types, GADTs, or higher-kinded types — that way lies a tower of type-level
arithmetic (башня type-level арифметики) where you wanted to write a function and
end up proving 2 + 2 = 4. The DSL must not become a new general-purpose language;
it stays a spec/model/contract layer. No new runtime, no rewriting the codebase —
brands and refinements lower to plain structs and smart constructors, and the
discipline is enforced by analyzer, not by a parallel type checker that drifts
from the core (the project's standing meta-irony). `[OwnIgnore("reason")]` remains
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
- **Phantom types** — already in scope, as the underlying mechanism behind brands.
- **Higher-kinded types** (abstract over `F<_>`: Functor / Monad). Do not touch:
  assembling a spaceship out of `IEnumerable`, `Task`, and pain.
- **Row types** ("an object with at least these fields"), **existential types**
  ("there is some hidden `T`" — plugin/handler systems, heterogeneous
  collections), **intersection `A & B`** / **union `A | B`** types, and
  **gradual typing** (strict + dynamic mixed; the risk is `any` spreading until
  the type system is a decorative quality sticker).
- **Modal types** (`Html<Trusted|Untrusted>`, `Sql<Untrusted|Parameterized>`,
  `sanitize: Html<Untrusted> -> Html<Trusted>`) and **indexed types**
  (`Buffer<Initialized|Uninitialized>`, `Password<PlainText|Hash>`, pipeline
  stages) — both for trust zones, escaping, and lifecycle. These overlap heavily
  with branded + typestate, so they may fall out for free once those two land.

Priority, most-applied → academic tail: **branded/opaque · units of measure ·
typestate · refinement · effect types (P-008) · session types · phantom**, then
**dependent / GADT / HKT** as the cognitively expensive end.

## Open questions

1. **Surface:** analyzer-only (annotate C# in place) vs `.own` spec + source
   generator vs both. Brands and refinements want a generator (smart
   constructors); typestate wants the analyzer + the affine core.
2. **Where do brands live** relative to P-006 capabilities — is a capability just
   a branded, non-`Copy` resource token, or its own kind?
3. **Refinement strength:** syntactic predicate enforced at the constructor
   boundary (cheap, sound-by-construction) vs flow-checked refinement (needs the
   verification backend, P-002). v0 should be the former.
4. **Typestate ↔ ownership seam:** confirm transitions express consume-self
   through the *existing* affine facts, so `commit` then `rollback` is reported as
   use-after-move by the one core — no second mechanism.
5. Do **modal/indexed** types ever need their own surface, or are they always
   reducible to brand + typestate in practice?
