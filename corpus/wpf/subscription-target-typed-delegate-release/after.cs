// FIXED. Single readonly source, subscribed in the ctor with C# 9 target-typed
// delegate creation `new(H)`, released in Dispose with a bare `-= H`. No receiver
// rebinding -> unconditionally clean.
//
// own-check MUST treat this as released (silent). The extractor has to normalize the
// target-typed delegate creation (ImplicitObjectCreationExpressionSyntax) to its inner
// handler, else `new(H)` != `H` on the release key and a correctly torn-down
// subscription is a false OWN001 (the P3 gap this case pins).
using System;
using System.ComponentModel;

public sealed class SourceView : IDisposable
{
    private readonly INotifyPropertyChanged _source;   // set once in the ctor, never rebound

    public SourceView(INotifyPropertyChanged source)
    {
        _source = source;
        _source.PropertyChanged += new(OnSourcePropertyChanged);   // target-typed delegate creation
    }

    public void Dispose()
    {
        _source.PropertyChanged -= OnSourcePropertyChanged;        // bare method group — releases the one subscription
    }

    private void OnSourcePropertyChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
