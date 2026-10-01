using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// 4. raw escape -> refuse/reject.
// Handing the raw entity to other code inside the region is the same violation.
public static class L4RawEscape
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            Audit.Record(order);     // MUST FAIL
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
