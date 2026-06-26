// BEFORE (buggy). Reduction of NethermindEth/nethermind#9322 — an ArrayPool
// buffer leak in Nethermind.Trie/PatriciaTree.cs `Get` / `GetNodeByKey` (fixed in
// Nethermind v1.35.0). For keys longer than the 64-byte stackalloc minimum the
// methods Rent a byte[] from ArrayPool<byte>.Shared, then call GetNew (which can
// throw TrieException) and Return the buffer only on the success path. A thrown
// TrieException skips the Return and leaks the rented buffer — gradual memory
// pressure under sustained RPC load with long keys.
//
// Reduced + helpers stubbed so the file is self-contained; representative of the
// pattern, not a verbatim copy of the PR diff.
using System;
using System.Buffers;

namespace Corpus
{
    internal sealed class PatriciaTree
    {
        public byte[] Get(ReadOnlySpan<byte> rawKey)
        {
            int nibblesCount = 2 * rawKey.Length;
            byte[] array = ArrayPool<byte>.Shared.Rent(nibblesCount);   // Rent (long key)
            byte[] result = GetNew(array);                             // can throw TrieException
            ArrayPool<byte>.Shared.Return(array);                      // never reached if GetNew threw -> leak
            return result;
        }

        private static byte[] GetNew(byte[] nibbles) => throw new TrieException();
    }

    internal sealed class TrieException : Exception { }
}
