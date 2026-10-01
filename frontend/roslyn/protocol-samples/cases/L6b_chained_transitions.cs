using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// The same two transitions written as a chain: the intermediate token is a temporary.
public static class L6bChainedTransitions
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithDraft(order, draft => draft.Submit().Approve());
        await db.SaveChangesAsync();
    }
}
