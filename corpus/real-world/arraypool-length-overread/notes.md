# ArrayPool over-read — the `.Length` spelling (POOL005)

**Pattern:** a pooled array from `ArrayPool<T>.Shared.Rent(n)` is *oversized*
(`Length >= n`). A view that uses `buf.Length` — the oversized backing length — as
its bound (`buf.AsSpan(0, buf.Length)`, `new Span<T>(buf, 0, buf.Length)`) spans the
whole array, so reading or copying through it processes the `n` valid bytes **plus**
the stale `[n, Length)` tail a previous renter left: a wrong-length read and a
potential information disclosure. The fix is to bound by the logical length:
`buf.AsSpan(0, n)`.

This is the `.Length` sibling of `arraypool-fullspan-overread` (which catches the
unbounded `buf.AsSpan()`): same OWN025, a different way of writing the oversized
length. The extractor recognises the `.Length`-as-length argument on the buffer's
own view (start `0`, resolved BCL symbols) and emits an `overspan` fact.

**Not flagged: the over-clear.** `Array.Clear(buf, 0, buf.Length)` (and the single-arg
`Array.Clear(buf)`) only *overwrite* the pooled tail with zeros — a safe
clear-before-`Return` idiom that exposes nothing. POOL005 is about *reading/copying*
too much, not *writing* too much (Codex review); only the **view** is flagged.

**What the checker says:** **OWN025** `[resource: pooled buffer]` at the view. The
buffer is still `Return`ed, so there is no OWN001 leak.

**Honesty / scope.** `case.own` is a faithful hand reduction (not C# ingested by the
checker); `before.cs` / `after.cs` are representative of the bug and its fix.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); replay target
AiDotNet.Tensors pooled-buffer over-read.
