using System;
using System.IO;
using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// Whatever SURROUNDS a region is walked through: try/catch/finally, a loop, a branch,
// a `return` after it. A region is a self-contained unit.
public static class L10RegionInsideTry
{
    public static async Task<bool> Run(Db db, int[] ids)
    {
        foreach (var id in ids)
        {
            var order = await db.SingleAsync(id);
            try
            {
                if (order.Id > 0)
                {
                    Protocol.WithApproved(order, approved =>
                    {
                        approved.Ship();
                    });
                }
            }
            catch (InvalidOperationException)
            {
                return false;
            }
            finally
            {
                Audit.Record(order);
            }
        }
        await db.SaveChangesAsync();
        return true;
    }
}
