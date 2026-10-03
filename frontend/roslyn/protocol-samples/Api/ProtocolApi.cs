using System;
using System.Threading.Tasks;

namespace Own.Protocols.Sample;

// The sample state protocol behind `protocol-samples/cases` (C# -> OwnIR v2 lowering,
// see frontend/roslyn/README.md). Deliberately minimal: one entity, three state tokens,
// two region entries, no persistence. It is a fixture, not an API proposal — the
// realistic shape, on an entity EF Core tracks, is `protocol-samples/efcore`. What it
// has to be is honestly lowerable:
//
//   * a region entry is a method marked [ProtocolRegion]: (entity, callback);
//   * a state token is a `ref struct` marked [ProtocolToken]; every instance METHOD
//     on it is a transition and consumes the token, a PROPERTY is a read;
//   * a token can only be obtained from a region entry or from a transition, so the
//     shapes the core cannot check (a token minted outside a region, two tokens for
//     one entity, a token spent against another entity) have no spelling here.
//
// The two attributes are matched by NAME, so this file has no dependency on Own.NET.

[AttributeUsage(AttributeTargets.Struct)]
public sealed class ProtocolTokenAttribute : Attribute { }

[AttributeUsage(AttributeTargets.Method)]
public sealed class ProtocolRegionAttribute : Attribute { }

public enum OrderStatus { Draft, Submitted, Approved, Shipped, Cancelled }

public sealed class Order
{
    public int Id { get; internal set; }
    public OrderStatus Status { get; internal set; }
    public string Note { get; private set; } = "";

    public static Order Load(int id) => new() { Id = id };

    // Ordinary public behaviour that is NOT protocol state: free outside a region, and a raw
    // access the region must exclude inside one. (A public member that wrote `Status` would
    // be a transition nobody declared; the protocol would not be admitted with it.)
    public void Annotate(string note) => Note = note;
}

[ProtocolToken]
public readonly ref struct DraftOrder
{
    private readonly Order _order;
    internal DraftOrder(Order order) => _order = order;

    public int Id => _order.Id;

    public SubmittedOrder Submit()
    {
        _order.Status = OrderStatus.Submitted;
        return new SubmittedOrder(_order);
    }

    public void Cancel() => _order.Status = OrderStatus.Cancelled;
}

[ProtocolToken]
public readonly ref struct SubmittedOrder
{
    private readonly Order _order;
    internal SubmittedOrder(Order order) => _order = order;

    public int Id => _order.Id;

    // Returns nothing: the token is spent and no further capability is handed out.
    public void Approve() => _order.Status = OrderStatus.Approved;
}

[ProtocolToken]
public readonly ref struct ApprovedOrder
{
    private readonly Order _order;
    internal ApprovedOrder(Order order) => _order = order;

    public int Id => _order.Id;

    public void Ship() => _order.Status = OrderStatus.Shipped;
}

public delegate void DraftRegion(DraftOrder draft);

public delegate void ApprovedRegion(ApprovedOrder approved);

public static class Protocol
{
    [ProtocolRegion]
    public static void WithDraft(Order order, DraftRegion body)
    {
        if (order.Status != OrderStatus.Draft)
            throw new InvalidOperationException("the order is not a draft");
        body(new DraftOrder(order));
    }

    [ProtocolRegion]
    public static void WithApproved(Order order, ApprovedRegion body)
    {
        if (order.Status != OrderStatus.Approved)
            throw new InvalidOperationException("the order is not approved");
        body(new ApprovedOrder(order));
    }
}

// Stand-ins so the cases look like a handler without pulling EF Core into the gate.
public sealed class Db
{
    public Task<Order> SingleAsync(int id) => Task.FromResult(Order.Load(id));

    public Task<int> SaveChangesAsync() => Task.FromResult(1);
}

public static class Audit
{
    public static void Record(Order order) { }
}

// Code that reaches an entity WITHOUT naming it at the call site: the shape an exclusive
// region cannot be allowed to wave through.
public static class Backdoor
{
    private static Order? _last;

    public static void Remember(Order order) => _last = order;

    public static void AnnotateLast() => _last?.Annotate("behind the call");
}
