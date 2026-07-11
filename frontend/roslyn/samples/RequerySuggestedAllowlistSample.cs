// P-004 (issue #223): a curated allowlist of ONE BCL/WPF static event —
// System.Windows.Input.CommandManager.RequerySuggested — known to be implemented
// internally over weak references, so a subscriber is never pinned alive by it.
// Mined from AvalonEdit's Editing/ImeSupport.cs (docs/notes/field-notes-patterns.md
// entry 17). No real WPF reference assembly is available on the Linux CI runner, so
// this file declares a self-contained stand-in for System.Windows.Input.CommandManager
// — the same technique WinFormsModelessSample.cs already uses for
// System.Windows.Forms. The extractor resolves the event against THIS declaration
// (all sample files are compiled together), so the allowlist predicate — which keys
// on the event's name + containing type + namespace, not on assembly identity —
// exercises exactly the same code path it would against the real WPF type.
using System;

namespace System.Windows.Input
{
    public static class CommandManager
    {
        public static event EventHandler? RequerySuggested;
    }
}

namespace Own.Samples.WeakStaticEvent
{
    using System.Windows.Input;

    // Positive: allowlisted weak-referenced static event, ordinary instance-bound
    // handler stored in a field, never `-=`'d — mirrors ImeSupport.cs exactly. Must
    // be SILENT (no OWN014 region escape).
    public sealed class ImeSupportLike
    {
        // "we need to keep the event handler instance alive because
        // CommandManager.RequerySuggested uses weak references" — same comment as the
        // real AvalonEdit source; the field exists to keep the HANDLER alive, not to
        // prevent a leak of the subscriber.
        private EventHandler? requerySuggestedHandler;

        public ImeSupportLike()
        {
            requerySuggestedHandler = OnRequerySuggested;
            CommandManager.RequerySuggested += requerySuggestedHandler;
        }

        private void OnRequerySuggested(object? sender, EventArgs e) { }
    }

    // Negative control: an ORDINARY process-lived static event (NOT on the
    // allowlist), same instance-handler-stored-in-a-field shape, never detached. The
    // fix must NOT weaken the general static-source tier — this must STILL raise
    // OWN014, proving the exemption is scoped to the one named CommandManager event.
    public static class OtherStaticSource
    {
        public static event EventHandler? SomethingChanged;
    }

    public sealed class OrdinaryStaticSubscriber
    {
        private EventHandler? handler;

        public OrdinaryStaticSubscriber()
        {
            handler = OnSomethingChanged;
            OtherStaticSource.SomethingChanged += handler;
        }

        private void OnSomethingChanged(object? sender, EventArgs e) { }
    }
}
