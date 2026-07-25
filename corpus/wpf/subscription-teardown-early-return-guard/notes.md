# A parameter guard spelled as an early return defeats the #278 guard detector (soundness FN)

**Pattern.** The exact SectorTS `UnregOnlyGoodys` guard from
`subscription-param-guarded-unregister`, rewritten from the enclosing-branch
form into the early-return form:

```csharp
// demoted today (enclosing branch):        // credited today (early return):
void Cleanup(bool keepAlive)                void Cleanup(bool keepAlive)
{                                           {
    if (!keepAlive)                             if (keepAlive)
    {                                               return;
        source.Changed -= OnChanged;            source.Changed -= OnChanged;
    }                                       }
}
```

The two spellings are semantically identical — the caller chooses whether the
`-=` runs — but only the left one is demoted.

**The bug (Own.NET extractor).** `IsParamGuardedRelease`
(`frontend/roslyn/OwnSharp.Extractor/Program.cs`, #278 rule 2) walks the
**lexical ancestors** of the `-=` site and demotes when an enclosing
`if`/`?:`/`switch`/`while`/`for` condition references a parameter. An early
`return` guard is a preceding **sibling** statement, never an ancestor, so it
is invisible. Meanwhile the symbol-based teardown closure
(`TeardownContextMethods`) adds `Cleanup` because `Dispose()` calls it —
argument **values** are not consulted, so `Cleanup(keepAlive: true)` credits
the helper even though that call provably skips the release. Net: `before.cs`
is silent, and the leak class #293 closed reopens one refactoring away.

**Why the core is not the gap.** The `.own` reduction models the guard as the
branch it is, and the branch-sensitive core flags it (OWN001, "not released on
every path"). This mirrors the Python bridge's own D7 fix
(`docs/notes/interprocedural-tz.md`, INF-S3: an early `return` reachable before
a forward makes the transfer conditional) — the same theorem, unfixed on the
extractor side.

**The fix (#305).** `IsParamGuardedByEarlyReturn`, folded into
`IsParamGuardedRelease`: a `return` lexically preceding the site inside the
enclosing callable, guarded by a parameter-referencing condition, demotes —
EXCEPT the canonical negated-disposing early exit (`if (!disposing) return;`),
which guarantees the site *does* run on every `Dispose()` call and stays
credited. Timer twin: `timer-stop-early-return-guard` (shared predicate). See
`docs/notes/teardown-predicate-adversarial-audit.md` (attack A).

**CI impact.** `before.cs` flips to caught with the fix; `after.cs` reuses the
proven-silent helper-from-Dispose shape of
`subscription-overload-conflated-cleanup`.
