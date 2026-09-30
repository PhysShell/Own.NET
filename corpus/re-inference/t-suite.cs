// resource-effects Stage 3 inference suite (pre-registered in Own.NET-paperwork
// paper-eval/resource-effects/stage3-inference-prereg-v1.json, tests T01-T14). One class per test; the
// expected summaries live in the prereg and the measured ones in stage3-inference-v1.json.
using System;

sealed class R : IDisposable { public bool IsOpen => true; public void Touch() { } public void Dispose() { } }

sealed class Conn : IDisposable
{
    public void Kill() { Dispose(); }
    public void Touch() { }
    public void Dispose() { }
}

interface IFactory { R Make(); }
interface IKill { void Kill(); }

static class T01 { public static R Make() { var r = new R(); return r; } }
static class T02 { public static R Make2() { return T01.Make(); } public static R Make3() { return new R(); } }
static class T03 { public static R Outer() => T02.Make2(); }
static class T04 { static void Run() { var c = new Conn(); c.Kill(); } static void RunUse() { var c = new Conn(); c.Kill(); c.Touch(); } }
static class T05 { public static void Drop(Conn c) { c.Kill(); } static void Run() { var c = new Conn(); Drop(c); } }
static class T06 { public static void Finish(R r, bool b) { if (b) { r.Dispose(); } } }
static class T07 { public static void Finish(R r, bool keep) { if (!keep) { r.Dispose(); } } }
static class T08 { public static R Make7(bool b) { if (b) { return new R(); } return T01.Make(); } static void Drop(bool b) { var a = Make7(b); a.Touch(); } }
static class T09 { public static void Finish(R r) { r.Dispose(); } public static void Fwd(R r) { Finish(r); } }
static class T10 { public static void Use(R r) { r.Touch(); } }
static class T11 { public static R Id(R x) => x; static void Run() { var r = new R(); var s = Id(r); s.Dispose(); } }
static class T11B { public static R Id(R x) { return x; } static void Run() { var r = new R(); var s = Id(r); s.Dispose(); } static void RunBoth() { var r = new R(); var s = Id(r); s.Dispose(); r.Dispose(); } }
static class T12 { public static R A(bool b) => b ? new R() : B(); public static R B() => A(false); static void Drop() { var a = A(true); a.Touch(); } }
static class T13 { public static R Ext() => Unknown.Get(); static void Drop() { var a = Ext(); a.Touch(); } }
static class T14
{
    public static R Via(IFactory f) => f.Make();
    public static void ViaKill(IKill k) { k.Kill(); }
    static void Drop(IFactory f) { var a = Via(f); a.Touch(); }
    static void Run(IFactory f, IKill k) { var r = new R(); ViaKill(k); r.Touch(); }
}
