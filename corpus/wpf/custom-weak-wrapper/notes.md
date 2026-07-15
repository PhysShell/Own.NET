# WPF custom weak-subscribe wrapper (project-declared accepted release)

**Pattern.** A ViewModel/document object subscribes to a *process-lived* settings
publisher in its constructor (`settings.PropertyChanged += OnSettingsChanged`) and
never unsubscribes. This is the archetypal strong-subscription leak — the same shape
as `zombie-viewmodel`, but the interesting part here is the **fix**, not the leak.

**What the checker says (the leak).** Modelling the VM as one scope (constructor =
scope start, teardown = scope end), the unreleased subscription is the generic
**OWN001**:

```text
$ python -m ownlang check corpus/wpf/custom-weak-wrapper/case.own
case.own:22:9: error: [OWN001] 'sub' is owned but not released at end of function
  (leaks on at least one path) [resource: event subscription]
```

**The fix, and why it is project-specific.** `after.cs` converts the `+=` to a
project-owned, thread-agnostic weak forwarder,
`WeakEvents.AddPropertyChanged(settings, OnSettingsChanged)`, which keeps only a
`WeakReference` to the listener — so the publisher no longer pins the VM and the
object is collectable with no explicit unsubscribe.

The natural first answer, the BCL `System.Windows.WeakEventManager` /
`PropertyChangedEventManager`, was tried on the motivating real codebase (a net472
customs-broker app) and was **unusable in that layer for two independent reasons**:

1. it keeps per-thread bookkeeping and the objects are constructed on **background
   threads** (an import/cloud-sync path builds them inside `Task.Run`), while the
   setting is toggled on the UI thread — the WPF weak-event infrastructure is built
   around a single UI thread; and
2. it **did not resolve** in the data-layer assembly's WPF markup-compile pass — the
   build failed.

So the accepted weak release is **not** a fixed BCL type; it is whatever weak
wrapper a repo actually uses. own-check should let a project *declare* that wrapper
rather than assume `WeakEventManager`. That declaration + its two consumers
(recognise the wrapper as a release; suggest it in the fix text) is
**[P-035](../../../docs/proposals/P-035-custom-weak-subscription.md)**.

**Honesty / scope.** `case.own` is a hand reduction of the C# pattern that exercises
the leak (**OWN001**) with today's checker. The *fixed* form (`after.cs`) is **not
yet** recognised as silent: the extractor sees only `event += handler`, so a
method-call weak wrapper is currently invisible rather than accepted — no false
positive exists *yet*, but there is also no positive recognition. This case is the
regression fixture for the P-035 recognition half: once a `[weak-subscription]`
convention is honoured, converting `before.cs` → `after.cs` must move the finding
from OWN001 to silent-and-recognised, not silent-and-invisible.
