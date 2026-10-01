using System;

namespace OrderBackend.Domain;

// The state protocol of Order, written by hand (a source generator could emit this file;
// none exists yet, and the profile does not need one).
//
// No reflection, no base class, no runtime library: two marker attributes, three ref
// structs, three delegates, three region entries.

[AttributeUsage(AttributeTargets.Struct)]
public sealed class ProtocolTokenAttribute : Attribute
{
}

[AttributeUsage(AttributeTargets.Method)]
public sealed class ProtocolRegionAttribute : Attribute
{
}

/// The runtime half of the refinement: the fact came from the database, so it is checked
/// once, at the region entry.
public sealed class InvalidOrderStateException(int id, OrderStatus actual, OrderStatus required)
    : InvalidOperationException($"order {id} is {actual}, not {required}")
{
}

[ProtocolToken]
public readonly ref struct DraftOrder
{
    private readonly Order _order;

    internal DraftOrder(Order order) => _order = order;

    public int Id => _order.Id;

    public SubmittedOrder Submit(DateTime at)
    {
        _order.MarkSubmitted(at);
        return new SubmittedOrder(_order);
    }
}

[ProtocolToken]
public readonly ref struct SubmittedOrder
{
    private readonly Order _order;

    internal SubmittedOrder(Order order) => _order = order;

    public int Id => _order.Id;

    public void Approve(DateTime at) => _order.MarkApproved(at);
}

[ProtocolToken]
public readonly ref struct ApprovedOrder
{
    private readonly Order _order;

    internal ApprovedOrder(Order order) => _order = order;

    public int Id => _order.Id;

    public void Ship(DateTime at) => _order.MarkShipped(at);
}

public delegate void DraftRegion(DraftOrder draft);

public delegate void SubmittedRegion(SubmittedOrder submitted);

public delegate void ApprovedRegion(ApprovedOrder approved);

public static class OrderProtocol
{
    [ProtocolRegion]
    public static void WithDraft(Order order, DraftRegion body)
    {
        Require(order, OrderStatus.Draft);
        body(new DraftOrder(order));
    }

    [ProtocolRegion]
    public static void WithSubmitted(Order order, SubmittedRegion body)
    {
        Require(order, OrderStatus.Submitted);
        body(new SubmittedOrder(order));
    }

    [ProtocolRegion]
    public static void WithApproved(Order order, ApprovedRegion body)
    {
        Require(order, OrderStatus.Approved);
        body(new ApprovedOrder(order));
    }

    private static void Require(Order order, OrderStatus required)
    {
        if (order.Status != required)
            throw new InvalidOrderStateException(order.Id, order.Status, required);
    }
}
