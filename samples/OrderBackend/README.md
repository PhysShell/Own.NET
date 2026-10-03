# OrderBackend: a typed Order lifecycle on ASP.NET Core + EF Core

`Draft → Submitted → Approved → Shipped`, on one ordinary EF Core entity. The
states are types, so an illegal transition **does not compile**. A stale or copied
state, or the raw entity touched while a state is open, is **rejected by Own.NET**.
None of this changes EF Core: the instance the query returned is the one the
ChangeTracker tracks, the transitions save as ordinary `UPDATE`s, and ordinary LINQ
stays ordinary.

> **Not claimed: concurrency.** Two requests racing on the same order are out of
> scope here: there is no concurrency token, and nothing below says the sample is
> correct under concurrent writes. The claim also does not cover writes that bypass
> the entity's C# surface: `ExecuteUpdate`, raw SQL, `Entry(order).Property(...)`,
> reflection, another process. Those belong to concurrency tokens, constraints and
> transactions.

## 1. Declare the protocol

`OrderBackend/Domain/Order.cs` is the only file you write. The entity is a plain
class: no base class, no interface.

```csharp
public enum OrderStatus { Draft, Submitted, Approved, Shipped }   // first member = initial state

[TypedProtocol]
public sealed partial class Order
{
    private Order() { }

    public int Id { get; private set; }

    [BuilderRequired]
    public string Customer { get; private set; } = "";

    [ProtocolState]
    public OrderStatus Status { get; private set; }

    public DateTime? SubmittedAt { get; private set; }
    // ... ApprovedAt, ShippedAt, TrackingNumber

    [Transition("Submit", OrderStatus.Draft, OrderStatus.Submitted)]
    private void OnSubmit(DateTime at) => SubmittedAt = at;

    [Transition("Approve", OrderStatus.Submitted, OrderStatus.Approved)]
    private void OnApprove(DateTime at) => ApprovedAt = at;

    [Transition("Ship", OrderStatus.Approved, OrderStatus.Shipped)]
    private void OnShip(DateTime at, int trackingNumber) { ShippedAt = at; TrackingNumber = trackingNumber; }
}
```

A transition's hook writes the transition's data. The **state** itself is
written by generated code, so a hook cannot send the order to the wrong state.

## 2. Generate

```sh
dotnet run --project frontend/roslyn/Own.TypedBuilder -- \
  samples/OrderBackend/OrderBackend/Domain/Order.cs \
  -o samples/OrderBackend/OrderBackend/Domain/Order.Protocol.cs
```

`Order.Protocol.cs` is committed and readable. Regenerate it whenever `Order.cs`
changes; the gate fails if the committed file is stale. Generation is
deterministic: same input, same bytes. The generator writes:

| | |
|---|---|
| `DraftOrder`, `SubmittedOrder`, `ApprovedOrder`, `ShippedOrder` | one state type each: a `ref struct` over **the same** `Order` instance |
| `DraftOrder.Submit`, `SubmittedOrder.Approve`, `ApprovedOrder.Ship` | the only transitions. Each returns the next state; `ShippedOrder` has none |
| `OrderProtocol.WithDraft / WithSubmitted / WithApproved` | the checked way from a loaded `Order` to its state |
| `Order.Create().Customer(...).Build()` | the builder. `Build()` does not exist until `Customer` was given |
| `OrderStatusStorage` | the strict text mapping EF uses: an unknown stored value is an error, never a state |

## 3. Create, refine, transition

```csharp
// create: the builder only ever makes a Draft
var order = Order.Create().Customer("alice").Build();
db.Orders.Add(order);
await db.SaveChangesAsync(ct);

// later: an ordinary EF query, then the checked refinement, then the typed transition
var order = await db.Orders.SingleOrDefaultAsync(o => o.Id == id, ct);
OrderProtocol.WithApproved(order, approved =>      // throws InvalidOrderStateException unless Approved
{
    approved.Ship(now, Shipping.TrackingNumber(id));
});
await db.SaveChangesAsync(ct);
```

