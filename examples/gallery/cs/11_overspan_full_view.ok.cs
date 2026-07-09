using System;
using System.Buffers;

namespace GalleryCs;

// 11_overspan_full_view (fixed) — the view is BOUNDED to the logical length,
// buf.AsSpan(0, n); the oversized [n, Length) tail is never read -> silent.
public static class OverspanFullViewOk
{
    public static void Frame(int n)
    {
        byte[] galleryOverspanOkBuf = ArrayPool<byte>.Shared.Rent(n);
        Fill(galleryOverspanOkBuf, n);
        Emit(galleryOverspanOkBuf.AsSpan(0, n)); // bounded view: only the logical [0, n)
        ArrayPool<byte>.Shared.Return(galleryOverspanOkBuf);
    }

    private static void Fill(byte[] b, int n)
    {
        for (int i = 0; i < n; i++)
        {
            b[i] = (byte)i;
        }
    }

    private static void Emit(ReadOnlySpan<byte> data) { }
}
