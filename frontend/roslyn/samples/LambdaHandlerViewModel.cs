using System;

// SUBSCRIPTION LEAK (injected source, lambda handler): subscribes a LAMBDA to an
// injected event bus in the constructor and never unsubscribes. Two things stack:
// (1) the source `bus` is INJECTED, so its lifetime is unknown — like
// CustomerViewModel.cs, the core reports OWN001 at WARNING level (a "possible
// leak") until lifetime/ownership modelling can prove it; (2) a lambda literal has
// no stored delegate, so it can NEVER be removed with `-=` even on purpose (you'd
// have to cache the delegate in a field just to detach it) — the finding spells
// that out. The extractor binds the LHS to the event symbol (a lambda RHS rather
// than a method group doesn't matter) and emits released=false, source=injected,
// lambda=true. Contrast CustomerViewModel.cs (method-group handler, same source).
public sealed class LambdaHandlerViewModel
{
    private int _count;

    public LambdaHandlerViewModel(IEventBus bus)
    {
        // captures `this` (via _count) -> not a static handler -> not exempt;
        // no matching `-=` is even possible -> leak.
        bus.CustomerChanged += (s, e) => _count++;
    }
}
