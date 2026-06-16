using System;

// NOT a leak (P-004 static-handler exemption): the handler is a STATIC method, so
// the stored delegate's Target is null — no instance is retained, however
// long-lived the source (here a static event that lives the whole program). The
// extractor must stay SILENT, unlike an instance-method handler which would pin
// its owner. Contrast: CustomerViewModel (instance handler → leak).
public sealed class StaticHandlerViewModel
{
    public StaticHandlerViewModel()
    {
        Calc.GlobalPing += OnGlobalPing;   // static handler -> null target, no leak
    }

    private static void OnGlobalPing(object? sender, EventArgs e) { }
}
