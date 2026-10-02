using System;
using System.IO;
using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// The SAME opaque calls that are refused inside a region are ordinary code outside it:
// before the region the entity is not borrowed, after it the borrow is over.
public static class L9OpaqueCallsAroundRegion
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Backdoor.Remember(order);
        Backdoor.AnnotateLast();
        var now = DateTime.UtcNow;
        Protocol.WithApproved(order, approved =>
        {
            approved.Ship();
        });
        Backdoor.AnnotateLast();
        Console.WriteLine(now);
        await db.SaveChangesAsync();
    }
}
