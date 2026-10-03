# Owen extension substrate: Snipper salvage audit

- **Audited:** `PhysShell/snipper` at commit `43b395abce6c0c2524d68919cf3c04f9e8f75b7e` (local checkout `/home/user/physshell/snipper`).
- **Date:** 2026-10-03.
- **Scope:** read-only audit. Covers the VS extension (`extensions/snipper-vs/`), the VS Code extension (`extensions/snipper-vscode/`), the Rust LSP adapter (`crates/snipper-lsp/`), the Roslyn sidecar (`sidecar/Snipper.Roslyn/`), the CI workflow (`.github/workflows/ci.yml`) and ADR-0007/0008. The question is which mechanisms Owen should **COPY**, **ADAPT** or **REJECT** for its extension substrate: `Owen.Build` (buildTransitive host), extension packages such as `Owen.TypedBuilder`, and a possible future `Owen.VisualStudio` or Owen LSP/diagnostic server.
- **Path notes:** the requested files exist, but under `extensions/snipper-vs/Snipper.VisualStudio/`, not directly under `extensions/snipper-vs/`. `SnipperLanguageServerProvider.cs` contains a class named `SnipperLanguageClient`, which implements the classic VSSDK `ILanguageClient`. It is not the new `LanguageServerProvider` API. There are two test projects. `Snipper.VisualStudio.IntegrationTests` runs against a **mocked** VS service container. `Snipper.VisualStudio.Tests` holds net8.0 unit tests plus an empty placeholder for the real IDE tests. Real-IDE coverage comes only from the manual script `extensions/snipper-vs/scripts/vs-smoke.ps1`.
- **License:** MIT (`LICENSE`, "Copyright (c) 2026 Snipper contributors"). Code can be copied if the copyright and permission notice go with it. A copied file needs an attribution header, or a `THIRD-PARTY-NOTICES` entry if Owen's license differs. Re-implementing an idea creates no obligation. Because most verdicts below are ADAPT (re-implement), the license matters only for the few literal copies (the test fake-server framing helpers, the smoke-script hive guard).

All paths below are relative to the Snipper repository root unless they are prefixed with `Own.NET/`. Line numbers refer to the audited commit.

## Summary

