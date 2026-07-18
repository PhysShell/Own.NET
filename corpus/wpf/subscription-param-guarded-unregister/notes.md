# Subscription with a parameter-guarded `-=` in a non-teardown method (soundness FN)

**Pattern (SectorTS `GTD`, issue #278).** A data class subscribes to a publisher
in its ctor. A matching `-=` exists — but it lives inside
`UnregisterEventHandlers(bool UnregOnlyGoodys = false)`, which is not a teardown,
and behind `if (!UnregOnlyGoodys)`:

```csharp
AppData.Properties.GBProperty.PropertyChanged += GBProperty_PropertyChanged;   // ctor

public void UnregisterEventHandlers(bool UnregOnlyGoodys = false)
{
    if (!UnregOnlyGoodys)                    // <-- GTDService/DocCloud pass true; the block never runs
    {
        AppData.Properties.GBProperty.PropertyChanged -= GBProperty_PropertyChanged;
    }
}
```

`Service/GTDService.cs` calls it with `true` at 5 sites, and the `DocCloud`
subsystem (8+ AutoMapper `.ConstructUsing(x => new GTD(null, null))` profiles)
never calls it at all — every mapped document pins itself to the static publisher
for the life of the process. Runtime proof (ClrMD retention-path walk, 31
documents): 66.3% of the heap genuinely retained, with the path
`[PinnedHandle] -> KernelProperty -> PropertyChangedEventHandler -> GTD`.

**The bug (Own.NET extractor).** The shipped release model treated *any* matching
`-=` anywhere in the class as releasing the subscription — no check that the
method holding it is a teardown, is ever called, or that the `-=` is not guarded
away by a parameter. So OWN001 paired the ctor `+=` with this flag-skipped `-=`
and stayed **silent** on the very codebase the heuristic was tuned against — a
false negative that silently swallows a leak class (the #238 doctrine violation:
the worst case of an exemption must be "keeps today's honest warning", never
"silently swallows a leak class").

**The fix (#278).** A matching `-=` credits release only when it sits in a
recognised teardown context (`Dispose`/`DisposeAsync`/`OnClosed`/`Unloaded`/…, a
handler wired to the class's own `Closed`/`Unloaded`-style lifecycle event, or a
method the teardown path calls intra-class) AND is not guarded by a parameter of
its enclosing method. `UnregisterEventHandlers(bool)` fails both rules, so
`before.cs` is flagged OWN001. `after.cs` releases unconditionally in `Dispose`
— a teardown with no caller-controlled guard — and stays silent.

**What the checker says (`.own` reduction).** The guard is modelled as an early
`return` before the `release`: on the flag=true path the token is never
released, so the core reports **OWN001** ("not released on all paths") with the
subscription-token resource tag.

**Regression guard.** `scripts/benchmark.py` runs the real C# through the
extractor + core: `before.cs` must be **caught** (the leak is real and
heap-proven) and `after.cs` must be **silent**. Before the #278 fix, `before.cs`
was silent — the false negative this case pins.

**Honesty / scope.** `case.own` is a hand reduction carrying the acquire/release
logic; the teardown-context and parameter-guard reasoning lives in the extractor
(`frontend/roslyn/OwnSharp.Extractor/Program.cs`, the `unsub` gating). The C#
here is representative of the SectorTS idiom (explicit delegate-creation `+=`,
default-parameter unregister), not a verbatim copy of `GTD.cs`.
