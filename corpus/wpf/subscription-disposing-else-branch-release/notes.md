# The canonical `if (disposing)` exception credits a `-=` in the ELSE branch (soundness FN)

**Pattern.** The textbook `Dispose(bool)` pattern with the unsubscribe
misplaced into the finalizer-only branch:

```csharp
private void Dispose(bool disposing)
{
    if (disposing) { /* ... */ }
    else
    {
        source.Changed -= OnChanged;   // runs only via ~Finalizer -> Dispose(false)
    }
}
```

**The bug (Own.NET extractor).** `IsParamGuardedRelease` demotes any release
under a parameter-dependent condition — EXCEPT the canonical positive
`disposing` guard of `Dispose(bool)` (`IsCanonicalDisposingGuardUse`,
`frontend/roslyn/OwnSharp.Extractor/Program.cs`). That exception classifies the
**use of the parameter identifier in the condition** (not negated, not
`== false`) and never asks **which branch the release site is in**. A site in
the `else` of a positive `if (disposing)` sees the same positive condition, so
it is credited — even though it executes only when `disposing == false`, i.e.
on the finalizer path.

That contradicts the extractor's own finalizer doctrine (#278 follow-up 1): for
a subscription leak the subscriber stays reachable through the publisher's
delegate, so the finalizer never runs while the subscription is live — a `-=`
on that path can never break the hold. A `-=` in a finalizer body is already a
non-context; the same `-=` moved into the `Dispose(false)`-only branch is that
exact code path wearing different syntax, and it is credited.

**Why the core is not the gap.** The `.own` reduction models the two branches
directly: on the managed path (`disposing` truthy) the function returns without
releasing — the branch-sensitive core reports OWN001.

**The fix (#305).** The canonical exception is branch-aware now
(`SiteOnNegativeBranch`): a positive `disposing` condition exempts only sites
within its THEN branch; a site in the `else` (or the when-false arm of a
ternary) demotes like any parameter guard. Timer twin:
`timer-stop-disposing-else-branch` (shared predicate). See
`docs/notes/teardown-predicate-adversarial-audit.md` (attack B).

**CI impact.** `before.cs` flips to caught with the fix; `after.cs` is the
canonical positive-branch pattern the #293 exception was built to credit
(exercised by `frontend/roslyn/samples/WinFormsDisposalSample.cs`).
