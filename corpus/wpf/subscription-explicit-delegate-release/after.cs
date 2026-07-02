// FIXED. The single injected source is subscribed once in the ctor and released in
// Dispose. There is NO receiver rebinding — `_source` is readonly, so the one
// subscription created is the exact one torn down, and the `-=` unconditionally
// releases it (this is why the case does not lean on own-check's non-flow-sensitive
// "any -= in the class = released" model; see notes.md).
//
// own-check MUST treat this as released (silent). The subscription and the
// unsubscription name the SAME (receiver, handler) pair; the only difference is that
// `+=` wraps the handler in `new PropertyChangedEventHandler(...)` while `-=` uses a
// bare method group. An extractor that keys release on the raw handler text sees
// `new Prop...Handler(H)` != `H` and falsely reports a leak — the false positive this
// case pins.
using System;
using System.ComponentModel;

public sealed class SourceView : IDisposable
{
    private readonly INotifyPropertyChanged _source;   // set once in the ctor, never rebound

    public SourceView(INotifyPropertyChanged source)
    {
        _source = source;
        _source.PropertyChanged += new PropertyChangedEventHandler(OnSourcePropertyChanged);  // explicit delegate
    }

    public void Dispose()
    {
        _source.PropertyChanged -= OnSourcePropertyChanged;   // bare method group — releases the one subscription
    }

    private void OnSourcePropertyChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
