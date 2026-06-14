# WPF ViewModel promoted to App lifetime (region escape)

**Pattern:** a Window-scoped ViewModel strongly subscribes itself to an
App-scoped (singleton) event bus and keeps no unsubscribe token. The strong
delegate makes the VM reachable from an App-lifetime GC root, so the VM is
*promoted* to App lifetime: it outlives its window and lives until the process
exits. The bug is the **lifetime mismatch** — VM expected `Window`, actually
`App` — not any single missing `Dispose` call in isolation.

**What the checker says:** this is the region-escape theorem (slice #2). With the
regions declared (`ViewModel < Window < App`) and the source tagged App-lived,
the strong `subscribe self to bus` where the source strictly outlives `self`
trips the generic **OWN014**:

```text
$ python -m ownlang check corpus/wpf/viewmodel-escapes-to-app/case.own
case.own:16:23: error: [OWN014] 'bus' (lifetime 'App') outlives the captured
  object 'CustomerViewModel' (lifetime 'ViewModel'); the strong subscription
  promotes 'CustomerViewModel' to 'App' and it leaks (no release path)
  16 |     subscribe self to bus;
                            ^
```

The *ordering* is what makes it a leak: subscribing to a same- or shorter-lived
source produces no diagnostic (no promotion possible). The fix (`after.cs`) keeps
a disposable token released on close — the slice-#1 acquire/release pattern —
which gives the VM a release path back to its Window lifetime.

**Honesty / scope.** `case.own` is a *hand reduction*, not C# the checker
ingested (no C# front-end yet). `self`/`source` are the function's own scope and
its annotated parameters — there is no cross-procedural points-to, and weak-event
policy as an explicit escape hatch is a later slice (see `docs/lifetimes.md`).
`before.cs` / `after.cs` are representative, not a verbatim copy of one PR.
