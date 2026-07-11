// P-004 (issue #224): a subscribed handler that unsubscribes ITSELF, inside its own
// body, the first time it fires — a common one-shot idiom ("do this once, then stop
// listening") that needs no external `-=`. Mined from AvalonEdit's
// Search/DropDownButton.cs (docs/notes/field-notes-patterns.md entry 18).
using System;

namespace Own.Samples.SelfDetachingHandler
{
    public sealed class PopupLike
    {
        public event EventHandler? Closed;
        public event EventHandler? Opened;
        public void FireClosed() => Closed?.Invoke(this, EventArgs.Empty);
    }

    // Positive: the handler removes itself from the SAME event, off the `sender`
    // parameter cast back to the source type, the first time it runs — bounded by
    // construction. Must be SILENT (no OWN001 warning).
    public sealed class DropDownButtonLike
    {
        private readonly PopupLike content;

        public DropDownButtonLike(PopupLike content)
        {
            this.content = content;
            content.Closed += DropDownContent_Closed;
        }

        private void DropDownContent_Closed(object? sender, EventArgs e)
        {
            ((PopupLike)sender!).Closed -= DropDownContent_Closed;
        }
    }

    // Negative control 1: the SAME shape, but the handler does NOT self-detach (it
    // just runs and returns) — must STILL warn (OWN001). Proves the new recognition
    // requires an ACTUAL matching self-`-=` in the handler body, not just "this is a
    // named handler on an injected source."
    public sealed class NonDetachingSubscriber
    {
        private readonly PopupLike content;

        public NonDetachingSubscriber(PopupLike content)
        {
            this.content = content;
            content.Closed += OnClosed;
        }

        private void OnClosed(object? sender, EventArgs e) { /* never detaches */ }
    }

    // Negative control 2: the handler DOES contain a `-=`, but against a DIFFERENT
    // event name (`Opened`, not the subscribed `Closed`) — a wrong-event detach must
    // NOT be credited as releasing the `Closed` subscription. Must STILL warn
    // (OWN001), proving the match requires the inner `-=`'s member name to equal the
    // SUBSCRIBED event's name.
    public sealed class WrongEventDetachSubscriber
    {
        private readonly PopupLike content;

        public WrongEventDetachSubscriber(PopupLike content)
        {
            this.content = content;
            content.Closed += OnClosed;
        }

        private void OnClosed(object? sender, EventArgs e)
        {
            ((PopupLike)sender!).Opened -= OnClosed;
        }
    }
}
