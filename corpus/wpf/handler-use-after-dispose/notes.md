# WPF subscription used after Dispose

**Pattern:** a ViewModel unsubscribes / disposes its subscription on close, but a
callback that was already queued on the dispatcher still runs and touches the
disposed, subscription-backed state. In real code this is an
`ObjectDisposedException` or a read of torn state — the use-after-dispose cousin
of the zombie-ViewModel leak.

**What the checker says:** using a resource after its `release` (Dispose) is the
generic **OWN002** (use after release), carrying the resource-kind tag:

```text
$ python -m ownlang check corpus/wpf/handler-use-after-dispose/case.own
case.own:16:9: error: [OWN002] use 'sub' after it was released
  [resource: subscription token]
  16 |     use sub;
               ^
```

**Honesty / scope.** `case.own` is a *hand reduction* of the C# pattern, not
direct C# extractor output (the C# extractor in P-001 is narrow — event
subscriptions only). It shows the ownership
*logic* maps onto the real bug; it does not model the dispatcher queue or
exception flow. `before.cs` / `after.cs` are representative, not a verbatim copy
of one PR.
