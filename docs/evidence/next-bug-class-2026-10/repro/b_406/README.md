`Capture.cs`: the #406 shapes. Run from the repository root:

```bash
dotnet run --project frontend/roslyn/OwnSharp.Extractor -- docs/evidence/next-bug-class-2026-10/repro/b_406 -o /tmp/b406.json --flow-locals
PYTHONPATH=. python -m ownlang ownir /tmp/b406.json --severity warning
```

Observed on `2fefb19f`: only `plain` (no lambda) reports OWN001; `LeakSyncLambda` and `LeakLocalFunction` are silent
(the capture-is-escape rule, `Program.cs` "capturedInClosure"); `ForEachAsync` (ShareX control) is silent.
