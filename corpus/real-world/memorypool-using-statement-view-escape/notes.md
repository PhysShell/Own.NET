# MemoryPool `using (...)`-statement view escape (POOL004, the statement form)

**Pattern:** identical to `memorypool-using-view-escape`, but the owner is scoped by a
`using (...)` **statement** instead of a `using` **declaration**:
`using (IMemoryOwner<byte> owner = MemoryPool<byte>.Shared.Rent(n)) { return owner.Memory; }`.
Both syntaxes dispose the owner at scope exit, so the returned `Memory<T>` dangles either
way — a use-after-free of pooled memory. The fix is the same: transfer ownership (return the
`IMemoryOwner`).

**Why this case exists (CodeRabbit review on #74):** the `using`-declaration desugaring in
#74 only matched `LocalDeclarationStatementSyntax` with a `using` keyword. The statement
form (`UsingStatementSyntax`) was still lowered as a plain body, so its MemoryPool owner was
neither tracked nor release-threaded — the same dangle, silent. This slice extends the
desugaring (and the flow-locals candidate scan) to the `using (...)` statement form, so a
tracked `using (owner = MemoryPool.Rent(…)) { return owner.Memory; }` is lowered to
`acquire; try { body } finally { release }` exactly like the declaration form → **OWN002**.

**What the checker says:** the OwnLang model and the real `before.cs` both trip **OWN002**.
The ownership-transfer fix in `after.cs` (return the owner directly, no `using`) is silent.

**Honesty / scope.** `case.own` is a faithful hand reduction (not C# ingested by the
checker); `before.cs` / `after.cs` are representative of the bug and its fix. (Returning the
owner itself from a `using` scope — `using owner; return owner;` — is a distinct, follow-up
gap: the escape pass untracks directly-returned owners as ownership transfers.)

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); the declaration form is
`memorypool-using-view-escape`.
