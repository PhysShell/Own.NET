using System;

// P-004 self-owned exemption (EXTENDED) — both subscriptions below must stay
// SILENT. A class can OWN its event source without a direct `_f = new ...`; these
// are the two shapes the WPF mining run on ScreenToGif surfaced, each a
// GC-collectable source<->this cycle rather than a leak:
//   * `_thumb` is constructed INDIRECTLY — handed by `ref` to a helper that `new`s
//     it (the adorner `BuildCorner(ref _thumb, ...)` shape);
//   * `_upButton` is one of this control's OWN template parts, fetched with
//     `GetTemplateChild(...)` (the templated-control shape).
// Contrast CustomerViewModel, whose source is an injected bus (a warning). Timers
// remain the exception (a running timer is dispatcher-rooted) — see TimerViewModel.
//
// Stand-in types (Tier A: no WPF reference set) mirror the real surface: a Thumb
// with DragDelta, a RepeatButton with Click, and a control with the protected
// GetTemplateChild(string) lookup. Namespaced so they cannot collide with the
// other samples compiled alongside this file.
namespace OwnSamples.SelfOwnedParts
{
    public sealed class SelfOwnedControlParts : TemplatedControlStub
    {
        private Thumb _thumb = null!;     // built indirectly, through a `ref` helper
        private RepeatButton? _upButton;  // fetched as one of our own template parts

        public SelfOwnedControlParts()
        {
            BuildCorner(ref _thumb);
            _thumb.DragDelta += OnDrag;   // self-owned (ref-constructed) -> not a leak
        }

        public override void OnApplyTemplate()
        {
            _upButton = GetTemplateChild("PART_Up") as RepeatButton;
            _upButton!.Click += OnUp;     // self-owned (template part) -> not a leak
        }

        private static void BuildCorner(ref Thumb t) => t = new Thumb();

        private void OnDrag(object? sender, EventArgs e) { }
        private void OnUp(object? sender, EventArgs e) { }
    }

    public sealed class Thumb { public event EventHandler? DragDelta; }
    public sealed class RepeatButton { public event EventHandler? Click; }

    public abstract class TemplatedControlStub
    {
        protected object? GetTemplateChild(string name) => null;
        public virtual void OnApplyTemplate() { }
    }
}
