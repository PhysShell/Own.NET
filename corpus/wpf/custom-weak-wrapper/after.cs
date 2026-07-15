// FIXED with a project-owned, thread-agnostic weak forwarder. WeakEvents keeps only
// a WeakReference to the listener, so the publisher no longer pins the VM: it is
// collectable with no explicit unsubscribe, and the leak is gone by construction.
//
// The BCL System.Windows.WeakEventManager / PropertyChangedEventManager were tried
// first and were UNUSABLE in this layer for two independent reasons: they keep
// per-thread bookkeeping (the VM is constructed on a background thread), and they
// did not resolve in the assembly's WPF markup-compile pass. That is precisely why
// the accepted weak-subscribe API is PROJECT-SPECIFIC and must be declared, not
// assumed — see docs/proposals/P-035-custom-weak-subscription.md.
//
// A repo tells own-check about this wrapper once, under [weak-subscription] in its
// P-015 config:
//     subscribe   = ["WeakEvents.AddPropertyChanged"]
//     unsubscribe = ["WeakEvents.RemovePropertyChanged"]
// With that declared, own-check recognises the call below as an accepted release
// and stays silent — no false positive on correctly-fixed code.
using System.ComponentModel;

public sealed class DocumentViewModel
{
    public DocumentViewModel(ISettings settings)
    {
        WeakEvents.AddPropertyChanged(settings, OnSettingsChanged);   // weak: does not pin `this`
    }

    private void OnSettingsChanged(object sender, PropertyChangedEventArgs e)
    {
        // recompute a display string when a global setting toggles
    }
}

public interface ISettings : INotifyPropertyChanged { }

// A tiny, thread-agnostic weak forwarder (the project owns the implementation;
// Own.NET only recommends the shape). Sketch:
//   AddPropertyChanged(src, handler) => src holds a strong ref only to a small
//   forwarder; the forwarder holds a WeakReference to handler.Target and unhooks
//   itself once that target is collected.
public static class WeakEvents
{
    public static void AddPropertyChanged(INotifyPropertyChanged source, PropertyChangedEventHandler handler) { /* ... */ }
    public static void RemovePropertyChanged(INotifyPropertyChanged source, PropertyChangedEventHandler handler) { /* ... */ }
}
