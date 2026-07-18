# Subscription whose only `-=` is in an arbitrary non-teardown method (soundness FN)

**Pattern (issue #278, rule 3).** A listener subscribes in its ctor; the only
matching `-=` is unconditional but lives in an arbitrary method
(`StopListening()`) that is not a teardown. Nothing proves any owner calls it:
in the SectorTS analog the `DocCloud` subsystem constructs the objects through
AutoMapper profiles and never calls the unregister method — every instance stays
pinned to the publisher.

**The bug (Own.NET extractor).** The shipped release model credited *any*
matching `-=` anywhere in the class, so this shape was silent. The design docs
specified the stricter rule all along (P-004: "no matching `-=` in
`Dispose`/`OnClosed`/`Unloaded`"; P-001 the same) — the implementation was looser
than its own spec, in the unsound direction.

**The fix (#278).** A `-=` credits release only in a recognised teardown context:
`Dispose`/`DisposeAsync`/`OnClosed`/`OnUnloaded`-style methods, a finalizer, a
handler wired to the class's own `Closed`/`Closing`/`Unloaded`-style lifecycle
event (including the XAML `Window_Closing` naming convention), or a method the
teardown path calls intra-class. An arbitrary method grounds nothing, so
`before.cs` keeps the honest OWN001. At most a non-teardown `-=` is a
*mitigation candidate* — never silence.

**Why `after.cs` uses an `Unloaded` hook (not `Dispose`).** The matching ok-case
for a `Dispose` release already exists
(`corpus/wpf/subscription-explicit-delegate-release`,
`subscription-param-guarded-unregister`). This case's `after.cs` pins the OTHER
acceptance half: a **recognised lifecycle teardown keeps its existing
no-finding behaviour** — the class wires `Unloaded += OnViewUnloaded` and
detaches there, and the extractor recognises the wired handler as a teardown
context. (The `Unloaded += OnViewUnloaded` wiring itself is a self-owned-source
subscription — `this`'s own event — and stays exempt as before.)

**What the checker says (`.own` reduction).** The ctor scope acquires the token
and no teardown path releases it => **OWN001** with the subscription-token
resource tag. The non-teardown `-=` is deliberately NOT modelled as a release —
existence is not execution.

**Regression guard.** `scripts/benchmark.py`: `before.cs` must be **caught**,
`after.cs` must be **silent**. Before the #278 fix, `before.cs` was silent.

**Honesty / scope.** `case.own` carries the acquire/release logic only; the
teardown-context recognition lives in the extractor. The C# is representative,
not a verbatim SectorTS copy.
