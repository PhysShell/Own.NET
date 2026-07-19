// FIXED. The release is unconditional and in a teardown.
//
// Two things changed, and both matter:
//
//   1. the `-=` moved into `Dispose()` — a teardown context, which is what P-001/P-004 require;
//   2. the flag no longer guards it. `UnregisterChildren` still exists for the callers that only
//      wanted the child rows detached, but it can no longer be mistaken for a full teardown, and
//      it cannot silently skip the static detach.
//
// own-check MUST treat this as released (silent). The point of the pair is that `before.cs` and
// `after.cs` differ ONLY in whether the release is provably reached — the `+=` and the `-=` name
// the same (receiver, handler) pair in both files. A model that keys on the mere existence of a
// matching `-=` cannot tell these two apart, which is exactly the soundness gap this case pins.
using System;
using System.ComponentModel;

public static class AppSettings
{
    public static readonly NotifyingOptions Options = new NotifyingOptions();
}

public class NotifyingOptions : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler PropertyChanged;
}

public sealed class Document : IDisposable
{
    public Document()
    {
        AppSettings.Options.PropertyChanged += new PropertyChangedEventHandler(OnOptionsChanged);
    }

    public void Dispose()
    {
        // Unconditional, in a teardown. This is the one the subscription is paired with.
        AppSettings.Options.PropertyChanged -= OnOptionsChanged;
        UnregisterChildren();
    }

    // Narrowed and honestly named: it detaches the child rows, and nothing else. It can no longer
    // be handed a flag that quietly turns it into a no-op for the static subscription.
    public void UnregisterChildren()
    {
        // ... detach the child rows only ...
    }

    private void OnOptionsChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}

public sealed class ImportService
{
    public void Import()
    {
        using (var doc = new Document())
        {
            // ... map / import ...
        }   // Dispose() detaches it from the static publisher
    }
}
