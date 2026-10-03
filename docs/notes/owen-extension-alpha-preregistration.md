# OX-01 — Owen extension substrate, with Typed Builder as extension #1: preregistration

**STATUS: REGISTERED BEFORE ANY PRODUCT CODE.** This commit holds this document and the
Snipper salvage audit ([`owen-extension-snipper-salvage.md`](owen-extension-snipper-salvage.md)),
and nothing else. A semantic change after this commit is an amendment, committed before the
official run it affects.

**Base:** `main` = `88cb8cc31c49d730290613208947102d0737cad2` (merge of #391, TB-MVP-01). The
base contains #391: `git merge-base --is-ancestor 04cb779a4ce8047e563d35edc72bdce9a13eaca8 88cb8cc3`
holds. `main` has not moved since, and nothing under Typed Builder, `OwnSharp.Cli` or
packaging changed after it.

## P0 — gates on the base

The results are in § *P0 results* at the end.

## Kill-first findings (throwaway spikes on the base, not committed)

**K-1 — the host already exists.** `owen check` (`frontend/roslyn/OwnSharp.Cli`, the `Owen.Cli` tool)
is a complete generic pipeline:
- bundled extractor, child process;
- facts;
- the authoritative Rust core `own-cli`, resolved only from an explicit locator or one computed packaged path (D3/D6, `RustCoreLocator.cs`);
- `--format msbuild`;
- a mapped exit-code contract.

On the Rust engine it needs **no Python**: the vendored core is unpacked only for `--engine python|compare`.

The core already renders the canonical VS Error List line itself (`own-cli ownir --format msbuild`).
A second runner or a second renderer would duplicate the authoritative path, so none is built.

**K-2 — the protocol must reach the scan as source.** The extractor's directory and `.csproj`
expansion skips `bin/`, `obj/` and `*.g.cs`. An **explicitly named** `.cs` input passes through
unfiltered (`Program.cs::Expand`).

A probe confirmed the path end to end:
1. the TB-MVP `OrderBackend` sources built with the generated protocol living only under `obj/.../generated/`;
2. the extractor ran on `OrderBackend.csproj` plus that generated file named explicitly;
3. `own-cli ownir --format msbuild` printed `C8.cs(18): error OWN002: …`.

No extractor change is needed.

**K-3 — generator delivery, both variants measured.**
- **A (Roslyn incremental source generator).**
  - **Setup:** the existing generator's model and renderer, compiled unchanged into a `netstandard2.0` analyzer against Roslyn 4.8.0, run inside the ordinary compilation.
  - **Output:** text byte-identical to the committed golden `samples/OrderBackend/OrderBackend/Domain/Order.Protocol.cs`, 6880/6880 bytes. The only Roslyn-specific `string[1..]` uses were rewritten as `Substring(1)`, with the same output.
  - **One difference, compiler side:** generated sources compile with nullable annotations off, so the golden's `string?` warns CS8669. The generator wrapper therefore prepends exactly one line, `#nullable enable`, to the golden text. The shared renderer's output, and so the golden, do not change.
- **B (MSBuild pre-compile Exec).**
  - **Full build:** works, adding about 0.5 s of `dotnet exec` per build.
  - **Design-time build (fails):** under the design-time build Visual Studio uses for IntelliSense (`-t:CompileDesignTime -p:DesignTimeBuild=true -p:SkipCompilerExecution=true -p:ProvideCommandLineArgs=true`), the generated file was **neither produced nor in the compile item list**. IntelliSense would show the typed API as missing until a full build, and an edit to the declaration would not regenerate it.
- **Decision: A.** A runs in every compilation, the IDE's included, and keeps the golden. B is not shipped.

**K-4 — packaging.**
- **Owen.Cli cannot be the reference.** It is a `DotnetTool` package, and NuGet refuses it as a `PackageReference` (NU1212). A referenceable host package is therefore needed.
- **The exec bit.** A `.nupkg` does not carry Unix file modes. `RustCoreLocator.ResolvePackaged` already copies the packaged `own-cli` into a content-addressed cache `~/.owen/rust-core/<sha256>/` and marks it executable there. The host reuses that code path as is.

## Install UX (the claim)

```
dotnet new web -n OrderBackend
dotnet add package Owen.TypedBuilder --version 0.1.0
dotnet build
```

That is all. The machine needs no Own.NET checkout, no Python, no Rust toolchain, no global
`owen` tool, no environment variable pointing at a repository, and no PATH lookup of a
development binary. The only executable taken from the machine is the `dotnet` muxer that is
already running the build: `DOTNET_HOST_PATH` as MSBuild sets it, then `DOTNET_ROOT`, then
`dotnet`.

## Packages (exact)

| package | kind | why it exists |
|---|---|---|
| `Owen.Build` | generic build host | One shared host is needed. It must be referenceable (K-4), carry exactly one copy of the extractor and of each platform's Rust core however many extensions are active, and depend on no extension. It is the only new non-extension package; there is no `Owen.Toolchain` or `Owen.CoreAssets`, because nothing would separate them from it. |
| `Owen.TypedBuilder` | extension #1 | The generator, the extension descriptor, and a dependency on `Owen.Build` of the same version. |
| `Owen.TestExtension` | **test fixture, never shipped** | A synthetic second extension: a descriptor only, no analysis. It is built by the gate into the isolated feed and nowhere else. |

Version: `0.1.0` for both shipped packages, matching `Owen.Cli` 0.1.0, which the host payload is.
Nothing is published to nuget.org. Every acceptance run uses a locally packed candidate in an
isolated feed.

**`Owen.Build` layout:**

| path | contents |
|---|---|
| `tools/net8.0/any/` | the `OwnSharp.Cli` publish closure (`ownsharp.dll`, `ownsharp-extract.dll`, Roslyn), the same payload as the `Owen.Cli` tool, **without** the vendored Python core |
| `tools/net8.0/any/rust-core/<platform-key>/own-cli[.exe]` | the packaged core, at the path `RustCoreLocator.PackagedPath` already computes |
| `build/Owen.Build.props` · `build/Owen.Build.targets` | the generic MSBuild host |
| `buildTransitive/…` | the same two files, so they flow through an extension's dependency |

**One source of truth for the platform inventory.** The set of supported platform keys and
binary names, and the "pack fails when a staged binary is missing" check, move into one
`frontend/roslyn/OwenRustCore.props`. Both `OwnSharp.Cli.csproj` and the `Owen.Build` project
import it. The `Owen.Cli` package payload must stay **file-for-file identical** to its base
payload, compared as a sorted file list plus per-file sha256.

## Extension discovery contract (exact)

An extension package adds, from its `buildTransitive/<Id>.props`:

```xml
<OwenExtensionDescriptor Include="$(MSBuildThisFileDirectory)owen-extension.json" />
```

The descriptor (`spec/OwenExtension.md`, `spec/owen-extension.schema.json`):

```json
{
  "owen_extension": 1,
  "id": "Owen.TypedBuilder",
  "version": "0.1.0",
  "requires": {
    "host": "0.1.0",
    "ownir": 2,
    "capabilities": ["ownership", "state-protocol", "heap-effects", "proven-call"]
  },
  "frontend": { "generators": ["Owen.TypedBuilder.Generator"] }
}
```

**Host 0.1.0 supports:** OwnIR 2, and the capabilities `ownership`, `state-protocol`,
`heap-effects` and `proven-call`. The host validates every descriptor before any analysis, and
**every violation is a build error**, never a skip. The new code family is `OWENB`, the host's;
no `OWN` code changes.

| condition | result |
|---|---|
| no descriptor at all (`Owen.Build` referenced alone) | warning `OWENB001` "no Owen extension is active; nothing was analysed". **Intentionally inactive, and loud about it.** |
| `owen_extension` ≠ 1, a missing or ill-typed field, a duplicate `id` | error `OWENB002` |
| `requires.ownir` ≠ 2, or `requires.host` newer than the host | error `OWENB003` (incompatible extension) |
| a required capability the host does not have | error `OWENB004`, naming it and the extension |
| no Rust core for this platform in the package, or an unsupported platform | error `OWENB005` (the locator's D3.1 message) |
| the extractor refuses a construct (exit 2) | error `OWENB010` at the refused `file(line)` |
| the core refuses the facts (exit 2, e.g. a `proven_call` not proven harmless) | error `OWENB011` at the `file(line)` the refusal names |
| an internal failure of either child | error `OWENB012` |

**What the host does with valid descriptors.**
- **Manifest.** It writes `obj/owen/extensions.json`, sorted by `id`: host version, OwnIR version, and each active extension's `id`, `version` and capabilities.
- **Logging.** It logs `Owen: active extensions: <id> <version>, …` at high importance.
- **Generator outputs.** It collects every `frontend.generators` name, takes the generated C# under `$(CompilerGeneratedFilesOutputPath)/<generator assembly>/**`, and passes those files to the extractor explicitly (K-2). The host props set `EmitCompilerGeneratedFiles=true`, so those files exist.
- **Analysis.** It runs the existing check pipeline exactly once, whatever the number of extensions, with `--engine rust --format msbuild --severity $(OwenSeverity)`.

The host contains **no extension identifier**: the gate greps the host sources and targets for
`TypedBuilder` and expects zero hits. Two extensions coexist by construction, because the
descriptors are a list.

**Where it lives.**
- **Validation, manifest, generated-file collection and refusal canonicalisation:** a new `owen build-check` subcommand of the same `OwnSharp.Cli` program. It is the generic host entry point the targets call, and it reuses `CheckCommand`'s pipeline rather than copying it.
- **Analysis semantics:** none in the host; they stay in the Rust core.

**MSBuild properties:**
- `OwenSeverity`: `warning` by default, `error` opt-in.
  - **Why warning is the default:** the first install never turns a legacy project red, because the existing `--severity` only changes how a finding is shown, never the verdict.
  - **Refusals are the exception:** OWENB010/011 are always errors. They only arise in a protocol the developer declared, and "cannot be checked" must never read as clean.
- `OwenEnabled`: `true` by default, `false` to switch the host off.

The target runs after the build has copied its output, because the extractor binds against the
built `bin/`. It is skipped in design-time builds and runs on every build, so warnings do not
vanish on an incremental build.

## The Typed Builder extension (exact)

- **`Owen.TypedBuilder.Generator`:** a `netstandard2.0` `IIncrementalGenerator` over Roslyn 4.8.0.
- **Shared core.** It and the existing CLI (`frontend/roslyn/Own.TypedBuilder`) share one model/renderer library, `Own.TypedBuilder.Core`. The CLI's output stays byte-identical to the golden, so `typed_builder_gate` keeps passing unchanged.
- **The attribute vocabulary** (`TypedProtocol`, `ProtocolState`, `BuilderRequired`, `Transition`, `ProtocolToken`, `ProtocolRegion`) is emitted by the generator's post-initialisation step as `internal` types in the global namespace. A consumer therefore writes `[TypedProtocol]` with no `using` and no dependency, and the generated protocol text stays the golden.
- **A refused declaration** is a generator error `OWENTB001` carrying the core's refusal line. It is never empty output.

## Supported platforms

`linux-x64` and `win-x64`: exactly the platforms `Owen.Cli` packs today. macOS is **not**
claimed. On any other platform the host fails with `OWENB005`; it never skips.

## Foundations: unchanged

No change to:
- OwnIR (version 2) or the ownership, state-protocol or H0/H1 semantics;
- any `OWN` code or message;
- the Rust core's analysis;
- T0 or the P-022 harness.

`git diff --stat 88cb8cc3..HEAD -- ownlang rust spec/OwnIR.md spec/Bridge.md spec/ownir.schema.json frontend/roslyn/OwnSharp.Extractor docs/evidence/calibration scripts/perf_baseline.py`
must be empty. If the substrate turns out to need one of these, the slice stops with a named
blocker.

## Snipper (P1)

The salvage audit is committed alongside this document. **For this slice:**
- **REJECT** Snipper's binary discovery (setting → bundled → PATH, with silent fall-through);
- **ADAPT** pack-time bundling with a hard failure on a missing binary (already the `Owen.Cli` rule), and the one-shot child-process discipline (drain both streams, map the exit code, kill on cancel).

Everything else is for a future `Owen.VisualStudio` or LSP and is **not** built here.

## IDE: investigated only, not shipped

- **E1 (generic VSIX host: `IErrorTag` + `ITableDataSource` + a long-lived Owen process).** This environment has no Windows and no Visual Studio, so the spike can only be specified. The verdict will be recorded as **not executed**, with the reasons and the exact acceptance it would need. No VSIX is built.
- **E2 (Roslyn `DiagnosticAnalyzer` → native Rust core).** A minimal experimental project under `experiments/owen-e2-native-analyzer/`, outside every shipping path and every CI build. It is exercised on Linux with `dotnet build` and repeated builds through the compiler server. Windows, the Visual Studio x64 in-proc compiler and unload/reload are recorded as not executed here. Verdict: `VIABLE` or `REJECT`.
- **Architecture invariant.** An extension is not an IDE plugin. A future IDE host is exactly one `Owen.VisualStudio`, and a future server is exactly one Owen diagnostic/language server, both serving all active extensions. No `Owen.TypedBuilder.VisualStudio`.

## Acceptance

**Gate:** `scripts/owen_extension_gate.py`. It runs on Linux and Windows CI, packs the candidate
packages, and tests them in an isolated consumer.

**The isolated consumer.**
- **Location:** a fresh directory **outside the checkout**.
- **Environment:**
  - `PATH` holds only the directory of the `dotnet` running the gate;
  - `HOME`, `DOTNET_CLI_HOME` and `NUGET_PACKAGES` are fresh temporary directories;
  - the `nuget.config` has `<clear/>`, the isolated feed and nuget.org, with package source mapping `Owen.*` → the isolated feed only.
- **Preconditions:**
  - `python`, `python3`, `cargo`, `rustc` and `owen` resolve to nothing on that `PATH`;
  - the consumer contains no path into the checkout.

The gate fails if any precondition fails.

**Steps, every one PASS/FAIL:**

| id | step | PASS iff |
|---|---|---|
| U1 | `dotnet new web -n OrderBackend`, `dotnet add package Owen.TypedBuilder --version 0.1.0`, then copy in the TB-MVP domain/data/endpoints/Shipping sources. Not `Order.Protocol.cs` (now generated) and not `TypedBuilder.cs` (now provided). | the project file holds exactly one Owen `PackageReference` |
| A | `dotnet build` | succeeds. The generated `Order.Protocol.g.cs` text = `#nullable enable\n` + the committed golden. `obj/owen/extensions.json` lists `Owen.TypedBuilder 0.1.0` and its capabilities |
| B | stage `C1_draft_approve` | the build fails with CS1061 naming `Approve`, and no manual generator step ran |
| C | stage `C8_stale_draft` with `OwenSeverity=error` | the build fails with `OWN002` |
| D | the C build's output | holds a canonical `file(line): error OWN002: …` line, whose file resolves from the project directory to the staged file and whose line is 18. With the default severity, the same build succeeds and shows the line as `warning OWN002` |
| E | U1–D under the stripped environment | all pass; the build logs contain no path into the Own.NET checkout |
| F | the whole TB-MVP corpus (8 positive, 20 negative, 2 limits) through the package, `OwenSeverity=error` | compiler cases: their CS code; extractor cases: `OWENB010` with the registered text; core verdict cases: their `OWN` code(s); core refusals: `OWENB011` with the registered text; positives: no `OWN`/`OWENB` diagnostic. K1 gives `OWN001`, K2 is clean, P5 and P8 have the `proven_call` (from `--emit-facts`) |
| G | the TB-MVP `Acceptance` runner against the consumer project | 44/44, with the transcript **byte-identical** to the committed `samples/OrderBackend/evidence/acceptance.txt` |
| H | the consumer with both `Owen.TypedBuilder` and `Owen.TestExtension` | the manifest lists both, analysis runs once, and the result is unchanged |

**Mutation and negative controls, each run in the isolated consumer:**

| id | mutation | PASS iff |
|---|---|---|
| M1 | delete `owen-extension.json` from the installed `Owen.TypedBuilder` | `OWENB001` is shown, and C8 produces **no** `OWN002`: the acceptance's C check would fail, so the gate detects it |
| M2 | add an unknown capability to the descriptor | error `OWENB004` naming it |
| M3 | delete the bundled `own-cli` for this platform | error `OWENB005`, never a clean build |
| M4 | `requires.ownir: 3`, and separately `requires.host: 9.0.0` | error `OWENB003` each |
| M5 | remove the host's build target (empty `Owen.Build.targets`) | C8 produces no `OWN002` and the gate's C check reports the absence |
| M6 | run from a consumer with no checkout | pass (it is E) |
| M7 | add `Owen.TestExtension` | no file of the host changes (H), and the host source has 0 occurrences of `TypedBuilder` |

**The other gates, on the final head:**
- `tests/run_tests.py`, `ruff`, `mypy`;
- `cargo fmt --check`, `cargo clippy --all-targets`, `cargo test`;
- `protocol_gate.py --rust`, `heap_effects_gate.py`, `typed_builder_gate.py --rust`;
- the `Owen.Cli` pack/install gate (the payload byte-identity above, then install → check → `OWN001`);
- the P-022 merge gate;
- server CI on Linux and Windows.

## Verdict

**`GO_OWEN_EXTENSION_ALPHA`** iff A–H, M1–M7 and every listed gate pass:

`PackageReference Owen.TypedBuilder` → generated API → CS diagnostics → OWN diagnostics on build
→ no external toolchain or setup → generic extension discovery proven.

Otherwise the verdict is **`NO_GO_OWEN_EXTENSION_ALPHA`**, with the exact blocker. The failing
case is preserved, and no foundation change is made to get to green. If E fails because the
package cannot run without a global Owen install, the verdict is NO_GO.

**Out of scope even after GO:**
- a production VSIX, LSP or VS Code extension;
- the Memory or TypeDisciplines extensions;
- BCL summaries (#394), typed write targets (#395), affine tokens (#392), diagnostic wording (#393), concurrency (#396);
- a second aggregate;
- a repo-wide rename.

## P0 results

Run on `88cb8cc31c49d730290613208947102d0737cad2`, a clean tree except for the two documents of this commit:

| gate | result |
|---|---|
| `python tests/run_tests.py` | rc 0, zero `FAIL` lines (the one textual hit is an `ok[...]` line quoting the word) |
| `ruff check .` / `mypy` | rc 0 / rc 0 |
| `cargo fmt --check` / `cargo clippy --all-targets` / `cargo test --no-fail-fast` | rc 0 / rc 0 / rc 0, 290 passed, 0 failed |
| `python scripts/protocol_gate.py --rust …/own-cli` | 0 failures |
| `python scripts/heap_effects_gate.py` | PASS |
| `python scripts/typed_builder_gate.py --rust …/own-cli` | 0 failures, transcript sha256 `ba447304cdf957ee` |
| `Owen.Cli` pack/install (gate A, replayed locally) | pass |
| P-022 merge gate | `success` on #391's final head `04cb779`, which became this base |

`protocol_gate.py` covered 29 documents byte-identical on both CLIs. `typed_builder_gate.py` covered 8 positive, 20 negative and 2 limit cases, with 44 acceptance checks run twice.

**Gate A, replayed locally.**
- **Pack:** with this platform's release `own-cli` staged under `linux-x64/`.
- **Install:** with `--tool-path` from an isolated feed, with a fresh `HOME` and `NUGET_PACKAGES`.
- **Check:** `owen check` on a seeded leak gives `OWN001` with rc 1; on clean code it gives rc 0.
- **One environmental detail:** this container's dotnet lives in `/root/.dotnet`, so the tool's native apphost needs `DOTNET_ROOT`. The first attempt, without it, failed in the apphost before Owen ran.

**K-4, observed rather than assumed.** A `PackageReference` to that same `Owen.Cli` 0.1.0 fails restore with `NU1212: Invalid project-package combination … DotnetToolReference project style can only contain references of the DotnetTool type`.
