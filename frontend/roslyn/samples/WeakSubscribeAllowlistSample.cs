// P-035 (issue #NNN): a project-declared weak-subscribe wrapper is a first-class,
// ALREADY-RELEASED subscription. The extractor is told the wrapper's exact
// (containing-type simple name, method name) via the internal `--weak-subscribe`
// transport flag (own-check --config own.toml forwards [weak-subscription].subscribe).
//
// This sample is scanned WITH `--weak-subscribe WeakEvents.AddPropertyChanged`.
// Self-contained (stand-in INotifyPropertyChanged) so no WPF/BCL reference assembly
// is needed on the Linux runner, the same technique RequerySuggestedAllowlistSample.cs
// uses. Expected facts:
//   * WeaklySubscribed        -> exactly one subscription, released:true  (acceptance #2)
//   * SameNameDifferentType   -> NO subscription (different type)          (acceptance #9)
//   * OrdinaryPlusEquals      -> one subscription, released:false (leak)   (acceptance #4)
//   * TooFewArgs              -> NO subscription (fewer than 2 args)       (acceptance #7)
// With NO --weak-subscribe flag, WeaklySubscribed also yields NO subscription
// (byte-for-byte unchanged — acceptance #1).
using System;
using System.ComponentModel;

namespace Own.Samples.WeakSubscribe
{
    public interface ISettings : INotifyPropertyChanged { }

    // A project's own thread-agnostic weak-subscribe wrapper (stand-in — the real one
    // holds the listener via a WeakReference). The declared API is
    // "WeakEvents.AddPropertyChanged".
    public static class WeakEvents
    {
        public static void AddPropertyChanged(INotifyPropertyChanged source, PropertyChangedEventHandler handler) { }
        // A one-argument overload so the too-few-args call below binds cleanly.
        public static void AddPropertyChanged(INotifyPropertyChanged source) { }
        public static void RemovePropertyChanged(INotifyPropertyChanged source, PropertyChangedEventHandler handler) { }
    }

    // A DIFFERENT type carrying a SAME-NAMED method. Must NOT be recognised — matching
    // is exact on (simple type name, method name), so `NotWeak.AddPropertyChanged` is
    // not the declared `WeakEvents.AddPropertyChanged`.
    public static class NotWeak
    {
        public static void AddPropertyChanged(INotifyPropertyChanged source, PropertyChangedEventHandler handler) { }
    }

    // POSITIVE: the declared wrapper -> exactly one released subscription, silent.
    public sealed class WeaklySubscribed
    {
        public WeaklySubscribed(ISettings settings)
        {
            WeakEvents.AddPropertyChanged(settings, OnChanged);
        }

        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // NEGATIVE CONTROL (acceptance #9): same method name, DIFFERENT type -> not
    // recognised. A plain method call (not a `+=`) produces no subscription fact.
    public sealed class SameNameDifferentType
    {
        public SameNameDifferentType(ISettings settings)
        {
            NotWeak.AddPropertyChanged(settings, OnChanged);
        }

        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // NEGATIVE CONTROL (acceptance #4): an ordinary `+=` to an injected source, never
    // detached -> MUST still be flagged. The weak-subscribe feature never weakens
    // ordinary event-subscription detection.
    public sealed class OrdinaryPlusEquals
    {
        public OrdinaryPlusEquals(ISettings settings)
        {
            settings.PropertyChanged += OnChanged;
        }

        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // NEGATIVE CONTROL (acceptance #7): the declared wrapper, but with fewer than two
    // arguments -> not recognised (the MVP contract needs positional (source, handler)).
    public sealed class TooFewArgs
    {
        public TooFewArgs(ISettings settings)
        {
            WeakEvents.AddPropertyChanged(settings);
        }
    }
}
