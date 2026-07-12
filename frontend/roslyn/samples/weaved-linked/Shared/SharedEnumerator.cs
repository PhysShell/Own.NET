// #240 linked-source weaver fixture: this file lives OUTSIDE the Fody-enabled project's
// directory and is pulled in via <Compile Include="../Shared/...">. No FodyWeavers.xml
// sits above THIS file — the kill-switch must learn the weaver from the OWNING project.
using System;
using System.Collections;
using System.Collections.Generic;

namespace Own.Samples.WeavedLinked;

public sealed class SharedEnumerator : IEnumerator<int>
{
    private int _i;
    public int Current => _i;
    object IEnumerator.Current => Current;
    public bool MoveNext() => ++_i <= 3;
    public void Reset() => _i = 0;
    public void Dispose() { }   // empty in source; the OWNING project weaves at build time
}

public sealed class SharedConsumer
{
    // FLAGGED when analysed THROUGH the .csproj: the project's FodyWeavers.xml disables
    // the empty-Dispose exemption even though this file's own ancestors carry none.
    public int Count()
    {
        var se = new SharedEnumerator();
        var n = 0;
        while (se.MoveNext()) n++;   // never disposed -> must STAY OWN001
        return n;
    }
}