| # | Mechanism | Snipper location | Verdict | Where it would land in Owen |
|---|---|---|---|---|
| 1a | Binary location: explicit setting -> bundled -> PATH | `extensions/snipper-vs/Snipper.VisualStudio/SnipperBinaryLocator.cs:18-42`, `extensions/snipper-vscode/src/serverPath.ts:13-40` | **REJECT** (PATH fallback, silent fall-through on a bad explicit path) | none. Owen keeps `RustCoreLocator` |
| 1b | Bundling the native binary into the host package at build time (MSBuild target copies `cargo` output into the package `bin/`) | `extensions/snipper-vs/Snipper.VisualStudio/Snipper.VisualStudio.csproj:78-111` | **ADAPT** | Owen.Build packing (`rust-core/{rid}/own-cli`) |
| 1c | Per-platform targeted packages, one binary per RID | `.github/workflows/ci.yml:136-206`, `serverPath.ts:31-40` | **ADAPT** | Owen.Build packaging / future Owen.VisualStudio |
| 2a | Long-lived LSP child (VS `ILanguageClient.ActivateAsync`) | `SnipperLanguageServerProvider.cs:34-54` | **REJECT** as a lifecycle model (no stderr, no exit/crash handling, no orphan control) | none now. Future Owen.VisualStudio must design its own |
| 2b | Short-lived child per command (spawn, handshake, best-effort shutdown, `Kill` in `finally`) | `SnipperCommands.cs:60-92`, `SnipperLspRpc.cs:20-51` | **ADAPT** (the `finally`-kill shape only) | Owen.Build one-shot invocations |
| 2c | Lazy sidecar child inside the Rust server with a 200 ms timeout and a "set to None" reset | `crates/snipper-lsp/src/lib.rs:100-174` | **REJECT** | none |
| 3a | LSP base-protocol framing via StreamJsonRpc `HeaderDelimitedMessageHandler` | `SnipperLspRpc.cs:26-29` | **COPY** (pattern), only if Owen ever speaks LSP from .NET | future Owen.VisualStudio |
| 3b | Newline-delimited JSON-RPC for the sidecar | `sidecar/Snipper.Roslyn/Program.cs:3-15,26-59`, `lib.rs:138-160`, ADR-0007 | **REJECT** for Owen's build path (Owen is one-shot, file/stdout based) | none |
| 4 | Cancellation | `SnipperLspRpc.cs:31-40` (token passed through), tower-lsp built-in `$/cancelRequest`; nothing in Snipper's own code | **REJECT** (nothing to salvage) | future LSP must design it |
| 5 | Stale document / version rejection | `lib.rs:34-38,219-249`: absent | **N/A** (does not exist) | future LSP must design it |
| 6a | Mock-VS integration tests (`Microsoft.VisualStudio.Sdk.TestFramework.Xunit`, net472, windows-latest) | `Snipper.VisualStudio.IntegrationTests/*.csproj:21`, `GlobalFixtures.cs:7-10`, `ci.yml:223-241` | **ADAPT** | future Owen.VisualStudio |
| 6b | In-memory fake JSON-RPC server over two one-directional `Pipe`s | `SnipperCommandRpcTests.cs:15-22,90-154` | **COPY** | future Owen.VisualStudio / LSP client tests |
| 6c | Real-IDE smoke via a dedicated `/rootsuffix` hive (manual PowerShell, not in CI) | `extensions/snipper-vs/scripts/vs-smoke.ps1` | **ADAPT** (manual gate only) | future Owen.VisualStudio |
| 6d | VS Code headless extension tests (`@vscode/test-electron` + `xvfb-run`) | `extensions/snipper-vscode/test/`, `ci.yml:109-134` | **ADAPT** (if a VS Code client is ever built) | none now |
| 7 | Thin VS Code client (`vscode-languageclient`, stdio, command -> `workspace/executeCommand`) | `extensions/snipper-vscode/src/extension.ts:14-43`, `commands.ts:13-58` | **ADAPT** (shape), REJECT its locator | future (not on the roadmap) |
| 8 | LSP-type isolation (INV-5) | `crates/snipper-lsp/tests/inv5_lsp_types_isolation.rs:1-22`, `lib.rs:1-5` | **ADAPT** (the principle; the check is too weak) | Owen Rust core and any future LSP crate |
| 9 | Roslyn sidecar (receiver-type lookup over stdin/stdout) | `sidecar/Snipper.Roslyn/Program.cs`, `lib.rs:83-174`, ADR-0007 | **REJECT** (it overlaps with the extractor and is weaker) | none |

## 1. Binary location

**Evidence.**
- VS: `SnipperBinaryLocator.Resolve` (`extensions/snipper-vs/Snipper.VisualStudio/SnipperBinaryLocator.cs:11-30`) checks three places in order:
  1. The Tools > Options `ServerPath`, used only `if File.Exists` (`:20-21`).
  2. `{assemblyDir}/bin/snipper-lsp.exe` (`:23-26`).
  3. A manual PATH scan (`:28-42`).

  The binary name is hard-coded to `snipper-lsp.exe` (`:9`). If the configured path does not exist, the locator silently falls through to the bundled copy or to PATH (`:20`). The test `SnipperBinaryLocatorTests.Resolve_NonExistentConfiguredPath_DoesNotReturn` (`Snipper.VisualStudio.IntegrationTests/SnipperBinaryLocatorTests.cs:25-31`) asserts nothing: its comment accepts either "null or a valid PATH hit". The options page text documents the PATH discovery (`SnipperOptionsPage.cs:10-11`).
- VS Code: `resolveServerPath` (`extensions/snipper-vscode/src/serverPath.ts:13-29`) returns the user setting **without checking that it exists** (`:17-19`), then `bin/<platform>/snipper-lsp[.exe]`, then the bare name `snipper-lsp` for the OS to resolve on PATH (`:28`). `getPlatformDir` (`:31-40`) maps every non-Windows, non-macOS platform to `linux-x64`, so a linux-arm64 host would look for an x64 binary.
- Bundling: the VSIX project runs `cargo build -p snipper-lsp` and copies the output into `bin/` with `VSIXSubPath=bin` (`Snipper.VisualStudio.csproj:78-97`). With `SnipperLspCargoBuild=false` the target only includes the binary `Condition="Exists(...)"` (`:99-111`), so a missing binary produces a VSIX without a server and no error. Only the manual smoke script checks VSIX contents (`vs-smoke.ps1:157-186`).
- Per-RID packaging: VS Code builds one targeted VSIX per `vsce --target` (`ci.yml:136-206`).
- Sidecar: `SNIPPER_ROSLYN` env var only. If the variable is unset or the path is missing, the sidecar is silently disabled (`crates/snipper-lsp/src/lib.rs:87-95`, ADR-0007 `:38-40`). The VS Code `roslynPath` setting is sent as `initializationOptions` (`extension.ts:53-63`), but the server's `initialize` ignores its params (`lib.rs:178`), so that setting has no effect. The VS options page `RoslynPath` (`SnipperOptionsPage.cs:16`) is never read.

