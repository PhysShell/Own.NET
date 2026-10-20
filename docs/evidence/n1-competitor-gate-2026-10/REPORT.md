# N1 competitor gate — report

**Result: `GO-CANDIDATE-N1`.** This is a decision for the owner, not a GO on an N1 PoC.

| Pair | Verdict | What CA2000 (`AllPaths`) does |
|---|---|---|
| W, whizbang#1204 | CAUGHT | reports the buggy `new ServiceBusClient(…)` in K2–K4; silent on the fix |
| R, rockbot#638 | MISSED | does not track `await McpClient.CreateAsync(…)` |
| X, NexusKit#34 | MISSED | does not track `services.BuildServiceProvider(…)` |
| B, BareWire#73 | MISSED | does not track `await _connection.CreateChannelAsync(…)` |

So 3 of 4 pairs are missed by every configuration (K1–K5) of all three analyzers: CA2000, IDisposableAnalyzers
4.0.8 and Sonar 10.35. In run 2, none of the three analyzers reports anything on the R, X or B acquisition lines.

Rules: [`00-preregistration.md`](00-preregistration.md), committed in `d06caf75` before any analyzer run. Time used:
21:11–21:20 +05 on 2026-10-20 for the scored work, inside the 0.25 agent-day budget.

No third-party project was built and no package was downloaded. The analyzers came from the SDK and the local NuGet
cache. Every build ran from a copy in the session scratch directory, with a nuget.org-only config and no
`PackageReference`.

## 1. Runs, in order (runs 1 and 2 kept in `data/`; run 0's output was overwritten and is not kept)

| Run | What changed | Result |
|---|---|---|
| 0 | first build | 0 diagnostics matched, because of a bug in my SARIF reader: csc wrote SARIF 1.0 and the reader expected 2.1. Not a result; the reader was fixed. No rule changed |
| 1 (`run1_stubs_in_compilation.tsv`) | reader fixed | control valid; W CAUGHT; R, X, B silent |
| 2 (`run2_scored.tsv`) | **scored run**: the stubs moved into a separate referenced assembly (§2) | control valid; W CAUGHT; R, X, B MISSED |

The harness control was valid in both runs 1 and 2:
- `new StreamReader` followed by an opaque throwing call and `Dispose` is reported under K2–K5 and silent under K1;
- the same with `using` is silent everywhere.

## 2. Fidelity correction before scoring (disclosed)

The pre-registration requires every MISSED to be checked for a reproduction deviation. The first check found one.

In run 1, the stubs were in the analysed compilation. `McpClient.CreateAsync` is a stub whose body is `throw`, and
CA2000's interprocedural analysis can read that body.

The real types (`ServiceBusClient`, `McpClient`, `IChannel`) live in external packages whose bodies the analyzer
does not see. Run 2 therefore compiles the stubs as their own assembly (`stubs/`), referenced by the reproductions.
The reproductions and the rules did not change. The verdicts were the same in both runs.

## 3. Why R, X and B are missed: analyzer limits, not reproduction artifacts

The probes are not scored (`probes/`, `data/probes_opaque_step.tsv`, `data/ablation_and_probes.tsv`). Each one has
the same leak: acquire a disposable, make an **opaque** throwing call through an interface, then dispose or hand it
over. Only the acquisition form changes.

A first probe set used empty local `MayThrow` methods. CA2000 proved that those cannot throw and stayed silent, so
the set was invalid; its output was overwritten and is not kept. It was redone with interface calls, which is how
the reproductions throw.

| Acquisition form (K2, `AllPaths`) | Tracked? |
|---|---|
| `new T(…)`; an in-source sync or async factory; `File.OpenText`; an external static sync factory (P10, P12) | yes |
| `new T(…)` then store in a dictionary, wrap and return, return, or inside an `async` iterator (P5–P8) | yes |
| **await of an external async factory** (P11), the shape of R and B | **no** |
| **result of an interface method** (P13), the shape of B (`IConnection.CreateChannelAsync`) | **no** |
| **`ServiceCollection.BuildServiceProvider()`** (P9), the shape of X; the real M.E.DI type | **no**, even in a three-line method; the reason was not established |

The ablation of each MISSED reproduction (`probes/Ablation.cs`) found no other feature that silences the analyzer:
- removing the catch-all retry loop (R) leaves it silent;
- removing the resolve calls (X) leaves it silent;
- removing the iterator, or swapping the interface for a class (B), leaves it silent.

The acquisition form alone decides. In all three pairs that form is the real code's own API, so the MISSEDs stand
and none is `UNRESOLVED`.

## 4. What this does and does not show

Confirmed:
- CA2000 with `AllPaths` is the documented tool for this class, and it does catch the `new`-acquired case (W).
- For the acquisition forms that are common in modern async .NET, it reports nothing on these reproductions:
  awaited async factories, interface factory methods and `BuildServiceProvider`.
- IDisposableAnalyzers and Sonar report nothing on any of the four acquisition lines. Inference, not measured: they
  accept a return or store as a hand-over and do not model the exception path before it.

Not shown:
- **No real build was run.** The verdicts come from faithful reproductions of the methods with stub third-party
  types, not from building the four repositories. CA2000 on the real repositories could differ if a real package
  type carries attributes or annotations that the stubs lack.
- **Only the options in the pre-registration were tested.** `interprocedural_analysis_kind` and
  `excluded_symbol_names` were not varied.
- W's fixed version is silent partly because the fix acquires through a `Func<…>` seam that CA2000 does not
  track. A `new` + `try`/`catch` fix was not tested.
- That Own.NET can do better is not shown. Phase 0 recorded that Own.NET tracks only non-escaping `new` locals and
  missed 3/3 here. A detector for factory-acquired and awaited acquisitions would be new work.
- Mature-code yield and precision of such a detector are unknown. This gate measured only competitor coverage.

## 5. Files

- [`00-preregistration.md`](00-preregistration.md)
- [`repro/`](repro/): W, R, X, B buggy/fixed reproductions, `Control.cs` and `N1Repro.csproj`.
- [`stubs/`](stubs/): the third-party stand-ins, built as a separate assembly.
- [`probes/`](probes/): explanatory probes and ablation. `ProbeExternals.cs` goes into the stub assembly for the
  ablation run only.
- [`scripts/run_gate.py`](scripts/run_gate.py): builds K1–K5 and collects the diagnostics on each acquisition line.
- `data/`: outputs of run 1, run 2 and the probes.
