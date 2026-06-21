# Pooled-buffer Span VIEW used after return — the borrow checker's first bite

**Pattern:** a rented `ArrayPool<T>` buffer is sliced into a `Span<T>`/`ReadOnlySpan<T>` local
(`Span<byte> view = buf.AsSpan(0, n)`), the buffer is `Return`ed to the pool, and the code then
reads/writes **through the view**. The `Span` borrows the buffer's memory; once the array is
recycled the pool may hand it to another caller, so the view now aliases someone else's data — a
silent corruption (the same family as a use-after-free). It is the use of a **borrow after its
owner was released**.

**What the checker says:** using a resource after it was released is the generic **OWN002**
(use-after-release) — the same code `arraypool-use-after-return` produces when the buffer itself is
read after return.

**Why this case exists (the borrow / B4 frontier).** The flat pass and the existing pool flow only
saw a use-after-return when the **buffer local itself** was referenced after `Return`. When the read
goes through a **stored Span view** (`view[0]`), the buffer name never appears at the use site, so
the buffer looked released-and-untouched — a **miss**. Now the extractor models a
`Span`/`ReadOnlySpan` view of a tracked buffer as a **borrow**: a reference to the view local lowers
to a **use of the owner** (`ViewOwnerOf` resolves the view through its declaration's `AsSpan(..)` /
`new Span<T>(buf)` initializer, the owner confirmed via the SemanticModel). The use after `Return`
then trips OWN002. This is the first slice of the **borrow checker on real C#** — lifetime/aliasing
analysis that the flat "disposed anywhere?" tools (and most general scanners) do not do — kept
purely in the extractor (the core needs no borrow concept; it sees a plain use-after-release).

**Conservative (0 FP).** A view of an untracked/escaped buffer, or a view used **before** the
return (`after.cs`), adds no finding — the borrow only lowers to a use of an owner that is still
tracked, so it can never invent a release. Ref-struct `Span` cannot escape the method, which is
what makes "use of the view = use of the owner, here" sound.

**Honesty / scope.** `case.own` is a faithful hand reduction (the borrow collapses to a use of the
owner, exactly what the extractor emits), not C# the `.own` checker ingested. `before.cs`/`after.cs`
are representative of the bug and its fix. First slice: `Span`/`ReadOnlySpan` views via `AsSpan()` /
`new Span<T>(buf)`; `Memory<T>` (which *can* escape) and view reassignment are deliberately left for
later rounds.