**Verdict.**
- **1a REJECT.** Every resolution order here ends in PATH discovery, and a bad explicit setting falls through instead of failing. That is the stale-binary failure that Owen's D3 rule prevents (`Own.NET/frontend/roslyn/OwnSharp.Cli/RustCoreLocator.cs`: "No discovery of any kind"; an empty or malformed `OWEN_RUST_CORE` is an exit-2 error, not a fall-through). The VS Code variant does not even check existence. The sidecar locator silently disables a feature on a typo. None of this belongs in Owen.
- **1b ADAPT.** Copying a separately built native binary into a fixed sub-path of the .NET package at pack time does fit Owen's "one computed packaged path". Changes for Owen.Build:
  - Do not run `cargo build` from the consumer-facing project. Stage prebuilt per-RID `own-cli` binaries as package content under `rust-core/{rid}/`.
  - Make a missing binary a **pack-time error**, not an `Exists()` skip.
  - Record the SHA-256 at pack time, so the packaged path can be checked against `RustCore.Sha256` as `RustCoreLocator` already records it.
- **1c ADAPT.** Per-RID targeting is sound. Owen should derive the RID from `RuntimeInformation` the way `RustCoreLocator.PlatformKey()` already does, not from a hand-written if/else that defaults to linux-x64.

## 2. Long-lived child-process lifecycle

**Evidence.**
- VS LSP child: `SnipperLanguageClient.ActivateAsync` (`SnipperLanguageServerProvider.cs:34-54`) calls `Process.Start` with only stdin/stdout redirected. Stderr is not redirected and not captured. The `Process` handle is not stored, there is no `Exited` handler, and there is no Job Object or kill-on-close. The `StopAsync` event is declared but never raised (`:30-32`). Initialize failures are swallowed: `ShowNotificationOnInitializeFailed => false` (`:27`) and `OnServerInitializeFailedAsync` returns null (`:61-63`). Restart and shutdown are left to VS's `ILanguageClient` infrastructure. ADR-0008 lists "server restarts on crash" as an extension responsibility (`docs/adr/0008-editor-extension-packaging.md:63`), but no extension implements it.
- VS command child: `SnipperCommandBase.ExecuteCommandAsync` (`SnipperCommands.cs:60-92`) starts a **new** server process for each command invocation (`:68-76`). It runs a full initialize, executeCommand, shutdown, exit handshake (`SnipperLspRpc.cs:20-51`) and then calls `process.Kill()` in `finally`, catching all exceptions (`SnipperCommands.cs:88-91`). Teardown errors are swallowed (`SnipperLspRpc.cs:42-48`). The exit code is never read. The command sends no `textDocument` or position arguments, unlike the VS Code client (`commands.ts:36-44`).
- VS Code: lifecycle is delegated entirely to `vscode-languageclient` (`extension.ts:19-22,36,41-43`). That library provides restart-on-crash with backoff and stop on deactivate.
- Rust server -> sidecar: `try_spawn_sidecar` (`lib.rs:100-116`) sends stderr to null (`:105`) and does not set `kill_on_drop`. tokio's default is false, so dropping `Child` does not kill the process. On a write error or a 200 ms timeout the state is reset to `None` (`:151,171`). The next completion **respawns** the sidecar (`:130-132`), which contradicts ADR-0007's "CST-only for the remainder of the session" (`docs/adr/0007-roslyn-sidecar-protocol.md:34-36`). Orphans are avoided only because the sidecar exits on stdin EOF (`Program.cs:14-15,27`). A sidecar that is busy and timed out keeps running until it finishes and reads EOF. The `Mutex` is held across the 200 ms wait (`lib.rs:128-160`), which serializes completions. `main` has no signal or parent-death handling (`crates/snipper-lsp/src/main.rs:6-12`).

