using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// 2. copied capability -> reject.
// C# copies a struct; the lowering reads the copy as a MOVE, so the source is dead.
public static class L2CopiedCapability
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithDraft(order, draft =>
        {
            var copy = draft;
            draft.Cancel();          // MUST FAIL
            copy.Cancel();
        });
        await db.SaveChangesAsync();
    }
}
