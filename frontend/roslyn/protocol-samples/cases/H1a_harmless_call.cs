using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1 (OwnIR v2 `proven_call`): a call that touches neither the entity nor the token and that
// the shared heap-effect summaries prove harmless -> ADMITTED, clean. The lowering does not
// decide it: it hands the core a `proven_call` and the facts; the core proves it.
public static class H1aHarmlessCall
{
    static int Twice(int x) => x * 2;

    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            var n = Twice(21);
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