**Verdict.**
- **2a REJECT** as a model. It is the minimum `ILanguageClient` example: no stderr capture, no exit observation, swallowed init failures, no orphan control. A future Owen.VisualStudio would need at least these:
  - Capture stderr into an output pane.
  - Use a Windows Job Object with `KILL_ON_JOB_CLOSE` so devenv crashes do not leave orphans.
  - Bound the restart policy.
  - Surface a visible error when the server cannot be resolved, instead of returning null.
- **2b ADAPT.** Only the shape transfers: spawn, talk, and always terminate in `finally`. For Owen.Build's one-shot `own-cli` invocations:
  - Redirect **and drain** stderr concurrently with stdout to avoid pipe deadlock.
  - Await `WaitForExitAsync` with a timeout before any kill.
  - Read and propagate `ExitCode` through Owen's ratified exit-code mapping (`CrashReport`/D5 carriers already exist in `Own.NET/frontend/roslyn/OwnSharp.Cli`).
  - Use `Kill(entireProcessTree: true)` only on timeout or cancellation.
  - Never swallow teardown failures silently.

  The per-command full LSP handshake is overhead that Owen has no reason to copy.
- **2c REJECT.** The lazy spawn, null stderr, no kill-on-drop and silent respawn add up to unobservable failure modes. The docs and the code disagree about the post-timeout behavior.

## 3. RPC framing

**Evidence.**
- VS side: StreamJsonRpc `HeaderDelimitedMessageHandler` with `JsonMessageFormatter` (`SnipperLspRpc.cs:26-29`). This is standard LSP base-protocol `Content-Length` framing.
- Rust server: tower-lsp 0.20 (`Cargo.toml:33`, `crates/snipper-lsp/Cargo.toml:27`) over stdio (`main.rs:6-12`).
- Test clients: hand-rolled `Content-Length` readers and writers in Rust (`crates/snipper-lsp/tests/smoke.rs:9-41`) and C# (`SnipperCommandRpcTests.cs:156-230`). The Rust `write_msg` uses `body.len()` (bytes), which is correct. The C# test helper reads the header one byte at a time.
- Sidecar: newline-delimited JSON-RPC (`Program.cs:3,26-59`; `lib.rs:138-160`). Unknown methods get `result: null` (`Program.cs:53-58`).

**Verdict.**
- **3a COPY (pattern)**, and only for a future .NET-side LSP client. If Owen.VisualStudio ever talks to an Owen server outside `ILanguageClient`, StreamJsonRpc's header-delimited handler is the right off-the-shelf choice. Do not write a custom framer. For a Rust server, tower-lsp (or `lsp-server`) is the obvious equivalent; the choice belongs to the future server design.
- **3b REJECT** for Owen now. The `own-cli` contract is one-shot: facts in, rendered diagnostics out, exit code. A line-delimited RPC channel adds framing, timeouts and correlation for no benefit. It also breaks if any payload ever contains a raw newline that is not JSON-escaped, and it has no way to resynchronize after a partial line.

## 4. Cancellation

**Evidence.** Snipper's own code does almost nothing with cancellation.
- `SnipperLspRpc` passes the `CancellationToken` to `InvokeWithParameterObjectAsync` (`SnipperLspRpc.cs:31-40`). Cancelling a StreamJsonRpc call sends `$/cancelRequest` to the server.
- The `finally { Kill }` (`SnipperCommands.cs:88-91`) is the effective cancellation of the child process.
- tower-lsp handles `$/cancelRequest` by dropping the pending handler future. Snipper's handlers do not check for cancellation. `query_receiver_type` is bounded only by its 200 ms timeout (`lib.rs:156-160`), and it does not propagate cancellation to the sidecar. The sidecar protocol has no cancel message (`Program.cs:3-12`).

**Verdict: REJECT, nothing to salvage.** For Owen.Build, cancellation means MSBuild's `ICancelableTask.Cancel()`, which should kill the `own-cli` process tree. Implement that directly in the build task. A future Owen LSP server must design `$/cancelRequest` handling and propagate cancellation into analysis. Snipper has no example of either.

