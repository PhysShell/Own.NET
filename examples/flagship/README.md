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

## The same bug where it actually lives (`wpf/`)

The console pair is the shape stripped to its bones. `wpf/` is that shape in
its native habitat: a `DocumentWindow` subscribed to the settings hub in its
constructor, an unsubscribe behind `Cleanup(keepAlive)`, and a `Closed`
handler that passes `true`. Every closed window — its whole visual tree — is
retained by the hub's delegate list.

```
dotnet run --project examples/flagship/wpf/bad      (Windows)
  → opened and closed 200 document windows; 200 still subscribed — every one
    of them, with its whole visual tree, is retained by the static settings hub.

owen check examples/flagship/wpf/bad --fail-on-finding
  → OWN001 … DocumentWindow … (exit 1)
```

The fix (`wpf/ok/`) moves the release into `OnClosed` — the method WPF itself
calls at the end of a window's life — unconditionally. Same windows, same
subscription; the count goes to zero.

Note what is and is not platform-bound. **Analysis is not**: the subscription
binds through `System.ComponentModel` and the release is recognised by
teardown name, so `owen check` reaches the same verdict on Linux, macOS and
Windows, and the projects themselves compile anywhere
(`EnableWindowsTargeting`). Only **running** the sample needs Windows, which
is where CI attaches the runtime witness and requires it to name the path:

```
AppSettings → PropertyChanged → _invocationList → handler → DocumentWindow
```

The `ok` side is held to the claim the fix actually makes — the hub retains
nothing — rather than to "the heap is empty": WPF's own focus and input
statics may legitimately hold the last closed window, and calling that our
leak would be the same overreach Owen refuses everywhere else.

### Holding a sample for a witness

Both pairs support `OWEN_FLAGSHIP_HOLD=1`, which parks the process after the
work is done and prints `holding (pid N)`. Release it by sending a line on
stdin (what `scripts/flagship-demo.sh` does through a FIFO) or, when stdin is
not a console — every CI runner — by setting `OWEN_FLAGSHIP_STOP=<path>` and
creating that file. Either way the hold is bounded by
`OWEN_FLAGSHIP_HOLD_SECONDS` (default 300), so a forgotten sample cannot
outlive its job.
