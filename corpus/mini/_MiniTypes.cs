using System;

// Supporting types for the frozen mini corpus. They exist so every `+=`, field and
// local in this directory binds to a REAL symbol under the type-aware extractor
// (P-014 Tier A) without referencing WPF or any third-party assembly — the same
// reason frontend/roslyn/samples/SampleTypes.cs exists.
//
// FROZEN. Adding a type here changes what the corpus resolves, which changes the
// findings, which is a corpus change and not a producer change. See README.md.

namespace Own.Corpus.Mini;

public interface IEventBus
{
    event EventHandler CustomerChanged;
    event EventHandler OrdersChanged;
}

// An event source a component can construct and own, plus a process-lived static
// event (the region-escape source).
public sealed class Calc
{
    public event EventHandler? Changed;
    public static event EventHandler? GlobalPing;
}

// A stand-in for System.Windows.Threading.DispatcherTimer: the same
// Tick / Start / Stop surface, so `_timer.Tick += OnTick` binds to a real event.
public sealed class DispatcherTimer
{
    public event EventHandler? Tick;
    public void Start() { }
    public void Stop() { }
}

// A plain owned IDisposable — no BCL special-casing (no dispose-optional exemption,
// no empty-Dispose exemption), so a field or local of it is an unambiguous OWN001.
public sealed class Handle : IDisposable
{
    private bool _open = true;
    public void Dispose() { _open = false; }
    public bool IsOpen => _open;
}

// Declared locally so the [OwnIgnore("reason")] shape compiles: the extractor
// matches the attribute by SIMPLE name, so a project may declare its own.
[AttributeUsage(AttributeTargets.Field | AttributeTargets.Property
              | AttributeTargets.Method | AttributeTargets.Class, AllowMultiple = false)]
public sealed class OwnIgnoreAttribute : Attribute
{
    public OwnIgnoreAttribute() { }
    public OwnIgnoreAttribute(string reason) { Reason = reason; }
    public string? Reason { get; }
}
