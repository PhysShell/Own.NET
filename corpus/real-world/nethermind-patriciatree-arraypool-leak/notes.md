# Nethermind PatriciaTree ArrayPool leak (leak on the exception path)

**Source.** [NethermindEth/nethermind#9322](https://github.com/NethermindEth/nethermind/pull/9322),
fixed in Nethermind **v1.35.0**. File `src/Nethermind/Nethermind.Trie/PatriciaTree.cs`,
methods `Get` / `GetNodeByKey`. (A replay target named in
[P-007](../../../docs/proposals/P-007-arraypool-span.md): *Nethermind ArrayPool leaks*.)

**Pattern.** For keys longer than the 64-byte `stackalloc` minimum the methods
`Rent` a `byte[]` from `ArrayPool<byte>.Shared`, then call `GetNew`, which can
throw `TrieException`. The buffer was `Return`ed only on the success path (after
the call), so a thrown `TrieException` skipped the `Return` and **leaked** the
rented buffer — gradual memory pressure under sustained RPC load with long keys.
The fix moves the `Return` into a `finally` block (`after.cs`).

**What the checker says.** The OwnLang reduction trips **OWN001** (owned resource
not released on all paths): `acquire` is `ArrayPool.Rent`, `release` is `.Return`,
and the `throw` path is modeled as an early `return` arm that exits before the
`release`.

```text
$ python -m ownlang check corpus/real-world/nethermind-patriciatree-arraypool-leak/case.own
case.own:12: error: [OWN001] 'array' is owned but not released before return (leaks on at least one path)
```

**Honesty / scope.** `case.own` is a *hand reduction* of the C# pattern, not direct
extractor output. The uncaught C# `throw` on `GetNew`'s `TrieException` is modeled
as an early `return` arm — a path that exits before cleanup, which is exactly what
an uncaught throw is. End to end, the real `before.cs` is caught by the
exception-edge flow detector (`--flow-locals`, which injects a throw exit before
each may-throw leaf), and the `finally` of `after.cs` is silent — both scored by
`scripts/benchmark.py` in the `corpus-benchmark` CI job. `before.cs` / `after.cs`
are reduced (helpers stubbed), not a verbatim copy of the PR diff.
