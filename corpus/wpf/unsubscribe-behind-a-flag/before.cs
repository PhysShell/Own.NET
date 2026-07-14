// BUGGY. A `-=` that exists is not a `-=` that runs.
//
// The document subscribes to a STATIC event in its constructor. A matching `-=` does exist —
// so own-check's release model ("any matching `-=` in the class releases it") falls silent —
// but it is unreachable in practice on two independent counts:
//
//   1. it lives in `UnregisterEventHandlers`, which is not a teardown (`Dispose`/`OnClosed`/
//      `Unloaded`); P-001 and P-004 both specify the release must be *in* a teardown, and the
//      extractor is looser than its own spec;
//   2. even when that method IS called, the `-=` sits behind `if (!unregOnlyChildren)`, and the
//      calling code passes `true`.
//
// The publisher is static, so the handler pins the whole document graph for the life of the
// process. Reduced from SectorTS `BrokerDataClasses/GTD.cs:5192` (subscribe) / `:5259`
// (the flag-guarded release); heap-proven — 66% of the heap still reachable from the GC roots
// after 31 documents, retention path
// [PinnedHandle] -> static KernelProperty -> GBProperty -> PropertyChangedEventHandler -> GTD.
using System.ComponentModel;

// The app-lifetime settings object. Static => lives for the whole process.
public static class AppSettings
{
    public static readonly NotifyingOptions Options = new NotifyingOptions();
}

public class NotifyingOptions : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler PropertyChanged;
}

public sealed class Document
{
    public Document()
    {
        // Subscribed to a STATIC publisher. Nothing detaches this unless somebody calls
        // UnregisterEventHandlers(false) — and nobody does. -> OWN001
        AppSettings.Options.PropertyChanged += new PropertyChangedEventHandler(OnOptionsChanged);
    }

    // NOT a teardown, and the release is guarded away by the parameter every caller passes.
    public void UnregisterEventHandlers(bool unregOnlyChildren = false)
    {
        if (!unregOnlyChildren)
        {
            AppSettings.Options.PropertyChanged -= OnOptionsChanged;   // the `-=` that never runs
        }

        // ... detach the child rows only ...
    }

    private void OnOptionsChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}

public sealed class ImportService
{
    public Document Import()
    {
        var doc = new Document();
        doc.UnregisterEventHandlers(true);   // true => the static `-=` above is skipped
        return doc;
    }
}
