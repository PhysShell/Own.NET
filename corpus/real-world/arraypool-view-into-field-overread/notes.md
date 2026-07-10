# ArrayPool full-length view over-read where the view is STORED INTO A FIELD (POOL005)

**Pattern:** the "into a field" twin of
[`arraypool-field-fullspan-overread`](../arraypool-field-fullspan-overread/notes.md).
A pooled array from `ArrayPool<T>.Shared.Rent(n)` is *oversized* — `Length >= n`, not
exactly `n`. A **full-length** view of it (`_buf.AsMemory()`, no length bound) is not
read inline; it is **cached into another field** (`_view = _buf.AsMemory()`,
`_metaView = _meta.AsMemory()`) in one member and read through in a **later** member
(`Flush`/`FlushMeta`). Whoever reads the stored view processes the `n` valid bytes
**plus** the stale `[n, Length)` tail a *previous* renter left behind — a wrong-length
read and an information disclosure. `Span<T>` is a `ref struct` and cannot be a field,
so the field-stored view is a `Memory<T>` / `ReadOnlyMemory<T>`. The fix is a bounded
view, `_buf.AsMemory(0, _n)`.

**Why it is already caught.** The extractor's POOL005 **field pass** (`Program.cs`,
`FullViewFieldOwner` + the per-member walk) fires on the full-length view
**expression**, wherever its result goes: the RHS `_buf.AsMemory()` of the store
`_view = _buf.AsMemory()` is exactly such an expression, so the over-read is caught
**at the store** — where the unbounded view is materialized — via the same synthetic
`acquire`/`overspan`/`release` flow the inline field twin uses (no new diagnostic, no
new op). Verified end to end with the real extractor (`dotnet run … --flow-locals`) →
OWN025 on both the `Memory` and `ReadOnlyMemory` field stores; the bounded `after.cs`
is silent. This case turns that incidental coverage into a pinned contract (P-007 had
it recorded as "the deeper alias-tracking frontier, left next").

**What the checker says:** OWN025 `[resource: pooled buffer]` at the cached view. The
buffers are still `Return`ed (in `Dispose`, class-wide via the POOL001 field pass), so
there is no OWN001 leak and no OWN002 use-after-return; the only finding is the
over-read itself.

**Honesty / scope — the deferred boundary.** What is caught here is the full-length
view *materialization* (the store). One shape past this is genuinely out of the
current intraprocedural machinery and is **deliberately deferred** (P-007 §Non-goals;
the issue's "a deliberate deferral beats a soft false positive"): a **bounded** view
cached into a field and then read **after the owner is `Return`ed in a *different*
member** — an object-level (cross-member) escape whose bug-ness depends on the caller's
method-call order (`Setup → Done → Late` is a use-after-return; `Setup → Late → Done`
is fine). Deciding that statically needs interprocedural / whole-program ordering the
per-method + field passes do not have, so flagging it would be a soft false positive.
Tracked as a follow-up (POOL004 object-level escape, #205). The `after.cs` here also exercises
that safe bounded-and-cached shape and stays silent, pinning the non-firing side.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); replay target
AiDotNet.Tensors pooled-buffer over-clear/over-read.
