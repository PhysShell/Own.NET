using System;

namespace Own.Samples;

// P-004 static-class region-escape exemption (mined: ImageSharp MemoryAllocatorValidator).
//
// A `static class` has NO instance, so subscribing to a process-lived STATIC event from its
// static ctor cannot promote an instance to the source's lifetime — OWN014 must NOT fire. A
// LAMBDA handler is used on purpose: it is NOT covered by the static-method-handler exemption,
// so silence here exercises the static-class drop itself, not that exemption. Contrast:
// StaticEventEscapeViewModel (an INSTANCE class on the same shape) must STILL raise OWN014.

public static class StaticDiagnosticsBus
{
    public static event EventHandler? Allocated;

    public static void Raise() => Allocated?.Invoke(null, EventArgs.Empty);
}

public static class StaticAllocationCounter
{
    private static int count;

    static StaticAllocationCounter()
    {
        StaticDiagnosticsBus.Allocated += (_, _) => count++;   // lambda + static event + static class -> SILENT
    }

    public static int Count => count;
}
