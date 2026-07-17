// S2 owen-rewrite sample: the acquire FORMS the rewriter must reproduce exactly,
// kept out of FixCandidatesSample.cs so the flag-off golden there stays pinned.
// Each class is one `--class` selection for the rewriter's regression set:
//   * ExplicitDelegate  -- `new PropertyChangedEventHandler(M)` must reach the weak
//     wrapper NORMALIZED (as `M`), the same peel the extractor's identity uses.
//   * ThisQualified     -- `this.M` is a stable symbol; the receiver is a nested
//     member access on the LHS.
//   * GenericHolder<T>  -- a GENERIC containing type: the candidate's
//     containing_type is `...GenericHolder<T>`, which the rewriter must rebuild
//     from syntax to match.
//   * Outer<T>.Inner<U> -- nested generics: both type parameter lists ride the FQN.
using System.ComponentModel;

namespace Own.Samples.FixRewrite
{
    public interface IPub : INotifyPropertyChanged { }

    // Explicit delegate construction on the +=; no teardown.
    public sealed class ExplicitDelegate
    {
        public ExplicitDelegate(IPub pub)
        {
            pub.PropertyChanged += new PropertyChangedEventHandler(OnChanged);
        }

        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // `this.`-qualified handler; no teardown.
    public sealed class ThisQualified
    {
        public ThisQualified(IPub pub)
        {
            pub.PropertyChanged += this.OnChanged;
        }

        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // A generic containing type -> containing_type is `Own.Samples.FixRewrite.GenericHolder<T>`.
    public sealed class GenericHolder<T>
    {
        public GenericHolder(IPub pub)
        {
            pub.PropertyChanged += OnChanged;
        }

        private void OnChanged(object sender, PropertyChangedEventArgs e) { }
    }

    // Nested generics -> `Own.Samples.FixRewrite.Outer<T>.Inner<U>`.
    public sealed class Outer<T>
    {
        public sealed class Inner<U>
        {
            public Inner(IPub pub)
            {
                pub.PropertyChanged += OnChanged;
            }

            private void OnChanged(object sender, PropertyChangedEventArgs e) { }
        }
    }
}
