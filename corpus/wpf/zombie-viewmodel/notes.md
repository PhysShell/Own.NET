# WPF zombie ViewModel (strong event subscription never disposed)

**Pattern:** a ViewModel subscribes to a longer-lived (App-lifetime) event
bus / event aggregator in its constructor and never unsubscribes. WPF
documentation is explicit that an ordinary event subscription creates a *strong*
reference from the event source to the listener; if the source outlives the
listener and the handler is never unregistered, the listener is kept alive —
a memory leak. The window closes, but the ViewModel lives until the process
ends. This is the single most common real WPF leak.

**What the checker says:** modelling the ViewModel as one scope (constructor =
scope start, `Dispose` = scope end), the unreleased subscription token is the
generic **OWN001** (owned resource not released on all paths), now carrying the
resource-kind tag:

```text
$ python -m ownlang check corpus/wpf/zombie-viewmodel/case.own
case.own:16:9: error: [OWN001] 'customerChanged' is owned but not released at
  end of function (leaks on at least one path) [resource: subscription token]
  16 |     let customerChanged = acquire Subscription(bus);
               ^
```

The `[resource: subscription token]` suffix is domain-neutral metadata: the core
stays a generic ownership checker, and a later WPF profile/front-end can read the
kind to phrase this as "WPF004: subscription token never disposed" without the
core knowing anything about WPF.

**Honesty / scope.** `case.own` is a *hand reduction* of the C# pattern, not C#
the checker ingested — OwnLang has no C# front-end (that is a later slice). It
shows the ownership *logic* maps onto the real leak: had the VM been written in
OwnLang, the checker would have rejected it. The lifetime-region machinery that
would catch "VM promoted to App-lifetime through the subscription" (the escape
path) is a separate, later slice; here the bug is caught by plain
acquire/release accounting. `before.cs` / `after.cs` capture the pattern; they
are representative, not a verbatim copy of one PR.
