# ArrayPool double-return through an aliased receiver

**Pattern:** the same rented array is returned to the pool twice (a `Return` on the
normal path plus another in `finally`), exactly like `arraypool-double-return` — but the
pool is reached through an **aliased receiver**: `ArrayPool<int> p = ArrayPool<int>.Shared;`
then `p.Rent(...)` / `p.Return(...)`. Caching the pool in a local or field is common real
C#; the bug is the double `Return`, which corrupts the pool (the array can be handed to
two renters at once). See dotnet/runtime#33767.

**What the checker says:** the OwnLang model trips **OWN003** (double release).

**Why this case exists (the semantic-model proof).** A purely *textual* pool detector
keyed on the receiver spelling (`Contains("Pool")`) cannot recognise `p.Rent`/`p.Return` —
the receiver `p` carries no "Pool" — so this buffer was invisible and the double-return was
**MISSED**. Binding the call to `System.Buffers.ArrayPool<T>` via the Roslyn SemanticModel
resolves the pool regardless of how the receiver is spelled, and the path-sensitive flow
engine then flags the double release. This fixture both proves and pins that upgrade — it
is a miss under the old text heuristic and a catch (OWN003) under the semantic one.

**Honesty / scope.** As with the other cases, `case.own` is a faithful hand reduction of
the pattern (not C# ingested by the checker); `before.cs` / `after.cs` are representative
of the bug and its fix, not a verbatim PR diff.

Reference: https://github.com/dotnet/runtime/issues/33767
