using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// 5. normal transition -> clean.
public static class L5NormalTransition
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
