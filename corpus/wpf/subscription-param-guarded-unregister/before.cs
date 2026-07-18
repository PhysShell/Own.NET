// BUGGY (SectorTS GTD shape, issue #278; hand-reduced into case.own).
//
// A data class subscribes to an injected publisher in its ctor and its ONLY
// matching `-=` sits inside a method that is NOT a teardown, behind a bool
// parameter of that method: `UnregisterEventHandlers(bool UnregOnlyGoodys)`
// with the detach under `if (!UnregOnlyGoodys)`. The leaking callers pass
// `true` (and one whole subsystem never calls it at all), so the `-=` provably
// does NOT run on those paths — the subscription pins the document graph to the
// publisher for the life of the process (heap-proven: 66% retained heap after
// 31 documents, GTD.cs:5192).
//
// own-check MUST flag this OWN001. The old "any matching `-=` in the class =
// released" model paired the ctor `+=` with this flag-skipped `-=` and stayed
// silent — the false negative this case pins.
using System.ComponentModel;

public sealed class GoodsDocument
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime

    public GoodsDocument(INotifyPropertyChanged properties)
    {
        _properties = properties;
        // SectorTS idiom: explicit delegate-creation on the `+=`.
        _properties.PropertyChanged += new PropertyChangedEventHandler(OnPropertiesChanged);
    }

    public void UnregisterEventHandlers(bool UnregOnlyGoodys = false)
    {
        if (!UnregOnlyGoodys)                 // callers pass true; the block never runs
        {
            _properties.PropertyChanged -= OnPropertiesChanged;
        }
        // only the goods rows are detached here
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
