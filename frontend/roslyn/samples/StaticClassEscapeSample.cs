using System;

namespace Own.Samples;

// P-004 static-handler exemption, robustly (mined: ImageSharp MemoryAllocatorValidator).
//
// A static class whose static ctor hooks a process-lived STATIC event with a STATIC METHOD
// handler stores a delegate whose Target is null — no instance is retained, so OWN014 must NOT
// fire. The mined case slipped through because the method-group symbol can surface as a member
// group (Symbol == null), which IsStaticHandler now resolves via CandidateSymbols. Contrast:
// StaticEventEscapeViewModel — an INSTANCE handler on a static event — must still raise OWN014
// (capturing lambdas in a static class likewise still escape: the closure is retained).

public static class StaticDiagnosticsBus
{
    public static event EventHandler? Allocated;

    public static void Raise() => Allocated?.Invoke(null, EventArgs.Empty);
}

public static class StaticAllocationCounter
{
    static StaticAllocationCounter()
    {
        StaticDiagnosticsBus.Allocated += OnAllocated;   // static-method handler -> null target -> SILENT
    }

    private static void OnAllocated(object? sender, EventArgs e) { }
}
