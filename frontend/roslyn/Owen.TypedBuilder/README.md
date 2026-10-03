# Owen.TypedBuilder

Typed states and a typed builder for an ordinary entity, generated from one annotated
declaration and checked by Owen on every build.

```
dotnet add package Owen.TypedBuilder
```

```csharp
public enum OrderStatus { Draft, Submitted, Approved, Shipped }

[TypedProtocol]
public sealed partial class Order
{
    private Order() { }
    public int Id { get; private set; }
    [BuilderRequired] public string Customer { get; private set; } = "";
    [ProtocolState]   public OrderStatus Status { get; private set; }

    [Transition("Submit", OrderStatus.Draft, OrderStatus.Submitted)]
    private void OnSubmit(DateTime at) { }
}
```

The generator writes `DraftOrder.Submit(…)`, `OrderProtocol.WithDraft(order, draft => …)`
and `Order.Create().Customer(…).Build()`. What it catches, and where:
- an illegal transition (`draft.Approve()`) is a compiler error;
- a stale or copied state, or the raw entity touched while a state is open, is an Owen
  finding reported by the build (`OWN002`, `OWN005`, `OWN013`), through `Owen.Build`.

A full example is in `samples/OrderBackend` in the Owen repository.
