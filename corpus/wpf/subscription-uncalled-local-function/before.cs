// BUGGY (#278 follow-up, blocker 4; hand-reduced into case.own).
//
// Both classes place the matching `-=` inside a callable DECLARED lexically
// inside Dispose — a local function in one, a lambda in the other — that
// Dispose never invokes. Declaration is not execution: a nested callable does
// not run just because its enclosing method does. Lexically inheriting the
// teardown context was a silent false-negative path in the first #278 slice.
//
// own-check MUST flag both OWN001.
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
        void Detach()
        {
            _model.PropertyChanged -= OnModelChanged;
        }
        // Detach() is never invoked — dead teardown code
    }

    private void OnModelChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}

public sealed class UncalledLambdaView : IDisposable
{
    private readonly INotifyPropertyChanged _model;   // injected, unknown lifetime

    public UncalledLambdaView(INotifyPropertyChanged model)
    {
        _model = model;
        _model.PropertyChanged += OnModelChanged;
    }

    public void Dispose()
    {
        Action detach = () => _model.PropertyChanged -= OnModelChanged;
        // detach is never invoked — the delegate is created and dropped
    }

    private void OnModelChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