## 5. Stale document / version rejection

**Evidence.**
- `DocumentState` stores only `text` and `language_id`, with no version (`lib.rs:34-38`).
- `did_open` inserts the document (`:219-227`). `did_change` overwrites the text with the last change and ignores `text_document.version` (`:242-249`). This is valid only because sync is `FULL` (`:187-189`).
- There is no `did_close`, so the document map only grows.
- Completion and code-action results are computed on a snapshot without any version check (`:274-282,330-334`).
- Neither the sidecar request (`lib.rs:138-143`) nor the command result carries a version.

**Verdict: N/A, the mechanism does not exist.** A future Owen diagnostic server must:
- key published diagnostics on the document version;
- drop results computed for a superseded version;
- handle `didClose`.

Owen.Build has no document versions. Its staleness concern is a different one: running a stale *binary*. `RustCoreLocator` already handles that (D3/D6 plus the recorded SHA-256).

## 6. VS integration tests

**Evidence.**
- `Snipper.VisualStudio.IntegrationTests` targets **net472** and uses `Microsoft.VisualStudio.Sdk.TestFramework.Xunit` 17.11.66 (`Snipper.VisualStudio.IntegrationTests.csproj:7,21`). That package provides a **mocked** VS service container through the `MockedVS` collection (`GlobalFixtures.cs:7-10`). No IDE instance is started.
- Production sources are linked as `Compile Include` items instead of a project reference, because VSIX outputs break test discovery (`.csproj:50-60`).
- CI runs these tests on `windows-latest` with plain `dotnet test` (`.github/workflows/ci.yml:223-241`).
- The tests are thin:
  - `SnipperLanguageClientTests.ActivateAsync_BinaryNotFound_ReturnsNull` (`SnipperLanguageClientTests.cs:16-23`) assumes no `snipper-lsp.exe` is on the runner's PATH.
  - The locator tests mostly assert "does not throw" (`SnipperBinaryLocatorTests.cs:25-43`).
- The most reusable piece is `SnipperCommandRpcTests` (`SnipperCommandRpcTests.cs`). It builds an in-memory fake JSON-RPC server over **two one-directional `System.IO.Pipelines.Pipe`s**, specifically so that swapping the input and output stream arguments fails the test (`:15-22,90-101`). It also asserts message order (`:62-81`).
- Real experimental-instance tests: `Snipper.VisualStudio.Tests/IntegrationTests.cs:1-39` contains only commented-out `Microsoft.VisualStudio.Extensibility.Testing.Xunit` examples and a TODO. The project itself is net8.0 unit tests that link two BCL-only files (`Snipper.VisualStudio.Tests.csproj:4,22-23`) and run on ubuntu (`ci.yml:208-221`).
- `extensions/snipper-vs/scripts/vs-smoke.ps1` is a manual real-IDE smoke that does not run in CI. It:
  - selects VS with `vswhere` (`:37-85`);
  - refuses the shared `Exp` hive and requires a dedicated `/rootsuffix` (`:141-143,399-401`);
  - builds and deploys with `DeployExtension=true` (`:427-439`);
  - checks VSIX contents (`:157-210`);
  - launches `devenv /rootsuffix ... /log`, with one relaunch when the ActivityLog asks for a restart (`:487-526`);
  - proves the package loaded from the loaded module list or the ActivityLog (`:363-397`);
  - opens a file through `devenv /command File.OpenFile` and waits for `snipper-lsp.exe` as a child of devenv (`:546-567`);
  - closes devenv, force-killing it after 15 s (`:577-588`).

**Verdict.**
- **6a ADAPT** for a future Owen.VisualStudio. Mock-VS xunit on windows-latest is CI-viable and cheap. Add assertions that actually fail. Do not depend on the runner's PATH contents.
- **6b COPY.** The two-pipe fake server is short, correct and generic. Attribute it under MIT if copied literally.
- **6c ADAPT as a manual or nightly gate.** The dedicated-hive guard, `vswhere` selection, ActivityLog evidence and process-parentage check are solid techniques. Hosted runners need VS installed and many minutes per run. Snipper itself never got this into CI, and its intended `Extensibility.Testing` route is still a TODO. Do not plan Owen gates around experimental-instance tests in CI.
- **6d ADAPT** only if a VS Code client is ever built. `@vscode/test-electron` under `xvfb-run` on ubuntu works in CI (`ci.yml:109-134`). Snipper's tests check only registration and activation (`test/suite/extension.test.ts:7-50`), and one of them relies on a 500 ms sleep (`:22-24`).

