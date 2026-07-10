using System;

namespace Own.Samples;

// Issue #199 — the SILENT lambda-handler tiers (the static/injected tiers live in
// AppDomainShutdownSample.cs / LambdaHandlerViewModel.cs). Source lifetime decides the
// verdict for a lambda exactly as for a method group; a lambda merely can never be
// `-=`'d (no handle), which matters only when the source actually outlives `this`.

// BOUNDED / LOCAL source + lambda: the publisher is constructed HERE (a local), so it is
// method-bounded — it dies with the scope and cannot outlive `this`, so the subscription
// is no heap leak -> SILENT (the extractor drops source=="local"). The lambda has no `-=`
// handle, but with a bounded source there is nothing to leak: this IS the
// "`-=`-impossible-but-bounded" shape that must stay silent.
public sealed class LocalBoundedLambda
{
    public void Work()
    {
        var pub = new Publisher();
        pub.Changed += (s, e) => Console.WriteLine("bounded");   // local source -> SILENT
        pub.Raise();
    }
}

// SELF-OWNED field source + lambda: the class constructs the source (a field it `new`s),
// so the source<->this cycle is collectable together -> SILENT (self-owned exemption),
// whether the handler is a lambda (captures `this`) or a method group.
public sealed class SelfOwnedFieldLambda
{
    private int _n;
    private readonly Publisher _pub = new Publisher();

    public SelfOwnedFieldLambda()
    {
        _pub.Changed += (s, e) => _n++;   // self-owned source -> SILENT
    }
}

public sealed class Publisher
{
    public event EventHandler? Changed;

    public void Raise() => Changed?.Invoke(this, EventArgs.Empty);
}
