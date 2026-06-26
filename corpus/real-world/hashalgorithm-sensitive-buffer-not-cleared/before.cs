// BEFORE (buggy). Reduction of the sensitive-data aspect of dotnet/runtime#71249 —
// System.Security.Cryptography.HashAlgorithm rents an ArrayPool buffer to stage the
// bytes being hashed, then Returns it with `clearArray: false`, leaving the
// (sensitive) input in the pooled array for the next renter to read — an information
// disclosure. (#71249 also flags the exception/cancellation *leak* on the same path;
// this case models the not-zeroed aspect.) The fix returns with `clearArray: true` /
// CryptographicOperations.ZeroMemory. Reduced + helpers stubbed; not verbatim.
using System.Buffers;
using System.IO;

namespace Corpus
{
    internal static class HashAlgorithmCore
    {
        public static byte[] ComputeHash(Stream source)
        {
            byte[] rented = ArrayPool<byte>.Shared.Rent(4096);          // stages sensitive input
            int read = source.Read(rented, 0, rented.Length);
            byte[] hash = Hash(rented, read);
            ArrayPool<byte>.Shared.Return(rented, clearArray: false);   // <-- secret bytes NOT zeroed
            return hash;
        }

        private static byte[] Hash(byte[] data, int length) => new byte[32];
    }
}
