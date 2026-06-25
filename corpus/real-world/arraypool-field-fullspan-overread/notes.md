# ArrayPool full-length view over-read on a FIELD-backed buffer (POOL005, field)

**Pattern:** the FIELD twin of [`arraypool-fullspan-overread`](../arraypool-fullspan-overread/notes.md).
A pooled array from `ArrayPool<T>.Shared.Rent(n)` is *oversized* — `Length >= n`, not
exactly `n`. Here it is rented into a **field** (`_buf = ArrayPool<byte>.Shared.Rent(n)`)
in one member and viewed full-length in a **later** member (`_buf.AsSpan()`,
`this._buf.AsMemory()`, `new Span<T>(_buf)`, or the `.Length` spelling
`_buf.AsSpan(0, _buf.Length)`). Reading or copying through that unbounded view
processes the `n` valid bytes **plus** the stale `[n, Length)` tail a *previous*
renter left behind — a correctness bug (wrong length) and an information disclosure.
The fix is a bounded view: `_buf.AsSpan(0, _n)`.

**Why a separate case.** The path-sensitive flow detector only tracks pooled buffers
held in **locals**, so a field-backed rent — rented in one member, viewed in another —
is out of its reach. The extractor's POOL005 **field pass** closes that gap: it
collects the fields a class `Rent`s (the shared `IsPoolRent`, so an aliased pool
receiver binds and a non-pool `.Rent` does not), and for each member that takes a
full-length view of such a field (receiver resolved through the `this`/bare
`ThisFieldName` shape, the over-read recognised by the same resolved
`System.MemoryExtensions` / `System.Span<T>` BCL symbols as the local path) emits a
synthetic `acquire`/`overspan`/`release` flow so the core raises **OWN025** at the
view — no new diagnostic, the same synthetic-flow trick the field use-after-dispose
and MemoryPool slices use. A *write*/wipe (`Array.Clear(_buf, 0, _buf.Length)`) is not
a view, so it is deliberately **not** flagged — only a read-capable VIEW is the
over-read.

**What the checker says:** OWN025 `[resource: pooled buffer]` at the view. The buffer
is still `Return`ed (in `Dispose`, found class-wide by the POOL001 field pass), so
there is no OWN001 leak and no OWN002 use-after-return; the only finding is the
over-read itself.

**Honesty / scope.** `case.own` is a faithful hand reduction — `.own` has no
fields/members, so it pins the *core* OWN025 verdict the field pass produces, while
the field-vs-local distinction lives in `before.cs` / `after.cs` (scanned end to end
by the dotnet `corpus-benchmark` CI job). `before.cs` / `after.cs` are representative
of the bug and its fix, not a verbatim PR diff. v0 of the field pass fires on the
*first* full-length view of each pooled field per member (a read site); a full-length
view of a pooled field **stored into another field** and only read elsewhere is a
deeper alias-tracking frontier, left honest.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); replay target
AiDotNet.Tensors pooled-buffer over-clear/over-read.
