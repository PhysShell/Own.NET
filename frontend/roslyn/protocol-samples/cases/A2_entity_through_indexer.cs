using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// The borrowed entity reached through an indexer -> reject.
// Still no alias analysis: `all[0]` PRODUCES a value of the entity's type, and inside a
// region every such value is treated as the borrowed entity.
public static class A2EntityThroughIndexer
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        var all = new[] { order };
        Protocol.WithApproved(order, approved =>
        {
            all[0].Annotate("x");    // MUST FAIL
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
