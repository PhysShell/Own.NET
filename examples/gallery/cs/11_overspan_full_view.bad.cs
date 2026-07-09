using System;
using System.Buffers;

namespace GalleryCs;

// 11_overspan_full_view (bad) — C#-native mirror of
// examples/gallery/11_overspan_full_view.own: OWN025, a full-length view of a
// pooled buffer reaching past its logical (rented) length. Real C#:
// ArrayPool<T>.Rent(n) returns an OVERSIZED array (Length >= n); an unbounded
// buf.AsSpan() reads the stale [n, Length) tail a previous renter left behind.
// Reduced from the same pattern as corpus/real-world/arraypool-fullspan-overread/.
public static class OverspanFullView
{
    public static void Frame(int n)
    {
        byte[] galleryOverspanBuf = ArrayPool<byte>.Shared.Rent(n);
        Fill(galleryOverspanBuf, n);
        Emit(galleryOverspanBuf.AsSpan()); // full-length view -> OWN025
        ArrayPool<byte>.Shared.Return(galleryOverspanBuf);
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
