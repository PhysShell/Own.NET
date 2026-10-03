using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1 leaves the entity rule alone: handing the borrowed entity to a method that keeps it is a
// USE of it -> a verdict, as before H1.
public static class H1iEscapesEntity
{
    static Order? _saved;
    static void Escapes(Order x) => _saved = x;

    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithApproved(order, approved =>
        {
            Escapes(order);
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
