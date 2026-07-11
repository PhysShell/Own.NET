// P-004 (issue #220): `using (field = new T()) { ... }` disposes the FIELD at the end
// of the using block, exactly like `using (var local = new T())` disposes the local —
// the flow-locals engine already threads a release for `using (existingLocal)`; this
// closes the sibling gap where the acquisition expression assigns a FIELD. Mined from
// ShareX's HashChecker.cs / TaskEx.cs / IndexerJson.cs
// (docs/notes/field-notes-patterns.md entry 14).
using System.Threading;

namespace Own.Samples.UsingFieldAcquisition
{
    // Positive: the field IS the `using` acquisition target — disposed at the end of
    // the using block. Must be SILENT (no OWN001 disposable-field leak).
    public sealed class HashCheckerLike
    {
        private CancellationTokenSource? cts;

        public void Check()
        {
            using (cts = new CancellationTokenSource())
            {
                cts.Token.ThrowIfCancellationRequested();
            }
        }

        public void Cancel() => cts?.Cancel();
    }

    // Negative control: the SAME field, constructed the SAME way (a `new
    // CancellationTokenSource()` assignment), but OUTSIDE any `using` — never
    // disposed anywhere. Must STILL warn (OWN001 disposable-field leak), proving the
    // new recognition is scoped to the `using (field = ...)` acquisition shape, not
    // "any field assignment from `new` is a release."
    public sealed class LeakyAssignerLike
    {
        private CancellationTokenSource? cts;

        public void Start()
        {
            cts = new CancellationTokenSource();
        }

        public void Cancel() => cts?.Cancel();
    }
}
