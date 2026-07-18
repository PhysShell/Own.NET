# ScreenToGif — view subscribes to its view-model in `Loaded`, never detaches

**Found by mining** (P-004 milestone 1, see `docs/notes/real-world-mining.md`).
Target: `NickeManarin/ScreenToGif` @ `27a49c3`, file
`ScreenToGif/Windows/Other/VideoSource.xaml.cs:50-83`.

**Pattern.** A WPF `Window` whose `_viewModel = DataContext as VideoSourceViewModel`
wires **four inline-lambda subscriptions** to the view-model's custom events inside
`Window_Loaded` (`ShowErrorRequested`, `HideErrorRequested`, `ShowWarningRequested`,
`CloseRequested`) and **never detaches them** — `Window_Closing` is present but does
no `-=`. Each lambda captures `this`, so the view-model holds a strong reference to
the window; and because `Loaded` can fire more than once, the handlers can stack up.

**What the checker says (real extractor output, with the WPF profile off):**

```text
VideoSource.xaml.cs:50: warning: [OWN001] event '_viewModel.ShowErrorRequested' is
  subscribed (handler '(_, args) => ...') but never unsubscribed; its source is an
  injected dependency whose lifetime is unknown, so it may outlive and keep
  'VideoSource' alive (possible leak — and being an inline lambda it has no '-='
  handle, so it could never be detached) [resource: subscription token]
```

These resolve **without** the WPF reference pack because `_viewModel`'s events are
the app's own types — exactly the differentiated view↔view-model lifetime shape
that generic IDisposable/CA analyzers don't flag.

**Why warning, not error (the honest part).** The C# extractor's source tiering
(P-004) rates this **warning**: `_viewModel` is an injected field, so the extractor
cannot *prove* it outlives the window. In fact, since the view-model is the window's
own `DataContext`, the two most likely share a lifetime (a collectable cycle), so
this may not leak memory at all — but the **duplicate-handler-on-reload** bug is
real regardless. "Possible leak" is the correct verdict, and the lambda note flags
the sharper problem: there is no handle to detach with.

**This `case.own`** models the subscription as a generic acquire/release and so
produces the core's domain-neutral **OWN001** (the severity tiering lives in the C#
extractor, above the core). As with the rest of the corpus, `case.own` is a hand
reduction of the C# pattern, not verbatim extractor output; `before.cs` / `after.cs`
are representative of the leak and its fix.

**#278 follow-up.** `after.cs` wires `Closing += Window_Closing` in the ctor. The
real ScreenToGif attaches the handler in XAML, which the extractor never sees — and
since #278's follow-up a `Window_Closing`-style *name* alone is NOT a teardown
context (a bare name may be stale dead code; the name-suffix exemption was a
silent-FN hole). The corpus case therefore carries the wiring in code, which is the
honest, provable form of the same fix; the name-only shape is pinned as a BAD case
in `corpus/wpf/subscription-xaml-name-only-release`. A future XAML-aware slice can
credit the XAML attach with actual evidence.
