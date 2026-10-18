Built-in .NET analyzers (`AnalysisMode=All`, SDK 10.0.401) over the three #400 shapes.

```bash
bash ../c_runtime_dictionary/fetch.sh && cp ../c_runtime_dictionary/BuggyMeziantou.cs .
dotnet build -c Release --no-incremental -v:minimal
```

Observed: two CA1062 (argument null check) in the Meziantou file and nothing else; no rule fires on the
dictionary-ref, MAUI-shape or `AsSpan` patterns. `BuggyMeziantou.cs` is downloaded, not committed.
