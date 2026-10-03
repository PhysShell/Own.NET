using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1: a strongly connected component that does nothing to memory (Even <-> Odd) solves to
// harmless at its least fixpoint -> ADMITTED, clean.
public static class H1cPureScc
{
    static bool Even(int n) => n == 0 || Odd(n - 1);
    static bool Odd(int n) => n != 0 && Even(n - 1);

    public static async Task Run(Db db, int id, int value)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            var even = Even(value);
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
