using System;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

// Kernels 2-4: is the LLVM advantage general, or confined to straight-line
// numeric loops? Run with a long warmup so every method is at tier-1.
static class Kernels
{
    const int N = 1 << 16;
    const int Reps = 4000;
    const int Warm = 5000;

    [MethodImpl(MethodImplOptions.NoInlining)]
    static long SumManaged(int[] a)
    {
        long s = 0;
        for (int i = 0; i < a.Length; i++) s += a[i];
        return s;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static long FilterSumManaged(int[] a, int lo, int hi)
    {
        long s = 0;
        for (int i = 0; i < a.Length; i++)
        {
            int v = a[i];
            if (v > lo && v < hi) s += v * 2; else s -= v;
        }
        return s;
    }

    // K3 control A: hand-written branchless C# (encourage cmov, kill the
    // misprediction cost without any SIMD).
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long FilterSumBranchless(int[] a, int lo, int hi)
    {
        long s = 0;
        for (int i = 0; i < a.Length; i++)
        {
            int v = a[i];
            int inRange = (v > lo & v < hi) ? 1 : 0;
            s += inRange * (v * 2) + (1 - inRange) * (-v);
        }
        return s;
    }

    // K3 control B: hand-written SIMD with a select -- the same transform
    // LLVM's vectorizer applies automatically (if-conversion + vectorize).
    [MethodImpl(MethodImplOptions.NoInlining)]
    static long FilterSumSimd(int[] a, int lo, int hi)
    {
        int w = System.Runtime.Intrinsics.Vector256<int>.Count, i = 0;
        var vlo = System.Runtime.Intrinsics.Vector256.Create(lo);
        var vhi = System.Runtime.Intrinsics.Vector256.Create(hi);
        // Accumulate in 64-bit to match the scalar version's `long s` exactly:
        // widen each 8x32 result to 2x 4x64 before adding.
        var accLo = System.Runtime.Intrinsics.Vector256<long>.Zero;
        var accHi = System.Runtime.Intrinsics.Vector256<long>.Zero;
        for (; i <= a.Length - w; i += w)
        {
            var v = System.Runtime.Intrinsics.Vector256.LoadUnsafe(ref a[i]);
            var mask = System.Runtime.Intrinsics.Vector256.GreaterThan(v, vlo)
                     & System.Runtime.Intrinsics.Vector256.LessThan(v, vhi);
            var sel = System.Runtime.Intrinsics.Vector256.ConditionalSelect(mask, v + v, -v);
            (var wLo, var wHi) = System.Runtime.Intrinsics.Vector256.Widen(sel);
            accLo += wLo; accHi += wHi;
        }
        long s = System.Runtime.Intrinsics.Vector256.Sum(accLo)
               + System.Runtime.Intrinsics.Vector256.Sum(accHi);
        for (; i < a.Length; i++)
        {
            int v = a[i];
            if (v > lo && v < hi) s += v * 2; else s -= v;
        }
        return s;
    }

    sealed class Node { public Node Next; public long Value; }

    [MethodImpl(MethodImplOptions.NoInlining)]
    static long ChaseManaged(Node head, long n)
    {
        long s = 0;
        for (long i = 0; i < n && head != null; i++) { s += head.Value; head = head.Next; }
        return s;
    }

    [DllImport("native2", EntryPoint = "sum_native")]
    static extern unsafe long SumNative(int* a, long n, long la);
    [DllImport("native2", EntryPoint = "filter_sum_native")]
    static extern unsafe long FilterSumNative(int* a, long n, long la, int lo, int hi);
    // check-free variants: the frontend hoisted the range check out of the loop
    [DllImport("native3", EntryPoint = "sum_free")]
    static extern unsafe long SumFree(int* a, long n, long la);
    [DllImport("native3", EntryPoint = "filter_sum_free")]
    static extern unsafe long FilterSumFree(int* a, long n, long la, int lo, int hi);

    static double Time(Action f, int reps)
    {
        var sw = Stopwatch.StartNew();
        for (int r = 0; r < reps; r++) f();
        sw.Stop();
        return sw.Elapsed.TotalMilliseconds;
    }

    public static unsafe void Run()
    {
        var a = new int[N];
        var rnd = new Random(42);
        for (int i = 0; i < N; i++) a[i] = rnd.Next(0, 1000);

        long sink = 0;
        for (int r = 0; r < Warm; r++) sink += SumManaged(a) + FilterSumManaged(a, 200, 800)
                                              + FilterSumBranchless(a, 200, 800) + FilterSumSimd(a, 200, 800);
        fixed (int* pa = a)
        {
            for (int r = 0; r < Warm; r++) sink += SumNative(pa, N, N) + FilterSumNative(pa, N, N, 200, 800)
                                                  + SumFree(pa, N, N) + FilterSumFree(pa, N, N, 200, 800);

            int* p = pa;
            double t;
            double elems = (double)N * Reps;

            Console.WriteLine($"\n-- K2 reduction (sum) --");
            t = Time(() => sink += SumManaged(a), Reps);
            double k2m = elems / t / 1e6;
            Console.WriteLine($"RyuJIT managed   : {t,8:F1} ms   {k2m,6:F2} Gelem/s   1.00x");
            t = Time(() => sink += SumNative(p, N, N), Reps);
            Console.WriteLine($"LLVM -O3 w/ check: {t,8:F1} ms   {elems / t / 1e6,6:F2} Gelem/s   {(elems / t / 1e6) / k2m,5:F2}x");
            t = Time(() => sink += SumFree(p, N, N), Reps);
            Console.WriteLine($"LLVM -O3 no check: {t,8:F1} ms   {elems / t / 1e6,6:F2} Gelem/s   {(elems / t / 1e6) / k2m,5:F2}x");

            // correctness gate: every K3 variant must return the SAME value, and
            // that value must be the pinned expected result -- comparing the
            // variants only to each other would let a shared defect pass.
            const long ExpectedFilterSum = 25_830_282;
            long r0 = FilterSumManaged(a, 200, 800), r1 = FilterSumBranchless(a, 200, 800),
                 r2 = FilterSumSimd(a, 200, 800), r3 = FilterSumNative(p, N, N, 200, 800);
            long r4 = FilterSumFree(p, N, N, 200, 800);
            if (r0 != ExpectedFilterSum || r0 != r1 || r0 != r2 || r0 != r3 || r0 != r4)
                throw new Exception($"K3 MISMATCH expected={ExpectedFilterSum} scalar={r0} " +
                                    $"branchless={r1} simd={r2} native={r3} free={r4}");
            long q0 = SumManaged(a), q1 = SumNative(p, N, N), q2 = SumFree(p, N, N);
            if (q0 != q1 || q0 != q2) throw new Exception($"K2 MISMATCH {q0} vs {q1} vs {q2}");
            Console.WriteLine($"\n-- K3 data-dependent branch (filter+sum) --  [all variants agree: {r0}]");
            t = Time(() => sink += FilterSumManaged(a, 200, 800), Reps);
            double k3m = elems / t / 1e6;
            Console.WriteLine($"RyuJIT managed   : {t,8:F1} ms   {k3m,6:F2} Gelem/s   1.00x");
            t = Time(() => sink += FilterSumBranchless(a, 200, 800), Reps);
            Console.WriteLine($"RyuJIT branchless: {t,8:F1} ms   {elems / t / 1e6,6:F2} Gelem/s   {(elems / t / 1e6) / k3m,5:F2}x");
            t = Time(() => sink += FilterSumSimd(a, 200, 800), Reps);
            Console.WriteLine($"RyuJIT SIMD+sel  : {t,8:F1} ms   {elems / t / 1e6,6:F2} Gelem/s   {(elems / t / 1e6) / k3m,5:F2}x");
            t = Time(() => sink += FilterSumNative(p, N, N, 200, 800), Reps);
            Console.WriteLine($"LLVM -O3 w/ check: {t,8:F1} ms   {elems / t / 1e6,6:F2} Gelem/s   {(elems / t / 1e6) / k3m,5:F2}x");
            t = Time(() => sink += FilterSumFree(p, N, N, 200, 800), Reps);
            Console.WriteLine($"LLVM -O3 no check: {t,8:F1} ms   {elems / t / 1e6,6:F2} Gelem/s   {(elems / t / 1e6) / k3m,5:F2}x");
        }

        // K4: managed pointer chasing has no native counterpart worth timing
        // (the object graph lives in the GC heap); measured to show the shape
        // of code where no vectorizer of any kind helps.
        const int Len = 1 << 14;
        Node head = null;
        for (int i = 0; i < Len; i++) head = new Node { Next = head, Value = i };
        double tc = Time(() => sink += ChaseManaged(head, Len), Reps / 4);
        Console.WriteLine($"\n-- K4 pointer chase (managed only) --");
        Console.WriteLine($"RyuJIT managed   : {tc,8:F1} ms   {(double)Len * (Reps / 4) / tc / 1e6,6:F2} Gnode/s");
        Console.WriteLine($"\n(sink={sink})");
    }
}
