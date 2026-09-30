// Stage 2 / Stage 3 E3 witness: Make5 (both arms new) and Make6 (both arms forwards) are fresh under OWEN_RE_BODY=1;
// Make7 (a new on one path, a forward on the other) is `none` until the engine rule E3 (Stage 3).
using System;
sealed class R : IDisposable { public void Touch() { } public void Dispose() { } }
static class S08C
{
    static R Make() { var r = new R(); return r; }
    static R Make5(bool b) => b ? new R() : new R();
    static R Make6(bool b) => b ? Make() : Make();
    static R Make7(bool b) { if (b) { return new R(); } return Make(); }
}
