// AFTER (fixed) — dotnet/runtime#71249. The pooled buffer holding the sensitive input
// is zeroed on return (`clearArray: true`, equivalent to CryptographicOperations.
// ZeroMemory) and returned in a `finally`, so no secret bytes survive in the pool and
// the buffer is returned even if Read/Hash throws.
using System.Buffers;
using System.IO;

namespace Corpus
{
    internal static class HashAlgorithmCore
    {
        public static byte[] ComputeHash(Stream source)
        {
            byte[] rented = ArrayPool<byte>.Shared.Rent(4096);
            try
            {
                int read = source.Read(rented, 0, rented.Length);
                return Hash(rented, read);
            }
            finally
            {
                ArrayPool<byte>.Shared.Return(rented, clearArray: true);   // zeroed on every path
            }
        }

        private static byte[] Hash(byte[] data, int length) => new byte[32];
    }
}
