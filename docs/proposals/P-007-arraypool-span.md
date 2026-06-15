# P-007 — ArrayPool / Span borrow-view profile

- **Status:** in progress (P1) — **POOL001 (rented-not-returned) built**;
  POOL002–005 (views, escape, double-return) next
- **Depends on:** `spec/OwnCore.md` (OWN001 leak, OWN002 use-after-release,
  OWN003 double-release, OWN008 release-while-borrowed), the buffer/borrow model
  in `spec/`, [P-001](P-001-csharp-extractor.md). See
  [`docs/ROADMAP.md`](../ROADMAP.md) (Milestone 4).

## Motivation

Pooled-buffer misuse is not the most *frequent* .NET bug, but it is the most
*on-message* one: an owned rented buffer, borrowed views (`Span`/`Memory`) over
it, and a `Return` that invalidates every view. That is precisely
owner/borrow/release — and ordinary analyzers rarely explain it in those terms.
It is the case that shows what Own.NET is *for*:

```csharp
var arr  = ArrayPool<byte>.Shared.Rent(n);   // acquire: arr owns the pooled buffer
var span = arr.AsSpan(0, n);                  // borrow:  span is a view of arr
ArrayPool<byte>.Shared.Return(arr);           // release: invalidates dependent views
Use(span);                                    // ❌ use-after-return  (POOL002)
```

The corpus already pins two real cases (`corpus/real-world/arraypool-double-return`,
`arraypool-use-after-return`), so this profile has ground truth on day one.

## Scope

| Finding | Pattern | Core verdict |
|---------|---------|--------------|
| **POOL001** rented not returned | `Rent(...)` with no matching `Return(buf)` in the same member | `OWN001` `[resource: pooled buffer]` ✅ |
| **POOL002** view after return | a `Span`/`Memory` view used after the owner is `Return`ed | `OWN002` |
| **POOL003** double return | `Return` reachable twice for the same buffer | `OWN003` |
| **POOL004** view escapes | a borrowed `Span` returned/stored beyond the owner's lifetime | `OWN004`/`OWN008` |
| **POOL005** clear/copy past length | write/clear beyond the logical length of the rented region | (buffer-policy check) |

Resource mapping:

```text
ArrayPool<T>.Shared.Rent(n)    -> acquire(PooledBuffer, loc)   // arr owns it
arr.AsSpan(...) / new Span(arr) -> borrow(view, from = arr)     // dependent view
ArrayPool<T>.Shared.Return(arr) -> release(arr)                 // all views of arr now invalid
MemoryPool<T>.Shared.Rent(...)  -> acquire (same shape, IMemoryOwner)
```

The "Return invalidates all borrowed views" rule is the heart of it — the same
release-while-borrowed / use-after-release reasoning the core already runs, lifted
to the pool API. Generics are needed only *narrowly*: recognise the specific
symbols `System.Buffers.ArrayPool<T>.Rent/Return`, `MemoryPool<T>.Shared.Rent`,
`System.Span<T>`, `System.Memory<T>` — not "understand generics".

## Non-goals

- Whole-program / interprocedural escape of a `Span` (a view passed through many
  callees). v0 is intraprocedural; a view crossing a call boundary with unknown
  ownership is a heuristic warning (see P-005 D5).
- `stackalloc` escape is already the buffer model's job (OWN015–017); this
  profile is about *pooled* ownership and its views, not re-deriving stack escape.
- Modelling pool internals (bucketing, array clearing semantics) — POOL005 is a
  logical-length check, not a pool simulation.

## Sketch

The extractor emits `acquire`/`borrow`/`release` facts for the pool/span symbols;
the core runs its existing loan + ownership lattice (the one that already yields
OWN002/OWN008 on `.own`). Nothing new in the checker — a new *frontend mapping*
plus the known-bug replay corpus.

```text
*.cs --[extractor: Rent / AsSpan / Return symbols]--> facts.json
     --[core: ownership + loans]--> POOL001..004 @ C# line
```

**Replay targets** (P-012): `dotnet/runtime` use-after-return, Nethermind
ArrayPool leaks/double-return, AiDotNet.Tensors pooled-buffer leak/over-clear.
Catching a real one of these is the milestone-4 success condition.

## Open questions

1. View provenance: track `arr.AsSpan()` → view-of-`arr` precisely, or
   conservatively treat any `Span` derived from a rented array as a loan of it?
   (Conservative first.)
2. `Return(arr, clearArray: true)` vs sensitive buffers — does POOL005 tie into
   the existing sensitive-buffer/clear-on-release check (OWN024)?
3. How much of POOL004 (view escape) overlaps the existing OWN004/OWN015 escape
   rules — reuse, don't duplicate.
4. `IMemoryOwner<T>` / `MemoryPool` `Dispose`-based release vs `ArrayPool`'s
   explicit `Return` — one model with two release spellings?
