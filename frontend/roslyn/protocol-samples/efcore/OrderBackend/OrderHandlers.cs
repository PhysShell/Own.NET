using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Microsoft.EntityFrameworkCore;
using OrderBackend.Data;
using OrderBackend.Domain;

namespace OrderBackend;

/// The endpoints. Ordinary ASP.NET Core + EF Core code: there is no annotation in this file,
/// and nothing here knows that an analyzer exists.
public static class OrderHandlers
{
    public static async Task<IResult> Create(string customer, AppDbContext db, CancellationToken ct)
    {
        var order = Order.NewDraft(customer);
        db.Orders.Add(order);
        await db.SaveChangesAsync(ct);
        return Results.Created($"/orders/{order.Id}", new { order.Id, Status = order.Status.ToString() });
    }

    public static async Task<IResult> Ship(
        int id,
        AppDbContext db,
        ILogger<Program> logger,
        CancellationToken ct)
    {
        await using var tx = await db.Database.BeginTransactionAsync(ct);

        var order = await db.Orders.SingleOrDefaultAsync(x => x.Id == id, ct);
        if (order is null)
            return Results.NotFound();

        // Everything that needs a call is done OUTSIDE the region: the clock is read here
        // and captured, the log lines sit before and after.
        var now = DateTime.UtcNow;
        logger.LogInformation("shipping order {OrderId}", order.Id);
        try
        {
            OrderProtocol.WithApproved(order, approved =>
            {
                approved.Ship(now);
            });
        }
        catch (InvalidOrderStateException refused)
        {
            return Results.Conflict(refused.Message);
        }

        await db.SaveChangesAsync(ct);
        await tx.CommitAsync(ct);
        logger.LogInformation("shipped order {OrderId}", order.Id);

        return Results.Ok(new { order.Id, Status = order.Status.ToString() });
    }

    public static async Task<IResult> SubmitAndApprove(int id, AppDbContext db, CancellationToken ct)
    {
        var order = await db.Orders.SingleOrDefaultAsync(x => x.Id == id, ct);
        if (order is null)
            return Results.NotFound();

        var now = DateTime.UtcNow;
        try
        {
            // two transitions inside ONE region: Draft -> Submitted -> Approved
            OrderProtocol.WithDraft(order, draft =>
            {
                var submitted = draft.Submit(now);
                submitted.Approve(now);
            });
        }
        catch (InvalidOrderStateException refused)
        {
            return Results.Conflict(refused.Message);
        }

        await db.SaveChangesAsync(ct);
        return Results.Ok(new { order.Id, Status = order.Status.ToString() });
    }

    public static async Task<IResult> Get(int id, AppDbContext db, CancellationToken ct)
    {
        var order = await db.Orders.AsNoTracking().SingleOrDefaultAsync(x => x.Id == id, ct);
        return order is null
            ? Results.NotFound()
            : Results.Ok(new { order.Id, Status = order.Status.ToString(), order.ShippedAt });
    }
}
