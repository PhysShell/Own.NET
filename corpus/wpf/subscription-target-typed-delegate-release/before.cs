// BUGGY — the target-typed (C# 9) twin of subscription-explicit-delegate-release.
// The ctor subscribes an injected source using target-typed delegate creation
// `new(H)` (Roslyn: ImplicitObjectCreationExpressionSyntax) and never unsubscribes
// — no Dispose. The injected source keeps this instance reachable => leak (OWN001).
using System.ComponentModel;

public sealed class SourceView
{
    private readonly INotifyPropertyChanged _source;   // injected, unknown lifetime

    public SourceView(INotifyPropertyChanged source)
    {
        _source = source;
        _source.PropertyChanged += new(OnSourcePropertyChanged);   // target-typed delegate creation, never released
    }

    private void OnSourcePropertyChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
