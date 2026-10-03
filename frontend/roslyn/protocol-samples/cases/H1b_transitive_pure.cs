using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1: A -> B -> pure work. Only B's summary says what A does, and it says nothing is
// touched -> ADMITTED, clean.
public static class H1bTransitivePure
{
    static int A(int x) => B(x) + 1;
    static int B(int x) => x * 3;

    public static async Task Run(Db db, int id, int value)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            var n = A(value);
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
