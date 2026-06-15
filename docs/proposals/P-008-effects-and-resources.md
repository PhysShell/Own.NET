# P-008 — Effects & Resources (`Own.Effects` / `Own.Resources`)

- **Status:** draft (horizon — not a near-term commitment)
- **Depends on:** `spec/OwnCore.md` (the ownership/resource core and its fact
  vocabulary), `spec/Lifetimes.md`; relates to P-006 (DI lifetime / captive
  dependency — layer policies) and P-010 (richer type disciplines — where the
  `resource`/capability types would actually live). See `docs/ROADMAP.md` for
  where this sits in the strategy.

## Motivation

Ownership answers *who owns a value*. It says nothing about *what a function
reaches for*: the DB, the clock, the log, the network, a pooled buffer. In C#
those are ambient globals dressed up with tidy namespaces — `ArrayPool.Shared`,
`DateTime.Now`, `Console.WriteLine`, a captured `DbContext` — and a method
signature lies about all of them. A `CalculateTax(doc)` that quietly hits the
database has the same type as one that doesn't.

The honest-interface thesis we already apply to ownership extends cleanly: make
a function's **external effects part of its interface**, checkable by the one
core, *without* threading `world0 → world1 → world2` by hand. That last clause is
the whole point — explicit effects are good, manual world-threading is
bookkeeping, not programming.

## Scope

Declared effects in OwnLang signatures, visible but not hand-threaded:

```text
resource Db; resource Log; resource Clock; resource ArrayPool<T>;

fn CalculateTax(doc: Declaration) -> Money pure;
fn LoadRates() -> Rates                  use DbRead, Clock;
fn SaveDeclaration(doc: Declaration)     use !DbWrite, !Log;
fn Hash(data: Bytes) -> Hash             use !ArrayPool<byte>;
```

Direction markers (borrowed from Wybe): no prefix = read/input only; `!` =
read+write/mutate. `use Log` reads, `use !Log` writes; `use Db` reads,
`use !Db` writes.

A resource may also carry an acquire/release protocol — capability *and*
ownership in one declaration, so the signature says "uses and mutates the pool"
instead of the pool being a global dumping ground:

```text
resource ArrayPool<T> {
  acquire Rent(size: int) -> owned Buffer<T>;
  release Return(buf: owned Buffer<T>);
}
```

What the core catches (effects flow up callees to callers like loans do):

1. **Hidden effects** — a `pure` function that does IO/DB/Log/Clock/Pool.
2. **Unprovided resource** — calling `use !Db` where `Db` isn't permitted.
3. **Wrong direction** — allowed `use Db` (read) but performs a write.
4. **Unpaired protocol** — `Rent` without `Return`, `BeginTransaction` without
   `Commit`/`Rollback` (this is just ownership of the capability handle).
5. **Architecture violations** — Domain `use !HttpClient`; Validation `use !Db`;
   UI `use !FileSystem`.

Diagnostics:

```text
EFF001  undeclared effect (e.g. DbRead)
EFF002  pure method uses Clock/Network/Db/Log/Pool
EFF003  forbidden effect in layer Domain
EFF004  mutable resource used without ! permission
```

## Non-goals

The most important section. We are **not** building:

- a full algebraic-effects / effect-handlers calculus;
- a monad-transformer replacement (no `ReaderT Config (StateT Log IO)` killer);
- a model of *all* of .NET's effect surface at once.

Start from an **API → effect spec table** and a handful of effects — Db
read/write, Log, Clock, Network, FileSystem, Pool — and grow it bug- and
architecture-driven. This lands **after** the concrete leak/DI checkers (P-004…
P-007) have proven value, so Own.NET ships an effect checker because real code
needed one, not a philosophical purity analyzer in search of a bug.

## Sketch

Effects are computed exactly like loans: a function's effect set is the union of
its own primitive effects and its callees', checked against its declaration. No
new engine — the core already does upward dataflow.

```text
*.cs --[Roslyn extractor]--> facts.ownir.json --[Python core]--> EFF001..EFF004
         |                         ^
         +-- api→effect spec ------+   (DateTime.Now ⇒ Clock, Console.WriteLine ⇒ !Console)
```

The Roslyn extractor (P-001's seam) carries no effect knowledge of its own; it
reads a spec table the same way the core reads `spec/`:

```yaml
resources:
  ArrayPoolByte:
    acquire: { symbol: System.Buffers.ArrayPool<byte>.Rent,   effect: "!Pool<byte>", returns: owned Buffer<byte> }
    release: { symbol: System.Buffers.ArrayPool<byte>.Return,  consumes: arg0 }
  Clock:   { read:  { symbol: System.DateTime.Now,             effect: "Clock" } }
  Console: { write: { symbol: System.Console.WriteLine,        effect: "!Console" } }
```

So given `var now = DateTime.Now; Console.WriteLine(now);` inside a method
declared `[OwnPure]`, the core reports *"Foo uses undeclared resources: Clock,
!Console."* C# surface mirrors the DSL:

```csharp
[OwnPure]                       // EFF002 if it touches the world
[OwnUses("DbRead")]             // read-only
[OwnUses("!Log")]              // mutating
```

Strictness ramps for legacy — warn-only → strict per folder → per namespace →
strict for new code only — so a brownfield solution can adopt it incrementally
instead of drowning in EFF001 on day one. Per-layer policies (Domain forbids
`!Db`, `!Http`; UI forbids `!FileSystem`) reuse P-006's layer machinery.

## Background — why resources, not monads

A quick survey of how pure languages let the dirty world in, and why we copy the
last one:

- **Haskell monads** (`IO a`): effect wrapped in a type, sequenced via `bind`/
  `do`. Honest, but `IO` is one giant box — it says "touches the world", not
  *which part*.
- **Clean uniqueness typing** (`*File -> *File`): explicit and unique; the
  compiler proves a single reference. Orthogonal to *what* effect it is.
- **Mercury** modes/determinism + unique modes (`io::di, io::uo`): world-state
  threaded explicitly — the bookkeeping we want to avoid.
- **Wybe resources**: named, declared, scoped, **directional** implicit
  parameters (`def foo() use !io`). Interface integrity = no hidden effects, and
  no hand-threading. **Plasma** adopts these, arguing resources compose more
  directly than monad-transformer towers.

The thesis we act on: *don't hide effects, make them part of the interface, but
without hand-threading `world0/world1/world2`.* A resource is a global that had
to pass passport control — the dependency is visible in the signature.
Resources and ownership/uniqueness are **orthogonal and compose**: in Wybe `io`
is both a resource and unique, which is exactly the seam where this proposal
meets the existing core.

## Open questions

1. Where do `resource` declarations live — a new `spec/Effects.md` vocabulary,
   or folded into P-010's type discipline? (Leaning: P-010 owns the types,
   `spec/Effects.md` owns the catalogue + diagnostics.)
2. Effect *polymorphism*: how does a higher-order `Map(f)` propagate `f`'s
   effects without inventing effect variables we swore off? (Probably: it just
   unions them, no row-polymorphism.)
3. Granularity of `Db` — one resource, or `DbRead`/`DbWrite` as the `!` already
   implies? The samples above mix both; pick one before shipping.
4. Does `pure` mean *no resources* or *no `!` resources*? (A read-only `Clock`
   user is not referentially transparent — so `pure` should mean no resources
   at all, and `LoadRates` is `use DbRead, Clock`, never `pure`.)
5. Ordering vs P-004…P-007: this is explicitly downstream of the concrete leak
   checkers. Confirm it stays a horizon item until at least one of them ships.
