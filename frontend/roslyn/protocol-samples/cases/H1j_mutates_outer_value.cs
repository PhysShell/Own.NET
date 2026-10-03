using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// H1: the argument is not the entity, but it is a variable of the code AROUND the call (the
// enclosing method's array). The call-site evidence reads every such variable as heap, so the
// callee's write through it is a heap write -> the core REFUSES. A mutation never vanishes
// because the mutated thing was declared outside the region.
public static class H1jMutatesOuterValue
{
    static void Fill(int[] buffer) => buffer[0] = 1;

    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        var buffer = new int[4];
        Protocol.WithApproved(order, approved =>
        {
            Fill(buffer);
            approved.Ship();
        });
        await db.SaveChangesAsync();
    }
}
