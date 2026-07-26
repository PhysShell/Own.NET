# The flagship leak — "a `-=` exists" is not "a `-=` runs"

The one-case demo of what Owen catches that ordinary cleanup matching misses.
Distilled from a real, heap-proven production leak (issue #278: a formally
present unsubscribe behind a parameter guard nobody ever passed `false` to —
66% of the process heap retained), reduced to ~80 cross-platform console
lines.

## The bug (`console/bad/`)

A static, process-lifetime publisher; a view subscribed in its constructor;
an unsubscribe that *exists* but sits behind `if (!keepAlive)` — and every
close path calls `Cleanup(keepAlive: true)`. The `-=` never runs; every
closed view stays pinned to the publisher forever.

```
dotnet run --project examples/flagship/console/bad
  → opened and closed 1000 views; 1000 still subscribed — every one of them
    is retained by the static publisher.

owen check examples/flagship/console/bad --fail-on-finding
  → OWN001 … subscribed but never provably unsubscribed   (exit 1)
```

A checker that pairs `+=` with any `-=` in the class calls this clean. Owen
demands the release be *provable*: a parameter-guarded `-=` in a non-teardown
method is not evidence (the corpus pins this predicate family —
`corpus/wpf/subscription-teardown-early-return-guard` and friends).

## The fix (`console/ok/`)

Move the release where it provably runs: `Dispose()`, unconditionally, called
on every close path.

```
dotnet run --project examples/flagship/console/ok
  → opened and closed 1000 views; 0 still subscribed.

owen check examples/flagship/console/ok --fail-on-finding
  → exit 0
```

Same publisher, same subscription, same handler — the only change is that
teardown became a teardown. The static finding disappears *and* the runtime
count goes to zero: the two halves of the same evidence.

Both variants are smoke-checked in CI (gate A) against the installed
`Owen.Cli` on Linux and Windows: `bad` must exit 1 with OWN001, `ok` must
exit 0.
