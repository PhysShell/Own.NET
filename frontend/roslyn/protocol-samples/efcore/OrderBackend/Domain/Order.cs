using System;

namespace OrderBackend.Domain;

public enum OrderStatus
{
    Draft,
    Submitted,
    Approved,
    Shipped,
}

/// An ordinary EF Core entity: no base class, no interface, no attribute. EF materializes it
/// through the private constructor and tracks THIS instance; the state tokens in
/// OrderProtocol.cs wrap the same reference and mutate it in place.
public sealed class Order
{
    private Order()
    {
    }

    public int Id { get; private set; }

    public string Customer { get; private set; } = "";

    public OrderStatus Status { get; private set; }

    public DateTime? SubmittedAt { get; private set; }

    public DateTime? ApprovedAt { get; private set; }

    public DateTime? ShippedAt { get; private set; }

    public static Order NewDraft(string customer) =>
        new() { Customer = customer, Status = OrderStatus.Draft };

    // The transitions themselves. Reachable only through a state token (same assembly).
    internal void MarkSubmitted(DateTime at)
    {
        Status = OrderStatus.Submitted;
        SubmittedAt = at;
    }

    internal void MarkApproved(DateTime at)
    {
        Status = OrderStatus.Approved;
        ApprovedAt = at;
    }

    internal void MarkShipped(DateTime at)
    {
        Status = OrderStatus.Shipped;
        ShippedAt = at;
    }
}
