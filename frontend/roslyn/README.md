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

## Use it on a real repo / in CI (P-013)

The two stages are chained by one orchestrator script, so you don't run them by
hand. It scans a directory (recursively, skipping `bin`/`obj`/generated files):

```bash
# from an Own.NET checkout, scan another repo's C#:
scripts/own-check.sh --format human -- /path/to/some/csharp/repo
scripts/own-check.sh --format msbuild -- .        # VS Error List format
scripts/own-check.sh --fail-on-finding -- src/     # non-zero exit on a leak
```

`--format` is the core's surface selector (the renderer lives in
`ownlang/ownir.py`, not here — one checker):

- `human` — the CLI line (default);
- `github` — `::error file=…,line=…::…` annotations on the PR diff;
- `msbuild` — `file(line): error OWN001: …`, which `dotnet build` and the
  Visual Studio Error List parse, so findings surface in-IDE with no analyzer.

**GitHub Action.** A composite action (`action.yml`) wraps the same script. A
consumer repo adds (see `examples/ci/own-check.yml`):

```yaml
- uses: actions/checkout@v4
- uses: PhysShell/own.net@main
  with: { path: ., format: github, fail-on-finding: "true" }
```

**`dotnet tool`.** The extractor alone is packable
(`dotnet pack` → `dotnet tool install --global OwnSharp.Extractor` →
`ownsharp-extract`). It emits facts only; the verdict still comes from the
Python core, so the script/Action are the complete product.

Why CI/CLI and not a native Roslyn analyzer: a true `DiagnosticAnalyzer` runs
in-process and would force a *second* checker in C# (or shelling out to Python
per keystroke) — a conflict with "one checker", not just effort. See
[P-013](../../docs/proposals/P-013-distribution-surface.md).

**Step-by-step usage** (terminal, Visual Studio Error List, CI) lives in
[`docs/howto-visual-studio.md`](../../docs/howto-visual-studio.md).

## Scope / honesty

This sandbox has no local `dotnet`, so the extractor is built and run only in CI
(the `wpf-extractor` job); the Python bridge + core are tested locally
(`tests/test_ownir.py`) against hand-written facts. The heuristic (RHS is a
method group) and non-goals (XAML, timers, IDisposable fields, semantic event
resolution) are tracked in the proposal.
