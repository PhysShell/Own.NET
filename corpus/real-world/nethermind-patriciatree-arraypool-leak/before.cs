// BEFORE (buggy). Reduction of NethermindEth/nethermind#9322 — an ArrayPool
// buffer leak in Nethermind.Trie/PatriciaTree.cs `Get` / `GetNodeByKey` (fixed in
// Nethermind v1.35.0). For keys longer than the 64-byte stackalloc minimum the
// methods Rent a byte[] from ArrayPool<byte>.Shared. The `Return` sat INSIDE the
// try, after the may-throw `GetNew`, so a thrown TrieException skipped it and
// leaked the rented buffer — gradual memory pressure under sustained RPC load with
// long keys. The fix moves the `Return` into a `finally` block (see after.cs).
//
// The Return is inside the `try` (after the may-throw call) on purpose: that is the
// real structure the PR fixed, and it is what the extractor's default throw-edge
// model (a throw exit before each may-throw leaf in a try, `--flow-locals`) sees.
// Reduced + helpers stubbed so the file is self-contained.
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
            try
            {
                byte[] result = GetNew(array);                         // can throw TrieException
                ArrayPool<byte>.Shared.Return(array);                  // in the try -> skipped on throw -> LEAK
                return result;
            }
            catch (TrieException)
            {
                throw;                                                 // buffer NOT returned on this path
            }
        }

        private static byte[] GetNew(byte[] nibbles) => throw new TrieException();
    }

    internal sealed class TrieException : Exception { }
}
