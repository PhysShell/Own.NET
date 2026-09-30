// resource-effects Stage 2 witness shape s15 (pre-registered in Own.NET-paperwork stage2-body-effects-prereg-v1.json):
// a first-party instance method whose body disposes the receiver on every normal exit (the CngKey.Delete shape),
// a conditional twin, and a wrapper. Truth: Run leaks nothing (Kill releases c); RunUse uses c after the kill
// (OWN002); RunMaybe keeps c (MaybeKill is conditional: OWN001 at the end is the truth since c is never
// disposed on the false path); RunDrop leaks nothing (Drop(c) consumes through Kill).
using System;

sealed class Conn : IDisposable
{
    bool _open = true;

    public void Kill()
    {
        _open = false;
        Dispose();
    }

    public void MaybeKill(bool really)
    {
        if (really)
        {
            this.Dispose();
        }
    }

    public void Touch() { }

    public void Dispose() { _open = false; }
}

static class S15
{
    static void Drop(Conn c)
    {
        c.Kill();
    }

    static void Run()
    {
        var c = new Conn();
        c.Kill();
    }

    static void RunUse()
    {
        var c = new Conn();
        c.Kill();
        c.Touch();
    }

    static void RunMaybe(bool really)
    {
        var c = new Conn();
        c.MaybeKill(really);
    }

    static void RunDrop()
    {
        var c = new Conn();
        Drop(c);
    }
}
