# MemoryPool `using`-owned view escape (POOL004, the idiomatic dangle)

**Pattern:** an `IMemoryOwner<T>` from `MemoryPool<T>` is held with a `using`
declaration (so it is `Dispose()`d at scope exit), but the method **returns a view of
it** — `using owner = …; return owner.Memory;`. The implicit dispose runs as the method
returns, so the caller receives a `Memory<T>` backed by a buffer already returned to the
pool: a dangling borrow / use-after-free. It is exactly
`try { return owner.Memory; } finally { owner.Dispose(); }` — the MemoryPool twin of the
ArrayPool try/finally `Memory` escape (`arraypool-memory-view-escape`, #70). The fix is to
**transfer ownership**: return the `IMemoryOwner` itself (no `using`) so the caller owns
its lifetime.

**Why it was missed before (Codex review on #73):** `using` locals are skipped by the
flow-locals candidate pass — they are auto-disposed, so normally not leak candidates — so
the owner never entered `tracked` and the returned view was not mapped to it. This slice
**desugars a tracked `using IMemoryOwner = MemoryPool.Rent(…)` declaration** into
`acquire; try { rest } finally { release }`: the implicit scope-exit dispose is threaded
onto the rest's returns (and throws), so the returned view's caller-use lands *after* the
release and trips OWN002 — reusing the same `onReturn` / `ReturnedViewOwners` machinery
that catches the ArrayPool try/finally form. Methods with no such `using` declaration are
lowered exactly as before.

**What the checker says:** the OwnLang model and the real `before.cs` both trip
**OWN002**. The ownership-transfer fix in `after.cs` returns the owner (no `using`), so the
escaped owner is untracked and the checker is silent.

**Honesty / scope.** `case.own` is a faithful hand reduction (not C# ingested by the
checker); `before.cs` / `after.cs` are representative of the bug and its fix.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); the ArrayPool twin is
`arraypool-memory-view-escape` (#70).