None of 6a-6d applies to Owen.Build. The right test for a buildTransitive host is a `dotnet build` of a fixture project that asserts on MSBuild output and the exit code.

## 7. Thin VS Code client

**Evidence.**
- `extension.ts:14-43`: `LanguageClient` over stdio with `documentSelector` for `csharp`, `client.start()` in `activate`, and `client.stop()` in `deactivate`.
- `commands.ts:13-58`: each command sends `workspace/executeCommand` with the document URI and position, and inserts the returned string through `editor.action.insertSnippet`.
- Command IDs are generated from TOML by an xtask into both clients (`src/commands.generated.ts`, `extensions/snipper-vs/Generated/SnipperCommands.cs`; ADR-0009).
- Activation is `onLanguage:csharp` (`package.json:2`).
- The `snipper.serverPath` setting advertises PATH discovery (`package.json:34`).

**Verdict: ADAPT (shape only), not on Owen's roadmap.** "No engine logic in the client, all behavior in the server" matches Owen's rule that the Rust core is authoritative. If a VS Code client ever exists, it should:
- use `vscode-languageclient` the same way;
- generate its contributed IDs from one source;
- replace `serverPath.ts` with the D3/D6 rule: an explicit setting that must exist and fails visibly, otherwise the one packaged per-RID path, with no PATH fallback.

## 8. LSP-type isolation

**Evidence.**
- `crates/snipper-lsp/src/lib.rs:1-5,56-57` states INV-5: LSP types stay in the adapter crate. Conversions happen at the boundary (`core_range_to_lsp` / `core_range_from_lsp` / `lsp_pos_to_byte`, `lib.rs:445-509`).
- The enforcement test `tests/inv5_lsp_types_isolation.rs:5-22` checks that the **text** of `snipper-core/Cargo.toml` and `snipper-context/Cargo.toml` does not contain `"lsp-types"`. It would not catch a `tower-lsp` dependency, which re-exports `lsp_types`, or any other LSP crate.
- `cargo public-api` runs only on `snipper-core`, as `continue-on-error: true` (`ci.yml:71-97`).
- `docs/architecture.md:105` calls the test a "compilation test". It is not one.

**Verdict: ADAPT.** The principle is right for Owen: the Rust core's facts, diagnostics and renderers must not depend on LSP protocol types, so the core stays usable by `own-cli`, Owen.Build and any future server. Enforce it more strongly than Snipper does. Options:
- `cargo tree -e normal -p <core crate>` in CI, failing on `lsp-types`, `tower-lsp`, `lsp-server` or `async-lsp`;
- `cargo-deny` `[bans]` scoped to the core crates;
- a crate-graph rule.

Keep LSP position conversions (UTF-16 columns) in the adapter only, as Snipper does.

## 9. Roslyn sidecar

**Evidence.** `sidecar/Snipper.Roslyn/Program.cs` is a net8.0 self-contained single-file executable (`Snipper.Roslyn.csproj:5-13`) using `Microsoft.CodeAnalysis.CSharp` 4.9.2 (`:18`). It reads newline-delimited JSON-RPC requests until stdin EOF (`Program.cs:26-59`). It supports one method, `receiverType {source, offset}`. For each request it:
- parses the **single file** passed in the request (`:63`);
- builds a fresh `CSharpCompilation` with three BCL references only (`:64-67,99-106`);
- walks up to a `MemberAccessExpressionSyntax` and returns the receiver type, its interfaces and its base chain as display strings (`:69-97`).

There is no project or workspace, no NuGet references, and no caching between requests. Further problems:
- **Offset unit mismatch.** Rust sends a UTF-8 byte offset (`lib.rs:284,300`; ADR-0007 `:60-61`), but `root.FindToken` expects a UTF-16 position (`Program.cs:71`). The two diverge whenever a non-ASCII character comes before the cursor.
- The ADR's "Roslyn workspace initialisation" warm-up (`docs/adr/0007-roslyn-sidecar-protocol.md:30-32`) describes a workspace that does not exist.
- Exceptions are converted to `types: []` (`Program.cs:46-47`).

