// BUGGY (the #278 parameter guard, rewritten as an early return — semantically
// identical to `if (!keepAlive) { -= }`, syntactically invisible to the shipped
// guard detector).
//
// Dispose() IS a teardown and it DOES call the helper — but it calls it with
// keepAlive: true ("light teardown", the SectorTS UnregOnlyGoodys idiom), and
// the helper's `-=` sits AFTER `if (keepAlive) return;`. The release provably
// never runs on any path, yet own-check credits it:
//   * the symbol-based teardown closure adds Cleanup (Dispose calls it —
//     argument VALUES are not consulted), so `InTeardownContext` says yes;
//   * `IsParamGuardedRelease` inspects only ENCLOSING conditions of the `-=`
//     site — an early `return` is a preceding SIBLING statement, not an
//     ancestor, so the caller-controlled guard is invisible.
// The enclosing-branch spelling of the exact same guard —
// `if (!keepAlive) { ... -= ...; }` — IS demoted
// (corpus/wpf/subscription-param-guarded-unregister). This case pins the
// asymmetry between the two spellings of one guard.
//
// own-check MUST flag this OWN001. The shipped #293 predicate credited it (an
// ancestors-only guard walk cannot see a sibling `return`) — the FN this pins.
using System;
using System.ComponentModel;

public sealed class SessionDocument : IDisposable
{
    private readonly INotifyPropertyChanged _properties;   // injected, unknown lifetime

    public SessionDocument(INotifyPropertyChanged properties)
    {
        _properties = properties;
        _properties.PropertyChanged += new PropertyChangedEventHandler(OnPropertiesChanged);
    }

    public void Dispose()
    {
        Cleanup(keepAlive: true);        // "light" teardown: the production path
    }

    public void Cleanup(bool keepAlive)
    {
        if (keepAlive)
            return;                      // every caller passes true
        _properties.PropertyChanged -= OnPropertiesChanged;   // never reached
    }

    private void OnPropertiesChanged(object sender, PropertyChangedEventArgs e) { /* ... */ }
}
