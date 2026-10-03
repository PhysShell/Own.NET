using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using OrderBackend.Data;
using OrderBackend.Domain;

namespace OrderBackend;

public sealed record CreateOrderRequest(string? Customer);

/// The endpoints: ordinary ASP.NET Core + EF Core code. Each transition is a tracked load, the
/// checked refinement (`OrderProtocol.WithX`), ONE typed transition, and SaveChangesAsync. A
/// transition the state does not have is not a runtime check here: it has no method.
public static class OrderEndpoints
{
    public static async Task<IResult> Create(CreateOrderRequest request, OrdersDb db, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(request.Customer))
            return Results.Json(new { error = "customer_required" }, statusCode: StatusCodes.Status400BadRequest);

        var order = Order.Create()
            .Customer(request.Customer)
            .Build();
        db.Orders.Add(order);
        await db.SaveChangesAsync(ct);
        return Results.Created($"/orders/{order.Id}", Summary(order));
    }

    public static async Task<IResult> Submit(int id, OrdersDb db, TimeProvider clock, CancellationToken ct)
    {
        try
        {
            var order = await db.Orders.SingleOrDefaultAsync(o => o.Id == id, ct);
            if (order is null)
                return Results.NotFound();

            var now = clock.GetUtcNow().UtcDateTime;
            OrderProtocol.WithDraft(order, draft =>
            {
                draft.Submit(now);
            });

            await db.SaveChangesAsync(ct);
            return Results.Ok(Summary(order));
        }
        catch (InvalidOrderStateException refused)
        {
            return Refused(refused);
        }
        catch (CorruptOrderStateException)
        {
            return Corrupt(id);
        }
    }

    public static async Task<IResult> Approve(int id, OrdersDb db, TimeProvider clock, CancellationToken ct)
    {
        try
        {
            var order = await db.Orders.SingleOrDefaultAsync(o => o.Id == id, ct);
            if (order is null)
                return Results.NotFound();

            var now = clock.GetUtcNow().UtcDateTime;
            OrderProtocol.WithSubmitted(order, submitted =>
            {
                submitted.Approve(now);
            });

            await db.SaveChangesAsync(ct);
            return Results.Ok(Summary(order));
        }
        catch (InvalidOrderStateException refused)
        {
            return Refused(refused);
        }
        catch (CorruptOrderStateException)
        {
            return Corrupt(id);
        }
    }

    public static async Task<IResult> Ship(int id, OrdersDb db, TimeProvider clock, CancellationToken ct)
    {
        try
        {
            var order = await db.Orders.SingleOrDefaultAsync(o => o.Id == id, ct);
            if (order is null)
                return Results.NotFound();

            var now = clock.GetUtcNow().UtcDateTime;
            OrderProtocol.WithApproved(order, approved =>
            {
                approved.Ship(now, Shipping.TrackingNumber(id));
            });

            await db.SaveChangesAsync(ct);
            return Results.Ok(new { order.Id, Status = OrderStatusStorage.ToStore(order.Status), order.TrackingNumber });
        }
        catch (InvalidOrderStateException refused)
        {
            return Refused(refused);
        }
        catch (CorruptOrderStateException)
        {
            return Corrupt(id);
        }
    }

    public static async Task<IResult> Get(int id, OrdersDb db, CancellationToken ct)
    {
        try
        {
            var order = await db.Orders.AsNoTracking().SingleOrDefaultAsync(o => o.Id == id, ct);
            return order is null
                ? Results.NotFound()
                : Results.Ok(new
                {
                    order.Id,
                    order.Customer,
                    Status = OrderStatusStorage.ToStore(order.Status),
                    order.SubmittedAt,
                    order.ApprovedAt,
                    order.ShippedAt,
                    order.TrackingNumber,
                });
        }
        catch (CorruptOrderStateException)
        {
            return Corrupt(id);
        }
    }

    /// Ordinary LINQ, translated by the provider: no typed state is involved in a query.
    public static async Task<IResult> List(string? status, OrdersDb db, CancellationToken ct)
    {
        if (!OrderStatusStorage.TryFromStore(status, out var wanted))
            return Results.Json(new { error = "unknown_status" }, statusCode: StatusCodes.Status400BadRequest);

        var rows = await db.Orders
            .Where(o => o.Status == wanted)
            .OrderBy(o => o.Id)
            .Select(o => new { o.Id, o.Customer })
            .ToListAsync(ct);
        return Results.Ok(rows);
    }

    private static object Summary(Order order) =>
        new { order.Id, Status = OrderStatusStorage.ToStore(order.Status) };

    private static IResult Refused(InvalidOrderStateException refused) =>
        Results.Json(new
        {
            error = "invalid_transition",
            id = refused.Id,
            state = refused.Actual.ToString(),
            required = refused.Required.ToString(),
        }, statusCode: StatusCodes.Status409Conflict);

    private static IResult Corrupt(int id) =>
        Results.Json(new { error = "corrupt_state", id }, statusCode: StatusCodes.Status500InternalServerError);
}
