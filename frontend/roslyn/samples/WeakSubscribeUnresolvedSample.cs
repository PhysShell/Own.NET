// P-035 acceptance #8 (the SYNTAX-FALLBACK half): a declared weak-subscribe wrapper
// that lives in an EXTERNAL package the runner cannot resolve. `External.WeakEvents`
// is deliberately NOT defined anywhere in the compilation, so the method symbol does
// not bind and the extractor falls back to the syntactic receiver name.
//
// Scanned WITH `--weak-subscribe WeakEvents.AddPropertyChanged`. Expected facts:
//   * UnresolvedWrapperSubscriber  -> exactly one subscription, released:true
//                                     (fallback: receiver's final simple name == "WeakEvents")
//   * UnresolvedDifferentReceiver  -> NO subscription (final receiver name "NotWeak" != declared)
//
// The unresolved control matters: it proves the fallback matches the RECEIVER TYPE
// name exactly, not "some similar word appeared in the call".
using System.ComponentModel;

namespace Own.Samples.WeakSubscribeUnresolved
{
    public interface ISettings : INotifyPropertyChanged { }

    // POSITIVE (fallback): the wrapper type `External.WeakEvents` is unresolved; the
    // receiver's final simple name is "WeakEvents" == the declared type.
    public sealed class UnresolvedWrapperSubscriber
    {
        public UnresolvedWrapperSubscriber(ISettings settings)
        {
            External.WeakEvents.AddPropertyChanged(settings, OnChanged);
        }

        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // NEGATIVE (fallback is exact): also unresolved, same method name, but a DIFFERENT
    // final receiver type name -> must NOT match.
    public sealed class UnresolvedDifferentReceiver
    {
        public UnresolvedDifferentReceiver(ISettings settings)
        {
            External.NotWeak.AddPropertyChanged(settings, OnChanged);
        }

        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }
}
