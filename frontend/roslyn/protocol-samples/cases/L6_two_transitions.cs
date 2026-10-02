using System.Threading.Tasks;
using Own.Protocols.Sample;

namespace Own.Protocols.Cases;

// 6. two transitions -> clean. Draft -> Submitted -> (approved, token spent).
public static class L6TwoTransitions
{
    public static async Task Run(Db db, int id)
    {
        var order = await db.SingleAsync(id);
        Protocol.WithDraft(order, draft =>
        {
            var submitted = draft.Submit();
            submitted.Approve();
        });
        await db.SaveChangesAsync();
    }
}
