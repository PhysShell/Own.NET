using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1: the call touches neither entity nor token, but it writes a static -> the core REFUSES
// the document (writes.static is may). Not harmless is not clean.
public static class H1dGlobalState
{
    static int _counter;
    static void TouchesGlobalState() => _counter++;

    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            TouchesGlobalState();
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
