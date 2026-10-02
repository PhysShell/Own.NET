using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// A transition on one branch only, then again after the merge -> reject (maybe-consumed).
public static class L8BranchInsideRegion
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            if (approved.Id > 0)
            {
                approved.Ship();
            }
            approved.Ship();         // MUST FAIL on the path that already shipped
        });
        await db.SaveChangesAsync();
    }
}
