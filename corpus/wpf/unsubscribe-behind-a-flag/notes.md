# Unsubscribe behind a flag, in a method nobody calls (release-reachability FN)

> **This case is RED today.** `before.cs` is a real, heap-proven leak and own-check is **silent** on it.
> It is a regression guard for #278, not a passing test. It goes green when release-matching stops
> concluding "released" from the mere *existence* of a `-=`.

**Pattern.** A document subscribes to a **static** publisher in its constructor. A matching `-=` does
exist in the class — so the current model pairs them and says nothing — but it never runs:

```csharp
public Document()
{
    AppSettings.Options.PropertyChanged += new PropertyChangedEventHandler(OnOptionsChanged);  // static publisher
}

public void UnregisterEventHandlers(bool unregOnlyChildren = false)   // NOT a teardown
{
    if (!unregOnlyChildren)                                            // callers pass true
        AppSettings.Options.PropertyChanged -= OnOptionsChanged;       // the `-=` that never runs
}
```

Three independent reasons the release is unreachable, any one of which is enough:

1. `UnregisterEventHandlers` is **not a teardown** — not `Dispose`, `OnClosed` or `Unloaded`.
   `docs/proposals/P-001-csharp-extractor.md:51` and `P-004-wpf-lifetime-profile.md:33` both specify the
   release must be *in* one of those. The extractor is looser than its own spec
   (`OwnSharp.Extractor/Program.cs:13`: *"released by a matching `-=` **in the class**"*).
2. The `-=` sits behind a **parameter guard**, and the calling code passes `true`.
3. Whole subsystems **never call the method at all**.

**Why it matters.** The publisher is static, so the handler pins the subscriber for the life of the
process — the strongest leak tier P-004 defines, and the one the analyzer is supposed to call a *provable*
leak rather than a possible one.

**Provenance.** Reduced from SectorTS `BrokerDataClasses/GTD.cs:5192` (subscribe to the static
`AppData.Properties.GBProperty`) and `:5259` (`UnregisterEventHandlers(bool UnregOnlyGoodys)`).
`Service/GTDService.cs` passes `true` at five sites; `BrokerDataClasses/DocCloud/**` — including eight
AutoMapper `.ConstructUsing(x => new GTD(null, null))` profiles that build a document per mapping —
never calls it at all.

Proven at runtime with a ClrMD root walk, after **31 documents**:

```
on the heap          : 1 685 951 objects   223 MB
REACHABLE from roots : 1 569 072 objects   148 MB
>>> 66.3% of the heap is genuinely RETAINED

[PinnedHandle] System.Object[]
  KernelProperty                 <- AppData.Properties (static)
    GBProperty
      PropertyChangedEventHandler
        System.Object[]           <- the delegate's invocation list
          PropertyChangedEventHandler
            GTD                   <- the whole document graph
```

Detaching after each document (`UnregisterEventHandlers(false)`) makes the process memory-flat —
peak RSS 2.71 GB → 0.61 GB on the same 389 documents, **byte-identical output** — which confirms the
diagnosis rather than merely being consistent with it.

**Relation to the known gap.** `corpus/wpf/subscription-explicit-delegate-release/notes.md:28-41`
already records that the release model is not flow-sensitive ("*it treats any matching `-=` in the class
as releasing the subscription … that soundness gap is pre-existing*", Codex P2 on #163). That note scoped
the gap to a **rebinding setter** and deferred it. This case shows the surface is much wider — a
parameter guard, a non-teardown method, and an uncalled method are all ordinary code — and gives the gap
its first real, heap-proven instance.

**Regression guard.** `scripts/benchmark.py` runs the real C# through the extractor + core:

* `before.cs` must be **caught** (OWN001) — it is a genuine leak. *Currently it is not: this is the bug.*
* `after.cs` must be **silent** — the release is unconditional and in `Dispose`. It must stay silent
  after the fix, or the fix has simply traded a false negative for a false positive.

The pair differs **only** in whether the release is provably reached; the `+=` and the `-=` name the same
`(receiver, handler)` in both. That is deliberate: a model that keys on the existence of a matching `-=`
cannot tell these two files apart.
