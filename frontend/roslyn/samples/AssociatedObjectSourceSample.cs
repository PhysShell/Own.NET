// issue #227 — a `Behavior`-derived subscriber whose event SOURCE is (an element
// reached from) its own base-class `AssociatedObject`. A behavior is attached to and
// detached from exactly one element and cannot outlive being attached, so that element
// is co-lifetimed with the behavior — the same collectable source<->this cycle the
// shipped self-owned-source exemption already encodes for a constructed field, just
// reached through the base-class accessor. Real-world shape: MahApps.Metro
// TiltBehavior.cs:62-70 (found by the issue #201 oracle sweep).
//
// The exemption is deliberately NARROW: the subscriber must derive from `Behavior`
// (attach/detach guarantees co-lifetime ONLY in that pairing), and the source must
// resolve — same-class, assignment-chain-local — to `this.AssociatedObject`. The
// negative controls below pin each edge.
using System;

namespace OwnSamples.AssociatedObject
{
    public class UiElement
    {
        public event EventHandler? Loaded;
        public void Raise() => Loaded?.Invoke(this, EventArgs.Empty);
    }

    public class Panel : UiElement { }

    // Stand-in for Microsoft.Xaml.Behaviors.Behavior<T> / System.Windows.Interactivity:
    // IsBehaviorSubscriber matches the base simple name `Behavior` syntactically (the
    // Interactivity assembly does not resolve on the Linux runner). `AssociatedObject`
    // is the base-class accessor for the attached element.
    public class Behavior<T> where T : class
    {
        protected T? AssociatedObject { get; set; }
    }

    // An injected event bus for the negative controls — unknown, longer-lived source.
    public class EventBus
    {
        public event EventHandler? Changed;
    }

    // POSITIVE (silent) + the REQUIRED negative control in one `OnAttached`: the
    // TiltBehavior shape — a field assigned from `AssociatedObject`, then an
    // `is`-pattern local subscribed with a lambda handler — is SILENT; a subscription
    // to an UNRELATED injected source in the SAME method stays flagged.
    public class TiltLikeBehavior : Behavior<UiElement>
    {
        UiElement? _attached;
        readonly EventBus _bus;

        public TiltLikeBehavior(EventBus bus) => _bus = bus;

        protected void OnAttached()
        {
            _attached = this.AssociatedObject;
            if (_attached is Panel panel)
                panel.Loaded += (s, e) => Handle();          // silent (#227): panel IS AssociatedObject

            _bus.Changed += (s, e) => Handle();              // OWN001: unrelated injected source
        }

        void Handle() { }
    }

    // POSITIVE (silent): the DIRECT receiver form — `this.AssociatedObject.Event`, no
    // intermediate local, method-group handler.
    public class DirectAssociatedBehavior : Behavior<UiElement>
    {
        protected void OnAttached()
        {
            this.AssociatedObject!.Loaded += OnLoaded;       // silent (#227)
        }

        void OnLoaded(object? sender, EventArgs e) { }
    }

    // POSITIVE (silent): a bare-identifier local bound from `AssociatedObject`.
    public class LocalAssociatedBehavior : Behavior<UiElement>
    {
        protected void OnAttached()
        {
            var el = AssociatedObject;
            if (el is { } e0)
                e0.Loaded += OnLoaded;                       // silent (#227)
        }

        void OnLoaded(object? sender, EventArgs e) { }
    }

    // CONTROL 1 (flagged): the SAME `AssociatedObject`-shaped subscription from a class
    // that does NOT derive from `Behavior` — the co-lifetime guarantee comes from the
    // attach/detach pairing, so the exemption gate stays the `Behavior` base. Here the
    // member is an ordinary injected property, not the base accessor.
    public class NotABehavior
    {
        UiElement AssociatedObject { get; }

        public NotABehavior(UiElement injected) => AssociatedObject = injected;

        public void Wire()
        {
            this.AssociatedObject.Loaded += OnLoaded;        // OWN001: subscriber is not a Behavior
        }

        void OnLoaded(object? sender, EventArgs e) { }
    }

    // CONTROL 2 (flagged): the field is assigned from `AssociatedObject` in OnAttached
    // but ALSO from an injected value in another member — its contents at the `+=` are
    // ambiguous, so every assignment must resolve to `AssociatedObject` or the proof is
    // denied.
    public class MixedFieldBehavior : Behavior<UiElement>
    {
        UiElement? _el;

        protected void OnAttached()
        {
            _el = this.AssociatedObject;
            if (_el is Panel panel)
                panel.Loaded += OnLoaded;                    // OWN001: _el is also injected below
        }

        public void Configure(UiElement injected) => _el = injected;

        void OnLoaded(object? sender, EventArgs e) { }
    }

    // CONTROL 3 (flagged): the local STARTS as `AssociatedObject` but is REASSIGNED to
    // an injected source before the `+=` — the declaration-site binding is stale.
    public class ReassignedLocalBehavior : Behavior<UiElement>
    {
        readonly UiElement _injected;

        public ReassignedLocalBehavior(UiElement injected) => _injected = injected;

        protected void OnAttached()
        {
            var src = this.AssociatedObject;
            src = _injected;                                 // rebind -> declaration binding stale
            if (src is { } s0)
                s0.Loaded += OnLoaded;                       // OWN001: reassigned local
        }

        void OnLoaded(object? sender, EventArgs e) { }
    }

    // CONTROL 4 (flagged, Codex P2): a PARAMETER named `AssociatedObject` SHADOWS the
    // inherited base accessor — the identifier text matches, but the symbol is an
    // injected parameter, not the co-lifetimed attached element, so the exemption must
    // check the binding, not just the name.
    public class ShadowParamBehavior : Behavior<UiElement>
    {
        public void Wire(UiElement AssociatedObject)
        {
            AssociatedObject.Loaded += OnLoaded;             // OWN001: shadowing parameter
        }

        void OnLoaded(object? sender, EventArgs e) { }
    }

    // CONTROL 5 (flagged): a PARTIAL behavior whose field is assigned from
    // `AssociatedObject` in one declaration but ALSO from an injected value in the
    // sibling partial — the field-population scan must span every partial of the type,
    // so the ambiguous field keeps the warning.
    public partial class PartialFieldBehavior : Behavior<UiElement>
    {
        UiElement? _el;

        protected void OnAttached()
        {
            _el = this.AssociatedObject;
            if (_el is Panel panel)
                panel.Loaded += OnLoaded;                    // OWN001: _el also injected in the sibling partial
        }

        void OnLoaded(object? sender, EventArgs e) { }
    }

    public partial class PartialFieldBehavior
    {
        public void Inject(UiElement injected) => _el = injected;   // sibling-partial injected write
    }
}
