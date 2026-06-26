// AFTER (fixed) — NethermindEth/nethermind#9322. The rented buffer is returned in
// a `finally` block, so it goes back to the pool even when GetNew throws. No leak.
using System;
using System.Buffers;

namespace Corpus
{
    internal sealed class PatriciaTree
    {
        public byte[] Get(ReadOnlySpan<byte> rawKey)
        {
            int nibblesCount = 2 * rawKey.Length;
            byte[] array = ArrayPool<byte>.Shared.Rent(nibblesCount);
            try
            {
                return GetNew(array);                  // may throw — buffer still returned below
            }
            finally
            {
                ArrayPool<byte>.Shared.Return(array);  // returned on every path, throw included
            }
        }

        private static byte[] GetNew(byte[] nibbles) => throw new TrieException();
    }

    internal sealed class TrieException : Exception { }
}
