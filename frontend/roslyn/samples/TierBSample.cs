// P-014 Tier B — proof that external-reference resolution flips an event from "unchecked"
// to a real, resolved subscription. `TierBSubscriber` holds a long-lived reference to a
// CommunityToolkit.Mvvm `ObservableObject` (a THIRD-PARTY type, not in the framework set)
// and subscribes to its `PropertyChanged` without ever `-=`'ing it.
//
//   WITHOUT --ref-dir : CommunityToolkit.Mvvm.dll is not referenced, so `ObservableObject`
//                       is an error type and `_vm.PropertyChanged += ...` cannot bind to an
//                       event symbol -> the extractor emits the advisory OWN050 ("leakage
//                       analysis skipped"), NEVER a guessed leak.
//   WITH --ref-dir    : the package DLL is referenced, the SemanticModel binds PropertyChanged
//                       to an IEventSymbol, and the un-detached subscription is a real OWN001
//                       leak (warning-tier — the source is injected, of unknown lifetime).
//
// Same source, two reference sets, two verdicts: the A/B delta is the Tier B proof. Roslyn reads
// metadata only, so this resolves a .NET Framework `bin/` exactly as a modern-.NET one — only the
// referenced DLLs differ. Exercised by the `tier-b-refs` CI job (ci.yml).
using System.ComponentModel;
using CommunityToolkit.Mvvm.ComponentModel;

namespace TierBSample
{
    public sealed class TierBSubscriber
    {
        private readonly ObservableObject _vm;

        public TierBSubscriber(ObservableObject vm)
        {
            _vm = vm;
            _vm.PropertyChanged += OnChanged;   // subscribed, never -='d
        }

        private void OnChanged(object? sender, PropertyChangedEventArgs e) { }
    }
}
