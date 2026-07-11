using System;

// P-004 (issue #222): the self-owned-template-part exemption (SelfOwnedControlParts.cs)
// only credited a FIELD assignment (`_field = GetTemplateChild(...) as T`). A template
// part is EQUALLY self-owned when captured as a plain LOCAL variable or an `is T x`
// PATTERN variable — same fetch, same template-owned lifetime, just not stored in a
// field. Mined: MahApps.Metro Controls/MetroWindow.cs (pattern-variable form, via
// GetTemplateChild), AvalonEdit CodeCompletion/OverloadViewer.cs (plain local-variable
// form, via Template.FindName). Stand-in types mirror SelfOwnedControlParts.cs's
// technique (Tier A, no WPF reference set needed), namespaced separately so they
// cannot collide with the other samples compiled alongside this file.
namespace OwnSamples.TemplatePartLocals
{
    // Positive (pattern variable): `GetTemplateChild(...) is T x`, captured as an `is`
    // pattern-match local, then subscribed. Must be SILENT (no OWN001 warning).
    public sealed class MetroWindowLike : TemplatedControlStub
    {
        public override void OnApplyTemplate()
        {
            if (GetTemplateChild("PART_Content") is ContentControlStub metroContentControl)
            {
                metroContentControl.TransitionCompleted += OnTransitionCompleted;
            }
        }

        private void OnTransitionCompleted(object? sender, EventArgs e) { }
    }

    // Positive (plain local via FindName): the template part is stored in an ordinary
    // local variable (not a field, not a pattern variable), then subscribed. Must be
    // SILENT (no OWN001 warning).
    public sealed class OverloadViewerLike : TemplatedControlStub
    {
        public override void OnApplyTemplate()
        {
            ButtonStub upButton = (ButtonStub)Template.FindName("PART_UP", this);
            upButton.Click += OnUpClick;
        }

        private void OnUpClick(object? sender, EventArgs e) { }
    }

    // Negative control: a local variable holding an INJECTED object (aliasing a
    // constructor-supplied field) — NOT a GetTemplateChild/FindName fetch — subscribed
    // the same way. Must STILL warn (OWN001), proving the exemption is scoped to an
    // actual template-part fetch, not "any local-variable subscription is self-owned."
    public sealed class InjectedLocalSubscriber
    {
        private readonly ButtonStub externalButton;

        public InjectedLocalSubscriber(ButtonStub externalButton)
        {
            this.externalButton = externalButton;
        }

        public void Wire()
        {
            ButtonStub local = externalButton;   // aliases an INJECTED field, not a template fetch
            local.Click += OnClick;
        }

        private void OnClick(object? sender, EventArgs e) { }
    }

    public sealed class ButtonStub { public event EventHandler? Click; }
    public sealed class ContentControlStub { public event EventHandler? TransitionCompleted; }

    public abstract class TemplatedControlStub
    {
        protected object? GetTemplateChild(string name) => null;
        protected TemplateStub Template { get; } = new TemplateStub();
        public virtual void OnApplyTemplate() { }
    }

    public sealed class TemplateStub
    {
        public object? FindName(string name, object scope) => null;
    }
}