Inside the callback, code may use only the state value, plain locals and
operators, and calls Own.NET can prove harmless. `Shipping.TrackingNumber` is such
a call: a pure function, admitted by the effect summaries. A logger call, a
`SaveChanges`, or a helper that writes shared state is refused. Read the clock and
log **before** the callback, and save **after** it.

Use a state only once. A transition you do not need further is written as a
plain statement (`draft.Submit(now);`). A state you bind to a variable must be
used.

## 4. The illegal ones fail before anything runs

```csharp
OrderProtocol.WithDraft(order, draft => draft.Approve(now));
// error CS1061: 'DraftOrder' does not contain a definition for 'Approve'

Order.Create().Build();
// error CS1061: 'Order.DraftBuilder.CustomerStep' does not contain a definition for 'Build'
```

The compiler cannot see every mistake. Own.NET checks the rest:

```sh
dotnet build samples/OrderBackend/OrderBackend
dotnet run --project frontend/roslyn/OwnSharp.Extractor -c Release -- \
  samples/OrderBackend/OrderBackend/OrderBackend.csproj --flow-locals -o facts.json
python -m ownlang ownir facts.json
```

```csharp
OrderProtocol.WithDraft(order, draft =>
{
    var submitted = draft.Submit(now);
    draft.Submit(now);            // rejected: 'draft' was spent by the Submit above
    submitted.Approve(now);
});
```

```text
OrderBackend/C8_stale_draft.cs:18: error: [OWN002] IDisposable local 'draft' is used after it is disposed [resource: disposable]
```

The wording is the core's generic resource wording, and the line is the region's. The verdicts mean:
- **OWN002:** a state used after a transition spent it;
- **OWN005:** a copied state;
- **OWN013:** the raw entity touched while a state is open;
- **OWN001:** a bound state never used.

`corpus/` holds the full set, each with the exact rejection it must produce:
- **8 programs that must pass**;
- **20 that must fail**: every illegal transition, stale and copied states, raw entity access, harmful calls inside the callback, a forged state, the builder without its required field;
- **2 stated limits.**

## 5. Run it

```sh
cd samples/OrderBackend
dotnet run --project OrderBackend          # SQLite file orders.db, created on first start
```

```sh
curl -s -X POST localhost:5000/orders -H 'content-type: application/json' -d '{"customer":"alice"}'
# 201 {"id":1,"status":"Draft"}
curl -s -X POST localhost:5000/orders/1/submit      # 200 {"id":1,"status":"Submitted"}
curl -s -X POST localhost:5000/orders/1/approve     # 200 {"id":1,"status":"Approved"}
curl -s -X POST localhost:5000/orders/1/ship        # 200 {"id":1,"status":"Shipped","trackingNumber":1007919}
curl -s localhost:5000/orders/1                     # 200 {..."status":"Shipped"...}
curl -s 'localhost:5000/orders?status=Shipped'      # 200 [{"id":1,"customer":"alice"}]
curl -s -X POST localhost:5000/orders/1/ship        # 409 {"error":"invalid_transition",...}
```

| answer | when |
|---|---|
| `409 invalid_transition` | the order's stored state has no such transition. Nothing is written |
| `404` | no such order |
| `500 corrupt_state` | the stored state is not exactly one of the four names. It is never guessed |

## Verify everything

```sh
python scripts/typed_builder_gate.py                    # from the repository root
python scripts/typed_builder_gate.py --clean-checkout   # the same, twice, in fresh worktrees of HEAD
```

The gate runs these steps:
1. generates the protocol twice and requires the same bytes, equal to the committed file;
2. builds the backend;
3. checks the backend with Own.NET;
4. holds every corpus program to its registered answer;
5. runs the acceptance twice.

The acceptance (`Acceptance/`) is real HTTP against a real SQLite file. Its
oracles do not go through the typed API:
- **database:** raw SQL on its own connection;
- **object identity:** EF's ChangeTracker;
- **HTTP:** the exact responses.
