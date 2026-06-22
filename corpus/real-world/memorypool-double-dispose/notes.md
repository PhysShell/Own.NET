# MemoryPool double-dispose (POOL003, the Dispose-released pool)

**Pattern:** `MemoryPool<T>.Shared.Rent(n)` returns an `IMemoryOwner<T>` whose
backing memory is returned to the pool by **`Dispose()`** (there is no `Return`).
Disposing the same owner twice — classically once on the normal path and again in a
`finally`/`Dispose`, or two explicit `Dispose()` calls — double-releases the memory,
so the pool can hand it to two renters simultaneously. This is the MemoryPool twin of
`arraypool-double-return` (dotnet/runtime#33767).

**What it adds:** the extractor now tracks `MemoryPool<T>.Shared.Rent` as an owned
resource (an `IMemoryOwner` released by `Dispose`, the IDisposable path — *not* a
`Return`-based pool buffer). With that one acquire recognised, the existing
flow-sensitive checker covers the whole MemoryPool family: **POOL001** (never
disposed → OWN001), **POOL002** (owner used after `Dispose` → OWN002), and
**POOL003** (this case — disposed twice → **OWN003**).

**What the checker says:** the OwnLang model and the real `before.cs` both trip
**OWN003** (double release). The `using` fix in `after.cs` disposes exactly once and
is silent.

**Honesty / scope.** `case.own` is a faithful hand reduction (not C# ingested by the
checker); `before.cs` / `after.cs` are representative of the bug and its fix. The
`IMemoryOwner.Memory.Span` *view* tracking (a borrow of the owner) is a follow-up;
this slice covers the owner's own acquire / use / release lifecycle.

Reference: dotnet/runtime#33767; [P-007](../../../docs/proposals/P-007-arraypool-span.md).
