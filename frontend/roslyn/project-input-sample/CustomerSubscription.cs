using System;

// SUBSCRIPTION LEAK, discovered via PROJECT-FILE input (not an explicit file list).
// The extractor is pointed at ProjectInputSample.csproj; ProjectCsFiles resolves the
// project to this source file (SDK default-compile-items directory scan), so the same
// `bus.CustomerChanged += handler` with no matching `-=` surfaces as OWN001 — proving
// the .csproj seam feeds the core exactly as the per-file path does.
public sealed class CustomerSubscription
{
    public CustomerSubscription(IEventBus bus)
    {
        bus.CustomerChanged += OnCustomerChanged;   // no matching -= anywhere -> leak
    }

    private void OnCustomerChanged(object? sender, EventArgs e) { }
}

// Local event-bus contract so the subscription binds type-aware (P-014 Tier A) without
// an external reference — keeps this sample self-contained (no OWN050 "unchecked" note).
public interface IEventBus
{
    event EventHandler CustomerChanged;
}
