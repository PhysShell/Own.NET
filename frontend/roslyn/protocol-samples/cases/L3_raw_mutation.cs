using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// 3. raw mutation -> reject.
// The entity is exclusively borrowed for the region; touching it directly is a violation.
public static class L3RawMutation
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            order.Annotate("x");     // MUST FAIL
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
