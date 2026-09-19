using System;

// A2.2-1a (formal note §10.6.3, conversion closure): a built-in EXPLICIT reference conversion
// preserves object identity when it succeeds and throws rather than producing an alternate
// value when it fails — the call is simply not entered. That is a transparent edge
// (`reference_checked`), unlike `r as Derived`, which succeeds INTO a null value and lets the
// call continue (may-value). Own types, no file system: the conversion is the whole point.
static class ShapeTransparentReferenceChecked
{
    class Base : IDisposable { public virtual void Dispose() { } }
    sealed class Derived : Base { }
    static void Take(Derived x, bool leaveOpen) { if (!leaveOpen) x.Dispose(); }
    static void Caller()
    {
        Base r = new Derived();
        Take((Derived)r, true);
    }
}
