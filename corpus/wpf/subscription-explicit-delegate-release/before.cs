// BUGGY (representative WPF/WinForms data-class pattern; hand-reduced into case.own).
//
// A view/data class exposes a settable `Source` (an injected INotifyPropertyChanged
// whose lifetime the class does not own). The setter subscribes to the new source's
// PropertyChanged but NEVER unsubscribes the old one. Each reassignment strands the
// previous source's handler, and the last subscription is never torn down — the
// injected source keeps this instance reachable. A real subscription leak (OWN001).
//
// This is the exact shape mined from SectorTS (e.g. BrokerDataClasses/BranchDescription.cs
// `Address` setter), minus the fix on `after.cs`.
using System.ComponentModel;

public sealed class SourceView
{
    private INotifyPropertyChanged _source;

    public INotifyPropertyChanged Source
    {
        get => _source;
        set
        {
            _source = value;
            // Explicit delegate-creation handler (the codebase's idiom), never released.
            _source.PropertyChanged += new PropertyChangedEventHandler(OnSourcePropertyChanged);
        }
    }

    private void OnSourcePropertyChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
