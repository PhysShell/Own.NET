// FIXED. Dispose now actually CALLS the local function holding the `-=`; the
// symbol-based teardown closure proves `Dispose() -> Detach()` and credits the
// release. (The wired-lambda good form lives in
// subscription-xaml-name-only-release/after.cs — a lambda counts only as the
// handler wired to a lifecycle event or when provably invoked.)
//
// own-check MUST treat this as released (silent).
using System;
using System.ComponentModel;

public sealed class UncalledLocalFunctionView : IDisposable
{
    private readonly INotifyPropertyChanged _model;   // injected, unknown lifetime

    public UncalledLocalFunctionView(INotifyPropertyChanged model)
    {
        _model = model;
        _model.PropertyChanged += OnModelChanged;
    }

    public void Dispose()
    {
        Detach();                                     // the call is the proof

        void Detach()
        {
            _model.PropertyChanged -= OnModelChanged;
        }
    }

    private void OnModelChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
