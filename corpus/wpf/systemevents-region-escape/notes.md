# WPF window promoted to process lifetime via a static SystemEvents subscription (region escape)

**Pattern:** a `Window`-scoped dialog strongly subscribes itself to
`Microsoft.Win32.SystemEvents.DisplaySettingsChanged` — a **static,
process-lifetime** event source — and keeps no unsubscribe token. The static
source holds a strong reference to the handler's owner (the dialog) for the whole
life of the process, so the dialog is *promoted* to process lifetime: it outlives
its window and lives until the process exits. The bug is the **lifetime mismatch**
(the dialog expected `Window`, actually `Process`), not any single missing
`Dispose` call in isolation. This is the SystemEvents leak the .NET docs
explicitly warn about; distilled from `NickeManarin/ScreenToGif`
(`GraphicsConfigurationDialog` / `Troubleshoot`).

**What the checker says:** the region-escape theorem (slice #2). With the regions
declared (`Window < Process`) and the static source tagged `Process`-lived, the
strong `subscribe self to systemEvents` where the source strictly outlives `self`
trips the generic **OWN014**:

```text
$ python -m ownlang check corpus/wpf/systemevents-region-escape/case.own
case.own:24:23: error: [OWN014] 'systemEvents' (lifetime 'Process') outlives the
  captured object 'GraphicsConfigurationDialog' (lifetime 'Window'); the strong
  subscription promotes 'GraphicsConfigurationDialog' to 'Process' and it leaks
  (no release path)
```

**Two views of one bug — token vs region.** The same SystemEvents leak appears in
the corpus twice, on purpose:

- `corpus/real-world/screentogif-systemevents-leak` models it through the **token
  model** — `event +=` acquires an owned subscription that is never released, so
  the core's **OWN001** fires (a static source is a hard error).
- **This case** models it through the **region model** — the source is
  process-lived, the subscriber is shorter-lived, and the strong capture promotes
  the subscriber to the longer lifetime, so **OWN014** fires. The *ordering* is
  what makes it a leak: subscribing to a same- or shorter-lived source produces no
  diagnostic (no promotion possible).

The region view is what the C# bridge produces for a static-event `+=`: a
`capture` OwnIR fact whose `source: "static"` maps to the process-lived region,
lowered to `subscribe self to <source>` and checked by `ownlang/lifetimes.py`
(pinned end-to-end by `tests/fixtures/ownir/capture.facts.json`). The region view
is also more *precise* than the token view — a subscription to an
equal-or-shorter-lived source is correctly silent, where the flat token model
would warn.

**Honesty / scope.** `case.own` is a *hand reduction*, not direct C# extractor
output — `self`/`source` are the function's own scope and its annotated
parameters; there is no cross-procedural points-to, and weak-event policy as an
explicit escape hatch is a later slice (see `docs/lifetimes.md`). `before.cs` /
`after.cs` are representative of the leak and its fix, not a verbatim copy of one
PR. The fix breaks the static source's hold (here on `Closed`; a disposable token
works too).
