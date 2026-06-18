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

Leak `#2` is the agreement that proves the RAII oracles ran on the fixture; `#1` is
the differentiator — Own.NET flags it, CodeQL / Infer# have no query for the
subscription-leak class. #3 is the recall slice: before `try`/`finally` was lowered,
Own.NET skipped any method containing a `try`, so this leak was *Oracle only*; now it
joins #2 in **Agree** across all three tools.

Run via the oracle's local-fixture mode — set `corpus/oracle-target.txt` to:

```
local:corpus/fixtures/systemevents-console
build=SystemEventsLeak.csproj
```

The `local:` target (copied into the oracle's `target/` instead of cloned) and the
sentinel are dev-loop scaffolding, like the rest of the oracle push path — not for
`main`.
