using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1: Ping <-> Pong, and only Pong writes a static. The write reaches every member of the
// component -> the call to Ping is REFUSED by the core.
public static class H1fPollutedScc
{
    static int _ticks;
    static void Ping(int n) { if (n > 0) Pong(n - 1); }
    static void Pong(int n) { _ticks++; Ping(n); }

    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            Ping(3);
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
