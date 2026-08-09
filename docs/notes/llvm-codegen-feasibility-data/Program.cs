using System;
using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Runtime.Intrinsics;

static class Bench
{
    const int N = 1 << 16;      // 64K ints per array = 256 KB, fits in L2
    const int Reps = 4000;

    [MethodImpl(MethodImplOptions.NoInlining)]
    static void AxpyManaged(int[] dst, int[] a, int[] b)
    {
        for (int i = 0; i < dst.Length; i++)
            dst[i] = a[i] + b[i] * 3;
    }

    // Control: what a C# developer can already write today, no LLVM involved.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void AxpySimd(int[] dst, int[] a, int[] b)
    {
        int w = Vector256<int>.Count, i = 0;
        var three = Vector256.Create(3);
        for (; i <= dst.Length - w; i += w)
        {
            var va = Vector256.LoadUnsafe(ref a[i]);
            var vb = Vector256.LoadUnsafe(ref b[i]);
            (va + vb * three).StoreUnsafe(ref dst[i]);
        }
        for (; i < dst.Length; i++) dst[i] = a[i] + b[i] * 3;
    }

    // Control 2: hand-SIMD + 4x unroll, i.e. exactly what LLVM's vectorizer
    // chose on its own (width 8, interleave 4). Written by hand in C#.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void AxpySimdUnrolled(int[] dst, int[] a, int[] b)
    {
        int w = Vector256<int>.Count, i = 0;
        var three = Vector256.Create(3);
        for (; i <= dst.Length - 4 * w; i += 4 * w)
        {
            (Vector256.LoadUnsafe(ref a[i]) + Vector256.LoadUnsafe(ref b[i]) * three).StoreUnsafe(ref dst[i]);
            (Vector256.LoadUnsafe(ref a[i + w]) + Vector256.LoadUnsafe(ref b[i + w]) * three).StoreUnsafe(ref dst[i + w]);
            (Vector256.LoadUnsafe(ref a[i + 2 * w]) + Vector256.LoadUnsafe(ref b[i + 2 * w]) * three).StoreUnsafe(ref dst[i + 2 * w]);
            (Vector256.LoadUnsafe(ref a[i + 3 * w]) + Vector256.LoadUnsafe(ref b[i + 3 * w]) * three).StoreUnsafe(ref dst[i + 3 * w]);
        }
        for (; i < dst.Length; i++) dst[i] = a[i] + b[i] * 3;
    }

    [DllImport("native", EntryPoint = "axpy_noalias")]
    static extern unsafe void AxpyNoalias(int* dst, int* a, int* b, long n, long ld, long la, long lb);

    [DllImport("native", EntryPoint = "axpy_alias")]
    static extern unsafe void AxpyAlias(int* dst, int* a, int* b, long n, long ld, long la, long lb);

    static unsafe void Main()
    {
        var dst = new int[N]; var a = new int[N]; var b = new int[N];
        for (int i = 0; i < N; i++) { a[i] = i; b[i] = N - i; }

        // Warm up well past the tier-1 / OSR thresholds. 200 reps is NOT
        // enough -- it leaves tier-0 code in the measurement (see the note).
        for (int r = 0; r < 5000; r++) AxpyManaged(dst, a, b);
        for (int r = 0; r < 5000; r++) AxpySimd(dst, a, b);
        for (int r = 0; r < 5000; r++) AxpySimdUnrolled(dst, a, b);
        fixed (int* pd = dst, pa = a, pb = b)
        {
            for (int r = 0; r < 5000; r++) AxpyNoalias(pd, pa, pb, N, N, N, N);
            for (int r = 0; r < 5000; r++) AxpyAlias(pd, pa, pb, N, N, N, N);
        }

        long checksum = 0;
        var sw = new Stopwatch();

        sw.Restart();
        for (int r = 0; r < Reps; r++) AxpyManaged(dst, a, b);
        sw.Stop(); var tManaged = sw.Elapsed.TotalMilliseconds; checksum += dst[N - 1];

        sw.Restart();
        for (int r = 0; r < Reps; r++) AxpySimd(dst, a, b);
        sw.Stop(); var tSimd = sw.Elapsed.TotalMilliseconds; checksum += dst[N - 1];

        sw.Restart();
        for (int r = 0; r < Reps; r++) AxpySimdUnrolled(dst, a, b);
        sw.Stop(); var tSimdU = sw.Elapsed.TotalMilliseconds; checksum += dst[N - 1];

        fixed (int* pd = dst, pa = a, pb = b)
        {
            sw.Restart();
            for (int r = 0; r < Reps; r++) AxpyNoalias(pd, pa, pb, N, N, N, N);
            sw.Stop(); var tNoalias = sw.Elapsed.TotalMilliseconds; checksum += dst[N - 1];

            sw.Restart();
            for (int r = 0; r < Reps; r++) AxpyAlias(pd, pa, pb, N, N, N, N);
            sw.Stop(); var tAlias = sw.Elapsed.TotalMilliseconds;

            double elems = (double)N * Reps;
            Console.WriteLine($"N={N} reps={Reps} checksum={checksum}");
            Console.WriteLine($"RyuJIT managed   : {tManaged,8:F1} ms   {elems / tManaged / 1e6,6:F2} Gelem/s   1.00x");
            Console.WriteLine($"RyuJIT Vector256 : {tSimd,8:F1} ms   {elems / tSimd / 1e6,6:F2} Gelem/s   {tManaged / tSimd,5:F2}x");
            Console.WriteLine($"RyuJIT Vec256 x4 : {tSimdU,8:F1} ms   {elems / tSimdU / 1e6,6:F2} Gelem/s   {tManaged / tSimdU,5:F2}x");
            Console.WriteLine($"LLVM -O3 noalias : {tNoalias,8:F1} ms   {elems / tNoalias / 1e6,6:F2} Gelem/s   {tManaged / tNoalias,5:F2}x");
            Console.WriteLine($"LLVM -O3 alias   : {tAlias,8:F1} ms   {elems / tAlias / 1e6,6:F2} Gelem/s   {tManaged / tAlias,5:F2}x");
        }

        Kernels.Run();
    }
}
