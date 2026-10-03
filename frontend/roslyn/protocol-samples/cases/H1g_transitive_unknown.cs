using System;
using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1: A -> Console.WriteLine. The call site is direct and touches nothing, but A reaches an
// external method no summary describes: Unknown is poison -> the core REFUSES.
public static class H1gTransitiveUnknown
{
    static void A(int x) => Console.WriteLine(x);

    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            A(1);
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
