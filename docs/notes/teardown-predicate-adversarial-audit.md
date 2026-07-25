# Adversarial soundness audit — the #293/#302 teardown-context predicates

> Status: **audit record** (2026-07-25). Method: adversarial code reading of the
> landed release-crediting predicates in
> `frontend/roslyn/OwnSharp.Extractor/Program.cs` — enumerate the predicate's
> implicit axioms, attack each with a counterexample class, verify the verdict
> against the code line-by-line. This is the same discipline that produced
> #278 (there: from a runtime heap walk; here: from the predicate's own text).
> Two attacks are pinned as red corpus fixtures
> (`corpus/wpf/subscription-teardown-early-return-guard`,
> `corpus/wpf/subscription-disposing-else-branch-release`); the CI corpus
> benchmark is the empirical confirmation surface (no .NET SDK on the audit
> box — every claim below is code-anchored, and the fixtures make CI the
> arbiter).

## 1. The predicate under audit

A `-=` (or, since #302, a timer `.Stop()`) credits release iff (Program.cs,
crediting loop at the class scan):

1. `InTeardownContext(site)` — the enclosing callable is in
   `TeardownContextMethods(cls)`: name-roots
   (`Dispose`/`DisposeAsync`/`OnClosed`/`OnClosing`/`OnUnloaded`/
   `OnFormClosed`/`OnFormClosing` among the class's own methods), wired-root
   handlers (`+=` of a method group / lambda to the class's OWN
   `Closed`/`Closing`/`Unloaded`/`FormClosed`/`FormClosing`/`Disposed`), plus
   the symbol-based intra-class call closure; finalizers, unwired name-only
   handlers, merely-declared local functions/lambdas are non-contexts
   (#278 follow-ups);
2. `!IsParamGuardedRelease(site)` — no enclosing
   `if`/`?:`/`switch`/`while`/`for` condition references a parameter of the
   enclosing method, with one canonical exception: a POSITIVE use of the single
   bool parameter of `Dispose(bool)`;
3. textual `(left, normalized-handler)` pairing against the `+=`.

The predicate's implicit axioms, each an attack surface:

- **AX1** — a caller-controlled skip always manifests as an *enclosing*
  condition of the release site;
- **AX2** — parameter influence is visible as a *direct* parameter identifier
  in that condition;
- **AX3** — a positive use of `disposing` in the condition implies the site
  runs on the managed-dispose path (branch membership never checked);
- **AX4** — a teardown-context *name* implies the platform actually invokes it
  (`Dispose` ⇒ someone disposes);
- **AX5** — a callee credited by the closure is credited for *all* argument
  values;
- **AX6** — the `-=`'s receiver text/symbol names the same runtime instance
  the `+=` subscribed to.

## 2. Confirmed holes (false-negative direction — a swallowed leak)

Severity per the #238 doctrine: *"the worst case of an exemption must be
'keeps today's honest warning', never 'silently swallows a leak class'"*. Every
entry below silently swallows.

### A. Early-return parameter guard (AX1 ∧ AX5) — **P1, FIXED (#305)**

```csharp
public void Dispose() { Cleanup(keepAlive: true); }   // the only caller
public void Cleanup(bool keepAlive)
{
    if (keepAlive) return;                            // sibling, not ancestor
    _properties.PropertyChanged -= OnPropertiesChanged;  // never reached — credited
}
```

`IsParamGuardedRelease` walks lexical *ancestors* only; an early `return` is a
preceding *sibling*. The closure adds `Cleanup` because `Dispose` calls it —
argument values are not consulted (AX5), so even a call site that provably
passes the skip value credits the helper. The SectorTS `UnregOnlyGoodys` guard
— the exact leak #293 was built to catch — reopens under a
semantics-preserving rewrite from `if (!flag) { -= }` to `if (flag) return; -=`.

This is the extractor-side twin of the Python bridge's **D7** defect
(`interprocedural-tz.md`: "ранний `return` не делал forward условным"), fixed
there as INF-S3. The same theorem, unfixed on the C# side.

Fixture: `corpus/wpf/subscription-teardown-early-return-guard`.

### B. `-=` in the ELSE of the canonical `if (disposing)` (AX3) — **P1, FIXED (#305)**

```csharp
private void Dispose(bool disposing)
{
    if (disposing) { }
    else { _properties.PropertyChanged -= OnPropertiesChanged; }  // credited
}
```

`IsCanonicalDisposingGuardUse` classifies the parameter identifier's use in
the *condition* (not negated, not `== false`) and never asks which *branch*
holds the site. A site in the `else` of a positive guard sees the same
positive condition ⇒ credited — yet it executes only when
`disposing == false`, i.e. on the finalizer path, which the extractor's own
finalizer doctrine (#278 follow-up 1) declares unreachable while the
subscription pins the subscriber. The predicate contradicts its own doctrine
one branch away from the case it handles.

Fixture: `corpus/wpf/subscription-disposing-else-branch-release`.

### C. Parameter laundered through a local (AX2) — P2, recorded (no fixture yet)

```csharp
void Cleanup(bool skip)
{
    bool s = skip;                    // launder
    if (!s) { source.Changed -= OnChanged; }   // condition names a LOCAL — credited
}
```

The guard check demotes only on `IParameterSymbol` in the condition. Locals and
fields are deliberately credited ("the class's own state"), but a local whose
only value is a parameter is caller-controlled state. Bounded fix: within the
enclosing method, taint locals whose initializer/assignments reference a
parameter (no cross-call dataflow). Realism moderate (refactorings produce it);
fixture worth adding together with the fix.

### D. Name-root without enrollment (AX4) — the #304 family, recorded

```csharp
public sealed class Cache            // does NOT implement IDisposable
{
    public Cache()  { AppSettings.Changed += OnChanged; }
    public void Dispose() { AppSettings.Changed -= OnChanged; }  // nobody ever calls
}
```

`Dispose` is a name-root regardless of whether the type implements
`IDisposable` — but the platform contract only invokes `Dispose` *through* the
interface (`using`, DI scope disposal). An ad-hoc `Dispose`/`OnClosed` that
nothing calls is a name, not a lifecycle. This is precisely P-036's
LifecycleEffect-vs-LifecycleEnrollment split (effect proven, enrollment
assumed); the full answer is #304's summary-composed reasoning. A cheap
bounded improvement exists before that: name-root `Dispose`/`DisposeAsync`
only when the type implements `IDisposable`/`IAsyncDisposable`;
`OnClosed`-family only when the method is an override. Kept-warning worst
case, so it is safe in the #238 sense.

### E. `switch` arm `when`-clause guard (AX2) — minor, recorded

`IsParamGuardedRelease` inspects a switch's *governing expression*, not the
per-arm `when` clauses: `case State.Full when skip == false: source.Changed -=
OnChanged;` (with `skip` a parameter, `State.Full` from a field) is credited.
Same family as A/C — parameter influence outside the inspected surface. Fold
into the same fix round.

### F. Receiver reassignment between `+=` and `-=` (AX6) — known family (#163), out of S0

Subscribe to `_pub.Changed`, later `_pub = new Publisher()`, then a teardown
`_pub.Changed -= OnChanged` detaches from the *new* instance; the old
subscription leaks while the textual/symbol pairing credits it. This is the
documented #163 rebinding gap generalized from setters to any reassignment —
proving receiver-instance stability is dataflow, explicitly out of the S0
design. Recorded here so the family has one name; the honest fix is #304's
place/heap identity, not another lexical patch.

## 3. Attacks the predicate survives (positive assurance)

Verified by the same reading — each of these stays a *kept warning* (FP
direction, doctrine-safe) or is correctly credited:

| attack | outcome |
|---|---|
| canonical early exit `if (!disposing) return; ... -=` | correctly credited — the negated-use check fires only on identifiers in *conditions*, and the site runs on every `Dispose()` — the asymmetry of attack A is what makes this work |
| `-=` in a finalizer body | non-context (explicit) |
| `Cleanup()` call crediting an uncalled `Cleanup(bool)` overload | ruled out — symbol-based closure |
| lambda/local function merely declared in `Dispose` | non-context unless wired/called |
| `Window_Closing` name with no code wiring | non-context (XAML slice deferred, documented) |
| teardown via delegate field (`_cleanup()` where `_cleanup = Cleanup`) | unresolved invocation extends nothing ⇒ kept warning |
| `Dispose` declared in the other file of a partial class | closure skips other-file halves ⇒ kept warning |
| `-=` inside a handler wired to ANOTHER object's `Closed` | `IsSelfLifecycleReceiver` rejects ⇒ kept warning |
| `-=` under `switch (param)` governing expression | demoted |
| `do { -= } while (param)` | body runs ≥ once — zero-trip impossible, crediting sound |
| nested-type `-=` credited to the outer class | scan is scoped to the immediate type |

## 4. Doctrine assessment

Attacks A and B are #238-doctrine violations *inside the fix that was built to
enforce the doctrine*: both silently swallow, both are one mechanical rewrite
away from shapes the corpus already pins (A ← `subscription-param-guarded-
unregister`, B ← the canonical-disposing exception's own motivating pattern).
C and E are the same axiom (AX2) leaking through adjacent syntax. D is the
enrollment gap P-036 names — bounded improvement available now, full answer in
#304. F is a documented family, honestly out of scope until #304's identity
model.

Because #302 routes timer `.Stop()` through the *same* predicate ("one
predicate, one context model"), every hole above applies verbatim to WPF002 —
timer twin fixtures should land together with the fixes, mirroring the
existing `timer-stop-*` families.

## 5. Fix directions (bounded, lexical — the #293 style, no call graph)

1. **A (early return):** demote when a `return` lexically precedes the site
   within the enclosing callable and is guarded by a parameter-referencing
   condition — EXCEPT the canonical negated-disposing exit
   (`if (!disposing) return;`), which *guarantees* the site runs on the
   managed path. Mirror of the bridge's INF-S3.
2. **B (else branch):** the canonical-disposing exception applies only to
   sites within the THEN branch of the positive guard; a site in the `else`
   demotes (equivalently: it is the finalizer branch — treat as non-context).
3. **C (laundered local):** extend the guard-identifier check to locals whose
   initializer/assignments (within the same method) reference a parameter.
4. **E (`when` clauses):** include switch-arm `when` clauses in the inspected
   condition set.
5. **D (enrollment, bounded):** name-root `Dispose`/`DisposeAsync` requires
   the type to implement the corresponding interface; `OnClosed`-family
   requires `override`. The general form is #304.

All five keep the #238 worst case at "kept warning". None require the
whole-program call graph — they stay inside the S0 lexical/symbol budget that
#293 established. The *general* solution (argument-value-aware crediting,
guarded effects, enrollment proof) is exactly P-036 Phase 2 / #304 — these
bounded fixes are the pre-cutover floor, not a substitute.

## 6. Verification status

- Confirmed by code reading against `Program.cs` (predicate internals quoted
  per attack above): A, B, C, E credit paths; survived-attack table.
- **A and B are fixed** (#305): `IsParamGuardedByEarlyReturn` (fix 1) and the
  branch-aware canonical exemption `SiteOnNegativeBranch` (fix 2), both folded
  into the shared `IsParamGuardedRelease` so `-=` and `.Stop()` inherit them
  together. Fixtures flipped red→green expectations; timer twins added
  (`timer-stop-early-return-guard`, `timer-stop-disposing-else-branch`). CI's
  corpus benchmark is the empirical arbiter (before caught, after clean).
- Not yet fixtured: C, E (next bounded round — same axiom AX2), D (needs the
  bounded-enrollment decision first), F (documented family, #304).
