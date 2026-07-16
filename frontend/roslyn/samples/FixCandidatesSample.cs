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

    // --- Blocker-1 regressions: a computed receiver/handler must NOT be exact ---

    // Receiver is an INVOCATION: two GetPublisher() calls can return different
    // instances even though the method symbol is identical -> ambiguous, not exact.
    public sealed class ComputedReceiverInvocation
    {
        private IPub GetPublisher() => null!;

        public ComputedReceiverInvocation() => GetPublisher().PropertyChanged += OnChanged;
        public void Dispose() => GetPublisher().PropertyChanged -= OnChanged;
        private void OnChanged(object s, PropertyChangedEventArgs e) { }
    }

    // Receiver is a PROPERTY: the getter may return different instances -> ambiguous.
    public sealed class ComputedReceiverProperty
    {
        private IPub Pub => null!;

        public ComputedReceiverProperty() => Pub.PropertyChanged += OnChanged;
        public void Dispose() => Pub.PropertyChanged -= OnChanged;
        private void OnChanged(object s, PropertyChangedEventArgs e) { }
    }

    public sealed class Holder
    {
        public IPub Publisher = null!;
    }

    // Different ROOT objects, same final field member: `_a.Publisher` != `_b.Publisher`
    // as instances -> the -= is not even a candidate -> none (certainly not exact).
    public sealed class DifferentRoots
    {
        private readonly Holder _a;
        private readonly Holder _b;

        public DifferentRoots(Holder a, Holder b)
        {
            _a = a;
            _b = b;
            _a.Publisher.PropertyChanged += OnChanged;
        }

        public void Dispose() => _b.Publisher.PropertyChanged -= OnChanged;
        private void OnChanged(object s, PropertyChangedEventArgs e) { }
    }

    // Handler is a PROPERTY returning a delegate: not stable even though both += and -=
    // resolve to the same IPropertySymbol -> ambiguous.
    public sealed class ComputedHandler
    {
        private readonly IPub _pub;
        private PropertyChangedEventHandler H => (_, __) => { };

        public ComputedHandler(IPub pub)
        {
            _pub = pub;
            _pub.PropertyChanged += H;
        }

        public void Dispose() => _pub.PropertyChanged -= H;
    }

    // --- Blocker-2 regressions: occurrence ordinal is scoped by enclosing member ---

    // The SAME identity tuple in two different members -> each ordinal 0.
    public sealed class OrdinalAcrossMembers
    {
        private readonly IPub _pub;

        public OrdinalAcrossMembers(IPub pub)
        {
            _pub = pub;
            _pub.PropertyChanged += OnChanged;
        }

        public void Reattach() => _pub.PropertyChanged += OnChanged;
        private void OnChanged(object s, PropertyChangedEventArgs e) { }
    }

    // Two identical acquires in ONE member -> ordinals 0 and 1.
    public sealed class OrdinalWithinMember
    {
        public OrdinalWithinMember(IPub pub)
        {
            pub.PropertyChanged += OnChanged;
            pub.PropertyChanged += OnChanged;
        }

        private void OnChanged(object s, PropertyChangedEventArgs e) { }
    }

    // Value vs ref overload -> DISTINCT enclosing_member signatures (IncludeParamsRefOut).
    public sealed class RefOverloadEnclosing
    {
        private readonly IPub _pub;

        public RefOverloadEnclosing(IPub pub) => _pub = pub;
        public void Attach(int x) => _pub.PropertyChanged += OnChanged;
        public void Attach(ref int x) => _pub.PropertyChanged += OnChanged;
        private void OnChanged(object s, PropertyChangedEventArgs e) { }
    }

    // --- Blocker-1 (handler half): a method symbol is not a delegate identity ---

    public sealed class Sibling
    {
        public void OnChanged(object s, PropertyChangedEventArgs e) { }
    }

    // Method group on a DIFFERENT receiver instance: `_left.OnChanged` and
    // `_right.OnChanged` are the SAME IMethodSymbol but different delegates -> not exact.
    public sealed class HandlerDifferentTarget
    {
        private readonly IPub _pub;
        private readonly Sibling _left;
        private readonly Sibling _right;

        public HandlerDifferentTarget(IPub pub, Sibling left, Sibling right)
        {
            _pub = pub;
            _left = left;
            _right = right;
            _pub.PropertyChanged += _left.OnChanged;
        }

        public void Dispose() => _pub.PropertyChanged -= _right.OnChanged;
    }

    // Delegate held in a FIELD reassigned between += and -=: same IFieldSymbol, different
    // delegate values -> not exact.
    public sealed class HandlerReassignedField
    {
        private readonly IPub _pub;
        private PropertyChangedEventHandler _handler;

        public HandlerReassignedField(IPub pub)
        {
            _pub = pub;
            _handler = OnFirst;
            _pub.PropertyChanged += _handler;
            _handler = OnSecond;
            _pub.PropertyChanged -= _handler;
        }

        private void OnFirst(object s, PropertyChangedEventArgs e) { }
        private void OnSecond(object s, PropertyChangedEventArgs e) { }
    }
}
