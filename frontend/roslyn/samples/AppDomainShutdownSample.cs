using System;

namespace Own.Samples;

// P-004 process-lifetime AppDomain-event exemption (mined: Npgsql PoolManager). Subscribing to
// AppDomain's process-host events — ProcessExit / DomainUnload (shutdown cleanup hooks) and
// UnhandledException / FirstChanceException (process-wide diagnostics) — is never a region
// escape: the handler is meant to live for the whole process. Must be SILENT. Contrast:
// NonAppDomainSubscriber below — a non-AppDomain static event with a lambda still raises OWN014,
// proving the exemption keys off the AppDomain source, not any process-lived static event.

public sealed class ShutdownCleanup
{
    public ShutdownCleanup()
    {
        AppDomain.CurrentDomain.ProcessExit += (_, _) => Cleanup();          // shutdown hook -> SILENT
        AppDomain.CurrentDomain.DomainUnload += (_, _) => Cleanup();         // shutdown hook -> SILENT
        AppDomain.CurrentDomain.UnhandledException += (_, _) => Cleanup();   // process diagnostics -> SILENT
        AppDomain.CurrentDomain.FirstChanceException += (_, _) => Cleanup(); // process diagnostics -> SILENT
    }

    private static void Cleanup() { }
}

// Codex control: a process-host AppDomain event is exempt only when the handler retains NO
// instance. A lambda that CAPTURES instance state (here `_count`) pins this subscriber to the
// process until shutdown — a real region escape that must STILL raise OWN014.
public sealed class CapturingShutdownSubscriber
{
    private int _count;

    public CapturingShutdownSubscriber()
    {
        AppDomain.CurrentDomain.ProcessExit += (_, _) => _count++;   // captures `this` -> OWN014
    }
}

public static class SomeBus
{
    public static event EventHandler? Pinged;

    public static void Raise() => Pinged?.Invoke(null, EventArgs.Empty);
}

// Control: a lambda on a NON-AppDomain process-lived (static) event -> region escape -> must WARN.
public sealed class NonAppDomainSubscriber
{
    public NonAppDomainSubscriber()
    {
        SomeBus.Pinged += (_, _) => Handle();   // static event, lambda, not AppDomain -> OWN014
    }

    private static void Handle() { }
}
