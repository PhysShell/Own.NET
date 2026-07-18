// BUGGY (#278 follow-up, blocker 1; hand-reduced into case.own).
//
// The ctor subscribes to an injected publisher; the only matching `-=` sits in
// the FINALIZER. That release can never run while it matters: the publisher's
// delegate holds a strong reference to this object, so as long as the
// subscription is live the subscriber is REACHABLE and the GC never finalizes
// it. The `-=` exists precisely on the one path that the leak itself blocks.
// (For a static/process-lived publisher the finalizer is simply never reached
// for the life of the process — same argument, absolute.)
//
// own-check MUST flag this OWN001. Crediting the finalizer was a silent
// false-negative path in the first #278 slice.
using System.ComponentModel;

public sealed class FinalizerDetachDocument
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime

    public FinalizerDetachDocument(INotifyPropertyChanged properties)
    {
        _properties = properties;
        _properties.PropertyChanged += OnPropertiesChanged;
    }

    ~FinalizerDetachDocument()
    {
        // unreachable while subscribed: the delegate keeps `this` alive
        _properties.PropertyChanged -= OnPropertiesChanged;
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
