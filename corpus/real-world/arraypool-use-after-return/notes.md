# ArrayPool use-after-return

**Pattern:** a buffer rented from `ArrayPool<T>.Shared` is `Return`ed to the
pool, and then a slice of it is still read. Once returned, the array may be
handed to another renter, so the later read sees torn/foreign data. This is one
of the most common real ArrayPool bugs; it shows up repeatedly in
dotnet/runtime's buffer-pooling code (the BigInteger division/GCD path is the
oft-cited example).

**What the checker says:** the OwnLang model trips **OWN002** (use after
release) — `release` is `ArrayPool.Return`, and `BuildResult(quotient)` reads
the buffer afterwards.

```
$ python -m ownlang check corpus/real-world/arraypool-use-after-return/case.own
case.own:14:14: error: [OWN002] borrow 'quotient' after it was released
 14 |   BuildResult(quotient);              // read after return -> OWN002
                    ^
```

**Honesty / scope.** `case.own` is a *hand reduction* of the C# pattern, not C#
the checker ingested — OwnLang has no C# front-end. It demonstrates that the
ownership *logic* maps onto the real bug: had the code been written in OwnLang,
the checker would have rejected it. The real-world specifics (the division math,
the exact slice bounds) are abstracted to `acquire`/`release`/`borrow`.
`before.cs` / `after.cs` capture the pattern; they are representative, not a
verbatim copy of a single PR.
