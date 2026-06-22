# MemoryPool view used after dispose (POOL002, the Dispose-released pool)

**Pattern:** `MemoryPool<T>.Shared.Rent(n)` returns an `IMemoryOwner<T>` whose pooled
buffer is exposed as a `Memory<T>` via `owner.Memory` (and a `Span<T>` via
`owner.Memory.Span`). That view is a **borrow** of the owner — valid only while the
owner is alive. Reading it after `owner.Dispose()` (which returns the memory to the
pool) reads memory that may already belong to another renter: a use-after-free. The
fix is to read the view *before* disposing, or to let a `using` own the lifetime.

This is the MemoryPool twin of `arraypool-span-view-after-return`: there a `Span`
view of a `Rent`ed array is used after `Return`; here a `Memory`/`Span` view of an
`IMemoryOwner` is used after `Dispose`. Both lower the view to a use of the **owner**
(`ViewOwner` in the extractor), so the core sees a plain use-after-release.

**What it adds:** the extractor now recognises `owner.Memory` / `owner.Memory.Span`
(resolved via the `System.Buffers.IMemoryOwner<T>.Memory` property) as a borrow of the
owner — completing the MemoryPool story begun in #72 (which tracked the owner's
acquire / release lifecycle: POOL001 leak, POOL003 double-dispose). With the view
recognised, a view-local read after an explicit `owner.Dispose()` is
**POOL002 → OWN002**. (The *returned*-`Memory` dangle from the idiomatic `using`
owner — `using owner; return owner.Memory;`, where the implicit scope-exit dispose
hands a stale view to the caller — is a follow-up: `using` locals are skipped as
non-leak candidates, so that escape needs the scope-exit dispose modelled as a
release on the return path, like the ArrayPool try/finally `Memory` escape.)

**What the checker says:** the OwnLang model and the real `before.cs` both trip
**OWN002** (use after release). The `using` fix in `after.cs` reads the view while the
owner is alive and is silent.

**Honesty / scope.** `case.own` is a faithful hand reduction (not C# ingested by the
checker); `before.cs` / `after.cs` are representative of the bug and its fix.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md).
