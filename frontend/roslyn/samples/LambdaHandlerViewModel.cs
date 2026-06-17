using System;

// LEAK (lambda handler): subscribes a LAMBDA to a longer-lived event bus in its
// constructor and never unsubscribes. A lambda literal has no handle, so it can
// NEVER be removed with `-=` — an especially nasty WPF leak (you'd have to store
// the delegate in a field just to detach it). The extractor binds the LHS to the
// event symbol (the RHS being a lambda rather than a method group doesn't matter)
// and emits the subscription with released=false, so the core reports OWN001 at
// the `+=` line. Contrast CustomerViewModel.cs (method-group handler, same leak).
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
