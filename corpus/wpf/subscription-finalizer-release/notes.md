# Subscription whose only `-=` is in the finalizer (soundness FN)

**Pattern (#278 follow-up, blocker 1).** Ctor `+=` to an injected publisher; the
matching `-=` sits in `~FinalizerDetachDocument()`. The release is circularly
unreachable: a finalizer runs only after the object becomes unreachable, but the
publisher's delegate (the subscription) is precisely what keeps the subscriber
reachable. While the subscription is live the finalizer cannot run; once the
finalizer can run, there is nothing left to release. For a static/process-lived
publisher the same argument is absolute — the finalizer is never reached for the
life of the process.

**The bug.** The first #278 slice treated `DestructorDeclarationSyntax` as a
teardown context, so this shape was silently credited as released — a
false-negative path of exactly the kind the slice existed to remove.

**The fix.** A finalizer is explicitly NOT a teardown context for subscription
release. `before.cs` keeps the honest OWN001; `after.cs` releases in `Dispose`
(deterministic, owner-called, does not depend on unreachability) and is silent.

**What the checker says (`.own` reduction).** The ctor scope acquires the token
and no reachable teardown path releases it => **OWN001** with the
subscription-token resource tag.

**Regression guard.** `scripts/benchmark.py`: `before.cs` must be **caught**,
`after.cs` must be **silent**.

**Honesty / scope.** `case.own` carries the acquire/release logic; the
finalizer-reachability reasoning lives in the extractor
(`InTeardownContext`: `DestructorDeclarationSyntax => false`). Timer `.Stop()`
release and the rest of the teardown model are unchanged by this case.
