// FIXED. The setter unsubscribes the previous source before rebinding, so no
// handler is stranded and the source<->handler edge is always torn down. This is
// the idiomatic SectorTS teardown (BranchDescription.cs `Address` setter): the
// `-=` is written as a BARE method group, while the `+=` wraps the same method in
// an explicit `new PropertyChangedEventHandler(...)`.
//
// own-check MUST treat this as released (silent). The subscription and the
// unsubscription name the SAME (receiver, handler) pair; the only difference is
// that `+=` wraps the handler in a delegate-creation and `-=` does not. An
// extractor that keys release on the raw handler text sees `new Prop...Handler(H)`
// != `H` and falsely reports a leak — the false positive this case pins.
using System.ComponentModel;

public sealed class SourceView
{
    private INotifyPropertyChanged _source;

    public INotifyPropertyChanged Source
    {
        get => _source;
        set
        {
            if (_source != null)
                _source.PropertyChanged -= OnSourcePropertyChanged;                 // bare method group
            _source = value;
            _source.PropertyChanged += new PropertyChangedEventHandler(OnSourcePropertyChanged);  // explicit delegate
        }
    }

    private void OnSourcePropertyChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
