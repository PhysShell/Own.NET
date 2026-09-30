// resource-effects Stage 1 hostile oracle control H1 (frozen in Own.NET-paperwork
// paper-eval/resource-effects/prereg-v1.json): a first-party method NAMED CreateLinkedTokenSource that
// returns a SHARED static source. Truth: no leak (borrowed). The identity answer key names only
// System.Threading.CancellationTokenSource.CreateLinkedTokenSource, so it must not fire here; the
// M1 name-rule mutant key (Create* -> fresh) MUST produce a false OWN001.
using System.Threading;

static class Linked
{
    static readonly CancellationTokenSource s_shared = new CancellationTokenSource();

    public static CancellationTokenSource CreateLinkedTokenSource(CancellationToken token) => s_shared;
}

static class H1
{
    static void Use(CancellationToken token)
    {
        var c = Linked.CreateLinkedTokenSource(token);
        c.Cancel();
    }
}
