// #238 weaver kill-switch fixture: this directory carries a FodyWeavers.xml, so even a
// PERFECT enumerator-shaped empty Dispose must NOT be exempted — a weaver (Janitor.Fody)
// can rewrite the body at build time and source-level emptiness proves nothing here.
using System;
using System.Collections;
using System.Collections.Generic;

namespace Own.Samples.Weaved;

public sealed class WeavedEnumerator : IEnumerator<int>
{
    private int _i;
    public int Current => _i;
    object IEnumerator.Current => Current;
    public bool MoveNext() => ++_i <= 3;
    public void Reset() => _i = 0;
    public void Dispose() { }   // empty in source; a weaver may fill it at build time
}

public sealed class WeavedConsumer
{
    // FLAGGED: the FodyWeavers.xml above disables the empty-Dispose exemption entirely.
    public int Count()
    {
        var we = new WeavedEnumerator();
        var n = 0;
        while (we.MoveNext()) n++;   // never disposed -> must STAY OWN001
        return n;
    }
}
