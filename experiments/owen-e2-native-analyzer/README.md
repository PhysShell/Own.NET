# E2 spike: a Roslyn analyzer calling the native Rust core (OX-01)

**Experimental.** Outside every shipping path and every CI build. It exists to answer one
kill-first question from `docs/notes/owen-extension-alpha-preregistration.md`: can live OWN
diagnostics ship as a NuGet-only Roslyn analyzer that calls the Rust core in process?

**Verdict: REJECT for the Alpha.** The reasons and the evidence are in
`docs/notes/owen-extension-ide-feasibility.md` (§ E2).

| piece | what it is |
|---|---|
| `native/` | a `cdylib` exporting `owen_e2_check(facts) -> msbuild lines`. It is the SAME `own_bridge::check_facts` + `render_finding` the CLI runs, with no semantics of its own, built in its own Cargo workspace |
| `analyzer/` | a `netstandard2.0` `DiagnosticAnalyzer`. It reads OwnIR facts from an `AdditionalFiles` entry and maps the core's `file(line): warning CODE: text` lines onto `Location`s |

Run on Linux x64, .NET 8 SDK:

```sh
(cd native && cargo build --release)
(cd analyzer && dotnet build -c Release)
# a consumer referencing analyzer/bin/Release/netstandard2.0/E2.Analyzer.dll as an <Analyzer>,
# with an *.owen-facts.json AdditionalFile, and (variant 2)
#   <OwenNativeCore>/abs/path/libowen_e2.so</OwenNativeCore> + <CompilerVisibleProperty Include="OwenNativeCore" />
```

**Variant 1: `DllImport` with `DllImportSearchPath.AssemblyDirectory`.**
- **Result:** `DllNotFoundException` on every build, including after `dotnet build-server shutdown`.
- **Why:** Roslyn shadow-copies analyzer assemblies and does not copy native files beside them.

**Variant 2: an explicit path, `CompilerVisibleProperty`, and `NativeLibrary` reached by reflection.**
- **The finding arrives:** `C8.cs(18,1): warning OWNE2: OWN002: …`, identical across three builds through the compiler server and after a server restart.
- **A replaced native file breaks loading:** after the native file was overwritten with garbage under a live server, loading failed. It did not fall back to a stale copy.
- **`NativeLibrary` exists only on .NET-hosted compilers.** A .NET Framework compiler host has none.
