# ArrayPool over-read / over-clear — the `.Length` spelling (POOL005)

**Pattern:** a pooled array from `ArrayPool<T>.Shared.Rent(n)` is *oversized*
(`Length >= n`). Code that uses `buf.Length` — the oversized backing length — as
the operative length, rather than the rented `n`, reaches past the valid payload
into the stale `[n, Length)` tail a previous renter left:

- `buf.AsSpan(0, buf.Length)` / `new Span<T>(buf, 0, buf.Length)` — an over-**read**
  (the consumer sees `n` valid bytes plus the stale tail: a wrong-length read and a
  potential information disclosure);
- `Array.Clear(buf, 0, buf.Length)` — an over-**clear** (touches the pool's tail
  past the data that was actually written).

The fix is to bound by the logical length: `buf.AsSpan(0, n)`, `Array.Clear(buf, 0, n)`.

This is the `.Length` sibling of `arraypool-fullspan-overread` (which catches the
unbounded `buf.AsSpan()`): same OWN025, a different way of writing the oversized
length. The extractor recognises the `.Length` argument on the buffer's own view /
`Array.Clear` (resolved BCL symbols) and emits an `overspan` fact.

**What the checker says:** **OWN025** `[resource: pooled buffer]` at each over-reach
site. The buffer is still `Return`ed, so there is no OWN001 leak.

**Honesty / scope.** `case.own` is a faithful hand reduction (not C# ingested by the
checker); `before.cs` / `after.cs` are representative of the bug and its fix. The
single-arg `Array.Clear(buf)` (a deliberate whole-buffer wipe) is intentionally not
flagged — only the explicit oversized `buf.Length` count is.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); replay target
AiDotNet.Tensors pooled-buffer over-clear/over-read.
