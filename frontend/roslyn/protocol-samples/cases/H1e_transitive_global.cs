using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1: A -> B, and B writes a static. A looks innocent at the call site; its summary carries
// B's write -> the core REFUSES.
public static class H1eTransitiveGlobal
{
    static int _counter;
    static int A(int x) { B(); return x; }
    static void B() => _counter++;

    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            var n = A(1);
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
