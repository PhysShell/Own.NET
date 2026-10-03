using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1 leaves the entity rule alone: a call that is handed the borrowed entity is a USE of it,
// and the core rejects it with a verdict, whatever a summary would say.
public static class H1hMutatesEntity
{
    static void Mutates(Order x) => x.Annotate("changed");

    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            Mutates(order);
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
