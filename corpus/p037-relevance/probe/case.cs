// P-037 A2.2-0 relevance-taxonomy probe: one method per argument shape through which a
// disposable local `r` can reach a callee, including the conversion edge on the way. Every method is classified in expected.json
// against corpus/p037-relevance/registry.json. The probe is NOT a golden for the
// sidecar's output: A2.2-4 turns each classification into a captured / excluded-by-rule
// assertion. Keep the method names stable; they are the classification keys.
using System;
using System.IO;
using System.Collections.Generic;

static class Probe
{
    static void Inner(Stream s, bool leaveOpen) { if (!leaveOpen) s.Dispose(); }
    sealed class Wrapper : IDisposable { public Wrapper(Stream s, bool leaveOpen) { } public void Dispose() { } }
    static void Run(Action a) => a();
    static void Use(Stream s) { }
    static Stream Wrap(Stream s) => s;
    sealed class Box { public Box(Stream s) { } public static implicit operator Box(MemoryStream m) => new Box(m); }
    static void TakeBox(Box b) { }
    sealed class XBox { public static explicit operator XBox(MemoryStream m) => new XBox(); }
    static void TakeXBox(XBox b) { }
    static void TakeDerived(MemoryStream? m) { }
    static void Use2((Stream s, int n) t) { }
    static void Use3(Stream[] ss) { }
    static void Use4(string s) { }
    static void Use5(long n) { }
    static void Same(MemoryStream m) { }
    class Base : IDisposable { public virtual void Dispose() { } }
    sealed class Derived : Base { }
    static void TakeDerivedRef(Derived d) { }
    struct Token : IDisposable { public void Dispose() { } }
    static void SinkObject(object o) { }

    // direct
    static void Plain() { var r = new MemoryStream(); Inner(r, true); }        // implicit reference upcast at the parameter
    static void PlainSame() { var r = new MemoryStream(); Same(r); }          // identity binding, no conversion at all

    // transparent wrappers
    static void Parens() { var r = new MemoryStream(); Inner((r), true); }
    static void IdentityCast() { var r = new MemoryStream(); Inner((MemoryStream)r, true); }   // identity conversion
    static void Cast() { var r = new MemoryStream(); Inner((Stream)r, true); }             // reference upcast
    static void AsCast() { var r = new MemoryStream(); Inner(r as Stream, true); }   // guaranteed reference upcast
    static void Bang() { var r = new MemoryStream(); Inner(r!, true); }
    static void CheckedRef() { Base r = new Derived(); TakeDerivedRef((Derived)r); }   // explicit reference conversion: same reference or no call

    // may-value
    static void Ternary(bool b) { var r = new MemoryStream(); var q = new MemoryStream(); Inner(b ? r : q, true); }
    static void Coalesce(MemoryStream? p) { var r = new MemoryStream(); Inner(p ?? r, true); }
    static void Switch(int k) { var r = new MemoryStream(); var q = new MemoryStream(); Inner(k switch { 0 => r, _ => q }, true); }
    static void AsMayFail() { Stream r = new MemoryStream(); TakeDerived(r as MemoryStream); }   // downcast: may yield null

    // call-like sites that are not invocation expressions
    static void Ctor() { var r = new MemoryStream(); var w = new Wrapper(r, true); }
    static void DelegateCall(Action<Stream> a) { var r = new MemoryStream(); a(r); }
    static void DelegateCallOwned(Stream p, Action<Stream> a) { a(p); }   // owned parameter, so the record exists regardless of legacy escape admission

    // indirect: the value that reaches the callee is not the handle
    static void Nested() { var r = new MemoryStream(); Use(Wrap(r)); }
    static void ArrayInit() { var r = new MemoryStream(); Use3(new Stream[] { r }); }
    static void CollectionInit() { var r = new MemoryStream(); var l = new List<Stream> { r }; }
    static void Tuple() { var r = new MemoryStream(); Use2((r, 1)); }
    static void Closure() { var r = new MemoryStream(); Run(() => Use(r)); }
    static void MethodGroup() { var r = new MemoryStream(); Run(r.Dispose); }
    static void UserConversion() { var r = new MemoryStream(); TakeBox(r); }              // implicit operator, no cast syntax
    static void ExplicitUserConversion() { var r = new MemoryStream(); TakeXBox((XBox)r); }  // explicit operator behind cast syntax
    static void NameOf() { var r = new MemoryStream(); Use4(nameof(r)); }
    static void MemberAccess() { var r = new MemoryStream(); Use5(r.Length); }

    // indirect: the value that reaches the callee is a boxed copy of a struct handle
    static void Boxing(Token r) { SinkObject(r); }   // owned struct parameter, boxed at the call

    // indirect: the site binds no summary parameter
    static void Receiver() { var r = new MemoryStream(); r.CopyTo(Stream.Null); }
    static void Indexer() { var r = new MemoryStream(); var d = new Dictionary<int, Stream>(); d[0] = r; }
}
