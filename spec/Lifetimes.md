# Lifetime Regions

> **Status: normative, descriptive.** Source of truth: `ownlang/lifetimes.py`.
> This layer adds region reasoning on top of OwnCore — the "object escapes to a
> longer-lived region" theorem (the WPF zombie-ViewModel leak).

## Model

`lifetime` declarations define regions with a strict partial order:

```ownlang
lifetime App;
lifetime Window < App;        // Window is strictly shorter-lived than App
lifetime ViewModel < Window;  // order is transitive
```

A function carries the lifetime of the object it sets up; its parameters carry
the lifetime of the service they are:

```ownlang
fn CustomerViewModel(bus: EventBus lifetime App) lifetime ViewModel {
    subscribe self to bus;    // strong capture: bus now holds self
}
```

## Rules (normative)

- **L1 — order is a strict partial order.** `<` is transitive. A region that
  ends up strictly longer than itself is a cycle → **OWN036**. A reference to an
  undeclared region → **OWN030**; a redeclared region → **OWN031**.
- **L2 — annotations resolve.** A function/parameter lifetime that names an
  undeclared region → **OWN030**.
- **L3 — region escape.** `subscribe self to SOURCE` where `lifetime(SOURCE)` is
  **strictly longer** than `lifetime(self)` promotes `self` to the longer region:
  it stays reachable for the whole longer region and leaks → **OWN014**. A
  capture by a source of equal-or-shorter lifetime is clean (no promotion). The
  *ordering* is what makes it a leak.

## L4 — resource kind metadata

A `resource` may declare `kind "subscription token"`. The kind is domain-neutral
metadata threaded onto the owning symbol and surfaced on diagnostics as a
`[resource: <kind>]` suffix. The core stays generic; a later WPF profile / C#
front-end keys off the kind to phrase findings in business terms — without the
core knowing about any domain.

## Mitigation

The safe counterpart to a leaking `subscribe` is the OwnCore token pattern:
`let t = acquire Subscription(bus); ... release t;`. A released token gives a
release path, so OWN001 stays quiet — i.e. both halves of the theorem reuse the
same machinery.

## Out of scope (see proposals)

No cross-procedural points-to: `self`/`source` are the function's own scope and
its annotated parameters, not an arbitrary object graph. Weak-reference policy as
an explicit escape hatch, and C# ingestion that would produce these facts from
real code, are tracked in [`docs/proposals/`](../docs/proposals/).
