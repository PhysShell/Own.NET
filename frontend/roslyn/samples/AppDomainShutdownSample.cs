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

// Control (the shape Codex defended — CsvHelper ConsoleHost's cts/resetEvent capture):
// a CAPTURING lambda on a NON-AppDomain process-lived (static) event pins the captured
// state (here the ctor's `cts`) for the whole process — a real region escape that must
// STILL raise OWN014. The non-retaining static gate (issue #199) must NOT clear this:
// HandlerRetainsNoInstance returns false because an enclosing local/parameter is captured.
public sealed class NonAppDomainSubscriber
{
    public NonAppDomainSubscriber(System.Threading.CancellationTokenSource cts)
    {
        SomeBus.Pinged += (_, _) => cts.Cancel();   // captures `cts` -> OWN014
    }
}

// CONTRAST (issue #199): a NON-CAPTURING lambda on the SAME non-AppDomain static event
// captures neither `this` nor any enclosing local (a bare static call) -> retains no
// instance -> the closure analog of the static-METHOD exemption (StaticHandlerViewModel)
// -> SILENT. This is the false positive the non-retaining static gate removes: a
// non-retaining handler cannot pin a subscriber, so OWN014's premise does not hold.
// Policy: docs/notes/subscription-leaks-and-profiles.md (static + non-retaining -> silent).
public sealed class NonCapturingStaticSubscriber
{
    public NonCapturingStaticSubscriber()
    {
        SomeBus.Pinged += (_, _) => Handle();   // no capture -> silent
    }

    private static void Handle() { }
}
