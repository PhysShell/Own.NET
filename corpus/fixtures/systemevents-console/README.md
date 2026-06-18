# Cross-tool oracle fixture — SystemEvents subscription leak (Linux-buildable)

A minimal `net8.0` console app reproducing **two leak classes**, so the oracle
(`oracle.yml`) can run all three tools — Own.NET, CodeQL **and Infer#** — over the
same code. ScreenToGif (the real finding) is WPF and does not `dotnet build` on the
Linux oracle runner, so Infer# was skipped there; this fixture builds on Linux, so
Infer# runs and the cross-tool picture is complete.

The leaks (`Program.cs`):

| # | leak | class | expected to flag |
|---|------|-------|------------------|
| 1 | `SystemEvents.DisplaySettingsChanged += …`, never `-=` | subscription / lifetime | **Own.NET only** |
| 2 | `new FileStream(…)` local, never disposed | Dispose / RAII | **all three** (the control) |
| 3 | `new FileStream(…)` never disposed, inside a `try`-method | Dispose / RAII | **all three** (closed by `try`-lowering) |
| 4 | `Dispose()` inside `try` after a may-throw call (skipped on the throw path) | Dispose-on-throw | **all three** (exception-edge slice) |

Leak `#2` is the agreement that proves the RAII oracles ran on the fixture; `#1` is
the differentiator — Own.NET flags it, CodeQL / Infer# have no query for the
subscription-leak class. #3 is the `try`-lowering recall slice: before `try`/`finally`
was lowered, Own.NET skipped any method containing a `try`, so this leak was *Oracle
only*; now it joins #2 in **Agree** across all three tools.

#4 is the **exception-edge** slice. The stream *is* disposed, but the `Dispose()` sits
inside the `try` after a may-throw call, so it's skipped if the call throws — a leak only
on the exceptional path. CodeQL has a dedicated query for this (`cs/dispose-not-called-on-throw`;
`cs/local-not-disposed` also models exceptional flow) and Infer#'s Pulse engine models
exceptional paths too. Own.NET used to miss it (disposed *somewhere* looked balanced)
until the exception-edge model inserted a throw edge before each may-throw statement in a
`try`; it now flags it too, so #4 joins #2/#3 in **Agree** across all three.

One wrinkle worth recording: the three tools anchor this leak at *different* program
points — Own.NET at the acquire, CodeQL at the `Dispose()` call, Infer# at the last
access — so a spread-out method puts them >3 lines apart and the oracle's ±3 line window
splits one leak into "Own.NET only" + "Oracle only". Keeping the `try` a one-liner (as
`LeakInTry` already is) pulls the anchors back within the window so the agreement is
visible. The line window is intentionally conservative; this is a property of the
*comparison*, not of the detections.

Run via the oracle's local-fixture mode — set `corpus/oracle-target.txt` to:

```
local:corpus/fixtures/systemevents-console
build=SystemEventsLeak.csproj
```

The `local:` target (copied into the oracle's `target/` instead of cloned) and the
sentinel are dev-loop scaffolding, like the rest of the oracle push path — not for
`main`.
