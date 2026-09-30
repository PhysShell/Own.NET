# ownership-semantics-lab: adoption classification probe (research-only)

Four fixture variants of the frozen RLC# held-out file `Aliases.cs` (resource-effects
Stage 5, digest in Own.NET-paperwork `paper-eval/resource-effects/stage5-heldout-freeze-v1.json`).
No analyzer code changed; the probe decides which gap kind the "field adoption" family has.

| variant | change to the frozen file | purpose |
|---|---|---|
| V0 | none | control (silent: the wrapper is not IDisposable, so `cw` is never a candidate) |
| V1 | `SqlConnectionWrapper : IDisposable` | the wrapper enrolled; production's P-005 D5.4 ctor-adopt (`alias_join`) fires |
| V2 | V1 + ctor body `con.Open();` | non-adopting twin (the rule must decline) |
| V3 | V1 + `if (connection != null) connection.Dispose();` | conditional-dispose twin (the rule must decline) |

Run (R1 environment of `paper-eval/ownership-lab/ab-reference-v1.json`, the System.Data.SqlClient
4.8.6 `ref/netstandard2.0` assembly on `--ref-dir`):

```
dotnet frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll --flow-locals V1.cs --ref-dir <refonly> -o V1.facts.json
python -m ownlang ownir V1.facts.json --format human --severity warning
```

`V*.expected.txt` are the observed outputs (Python engine; Rust identical on every variant).
Record: Own.NET-paperwork `paper-eval/ownership-lab/hard-case-taxonomy-v1.json`
(`classification_probe`). Not a fixture of any production test; never merged to `main`.
