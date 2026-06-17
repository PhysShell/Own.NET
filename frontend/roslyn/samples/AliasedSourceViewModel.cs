using System;

// SUBSCRIPTION SOURCE PROVENANCE (P-004): two locals, two verdicts.
//
//  (1) `src` ALIASES the injected `_bus` (a ctor dependency of unknown lifetime).
//      A local is not automatically method-bounded — this one may hold a
//      long-lived source, so the extractor must NOT drop it. It is classified
//      `injected`, and the core reports OWN001 at WARNING, like CustomerViewModel.
//
//  (2) `owned` is a publisher this scope CONSTRUCTS (`new Calc()`); it dies with
//      the constructor, so the subscription cannot outlive `this` — a genuinely
//      method-local source. The extractor classifies it `local` and DROPS it (no
//      finding), the same spirit as the self-owned-field exemption.
public sealed class AliasedSourceViewModel
{
    private readonly IEventBus _bus;

    public AliasedSourceViewModel(IEventBus bus)
    {
        _bus = bus;

        var src = _bus;                       // aliases an injected field
        src.CustomerChanged += OnAliased;     // unknown lifetime -> WARNING leak

        var owned = new Calc();               // constructed here -> method-bounded
        owned.Changed += OnLocal;             // dies with the ctor -> dropped
    }

    private void OnAliased(object? sender, EventArgs e) { }
    private void OnLocal(object? sender, EventArgs e) { }
}
