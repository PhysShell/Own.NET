# Owen in the IDE: E1 and E2 feasibility (OX-01, P9 and P10)

This is a kill-first report, not a product. Nothing here ships. The shipped path in OX-01 is
the **build host**:
- `Owen.Build` runs Owen on every `dotnet build`;
- its findings are canonical MSBuild diagnostics;
- Visual Studio puts canonical MSBuild diagnostics in the Error List on build, with file and line navigation (spec/OwenExtension.md).

The question here is the next step: **live** diagnostics while typing.

## The architecture invariant (from the clang-tidy model)

One authoritative external analyzer and thin adapters. Concretely:
- **An extension is not an IDE plugin.** There is no `Owen.TypedBuilder.VisualStudio`, no `Owen.Memory.VisualStudio`.
- **At most one `Owen.VisualStudio`,** serving every active extension from the manifest the build host already writes (`obj/owen/extensions.json`).
- **At most one Owen diagnostic/language server.**
- **Every adapter reads findings produced by the one Rust core.** None re-derives a verdict in C# or TypeScript (owen-diagnostics-model.md).

clang-tidy's integration code is not copied; only the shape is borrowed.

## E1: a generic VSIX host (`IErrorTag` + `ITableDataSource` + a long-lived Owen process)

**Update (OX-02): executed and shipped as `Owen.VisualStudio`; see owen-visual-studio-report.md
(GO). The two blockers below were solved by the in-process extractor with an overlay and by
`owen serve`.**

**Verdict at OX-01: NOT EXECUTED in this environment.** The session runs on Linux with no Windows
and no Visual Studio, so a VSIX cannot be built, deployed to an experimental instance or
observed. Nothing below is measured. It is the specification of the spike, plus the two
blockers already visible from the code.

**The acceptance the spike must meet** (as registered):
1. an unsaved C# buffer;
2. an OWN diagnostic;
3. a squiggle (`IErrorTag`);
4. an Error List entry (`ITableDataSource`);
5. navigation to it;
6. delete the offending line, and the diagnostic disappears.

**Blockers found by reading the code; both must be solved before E1 can pass:**
1. **Unsaved buffers.**
   - **The gap:** the extractor reads **files** (`OwnSharp.Extractor/Program.cs::Expand`), and an unsaved buffer is not a file. Live diagnostics need an overlay input, "this path, these contents", or an in-memory workspace.
   - **Scope:** this is frontend work, not core semantics, and it is the precondition of any live host, E1 and E2 alike.
2. **Latency.**
   - **The cost today:** one `owen check` spawns the extractor, compiles the project with Roslyn and runs the core: seconds per project. The build host pays that once per build, which is acceptable. A host that runs on every keystroke cannot.
   - **What E1 implies:** a **long-lived** Owen process with an incremental extractor, which does not exist today.
   - **What Snipper shows** (owen-extension-snipper-salvage.md): its long-lived process lifecycle is the part to **reject**. Stderr is lost, crashes are unwatched, and orphans are not prevented. A future host needs a lifecycle written for this, not that one.

**Salvage that applies when E1 is attempted** (from the Snipper audit):
- **ADAPT** the mocked-VS integration tests;
- **COPY** the fake two-pipe JSON-RPC server pattern;
- **ADAPT** the `/rootsuffix` real-IDE smoke as a manual or nightly gate (not CI).

**Recommendation.** E1 is the right *shape* for live diagnostics, but it is a separate slice
whose first task is the extractor overlay input (1) and a resident analysis process (2). It
must be run on Windows with Visual Studio against the six-step acceptance above.

## E2: a NuGet-only Roslyn `DiagnosticAnalyzer` calling the native Rust core

**Verdict: REJECT** (for the Alpha and as the live-diagnostics route).

**What was run.** `experiments/owen-e2-native-analyzer/`, on Linux x64 with the .NET 8 SDK:
- a `cdylib` exporting `owen_e2_check(facts) -> msbuild lines`, the SAME `own_bridge::check_facts` + `render_finding` as the CLI;
- a `netstandard2.0` analyzer that P/Invokes it and maps the lines to `Location`s;
- a consumer project.

| check | result |
|---|---|
| Linux, `dotnet build` (compiler server), variant 1: `DllImport` + `DllImportSearchPath.AssemblyDirectory` | **FAIL**: `DllNotFoundException` on every build. Roslyn shadow-copies analyzer assemblies and does not copy native files beside them. |
| variant 2: explicit path via `CompilerVisibleProperty` + `NativeLibrary.Load`, reached by reflection (absent from `netstandard2.0`) | **works**: `C8.cs(18,1): warning OWNE2: OWN002: …` |
| repeated builds through the compiler server | identical over 3 builds |
| after `dotnet build-server shutdown` | identical |
| the native file replaced under a live server | the next load fails; no stale fallback |
| Windows, Visual Studio x64 in-proc / ServiceHub, unload/reload | **NOT EXECUTED** (no Windows here) |
| no duplicate semantics in C# | holds for the **verdict**. **Fails for the facts**: an analyzer cannot run the extractor, a separate program that reads files. Extraction would have to move inside the analyzer, which is a second frontend host. |

**Why REJECT.**
1. **Only a hand-built workaround works.** The default native-asset resolution, the thing a NuGet-only analyzer relies on, fails outright under the shadow copy.
2. **The workaround is .NET-hosted only.** `NativeLibrary` exists only on .NET (Core) hosts. A .NET Framework compiler host needs a third, Windows-only `LoadLibrary` path.
3. **Native libraries never unload.** On Windows they are locked by long-lived compiler and IDE processes, which fights package updates.
4. **The analyzer would still need the extractor in process.** That duplicates the frontend host the build path already has.

**What would change the verdict:**
- the same extractor overlay/library refactor that E1 needs;
- a measured Windows + Visual Studio run of variant 2.

Until then the build host is the shipped path, and E1 is the live-diagnostics direction.