**Overlap with Owen's extractor: yes, and Owen's is the stronger component.** Owen's C# extractor (`Own.NET/frontend/roslyn/OwnSharp.Extractor`) already builds real compilations from project inputs and emits facts to the Rust core. Snipper's sidecar is a per-keystroke single-file semantic query with incomplete references.

**Verdict: REJECT.** Do not import it, its protocol or its lifecycle. One idea is noted only as a future consideration: degrading gracefully to syntax-only behavior when semantic data is unavailable. Owen's diagnostics contract is authoritative, so any such degradation would have to be explicit and visible, never silent as it is in Snipper (`lib.rs:87-95`, ADR-0007 `:38-40,105-110`).

## Not adopted as backbone

Snipper's LSP (`snipper-lsp` plus the VS and VS Code thin clients) is **not** a candidate for Owen's mandatory spine. Reasons:

1. **Wrong product shape.** Owen's authoritative path is a batch pipeline: the extractor emits facts, `own-cli` renders human/github/msbuild/sarif output, and the run sets an exit code. It must work under `dotnet build`, in CI and on headless agents with no editor. An LSP spine would make a long-lived, editor-session-scoped process the center of a system whose main consumer is a build.
2. **Snipper's LSP is an editor-completion adapter, not a diagnostics server.**
   - It does not publish diagnostics (`lib.rs:185-206`: completion, code actions and executeCommand only).
   - It has no document versioning (section 5) and no cancellation design (section 4).
   - It has no lifecycle robustness (section 2).
   - Its configuration contract has drifted: `initializationOptions.roslynPath` is ignored (`lib.rs:178` vs `extension.ts:53-63`, ADR-0008 `:41-42`).

   Adopting it would mean rebuilding most of it.
3. **It conflicts with Owen's locator rule.** Every Snipper client ends in PATH discovery (section 1). A backbone built on it would reintroduce exactly what D3 prohibits.
4. **Sequencing.** Owen.VisualStudio and an Owen LSP/diagnostic server are explicitly future work. If they arrive, they should be thin clients of Owen's own core, sitting beside Owen.Build, not underneath it. The extension contract (packages declaring themselves to `Owen.Build`) must not depend on any long-lived server.

## Applies to this slice (Owen extension Alpha) vs later

**Matters now (Owen.Build, buildTransitive host, one-shot child processes):**

| Item | Verdict | Action for Alpha |
|---|---|---|
| 1a Binary location | REJECT | Keep `RustCoreLocator` semantics (explicit `OWEN_RUST_CORE` or the one computed packaged path, no PATH, a bad explicit value is a visible error). Apply the same rule to the extractor binary that Owen.Build ships. |
| 1b Bundle native binary at pack time | ADAPT | Pack prebuilt `rust-core/{rid}/own-cli[.exe]`. Fail the pack when any RID binary is missing. Record SHA-256. |
| 1c Per-RID packaging | ADAPT | Derive the RID from the runtime, not from an if/else that defaults to linux-x64. Decide between a fat multi-RID package and per-RID packages. |
| 2b One-shot child lifecycle | ADAPT | Redirect and drain stdout and stderr concurrently. Wait with a timeout. Map the exit code through Owen's ratified codes. Kill the process tree on timeout or MSBuild cancel. Surface stderr into the MSBuild log or crash report, never swallow it. |
| 4 Cancellation (build flavour) | REJECT Snipper's; implement fresh | `ICancelableTask.Cancel()` -> kill the `own-cli` tree. |
| 8 Protocol-type isolation | ADAPT | Add a CI dependency-graph check now, cheaply. It keeps the core usable by a later server without a refactor. |

**Only for a future Owen.VisualStudio / Owen LSP server:**
2a (long-lived server lifecycle, which needs a fresh design), 3a (StreamJsonRpc header framing), 5 (version rejection, which needs a fresh design), 6a/6b/6c (mock-VS tests, two-pipe fake server, dedicated-hive smoke), 6d and 7 (VS Code client and headless tests, not on the roadmap).

**Not applicable at any stage:** 2c and 3b (sidecar lifecycle and line-delimited RPC), 9 (Roslyn sidecar; Owen's extractor already covers this ground with real compilations).
