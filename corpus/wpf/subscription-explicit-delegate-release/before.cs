// BUGGY (representative WPF/WinForms data-class pattern; hand-reduced into case.own).
//
// A view holds an injected INotifyPropertyChanged whose lifetime it does NOT own,
// subscribes to it in the ctor via an explicit delegate-creation handler, and never
// unsubscribes — no Dispose, no teardown. The injected source keeps this instance
// reachable => a real subscription leak (OWN001). This is the codebase's idiom
// (`+= new PropertyChangedEventHandler(H)`), minus the fix on `after.cs`.
using System.ComponentModel;

public sealed class SourceView
{
    private readonly INotifyPropertyChanged _source;   // injected, unknown lifetime

    public SourceView(INotifyPropertyChanged source)
    {
        _source = source;
        // Explicit delegate-creation handler, never released -> leak.
        _source.PropertyChanged += new PropertyChangedEventHandler(OnSourcePropertyChanged);
    }

    private void OnSourcePropertyChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
