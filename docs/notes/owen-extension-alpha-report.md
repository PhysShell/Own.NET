# OX-01 — Owen extension substrate with Typed Builder as extension #1: report

**VERDICT: `GO_OWEN_EXTENSION_ALPHA`.**

| | commit |
|---|---|
| base (`main`, TB-MVP-01 merged, #391) | `88cb8cc31c49d730290613208947102d0737cad2` |
| preregistration + Snipper audit | `49f5493` ([`owen-extension-alpha-preregistration.md`](owen-extension-alpha-preregistration.md)) |
| implementation + Amendment 1 (before any official run) | `6e65bfb` |
| gate fix (Windows: paths on two drives; gate mechanics only) | `89bdb86` |
| notes, E2 spike | `48c71e6` |
| this report | the head of the PR |

## What a user does now

```
dotnet new web -n OrderBackend
dotnet add package Owen.TypedBuilder --version 0.1.0
dotnet build
```

1. **Generation.** The typed API is generated on every compilation by a Roslyn incremental generator: `DraftOrder.Submit`, `OrderProtocol.WithDraft`, `Order.Create().Customer(…).Build()`.
2. **Compiler errors.** An illegal transition is a compiler error: `CS1061 'DraftOrder' does not contain a definition for 'Approve'`.
3. **Owen findings on build.** A stale state token is an Owen finding, reported by the build in the canonical MSBuild form and so in Visual Studio's Error List:
   `…/C8_stale_draft.cs(18): warning OWN002: …`
   It is a `warning` by default and an `error` with `OwenSeverity=error`.
4. **The project names its extensions** in `obj/owen/extensions.json`.

None of it needs Python, a Rust toolchain, a global `owen`, a checkout, an environment
variable, or a PATH lookup of an Owen binary.

## Architecture as built

```
Owen.TypedBuilder (package, extension #1)
  ├─ analyzers/: Owen.TypedBuilder.Generator — Roslyn incremental generator
  │              (shares TypedBuilderCore.cs with the CLI generator: one model, one renderer)
  ├─ build*/:    owen-extension.json + <OwenExtensionDescriptor> item
  └─ depends on ─────────────────────────────┐
                                             ▼
Owen.Build (package, the GENERIC host: names no extension)
  ├─ build*/Owen.Build.targets: after the build → `owen build-check`
  └─ tools/net8.0/any/: the Owen.Cli program + bundled extractor + rust-core/<platform>/own-cli
                         │
                         ▼
          the authoritative Rust core (`own-cli ownir --format msbuild`)
```

- **No `Owen.Toolchain` or `Owen.CoreAssets`.** `Owen.Build` is the one host package. It exists because a tool package cannot be a `PackageReference` (NU1212, observed) and because every extension must share one engine.
- **The platform inventory** lives in one `frontend/roslyn/OwenRustCore.props`, imported by both `Owen.Cli` and `Owen.Build`.
- **The host entry point** is a new `owen build-check` subcommand of the same program. It reuses `owen check`'s extractor and engine runner; it neither copies them nor renders findings.
- **The contract:** [`spec/OwenExtension.md`](../../spec/OwenExtension.md) and its JSON schema.
- **Generator delivery: A**, a Roslyn incremental generator, chosen on measurement (preregistration K-3). B was absent from the design-time build that Visual Studio's IntelliSense uses.

## Official runs

| run | where | result |
|---|---|---|
| `scripts/owen_extension_gate.py` from a fresh `git worktree` of `6e65bfb` (no `bin/`/`obj/`) | local Linux x64 | **55/55 PASS** |
| the same gate on `6e65bfb` | server CI `owen-extension`, ubuntu-latest | **55/55 PASS** |
| the same gate on `6e65bfb` | server CI `owen-extension`, windows-latest | **FAIL before any check.** The gate's own outside-checkout test called `os.path.commonpath` on a `D:` checkout and a `C:` temp directory and raised. Fixed in `89bdb86`, gate mechanics only. |
| the same gate on `48c71e6` | server CI `owen-extension`, ubuntu-latest | **55/55 PASS** |
| the same gate on `48c71e6` | server CI `owen-extension`, windows-latest | **55/55 PASS**: the `win-x64` core, absolute `C:\…\C8_stale_draft.cs(18)` origins, Exec through `cmd` |
| server CI run 37149198078 (`48c71e6`) | all jobs | **36/36 success**, including `owen CLI (gate A)` on both platforms, `state protocols` on both, lint, tests ×3, rust, formal kernel |

## Counts (Linux official run)

| | |
|---|---|
| packages | 2 shipped (`Owen.Build`, `Owen.TypedBuilder`) + 1 synthetic test extension |
| isolation | consumer PATH = the `dotnet` dir + `sh` only; `python`/`python3`/`py`/`cargo`/`rustc`/`owen` resolve to nothing; fresh `HOME`/`NUGET_PACKAGES`; `Owen.*` mapped to the candidate feed only; the consumer outside the checkout; no checkout path in any build output |
| A | build ok; the generated `Order.Protocol.g.cs` = `#nullable enable\n` + the committed golden (6880 bytes); the manifest lists `Owen.TypedBuilder 0.1.0` with its 4 capabilities; the clean sample has no Owen diagnostic |
| B | `draft.Approve(…)` → CS1061 `'Approve'` |
| C | `OwenSeverity=error` → `…/C8_stale_draft.cs(18): error OWN002: …`, build fails |
| D | the origin is the **absolute** path of the staged file, line 18; the default severity gives the same line as `warning OWN002`, and the build succeeds |
| F | **30/30** corpus cases through the package: compiler-stage CS codes, extractor refusals as `OWENB010`, core refusals as `OWENB011`, verdicts `OWN002`/`OWN005`/`OWN013`, positives clean, the P5/P8 `proven_call` present, K1 `OWN001`, K2 clean |
| G | the TB-MVP acceptance runner against the package-built consumer: **44/44**, transcript **byte-identical** to `samples/OrderBackend/evidence/acceptance.txt` |
| H | `Owen.TestExtension` beside `Owen.TypedBuilder`: the manifest lists both, and the project is analysed once (1 `OWN002`) |
| M1a | the declared descriptor deleted → `OWENB002`, no `OWN002` |
| M1b | the whole declaration deleted → `OWENB001` ("no Owen extension is active"), no `OWN002` |
| M2 | unknown capability `teleportation` → `OWENB004` |
| M3 | the bundled `own-cli` deleted → `OWENB005` (never a clean build) |
| M4 | `requires.ownir: 3` → `OWENB003`; `requires.host: 9.0.0` → `OWENB003` |
| M5 | the host target emptied → no `OWN002`, so the C check catches the absence |
| M6 | consumer with no checkout → E holds |
| M7 | the host sources (`Owen.Build/**`, `BuildCheckCommand.cs`, `OwenRustCore.props`) contain `TypedBuilder` 0 times |

## Existing guarantees kept

On the implementation commit:
- `typed_builder_gate.py --rust`: 8/20/2 corpus, 44 checks ×2, transcript `ba447304cdf957ee`, 0 failures. The CLI generator now runs on the shared core and still writes the golden byte for byte.
- `protocol_gate.py --rust`: 0 failures, 29 documents byte-identical on both CLIs.
- `heap_effects_gate.py`: unchanged; the extractor is untouched.
- `ruff` and `mypy` clean.

**`tests/run_tests.py` locally:**
- `fresh-record-valid` fails only on a dirty tree, by design.
- Two stage-1 controls (`divergence-is-5`, `exec-failure-is-5`) fail **on the owen surface only**, and only once a launcher is built locally. In the base run they were skipped ("no built launcher"). A launcher built from the **base** commit `88cb8cc3` fails them identically, so this is pre-existing and not caused by this change. The server CI is authoritative for it.

**Foundations.**
`git diff --stat 88cb8cc3..HEAD -- ownlang rust spec/OwnIR.md spec/Bridge.md spec/ownir.schema.json frontend/roslyn/OwnSharp.Extractor docs/evidence/calibration scripts/perf_baseline.py`
is **empty**. No OwnIR, ownership, state-protocol, H0/H1, T0, P-022 harness, `OWN` code or core
change.

**`Owen.Cli` payload** (Amendment 1.2), measured against a pack of the base commit with the
same staged core:
- identical **file list**, 109 entries;
- every Roslyn assembly, `deps.json`/`runtimeconfig.json`, vendored `.py` and the Rust core **byte-identical**;
- only `ownsharp.dll`/`.pdb` (gains `build-check`), `ownsharp-extract.dll`/`.pdb` (commit-stamped build metadata; source unchanged) and the nuspec `repository commit` differ.

Gate A (`owen-cli` install → `owen check` → `OWN001`) runs in server CI on both platforms.

## Snipper salvage (P1)

[`owen-extension-snipper-salvage.md`](owen-extension-snipper-salvage.md), read-only at `43b395a`, MIT. **For this slice:**
- **REJECT** its binary discovery (setting → bundled → PATH with silent fall-through), the long-lived VS process lifecycle, and the Roslyn sidecar.
- **ADAPT** pack-time bundling with a hard fail, already `OwenRustCore.props`, and one-shot child discipline. MSBuild's Exec kills the child tree on cancellation; `owen` drains both streams and maps exit codes.
- **Later only:** StreamJsonRpc framing (COPY), mocked-VS and two-pipe fake-server tests, the thin VS Code client shape.

## Diagnostics model (P8)

[`owen-diagnostics-model.md`](owen-diagnostics-model.md). The model already exists:
`own_bridge::Finding` → `render_finding` (human/github/msbuild) / `build_sarif`. No new layer
was built. The host only absolutises the origin path.

**Recorded gaps, not changed:**
- the msbuild line has no column although `Finding` has one;
- the state-protocol wording and line (#393).

## IDE (P9/P10)

[`owen-extension-ide-feasibility.md`](owen-extension-ide-feasibility.md):
- **E1 (generic VSIX): NOT EXECUTED.** There is no Windows or Visual Studio here. It is specified, with its two blockers: extractor overlay input for unsaved buffers, and a resident process.
- **E2 (native Roslyn analyzer): REJECT.** Measured on Linux:
  - shadow copy defeats default native resolution;
  - only an explicit path through reflection-reached `NativeLibrary` works, and only on .NET-hosted compilers;
  - the extractor cannot run inside an analyzer.
- **Invariant:** one `Owen.VisualStudio`, one Owen server, extension ≠ IDE plugin.

## Findings worth carrying forward

1. **Top-level statements.** A region in top-level statements is not modelled by the extractor. The TB-MVP acceptance runner has one, and the host refuses it with `OWENB010` instead of skipping it, which is correct fail-closed behaviour. The gate builds that runner with `OwenEnabled=false`.
2. **`buildTransitive` reach.** It makes every project that references an Owen-enabled project Owen-enabled too. That is intended (the same analysis everywhere) and documented. A project opts out with `OwenEnabled=false`.
3. **A system shell.** MSBuild's `Exec` needs a system shell (`sh` on Unix, `cmd` on Windows). That is not a toolchain dependency, but the isolation harness must provide it.
4. **Windows console encoding.** On Windows the core's em dash in a refusal text reaches the build log as `-`: `build-check` writes through the console encoding. The codes, locations and gate checks are unaffected. The fix is to emit UTF-8 explicitly (`Console.OutputEncoding` plus Exec `StdOutEncoding`); it is left for a follow-up, not changed after the official run.

## Verdict

**`GO_OWEN_EXTENSION_ALPHA`**, on `48c71e6`. Every condition registered for GO holds:

| registered condition | evidence |
|---|---|
| `PackageReference Owen.TypedBuilder` → generated API | A on Linux and Windows: generated text = `#nullable enable` + golden; manifest written |
| → CS diagnostics | B, plus the 10 compiler-stage corpus cases |
| → OWN diagnostics on build | C/D, plus the core-stage corpus cases, as canonical, absolute, navigable MSBuild lines |
| → no external toolchain or setup | E: a stripped PATH, fresh HOME/NuGet, outside the checkout, no checkout path in any output, on both platforms |
| → generic extension discovery proven | H (two extensions, one analysis), M7 (the host names no extension), M1a/M1b/M2/M3/M4/M5 (fail loud) |
| existing TB-MVP guarantees | F (30/30 through the package), G (44/44, transcript byte-identical), `typed_builder_gate` unchanged |
| foundations unchanged | the foundation diff is empty; `protocol_gate`/`heap_effects_gate`/`cargo` green |
| Windows + Linux server CI | 36/36 |

**After GO: STOP.** None of the following is started:
- a production VSIX, LSP or VS Code extension;
- the Memory or TypeDisciplines extensions;
- BCL summaries (#394), typed write targets (#395), affine tokens (#392), diagnostic wording (#393), concurrency (#396);
- a second aggregate;
- a repo-wide rename.

**For publishing:** nothing was pushed to nuget.org. The license blocker that gates `Owen.Cli` gates these two packages too.
