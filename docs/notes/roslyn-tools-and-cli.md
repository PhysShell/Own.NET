# `dotnet/roslyn-tools` and the C# extractor CLI — what to borrow, what to avoid

A scoping note, prompted by "could `dotnet/roslyn-tools` give us a ready-made C#
frontend for ownership?" Short answer: **no — it is engineering harness, not an
analysis source.** Recording the verdict so we don't re-open the question.

## Verdict

`dotnet/roslyn-tools` is a grab-bag of *infrastructure* tooling around Roslyn —
its own README is honestly terse ("A set of tools used by Roslyn"), and its
builds live in an Azure package feed. It is **not** a library that "understands
C# for us."

```text
not a source of ownership analysis
a donor of engineering scaffolding (CLI shape, packaging, repo tooling, CI)
```

For actually reading C# the real sources are **`dotnet/roslyn`, the Roslyn SDK,
and the Roslyn APIs** — which is exactly what `OwnSharp.Extractor` already uses.

What's actually in `roslyn-tools` (so nobody has to spelunk again): a zoo of
internal tools — `ModifyVsixManifest`, `SignTool`, `VSIXExpInstaller`,
`RoslynInsertionTool`, `CompilerPerfTests`, `BuildTasks`, `NuGetRepack`,
`RepoToolset`, `ProjectDependencies`, and the `Microsoft.RoslynTools` CLI
(auth, PR finder/tagger, NuGet dependencies/prepare/publish, release tags, VS
branch info, PR validation, insertion/update-insertion). All release/insertion/
signing plumbing — none of it ownership.

## Our seam is already the right one

The architecture in the [README](../../README.md) and
[P-001](../proposals/P-001-csharp-extractor.md) already nails the boundary:

```text
C# (Roslyn) extractor  ->  OwnIR facts JSON  ->  Python Own.Core  ->  diagnostics mapped back to C#
```

The C# side is a **fact extractor, not a second checker**. P-001 v0
(`event += without -=`) already does this: type-aware, project-local
`SemanticModel`, emits OwnIR facts, and the Python bridge runs them through the
*existing* core and maps `OWN001` back onto the C# location. A full C# ownership
frontend (generics / async / interprocedural dataflow) is explicitly rejected as
"human-years." Keep it rejected.

## What to borrow from `roslyn-tools`

1. **CLI-first, shipped as a `dotnet tool`** — not a VSIX, not an analyzer
   package first. The mature tooling repos all start from a CLI:

   ```bash
   ownsharp extract --project MyApp.csproj --out facts.ownir.json
   ownsharp check   --solution MyApp.sln
   ownsharp explain OWN001 --json diagnostic.json
   ```

   Why: easier CI, easier debug, easier golden tests, and no living inside a
   Visual Studio extension before the analysis is even solid. (Use
   `System.CommandLine`, as they do.) IDE squiggles come *later*.

2. **Repo-tooling separation.** Their repo tools live apart from compiler logic;
   we want the same layering so one concern can't break another:

   ```text
   Own.Core            Python checker / OwnIR schema + logic
   OwnSharp.Extractor  C# Roslyn fact extractor
   Own.Cli             orchestration (extract / check / explain)
   Own.Tests           golden facts + expected diagnostics
   Own.Corpus          real-world before/after cases
   ```

   Don't blend Roslyn-walking, OwnIR schema, ownership logic, diagnostic
   rendering, and CI packaging into one pile — that's how "the event-handler
   change broke ArrayPool codegen" becomes a recurring genre.

3. **`ProjectDependencies` as a *category*, not a dependency.** For a future
   DI-lifetime checker and solution-wide scans we'll need the solution/project
   graph (project references, package references, target frameworks, compilation
   references). The v0 WPF event extractor doesn't need it; DI/effects will.

## What NOT to do

- **Don't take `roslyn-tools` as a dependency.** It is an internal tooling repo;
  importing its insertion/release/signing baggage "in case it's useful" is the
  classic way to adopt someone else's enterprise suitcase without a handle.
- **Don't reimplement the checker in C#.** P-001 already says "Do not reimplement
  the checker in C#" — worth carving in stone. The C# frontend's whole job is:

  ```text
  find syntax/semantic facts -> resolve symbols -> get the location -> emit OwnIR
  ```

  It must **not** decide ownership, join states at merges, reason about borrows,
  or otherwise produce an alternative truth. One checker; the C# side feeds it.

