using System;

namespace Own.HeapEffects.Samples;

// H0 heap-effect summaries (docs/notes/heap-effect-summaries.md): the C# behind the committed
// sidecar `tests/fixtures/heap_effects/samples.sidecar.json` and its solved golden
// `samples.summaries.json`. scripts/heap_effects_gate.py re-extracts this file and requires
// the committed sidecar back, byte-equal as JSON. Lives under frontend/roslyn/ (not examples/)
// so the #260 shadow sweep does not treat it as an application.

public sealed class Order
{
    public int State { get; set; }
    public Order? Next { get; set; }

    // receiver effects
    public void Touch() => State = 1;
    public int Peek() => State;
}

public interface IShape
{
    int Area();
}

public static class Kill
{
    public static Order? Saved;
    public static int Counter;

    // 1. harmless candidate: every parameter plain, no writes, nothing returned that aliases
    public static int Twice(int x) => x * 2;

    // 2. BorrowMut(0)
    public static void Mutates(Order x) => x.State = 1;

    // 3. MayEscape(0) + a static write
    public static void Escapes(Order x) => Saved = x;

    // 4. a static write, no parameter at all
    public static void TouchesGlobalState() => Counter++;

    // 5. an external call: Unknown (nothing proves what Console does)
    public static void Logs() => Console.WriteLine("x");
}

public static class Transitive
{
    // A(x) => B(x); B mutates / escapes: the effect reaches A only through B's summary
    public static void A(Order x) => B(x);
    public static void B(Order x) => x.State = 2;

    public static void EscapeOuter(Order x) => EscapeInner(x);
    public static void EscapeInner(Order x) => Kill.Saved = x;

    // Unknown propagates: a caller of an unknown is unknown where it matters
    public static void CallsLogs() => Kill.Logs();

    // receiver effect, mapped to the argument that is the receiver
    public static void CallsTouch(Order o) => o.Touch();
    public static int CallsPeek(Order o) => o.Peek();

    // local alias: the write is to the parameter's object
    public static void AliasMutates(Order o)
    {
        var a = o;
        a.State = 3;
    }

    // a reassigned parameter: its later value may be the heap's
    public static void Reassigned(Order o)
    {
        o = Kill.Saved!;
        o.State = 4;
    }

    // array element: the array is mutated, the stored value escapes
    public static void SetFirst(Order[] items, Order o) => items[0] = o;

    // reads only
    public static int ReadsDeep(Order o) => o.Next!.State;
}

public static class Returns
{
    public static Order Id(Order o) => o;
    public static Order ViaCall(Order o) => Id(o);
    public static Order? FromHeap() => Kill.Saved;
    public static Order Fresh() => new Order();
    public static void MutatesResult(Order o) => Id(o).State = 5;
}

public static class Recursive
{
    // a pure SCC: stays plain
    public static bool Even(int n) => n == 0 || Odd(n - 1);
    public static bool Odd(int n) => n != 0 && Even(n - 1);

    // an SCC whose one member mutates: both carry it
    public static void Ping(Order o, int n)
    {
        if (n > 0)
            Pong(o, n - 1);
    }

    public static void Pong(Order o, int n)
    {
        o.State = n;
        Ping(o, n);
    }

    // an SCC with an unknown member: Unknown absorbs the whole cycle
    public static void Tick(Order o, int n)
    {
        if (n > 0)
            Tock(o, n - 1);
    }

    public static void Tock(Order o, int n)
    {
        Console.WriteLine(n);
        Tick(o, n);
    }
}

public static class Opaque
{
    // virtual dispatch: the override is not known
    public static int Virtual(IShape s) => s.Area();

    // a lambda: unmodelled, Unknown
    public static Func<int> Lambda(Order o) => () => o.State;

    // a static constructor runs on first touch of the type
    public static int CallsLazy() => Lazy.Value();
}

public static class Lazy
{
    private static readonly int Seed;

    static Lazy() => Seed = Environment.ProcessorCount;

    public static int Value() => Seed;
}

// A primary-constructor parameter is hidden state of the instance, not a parameter of the
// member that reads it: Unknown, never mistaken for the member's own argument.
public sealed class Holder(Order order)
{
    public void Touch() => order.State = 6;
}
