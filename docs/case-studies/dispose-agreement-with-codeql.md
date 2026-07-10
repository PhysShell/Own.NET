# Case study: where Own.NET agrees with CodeQL (and Infer#)

The other two case studies ([`VideoSource`](screentogif-videosource.md),
[`SystemEvents`](screentogif-systemevents.md)) are about the defect class Own.NET
finds that Dispose/RAII checkers structurally cannot. This one is the other
half of an honest positioning: proof that on the class those checkers *do*
cover, Own.NET's verdict lines up with theirs — not just argued, but run
side-by-side through the cross-tool oracle
([`docs/notes/oracle.md`](../notes/oracle.md)) and pinned as a regression fixture.

ScreenToGif itself is WPF and doesn't `dotnet build` on the Linux oracle
runner, so Infer# can't run against it there. The fixture below
(`corpus/fixtures/systemevents-console/`) is a small `net8.0` console program,
Linux-buildable, that reproduces the same leak classes so all three tools —
Own.NET, CodeQL, **and** Infer# — run over identical code.

## Bad

```csharp
private static void LeakAFile()
{
    var stream = new FileStream("scratch.bin", FileMode.Create);
    stream.WriteByte(0x42);
    // ...no Dispose()/using -> resource leak
}
```

A local `FileStream`, never disposed, never wrapped in `using`. The plainest
possible Dispose/RAII leak — deliberately plain, because its job in this
fixture is to be the **control**: if all three tools don't flag it, the
comparison itself is broken, not informative.

## Fixed

```csharp
private static void LeakAFile()
{
    using var stream = new FileStream("scratch.bin", FileMode.Create);
    stream.WriteByte(0x42);
}
```

## What others miss (here: nothing — that's the point)

| Finding (`Program.cs`) | class | Own.NET | CodeQL | Infer# |
|---|---|:-:|:-:|:-:|
| `:43` `new FileStream(…)` never disposed | Dispose/RAII (control) | ✓ | ✓ | ✓ |
| `:54` undisposed local inside a `try`-method | Dispose/RAII (`try`-lowering) | ✓ | ✓ | ✓ |
| `:77` `Dispose()` in `try`, skipped on the throw path | dispose-on-throw (exception-edge) | ✓ | ✓ | ✓ |
| `:20` `SystemEvents.DisplaySettingsChanged +=`, never `-=` | subscription | ✓ | — | — |

The first three rows are **Agree** across all three tools — CodeQL via
`cs/local-not-disposed` (and, for the third row, `cs/dispose-not-called-on-throw`),
Infer# via Pulse. The fourth row is the same differentiation the other two case
studies make: Own.NET flags the subscription leak, and **neither CodeQL nor
Infer# has an equivalent query** — not "they missed it," they don't model the
defect class at all.

The middle two rows are not filler: they mark recall Own.NET didn't always
have. Before `try`/`finally` lowering, a method containing a `try` was skipped
entirely, so row `:54` used to be oracle-only (CodeQL/Infer# caught it, Own.NET
didn't). Before the exception-edge model, a resource disposed *somewhere* in
the method looked balanced, so row `:77` — disposed on the normal path, leaked
on the exceptional one — was also invisible to Own.NET. Both are now closed and
both land in the CI-pinned `Agree` bucket, matching CodeQL's dedicated
`cs/dispose-not-called-on-throw` query on the third row specifically.

## How Own reports it

```text
Program.cs:43: error: [OWN001] 'stream' is owned but not released at end of
  function (leaks on at least one path)
Program.cs:54: error: [OWN001] 'tried' is owned but not released at end of
  function (leaks on at least one path)
Program.cs:77: error: [OWN001] 'onThrow' is owned but not released on the
  exceptional path (disposed on the normal path only)
Program.cs:20: error: [OWN001] event 'SystemEvents.DisplaySettingsChanged' is
  subscribed (handler 'OnDisplayChanged') but never unsubscribed — the source
  keeps 'DisplayWatcher' alive (leak) [resource: subscription token]
```

Same core, same `OWN001` code, for two structurally different defect classes
(a plain leaked handle vs. an unreleased event subscription) — the `[resource:
...]` tag is what a later profile/front-end would use to phrase them
differently, not a second checker.

Fixture: `corpus/fixtures/systemevents-console/` (`Program.cs` + its own
[README](../../corpus/fixtures/systemevents-console/README.md) with the full
expected 2×2), exercised by `oracle.yml`'s local-fixture mode.