## Project/solution input (landed)

The first borrowed plyushka is real: the extractor now accepts a `.csproj` or
`.sln` as input (positional or via `--project` / `--solution`), not just a file
list — the CLI-first project resolution the mature tooling repos start from.

```bash
dotnet run --project frontend/roslyn/OwnSharp.Extractor -- \
  frontend/roslyn/project-input-sample/ProjectInputSample.csproj \
  -o artifacts/facts.ownir.json
python -m ownlang ownir artifacts/facts.ownir.json
# -> CustomerSubscription.cs:11: warning: [OWN001] event 'bus.CustomerChanged'
#    is subscribed (handler 'OnCustomerChanged') but never unsubscribed
```

Resolution is **dependency-free** (text/XML, no MSBuild evaluation): a `.csproj`
maps to its directory's `*.cs` the SDK default-compile-items way plus concrete
linked `<Compile>` files; a `.sln` fans out over its member projects (see
`ProjectCsFiles` / `SolutionProjects` in `Program.cs`). It deliberately stops
short of the full project/package/reference graph — that is the
`ProjectDependencies`-category work, parked for DI/solution scans. A
`wpf-extractor` CI step pins the `.csproj` path to a golden (positional ==
`--project`).

## The `extract` / `check` / `explain` surface (landed)

The advertised three-verb CLI is realised — but split to where the architecture
puts each, not bolted onto one binary (there is one checker; the C# tool only
emits facts):

```bash
ownsharp-extract extract --project App.csproj --out facts.ownir.json   # C# extractor
scripts/own-check.sh --format human -- App.sln                         # `check`: the orchestrator
python -m ownlang explain OWN001                                       # `explain`: the core's catalogue
python -m ownlang explain --json facts.ownir.json                      #   (or every code in a findings/SARIF file)
```

- **`extract`** is an optional leading verb on the C# tool (the bare form stays the
  default), plus `--out` as the long twin of `-o`. The tool's one job.
- **`check`** is *not* a C# verb: `own-check.sh` already chains the extractor and the
  core, and since the project/solution PR it takes a `.csproj`/`.sln` directly.
  Re-implementing a checker in C# is the rejected path.
- **`explain`** lives in the core next to the diagnostic catalogue
  (`ownlang/diagnostics.py`: `TITLES` + `EXPLANATIONS`): it prints what a code means,
  why it fires, and how to fix it; `--json` harvests every code from a findings/SARIF
  file so you can explain exactly what a run produced.

A `System.CommandLine` migration of the C# tool (auto `--help`, validation) and
`--ref-dir`-from-project-`bin` auto-derivation remain the next polish — deferred over
a blind framework swap, since the extractor builds only in CI here.

## Earlier next-PR sketch (kept for the record)

```bash
ownsharp extract --project App.csproj --out facts.ownir.json
ownsharp check   --solution App.sln
ownsharp explain OWN001 --json diagnostic.json
```

A facts record carries enough to place and explain the finding — kind, resource,
owner, subject, location, and domain-neutral metadata:

```json
{
  "ownir_version": 0,
  "source": "CustomerViewModel.cs",
  "facts": [
    {
      "kind": "acquire",
      "resource": "subscription",
      "owner": "this",
      "subject": "bus.CustomerChanged",
      "location": { "file": "CustomerViewModel.cs", "line": 9, "column": 13 },
      "metadata": { "handler": "OnCustomerChanged", "resource_kind": "subscription token" }
    }
  ]
}
```

This already works conceptually (`tests/test_ownir.py` exercises the bridge on
hand-written facts); the work is hardening the CLI/contract/golden.

## WPF track priorities (once the CLI is solid)

```text
1. event += without -=        v0; drive to an iron golden
2. DispatcherTimer            Tick += / Start  =>  Stop + Tick -=
3. IDisposable fields         an owned field must be disposed by the owner's Dispose
4. Subscribe() -> IDisposable an ignored token => leak
5. region/lifetime facts      App > Window > ViewModel  =>  OWN014
```

The `ArrayPool`/`Span` storage track lives alongside this, not blocking it. One
pattern, one facts schema, one golden, one CI step at a time — then the next
pattern.

## Where `roslyn-tools` *does* help later

`dotnet tool` packaging, build/release automation, VSIX packaging (if an IDE
extension ever happens), repo-wide validation, perf-testing style, and CI
conventions. Useful as a *worked example* of the engineering layer — not as a
source of the analysis.
