using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// 1. stale capability -> reject.
// `draft` is spent by Submit(); using it again is a use of a consumed token.
public static class L1StaleCapability
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithDraft(order, draft =>
        {
            var submitted = draft.Submit();
            draft.Cancel();          // MUST FAIL
            submitted.Approve();
        });
        await db.SaveChangesAsync();
    }
}
