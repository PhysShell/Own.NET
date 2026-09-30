// Stage 2 E1 caller twin (pre-registered expected: with OWEN_RE_BODY=1 the three direct-return factories are fresh and
// Drop1..Drop3 leak; Make4 (a conditional of new and a forward) stays `none` until the Stage 3 engine rule E3).
// Stage 2 E1 caller twin: a method that drops the result of each factory shape (truth: three leaks).
using System;
sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }
static class S08B
{
    static R Make() { var r = new R(); return r; }
    static R Make2() { return Make(); }
    static R Make3() { return new R(); }
    static R Make4(bool b) => b ? new R() : Make();
    static void Drop1() { var a = Make(); a.Touch(); }
    static void Drop2() { var a = Make2(); a.Touch(); }
    static void Drop3() { var a = Make3(); a.Touch(); }
    static void Drop4(bool b) { var a = Make4(b); a.Touch(); }
}
