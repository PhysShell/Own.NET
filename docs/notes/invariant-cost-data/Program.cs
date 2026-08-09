using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Runtime.CompilerServices;

// Question: a static rule can find "loop-invariant query evaluated inside a
// loop". Can it tell you how much it COSTS? Every case below is the SAME
// syntactic shape -- an invariant call in a loop body -- so a static rule sees
// them as identical. Measure the actual penalty.
static class Program
{
    static long sink;

    // ---- shape A: Any() over a List, predicate over a captured local ----
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long A_Inline(List<int> data, int threshold, int iters)
    {
        long acc = 0;
        for (int i = 0; i < iters; i++)
            if (data.Any(x => x > threshold)) acc += i;   // loop-invariant
        return acc;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static long A_Hoisted(List<int> data, int threshold, int iters)
    {
        long acc = 0;
        bool inv = data.Any(x => x > threshold);          // hoisted by hand
        for (int i = 0; i < iters; i++) if (inv) acc += i;
        return acc;
    }

    // ---- shape B: Count() on a Select-wrapped sequence (O(n) here; Count()
    //      is O(1) when the source implements ICollection<T>) vs .Count property ----
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long B_Inline(IEnumerable<int> data, int iters)
    {
        long acc = 0;
        for (int i = 0; i < iters; i++) acc += data.Count();
        return acc;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static long B_Hoisted(IEnumerable<int> data, int iters)
    {
        long acc = 0; int c = data.Count();
        for (int i = 0; i < iters; i++) acc += c;
        return acc;
    }

    // ---- shape C: OrderBy().First() -- repeated linear key scanning every
    //      iteration (.NET 9 takes a specialized TryGetFirst path rather than
    //      materializing and sorting a buffer) ----
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long C_Inline(List<int> data, int iters)
    {
        long acc = 0;
        for (int i = 0; i < iters; i++) acc += data.OrderBy(x => x).First();
        return acc;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static long C_Hoisted(List<int> data, int iters)
    {
        long acc = 0; int v = data.OrderBy(x => x).First();
        for (int i = 0; i < iters; i++) acc += v;
        return acc;
    }

    // ---- shape D: a trivially cheap invariant -- the control ----
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long D_Inline(List<int> data, int iters)
    {
        long acc = 0;
        for (int i = 0; i < iters; i++) acc += data.Count;   // O(1) property
        return acc;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static long D_Hoisted(List<int> data, int iters)
    {
        long acc = 0; int c = data.Count;
        for (int i = 0; i < iters; i++) acc += c;
        return acc;
    }

    static double Bench(Func<long> f, int reps)
    {
        for (int i = 0; i < 20; i++) sink += f();          // warm
        var sw = Stopwatch.StartNew();
        for (int i = 0; i < reps; i++) sink += f();
        sw.Stop();
        return sw.Elapsed.TotalMilliseconds / reps;
    }

    static void Row(string shape, int n, Func<long> inline, Func<long> hoisted, int reps)
    {
        // Correctness gate FIRST, and it must fail the run: timing two
        // non-equivalent implementations produces a meaningless ratio, and a
        // printed warning would still exit 0 and look like a good measurement.
        long a = inline(), b = hoisted();
        if (a != b)
            throw new InvalidOperationException($"{shape} n={n}: MISMATCH {a} vs {b}");

        double ti = Bench(inline, reps), th = Bench(hoisted, reps);
        Console.WriteLine($"{shape,-38} n={n,-7} inline={ti,9:F4} ms  hoisted={th,9:F4} ms   penalty = {ti / th,8:F1}x");
    }

    static void Main()
    {
        const int Iters = 1000;
        Console.WriteLine("Same syntactic shape everywhere: a loop-invariant call in a loop body.");
        Console.WriteLine($"Inner loop = {Iters} iterations. 'penalty' = how much the un-hoisted version costs.\n");

        foreach (int n in new[] { 4, 64, 4096, 100_000 })
        {
            var list = Enumerable.Range(0, n).ToList();
            IEnumerable<int> seq = list.Select(x => x);   // hides ICollection fast path
            int th = -1;                                  // Any() hits on the FIRST element

            Row("A: Any(x => x > t)  [hit@0]", n, () => A_Inline(list, th, Iters), () => A_Hoisted(list, th, Iters), 20);
            Row("A: Any(x => x > t)  [miss]", n, () => A_Inline(list, int.MaxValue, Iters), () => A_Hoisted(list, int.MaxValue, Iters), 5);
            Row("B: Count() on Select-wrapped IEnumerable", n, () => B_Inline(seq, Iters), () => B_Hoisted(seq, Iters), 5);
            Row("C: OrderBy().First()", n, () => C_Inline(list, Iters), () => C_Hoisted(list, Iters), n > 10000 ? 1 : 3);
            Row("D: .Count property (cheap)", n, () => D_Inline(list, Iters), () => D_Hoisted(list, Iters), 50);
            Console.WriteLine();
        }
        Console.WriteLine($"(sink={sink})");
    }
}
