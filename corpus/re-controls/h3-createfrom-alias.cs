// resource-effects Stage 1 hostile oracle control H3: a Create*-named method that RETURNS ITS PARAMETER
// (an alias, not a fresh resource). Truth: no leak and no double release. The identity answer key must
// not fire; the M1 name-rule mutant key (Create* -> fresh) MUST fabricate a second resource.
using System;

sealed class R : IDisposable
{
    public void Touch() { }
    public void Dispose() { }
}

static class H3
{
    static R CreateFrom(R x) => x;

    static void Run()
    {
        var r = new R();
        var s = CreateFrom(r);
        s.Dispose();
    }
}
