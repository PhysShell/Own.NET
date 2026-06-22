# MemoryPool bare-owner `using` escape (`using owner = …; return owner;`)

**Pattern:** an `IMemoryOwner<T>` from `MemoryPool<T>` is held with a `using` declaration (so it is
`Dispose()`d at scope exit), but the method **returns the owner itself**. The implicit dispose runs
as the method returns, so the caller receives an `IMemoryOwner<T>` whose pooled buffer has already
been handed back to the pool — a dangling owner / use-after-free. It is exactly
`try { return owner; } finally { owner.Dispose(); }` — the **bare-owner** twin of the returned-view
dangle (`memorypool-using-view-escape`, which returns `owner.Memory`). The fix is to **transfer
ownership**: drop the `using` and return the live owner so the caller owns its lifetime.

**Why it was missed before (Codex follow-up on #74):** a local that is `return`ed is treated as an
ownership transfer (the caller's to release) and dropped from the tracked set — so the bare-owner
return escaped and was never analysed, even though the `using` makes it a dangle rather than a
transfer. This slice keeps a **`using`-declared MemoryPool owner that is returned bare** tracked
(only this shape is exempted from the return-escape — a non-`using` returned owner stays a genuine
transfer, untracked, silent), and threads a use of the returned owner after the `using`-desugar's
scope-exit release — reusing the exact return-chain insertion that already catches the returned
**view** (`memorypool-using-view-escape`). So the caller's use of the owner lands after the release
and trips OWN002.

**What the checker says:** the OwnLang model and the real `before.cs` both trip **OWN002**. The
ownership-transfer fix in `after.cs` returns the owner with no `using`, so the escaped owner is
untracked and the checker is silent.

**Honesty / scope.** `case.own` is a faithful hand reduction (not C# ingested by the checker);
`before.cs` / `after.cs` are representative of the bug and its fix. One escape vector each: this
catches the bare OWNER return; `memorypool-using-view-escape` catches the returned VIEW.

Reference: [P-007](../../../docs/proposals/P-007-arraypool-span.md); the view twin is
`memorypool-using-view-escape` (#73/#74).
