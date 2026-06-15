# OwnSharp Roslyn extractor (P-001 v0)

The C# half of the [P-001](../../docs/proposals/P-001-csharp-extractor.md)
pipeline: scan **real C#** and emit OwnIR facts that the existing Python core
checks.

```text
*.cs --[OwnSharp.Extractor (Roslyn)]--> facts.json --[python -m ownlang ownir]--> OWN001 @ C# location
```

## What it does (v0)

Syntax-only (no compilation, no references): finds `target += handler` event
subscriptions and marks each `released` iff a matching `target -= handler` exists
in the same class. Exactly the `event += without -=` leak pattern. The verdict
(OWN001) comes from the core, not from here — there is one checker, not two.

## Run

```bash
dotnet run --project OwnSharp.Extractor -- samples/CustomerViewModel.cs samples/OrdersViewModel.cs -o facts.json
python -m ownlang ownir facts.json
# -> CustomerViewModel.cs:9: error: [OWN001] event 'bus.CustomerChanged' ... (leak)
#    (OrdersViewModel unsubscribes in Dispose -> nothing reported)
```

## Scope / honesty

This sandbox has no local `dotnet`, so the extractor is built and run only in CI
(the `wpf-extractor` job); the Python bridge + core are tested locally
(`tests/test_ownir.py`) against hand-written facts. The heuristic (RHS is a
method group) and non-goals (XAML, timers, IDisposable fields, semantic event
resolution) are tracked in the proposal.
