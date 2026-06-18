# ScreenToGif — `SystemEvents.DisplaySettingsChanged` subscribed, never detached

**Found by mining** (P-004 milestone 1, see `docs/notes/real-world-mining.md`),
surfaced once the WPF reference pack was loaded (`OWN_EXTRA_REF_DIRS`). Target:
`NickeManarin/ScreenToGif` @ `27a49c3`, **two** independent occurrences:

- `ScreenToGif/Windows/Other/GraphicsConfigurationDialog.xaml.cs:35`
- `ScreenToGif/Windows/Other/Troubleshoot.xaml.cs:27`

**Pattern.** A `Window` subscribes to `Microsoft.Win32.SystemEvents.DisplaySettingsChanged`
with a method-group handler and never unsubscribes. `SystemEvents` is a **static,
process-lifetime** class; its events hold a strong reference to every subscriber
for the life of the process. The window closes but cannot be collected — the
canonical SystemEvents leak that the .NET docs explicitly warn about.

**What the checker says (real extractor output, WPF profile on):**

```text
GraphicsConfigurationDialog.xaml.cs:35: error: [OWN001] event
  'SystemEvents.DisplaySettingsChanged' is subscribed (handler
  'SystemEvents_DisplaySettingsChanged') but never unsubscribed — the source keeps
  'GraphicsConfigurationDialog' alive (leak) [resource: subscription token]
```

**Why error, not warning (the tiering).** Contrast the `VideoSource` finding next
door (`screentogif-loaded-subscription/`), which the extractor rates a *warning*
because its source is an *injected* field of unknown lifetime. Here the source is a
**static** event, so it *provably* outlives the window — the P-004 severity tiering
classifies it `static` and the leak is a hard **error**, not a "possible leak". The
extractor draws that line from the source's lifetime, exactly as designed.

**This `case.own`** models the subscription as a generic acquire/release, so it
produces the core's domain-neutral **OWN001** (which already defaults to error —
matching the static-source tier; the warning/error split for injected sources lives
in the C# extractor, above the core). As elsewhere in the corpus, `case.own` is a
hand reduction; `before.cs` / `after.cs` capture the leak and its fix.
