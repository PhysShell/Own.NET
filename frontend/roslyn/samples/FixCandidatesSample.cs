// S0 fix-candidate metadata sample. Scanned WITH `--fix-candidates`; the
// `fix` block on each `+=` subscription fact is asserted by
// tests/check_fix_candidates_facts.py. Every case here is deliberate:
//   * INPC contract is SEMANTIC (implements INotifyPropertyChanged), not
//     name-matching -- FakePub's same-named event must classify name_only.
//   * teardown is symbol-based: none / exact (one proven -=) / ambiguous (>1).
//   * a nested class's subscription must NOT get a fix block in the OUTER
//     component (it is fixed by the nested type's own iteration).
using System;
using System.ComponentModel;

namespace Own.Samples.FixCandidates
{
    // A genuine INotifyPropertyChanged publisher.
    public interface IPub : INotifyPropertyChanged { }

    // INPC subscription with an EXACT teardown (ctor +=, Dispose -=).
    public sealed class InpcExactTeardown
    {
        private readonly IPub _pub;
        public InpcExactTeardown(IPub pub)
        {
            _pub = pub;
            _pub.PropertyChanged += OnChanged;
        }

        public void Dispose() => _pub.PropertyChanged -= OnChanged;
        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // INPC subscription, NO teardown -> status none.
    public sealed class InpcNoTeardown
    {
        public InpcNoTeardown(IPub pub) => pub.PropertyChanged += OnChanged;
        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // Two -= for the same acquire -> ambiguous (do not guess the lifecycle).
    public sealed class InpcAmbiguousTeardown
    {
        private readonly IPub _pub;
        public InpcAmbiguousTeardown(IPub pub)
        {
            _pub = pub;
            _pub.PropertyChanged += OnChanged;
        }

        public void Detach1() => _pub.PropertyChanged -= OnChanged;
        public void Detach2() => _pub.PropertyChanged -= OnChanged;
        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // An event NAMED PropertyChanged but NOT INotifyPropertyChanged -> name_only.
    public class FakePub
    {
        public event EventHandler PropertyChanged;
    }

    public sealed class NameOnlySubscriber
    {
        public NameOnlySubscriber(FakePub p) => p.PropertyChanged += OnChanged;
        private void OnChanged(object sender, EventArgs e) { }
    }

    // An unrelated event -> other.
    public class ClickPub
    {
        public event EventHandler Clicked;
    }

    public sealed class OtherEventSubscriber
    {
        public OtherEventSubscriber(ClickPub p) => p.Clicked += OnClick;
        private void OnClick(object sender, EventArgs e) { }
    }

    // Two subscriptions on ONE physical line -> a single `line` cannot tell them
    // apart, but their full spans (start/length) must differ.
    public sealed class TwoOnOneLine
    {
        public TwoOnOneLine(IPub a, IPub b) { a.PropertyChanged += OnA; b.PropertyChanged += OnB; }
        private void OnA(object s, PropertyChangedEventArgs e) { }
        private void OnB(object s, PropertyChangedEventArgs e) { }
    }

    // Wrapped delegate creation on the +=; bare method group on the -=. The
    // handler identity must NORMALIZE so the teardown is still exact.
    public sealed class WrappedDelegate
    {
        private readonly IPub _pub;
        public WrappedDelegate(IPub pub)
        {
            _pub = pub;
            _pub.PropertyChanged += new PropertyChangedEventHandler(OnChanged);
        }

        public void Dispose() => _pub.PropertyChanged -= OnChanged;
        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // A nested class's subscription must not appear as a fix candidate on the
    // OUTER component; the outer's own subscription still does.
    public sealed class OuterWithNested
    {
        public OuterWithNested(IPub pub) => pub.PropertyChanged += OnOuter;
        private void OnOuter(object s, PropertyChangedEventArgs e) { }

        public sealed class Nested
        {
            public Nested(IPub pub) => pub.PropertyChanged += OnNested;
            private void OnNested(object s, PropertyChangedEventArgs e) { }
        }
    }
}
