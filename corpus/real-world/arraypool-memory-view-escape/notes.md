# Pooled-buffer `Memory<T>` view that ESCAPES after return — the borrow checker, second bite

**Pattern:** a rented `ArrayPool<T>` buffer is sliced into a `Memory<T>` local
(`Memory<byte> view = buf.AsMemory(0, n)`), the buffer is `Return`ed to the pool, and the view is
then **returned from the method** (or stored in a field). The borrow **escapes** its owner: the
caller holds a `Memory<byte>` into an array the pool has already recycled to someone else — a silent
cross-tenant corruption (read/write of freed-and-reused memory).

**What the checker says:** the view's escape (the `return`) is a use of the owner after it was
released → the generic **OWN002** (use-after-release), surfaced at the escape site.

**Why this case exists (P-007 POOL004 — view escape).** [`arraypool-span-view-after-return`](../arraypool-span-view-after-return)
caught a `Span` view used after `Return` **inside** the method. But a `Span` is a **ref struct** —
the C# compiler keeps it inside the method, so it cannot escape. A **`Memory<T>` is not a ref
struct**: it *can* be returned or stored in a field, which is the genuinely dangerous escape the
borrow checker must catch. The view recognition (`ViewOwner`) is now extended from `AsSpan` /
`new Span<T>` to **`AsMemory` / `new Memory<T>`** (and the `ReadOnly*` forms), resolved via the same
BCL symbols (`System.MemoryExtensions`, `System.Memory<T>`). Because a reference to the view lowers
to a use of the owner — and `return view` is such a reference — the escape of a dangling view after
`Return(buf)` trips OWN002. Before this slice the `Memory` view was unrecognised, so the dangling
return looked balanced (acquire + release) — a **miss**.

**Conservative (0 FP).** Only a view of a **tracked** owner that is used/returned **after** the
owner's release fires. The fix (`after.cs`) copies out of the buffer (`AsSpan(..).ToArray()`) and
returns the **copy**, so no view escapes — silent. A view used before the return, or a view of an
untracked buffer, adds no finding; the borrow can never invent a release.

**Honesty / scope.** `case.own` is a faithful hand reduction (the escaping view collapses to a use
of the owner, exactly what the extractor emits), not C# the `.own` checker ingested.
`before.cs`/`after.cs` are representative of the bug and its fix. This slice covers the **return**
escape; storing the view in a **field** (object-level escape) and view **reassignment** are left for
later rounds.
