# ArrayPool double-return

**Pattern:** the same rented array is returned to `ArrayPool<T>.Shared` twice —
classically a `Return` on a normal path plus another in a `finally`/`Dispose`,
or two `Dispose()` calls. The pool can then hand the same array to two renters
simultaneously. See dotnet/runtime#33767 ("Do not double-return arrays to
ArrayPool").

**What the checker says:** the OwnLang model trips **OWN003** (double release).

**Honesty / scope.** As with the other cases, `case.own` is a faithful hand
reduction of the pattern (not C# ingested by the checker); `before.cs` /
`after.cs` are representative of the bug and its fix, not a verbatim PR diff.

Reference: https://github.com/dotnet/runtime/issues/33767
