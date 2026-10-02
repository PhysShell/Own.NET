using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// The entity is free again once the region closes: `return Ok(order)` territory.
public static class L7ReadAfterRegion
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            approved.Ship();
        });
        Audit.Record(order);
        await db.SaveChangesAsync();
    }
}
