# Subscription whose only `-=` is in a XAML-convention-NAMED but unwired handler (soundness FN)

**Pattern (#278 follow-up, blocker 2).** Ctor `+=` to an injected publisher; the
matching `-=` sits in `Window_Closing(object, EventArgs)` — a method named
exactly like a XAML-wired lifecycle handler — but nothing in code attaches it
to any event. The XAML attach (if one ever existed) never reaches the
extractor; a bare handler-shaped name may equally be stale dead code after the
XAML attribute was removed. The name proves nothing about execution.

**The bug.** The first #278 slice recognised the `*_Closed`/`*_Closing`/
`*_Unloaded`/... naming convention as a teardown root, so this shape was
silently credited as released — a name-only silent-exemption path.

**The fix.** The suffix rule is removed entirely. A `Window_Closing`-style
handler is a teardown context only when the class provably wires it in code
(`this.Closing += Window_Closing`, or an inline lambda on the same event). The
previously name-carried corpus control
(`corpus/real-world/screentogif-loaded-subscription/after.cs`) now carries the
wiring in code — the honest form of the same fix. XAML-backed release without
code wiring is deliberately left as a kept warning until a XAML-aware slice can
credit the attach with actual evidence.

**`after.cs` pins both wired forms**: the method-group handler
(`this.Closing += Window_Closing`, `-=` inside the handler) and the
inline-lambda handler on the same lifecycle event. Both silent. Note the wiring
recognition works even when the lifecycle event itself cannot be resolved (a
WPF `Window.Closing` on a Linux runner): a method GROUP carries no argument
list, so falling back to the group's name selects the same overload set the
group denotes — distinct from the invocation-overload conflation ruled out in
`subscription-overload-conflated-cleanup`.

**What the checker says (`.own` reduction).** The ctor scope acquires the token
and no provable teardown path releases it => **OWN001** with the
subscription-token resource tag.

**Regression guard.** `scripts/benchmark.py`: `before.cs` must be **caught**,
`after.cs` must be **silent**.
