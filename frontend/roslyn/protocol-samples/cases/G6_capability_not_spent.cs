using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// KNOWN GAP (not part of this gate): a capability that is never spent.
// Today: OWN001. Expected once tokens are affine: clean.
public static class G6CapabilityNotSpent
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
        });
        await db.SaveChangesAsync();
    }
}
