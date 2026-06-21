# ArrayPool full-length view over-read (POOL005)

**Pattern:** a pooled array from `ArrayPool<T>.Shared.Rent(n)` is *oversized* — the
pool returns an array of `Length >= n`, not exactly `n`. Code that takes a
FULL-length view of it (`buf.AsSpan()` / `buf.AsMemory()` / `new Span<T>(buf)`, all
with **no length bound**) and reads, copies, or writes through that view processes
the `n` valid bytes **plus** the stale `[n, Length)` tail — bytes a *previous*
renter left behind. That is a correctness bug (wrong length) and an information
disclosure (a prior renter's data leaks out). The fix is a bounded view:
`buf.AsSpan(0, n)`.

This is P-007's **POOL005** ("clear/copy past the logical length") — the over-read /
over-copy vehicle is the unbounded view. It is distinct from **OWN024** (a
*sensitive* buffer not cleared on release): POOL005 is reading/copying *too much*;
OWN024 is clearing *too little*.

**What the checker says:** the OwnLang model trips **OWN025**
`[resource: pooled buffer]` at the view. The extractor recognises an unbounded
`AsSpan()`/`AsMemory()`/`new Span<T>(buf)` over a `Rent`ed local (by the resolved
`System.MemoryExtensions` / `System.Span<T>` BCL symbols, so a look-alike is not
mistaken for it) and emits an `overspan` fact; the core — and the hand `case.own`
reduction — raise OWN025. The buffer is still `Return`ed, so there is no OWN001
leak and no OWN002 use-after-return; the only finding is the over-read itself.

**Honesty / scope.** `case.own` is a faithful hand reduction (not C# ingested by the
checker); `before.cs` / `after.cs` are representative of the bug and its fix, not a
verbatim PR diff. This first slice catches the unbounded view used in an
*expression* (`Emit(buf.AsSpan())`, `buf.AsSpan().CopyTo(...)`, `... .ToArray()`).
A view stored in a local first (`var s = buf.AsSpan(); Use(s);`) and the
`Array.Clear(buf, 0, buf.Length)` spelling are follow-ups.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); replay target
AiDotNet.Tensors pooled-buffer over-clear/over-read.
