# P-007 — ArrayPool / Span borrow-view profile

- **Status:** in progress (P1) — **POOL001 (rented-not-returned) built**; **POOL002 (Span/Memory
  view used after `Return` → OWN002) built** and **POOL004 (view ESCAPE) first slice built** — a
  `buf.AsSpan()` / `buf.AsMemory()` / `new Span<T>(buf)` view is a borrow lowered to a use of the
  owner (`ViewOwner` in the extractor), so using it after `Return` trips OWN002; because a
  `Memory<T>` (unlike a ref-struct `Span`) can leave the method, RETURNING a dangling `Memory` view
  is caught at the escape (corpus `arraypool-span-view-after-return`, `arraypool-memory-view-escape`).
  The borrow checker on real C#. **POOL005 (full-length view over-read → OWN025) first slice
  built** — an unbounded `buf.AsSpan()` / `buf.AsMemory()` / `new Span<T>(buf)` over a `Rent`ed
  local reaches past the logical length `n` into the oversized `[n, Length)` tail; the extractor
  emits an `overspan` fact and the core raises OWN025 `[resource: pooled buffer]` at the view —
  both when the view is used in an EXPRESSION (`Emit(buf.AsSpan())`) and when it is a local-decl
  INITIALIZER (`var copy = buf.AsSpan().ToArray();`, `Span<T> s = buf.AsSpan();`) (corpus
  `arraypool-fullspan-overread`) — and the **`.Length` view spelling** too (`buf.AsSpan(0, buf.Length)`
  / `new Span<T>(buf, 0, buf.Length)`, where the oversized self-`.Length` is the bound; corpus
  `arraypool-length-overread`). A *write*/wipe like `Array.Clear(buf, 0, buf.Length)` is deliberately
  NOT flagged — it zeros the tail (a safe clear-before-`Return`) and exposes nothing; only a
  read-capable VIEW is the over-read. **POOL003 (double-return → OWN003) is built** for ArrayPool
  (try/finally + aliased-receiver, corpus `arraypool-double-return` / `arraypool-aliased-receiver`),
  and **MemoryPool is now tracked** — a `MemoryPool<T>.Rent` `IMemoryOwner` is released by Dispose,
  so its leak / double-dispose ride the same flow as POOL001/003 (corpus `memorypool-double-dispose`
  → OWN003), and its `owner.Memory` / `owner.Memory.Span` is a borrow lowered to a use of the OWNER
  (`ViewOwner`), so reading the view after `Dispose` trips **POOL002 → OWN002** (corpus
  `memorypool-view-after-dispose`). The idiomatic `using owner = MemoryPool.Rent(…); return
  owner.Memory;` — which dangles after the implicit scope-exit dispose — is caught too:
  the flow desugars a tracked `using IMemoryOwner` declaration to `acquire; try { rest }
  finally { release }`, so the returned view is read after the release (**POOL004 → OWN002**;
  corpus `memorypool-using-view-escape`). A POOL005 view stored in a FIELD is next
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
| **POOL003** double return | `Return`/`Dispose` reachable twice for the same buffer (ArrayPool *and* MemoryPool) | `OWN003` ✅ |
| **POOL004** view escapes | a borrowed `Span` returned/stored beyond the owner's lifetime | `OWN004`/`OWN008` |
| **POOL005** read/copy past length | a full-length **view** (`buf.AsSpan()`, no bound) **or** the `.Length` spelling (`buf.AsSpan(0, buf.Length)`) reads/copies beyond the logical length (a write/wipe like `Array.Clear(buf, 0, buf.Length)` is NOT flagged — it exposes nothing) | `OWN025` `[resource: pooled buffer]` ✅ (a view stored in a FIELD next) |

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

1. **(resolved)** View provenance: track `arr.AsSpan()` → view-of-`arr` precisely, or
   conservatively treat any `Span` derived from a rented array as a loan of it? —
   **precise-by-identifier** was the implemented behaviour from the start (`ViewOwnerOf`
   resolves the view through its declaration's `AsSpan`/`new Span<T>` initializer to the
   *specific* owner; two live buffers never conflate). The one gap was **reassignment**: the
   owner was read from the declaration only, so after `v = otherBuf.AsSpan()` every later
   reference to `v` was still attributed to the original buffer — a false OWN002 when that
   original was already `Return`ed. Closed (b′): an assignment *target* is not a use, and a
   reference past a reassignment of the view local drops the declared owner (silent). The fix
   only ever removes a use, so it cannot manufacture a false positive; full flow-sensitive
   per-path provenance (branch-merge, loop back-edges) is still deferred. Pinned by
   `FlowLocalsSample.ReassignedView` (exactly one OWN002 on the pre-reassignment owner).
2. `Return(arr, clearArray: true)` vs sensitive buffers — does POOL005 tie into
   the existing sensitive-buffer/clear-on-release check (OWN024)?
3. How much of POOL004 (view escape) overlaps the existing OWN004/OWN015 escape
   rules — reuse, don't duplicate.
4. **(resolved)** `IMemoryOwner<T>` / `MemoryPool` `Dispose`-based release vs
   `ArrayPool`'s explicit `Return` — yes, one flow model, two release spellings: a
   `MemoryPool.Rent` owner is tracked as an IDisposable (released by `Dispose`,
   arg-passing is an escape), an `ArrayPool.Rent` buffer by `Return` (arg-passing is
   a borrow). Both feed the same acquire/use/release lattice → POOL001/002/003.
