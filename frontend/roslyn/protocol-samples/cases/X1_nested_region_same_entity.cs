using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// A second region on the entity that is already borrowed -> reject.
// This is the only way the surface can ASK for a second capability.
public static class X1NestedRegionSameEntity
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            Protocol.WithDraft(order, draft => draft.Cancel());   // MUST FAIL
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
