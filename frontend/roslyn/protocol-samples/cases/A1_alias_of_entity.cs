using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// An alias made BEFORE the region, used inside it -> reject.
// No alias analysis: inside a region every value of the entity's type is treated as
// the borrowed entity (exclusivity by type).
public static class A1AliasOfEntity
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        var same = order;
        Protocol.WithApproved(order, approved =>
        {
            same.Annotate("x");      // MUST FAIL
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
