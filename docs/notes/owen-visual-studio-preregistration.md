# OX-02 preregistration: one generic `Owen.VisualStudio` host

Fixed **before** any product code. A change to anything below is an **Amendment** appended at
the end, dated, with its reason; nothing above the amendments is edited after the commit.

## 0. Base

- Base: `main` = `e889f8b37f04f94446855f0c7924521d28d8bb94` (merge of #397, OX-01). Verified present: `frontend/roslyn/Owen.Build`, `frontend/roslyn/Owen.TypedBuilder`, `spec/OwenExtension.md`, `scripts/owen_extension_gate.py`, `OwnSharp.Cli/BuildCheckCommand.cs`, `frontend/roslyn/OwenRustCore.props`, `docs/notes/owen-extension-alpha-report.md` (verdict `GO_OWEN_EXTENSION_ALPHA`).
- Nothing in the areas OX-02 touches (extractor input, build host, Rust core renderers) moved since OX-01: the plan in `owen-extension-ide-feasibility.md` (E1) stands, with its two blockers (unsaved buffers, resident process) as the first work.
- Baseline gates on `e889f8b`, run in a clean worktree (results in §11).

## 1. Read before planning

- OX-01 contract: `spec/OwenExtension.md` (descriptors, capabilities, OWENB codes, manifest), `owen-extension-alpha-preregistration.md`, `owen-diagnostics-model.md` (the `Finding` model, the missing column on the msbuild line), `owen-extension-ide-feasibility.md`.
- `docs/howto-visual-studio.md`: today's VS path is the build host; Error List rows come from canonical MSBuild lines on build.
- Microsoft VSSDK samples (pattern only, nothing copied): `ErrorList` (an `ITableDataSource` registered on `StandardTables.ErrorsTable`, entries as `TableEntriesSnapshotBase` with `StandardTableKeyNames`), the `IErrorTag` tagger pattern (`ITaggerProvider` + `TagsChanged`).
- Snipper (`PhysShell/snipper` 43b395a, MIT): `extensions/snipper-vs` (SDK-style VSIX csproj with `Microsoft.VSSDK.BuildTools`, `scripts/vs-smoke.ps1` real-IDE smoke, mocked-VS tests). Reuse inventory in §9.

## 2. What is built (architecture)

    Visual Studio (devenv, net472)
      Owen.VisualStudio (VSIX, MEF; ONE project, knows no extension)
        | reads   <project>/obj/owen/live.txt      (written by Owen.Build: §3)
        | snapshot of the Roslyn workspace: unsaved text of open documents + source-generated documents
        v  framed JSON over the child's stdin/stdout (owen-live/1, §4)
      `dotnet exec <Owen.Build package>/tools/net8.0/any/ownsharp.dll serve`   (long-lived)
        = the build host's own code path (descriptor validation, input set, refusals)
        + InProcessExtractor: the ONE extractor program, run in-process over an overlay
        -> facts (OwnIR v2 + extension facts) -> packaged Rust core `own-cli ownir --format sarif`
        <- findings: the core's Finding, unchanged

- **One frontend.** The extractor is not copied, ported or wrapped in a second implementation. `OwnSharp.Extractor` gains `InProcessExtractor.Run(args, cwd, overlay)`: the same program with the same arguments, whose one source read consults an in-memory overlay first. The CLI, `owen build-check` and `owen serve` all run that program.
  - *Why not `Analyze(Compilation)`:* the VS host runs on .NET Framework inside devenv; the extractor is .NET 8 and builds its own compilation (TPA + project `bin/` references). Handing it a VS `Compilation` object across a process boundary is impossible, and building the facts from a different compilation would be a second frontend semantics. The snapshot crossing the boundary is therefore **text** (path -> contents), and the compilation is built by the one extractor exactly as on the CLI.
- **P1 kill-first result (measured before this commit, the only code written before it).** The extractor *is* separable without a semantic rewrite. Its process-global state is four statics: two were already reset at entry (`BodyThrowEdges`, `WeaverOwnedFiles`), two were not (`GuardedFactsViolations`, `OrphanedAwaitables.Sites`) and now are; its one source read (`File.ReadAllText` in the parse loop) consults the overlay. `tests/check_extractor_in_process.py`: 98 extractor jobs (every sample, every protocol case, 6 flag combinations, the OrderBackend project) run in ONE process, forward and reversed, are byte-identical to the command line's facts and exit codes; an overlay equal to the disk changes nothing; an overlay that differs is read instead of the disk and equals the command line over the same contents on disk: **198/198**. No STOP.
- **One host contract.** `owen serve` reuses `BuildCheckCommand`'s descriptor validation, input-set rule (project + the declared generators' output), refusal canonicalisation and capability list. Nothing about any extension is in the service or the VSIX.
- **One engine.** The Rust core decides; the VSIX and the service only carry its `Finding` (via the existing SARIF renderer, pinned by BR-V9) to the editor.
- **No new packaging.** The service is the `ownsharp.dll` already inside `Owen.Build` (`tools/net8.0/any/`, Rust core included). The VSIX ships no core, no extractor, no Python; it needs `dotnet` (already required by Owen.Build) and a project that references `Owen.Build` through any extension.
- Extensions never ship VS code. There is no `Owen.TypedBuilder.VisualStudio` / `Owen.Memory.VisualStudio` / `Owen.Types.VisualStudio`; a future extension gets the IDE transport by declaring a descriptor, exactly as it gets the build host.

## 3. How the VSIX learns the active extensions (P6) without a build

- `Owen.Build.targets` gains target `OwenLiveRequest` that writes `obj/owen/live.txt` in the **same key/value format** as the build host's `request.txt`, from the **same items**: `project`, every `descriptor` (`@(OwenExtensionDescriptor)`), `generated-root`, `severity`, plus `host` (the package's `ownsharp.dll`) and `dotnet` (`$(DOTNET_HOST_PATH)` when MSBuild knows it).
- It runs in **design-time builds** (which Visual Studio performs on project load without the user building) and in normal builds. It does nothing else: no analysis in a design-time build.
- No `live.txt` (Owen.Build not referenced, `OwenEnabled=false`): the VSIX does nothing for that project. `live.txt` present but the service rejects a descriptor (OWENB002/003/004, e.g. an unknown required capability): that OWENB diagnostic is shown live, as an Error List row on the descriptor (K7); never a silent skip.

## 4. Process model and protocol `owen-live/1`

- **Process.** One service process per `host` path (projects on the same Owen.Build version share it), started lazily by the VSIX on the first analysis, `DOTNET_ROLL_FORWARD=Major`, no window, stdin/stdout piped for the protocol, stderr captured into the VSIX's output pane (never discarded). Killed with devenv (Windows job object, `KILL_ON_JOB_CLOSE`) so it is never orphaned.
- **Framing.** Every message both ways is `Content-Length: <n>\r\n\r\n` + `n` bytes of UTF-8 JSON. Nothing else is ever written to the service's stdout: the service replaces `Console.Out` with stderr at start-up and writes frames to the raw stdout stream only.
- **Handshake.** First client frame `{"type":"hello","protocol":"owen-live/1"}`; the service answers `{"type":"hello","protocol":"owen-live/1","host":"<version>","capabilities":[...]}`. Any other protocol string, a malformed header, a non-JSON body, an unknown `type`: the service writes one `{"type":"fatal","message":...}` frame when it still can, prints the reason to stderr and exits **3**. The client treats a `fatal` frame or EOF as service death (K6). No guessing, no resynchronisation.
- **Requests.** `{"type":"analyze","id":n,"key":"<project path>","version":v,"request":"<live.txt path>","documents":[{"path","text"}],"generated":[{"path","text"}]}` — `documents`: the open documents of the project, with their current (unsaved) text; `generated`: the project's source-generated documents with the path Roslyn gives them. `{"type":"cancel","id":n}`; `{"type":"shutdown"}` (exit 0).
- **Responses.** `{"type":"result","id":n,"key","version","status":"ok"|"superseded"|"cancelled"|"error","diagnostics":[...],"timing":{...}}`.
- **Determinism.** Same request -> same diagnostics in the same order (the core's order; host diagnostics first, in the build host's order).

## 5. Cancellation and versioning contract (P7, K4)

- **Client.** Each edit of a project's open document (re)starts a **250 ms** debounce for that project. When it fires, the client takes ONE workspace snapshot, assigns `version = ++counter[project]` and sends `analyze`. A response is **published only if** its `version` equals the latest version issued for that project; anything older is dropped on arrival, whatever its order of arrival. Diagnostics are always mapped onto the text snapshot the request was taken from and translated forward with tracking spans; a buffer edited after the request keeps the last published result until the newer one arrives.
- **Service.** Requests run one at a time. A queued `analyze` for a key that has a newer queued `analyze` is answered `superseded` without running; `cancel` of a queued request answers `cancelled`. A running analysis is not interrupted mid-extraction (the extractor is not cancellable) — its answer is dropped by the client rule above.
- **Stale never reappears:** a response with version N arriving after N+1 was issued is never shown (K4; mutation M1 removes the version check and K4 must go red).

## 6. Diagnostic contract (P4) and the coordinate gap

- **Carried per diagnostic:** `code`, `severity` (error|warning, the host's `OwenSeverity` applied by the core exactly as for the build), `message` (the core's text, byte-identical to the msbuild line's), `file` (absolute), `line`, `column` (when known), `origin` (`core` | `host`), `source` = `Owen`, `extension` (the active extension ids of the project; a finding is not attributed to one extension, because the core does not attribute it), `related` (`file`, `line`, `column?`, `message`: the core's witness/flow steps).
- **Source:** the core's `Finding` through `own-cli ownir --format sarif` (existing, pinned renderer): `ruleId`, `level`, `message.text`, `region.startLine/startColumn`, `codeFlows`/`relatedLocations`. Host conditions (OWENB) come from the build host's own records, not parsed from text.
- **Gap 1 — columns.** `Finding.column` exists, but the state-protocol lowering emits lines only (`ProtocolLowering.Line`), so OWN002 has **no column** in the facts or the finding. Adding columns to the protocol ops would change facts bytes and the core's pinned output: forbidden here (P2, P13). **Coordinate contract (narrowest):** when the core gives a column, the span starts there; when it gives none, the span is the line's text without leading/trailing whitespace, and the column shown is that span's first character (1-based). The VSIX computes it from the snapshot the request was taken from; it is a coordinate, never a verdict. The build's msbuild line has no column at all: **declared renderer difference** for the parity test.
- **Gap 2 — where OWN002 points (issue #393).** For a stale state token the core reports the finding at the **region entry** (`OrderProtocol.WithDraft(order, draft =>`), and its witness step "used here after it was released/returned" at the stale use (the second `draft.Submit(now);`). Moving the primary location is a core change (forbidden, #393 stays open). The VS host therefore shows the finding **once in the Error List at the core's location** (identical to the build's row), and draws a squiggle at the primary span **and at each witness step** of the same finding, with the step's message. The squiggle on the second `draft.Submit(now);` is the core's witness step, not a location the VSIX derived. This is the acceptance's "squiggle on the second Submit".

## 7. Acceptance scenarios

Fixture `tests/owen-live/LiveFixture/`: a net8.0 project with `PackageReference Owen.TypedBuilder` (local feed, as in the OX-01 gate), an `Order` declared for the generator, and `Use.cs` whose `Run` has ONE `draft.Submit(now);` in a `WithDraft` region (clean). Synthetic second extension `tests/owen-extensions/Owen.TestProtocol/` (never shipped): a descriptor + its own incremental generator that emits a different protocol (`Turnstile`) as generated source.

| id | scenario | pass | where |
|---|---|---|---|
| K1 | unsaved edit that stays clean | no OWN row, no OWN tag; Owen ran (a result for that version arrived) | service tests + VS run |
| K2 | unsaved edit inserting a second `draft.Submit(now);` | OWN002 Error List row (file, line = region entry, column per §6), squiggle tags at the primary span and on the inserted line, no save, no build | service tests + **VS run** |
| K3 | delete the inserted line (unsaved) | the OWN002 row and every tag disappear | service tests + **VS run** |
| K4 | response N delivered after N+1 | N is never published; final state = N+1's | client unit test (scheduler/gate) |
| K5 | syntax-broken edit | no crash, no stale-looking verdict: a result arrives (findings or an OWENB010 refusal row, as the build would give for the same text); the next good edit recovers | service tests |
| K6 | the service dies | one operational Error List row `OWENV001` (Owen live analysis stopped: exit code, stderr tail); restart on the next edit, at most 3 restarts in 5 minutes, then the row stays and says live analysis is off until the solution is reopened. Never silent. | client unit test + service kill test |
| K7 | an active extension requires an unknown capability | OWENB004 row live, on the descriptor; no analysis claimed | service tests |
| K8 | two extensions (Typed Builder + Owen.TestProtocol) | both protocols' findings live, no change to the service or the VSIX | service tests (+ VS run if the second fixture is opened) |
| P9 | `CS1061` and OWN002 at once | both rows in the Error List; Owen never converts a CS diagnostic | **VS run** |
| P10 | build/live parity | for the same saved source: `dotnet build` OWN rows == live diagnostics on (code, severity, message, file, line); a live-only or build-only OWN verdict fails | `scripts/owen_live_gate.py` |

**"Live"** means: the diagnostics reflect the text in the editor, unsaved, within the latency budget, without a save, a build or any user command.

## 8. Latency and resources (P15) — thresholds fixed now

Measured on the CI Windows runner in the real VS run (and on Linux for the service alone), on the small fixture:
- cold start (service spawn + hello + first analysis): report only;
- warm analysis inside the service (extractor + core): **p95 < 750 ms**;
- edit -> squiggle visible (end of debounce included): **p95 < 1 s** (over >= 10 edits); NO_GO if the warm small-project diagnostic takes several seconds;
- clean edit -> disappearance: **p95 < 1 s**;
- burst of 20 keystrokes 30 ms apart -> exactly 1-2 analyses run, the last version published;
- UI thread: no Owen handler longer than **50 ms** (stopwatch around every UI-thread callback, max reported);
- service working set after 100 analyses: **< 2x** the working set after 10 (no unbounded growth).

## 9. Snipper reuse (P11) — ADAPT only, MIT, origin recorded in each file

| chunk | origin | how |
|---|---|---|
| SDK-style VSIX project skeleton (`Microsoft.VSSDK.BuildTools`, pkgdef/vsix properties) | `extensions/snipper-vs/Snipper.VisualStudio/Snipper.VisualStudio.csproj` | ADAPT |
| real-IDE smoke: vswhere instance pick, deploy with `DeployVsixExtensionFiles` into a dedicated root suffix (never the shared `Exp`), restart-after-registration relaunch, activity-log evidence | `extensions/snipper-vs/scripts/vs-smoke.ps1` | ADAPT |
| test project compiling the VSIX's VS-independent sources by `<Compile Link>` | `Snipper.VisualStudio.IntegrationTests.csproj` | ADAPT (pattern) |
| NOT reused | LSP client spine, PATH fallback binary locator, Snipper commands, its process lifecycle (stderr lost, no orphan protection: rejected in the OX-01 audit) | — |

## 10. Real Visual Studio (P14)

- Probe on `windows-latest` (this branch, run 37163037704): **Visual Studio Enterprise 2026, 18.10**, with the extension-development workload, `devenv` and `VSIXInstaller` present, interactive session. A DTE object is obtained, but calls were rejected during first launch: the first-run experience must be handled (UI Automation dismissal or settings preseed) — this is infrastructure work, not product.
- Supported target: VS 2022 17.10+ and VS 2026 (`InstallationTarget [17.10,19.0)`); proven on whatever the runner has (18.x). VS 2022 unproven unless a run happens.
- The VS run (`scripts/vs/owen-vs-acceptance.ps1`, workflow `owen-vs.yml`): build + deploy the VSIX into a dedicated root suffix; pack Owen.Build / Owen.TypedBuilder into a local feed; restore the fixture; launch devenv; drive it with DTE: open `Use.cs`, insert the second `draft.Submit(now);` through `EditPoint` (unsaved), poll the Error List (`ErrorItems`: description, file, line, column, project), `Navigate()` the OWN002 row and read the caret line/column, delete the line, poll until gone. The tagger's tags are observed through an opt-in trace (`OWEN_LIVE_TRACE=<file>`: one JSON line per tag set the tagger publishes — file, snapshot version, line, column, length, code) since DTE cannot read tags. A screenshot of the squiggle is kept.
- **GO without a passing real VS run is forbidden.** If the runner cannot be driven, the verdict is NO_GO with that measured blocker.

## 11. Gates kept green

`tests/run_tests.py`, ruff, mypy, `cargo fmt/clippy/test`, `protocol_gate --rust`, `heap_effects_gate`, `typed_builder_gate --rust`, `owen_extension_gate` (55/55), Owen.Cli packaging, the P-022 merge gate. Plus new: `tests/check_extractor_in_process.py` (E1–E4), `scripts/owen_live_gate.py` (service + parity + K-scenarios on Linux and Windows), the VS run.

Baseline on `e889f8b` (clean worktree): filled in by Amendment 1 when the runs finish; a pre-existing red is recorded, not fixed.

## 12. Mutation controls

| id | mutation | must turn red |
|---|---|---|
| M1 | the client ignores `version` (publishes every response) | K4 |
| M2 | the service cannot start (bad host path) | the OWENV001 row appears (K6 test) |
| M3 | wrong line/column mapping (off by one) | navigation/coordinate test (VS run and the client coordinate unit test) |
| M4 | the service routes generated files only for `Owen.TypedBuilder.Generator` | K8 (Owen.TestProtocol's finding missing) |
| M5 | live renders with a different verdict path (e.g. severity forced, or msbuild text parsed with a different message) | P10 parity |
| M6 | the unsaved document is read from disk | K2 (service test) and E4 |

## 13. Out of scope

VS Code, an LSP server, Rider/ReSharper, code fixes/lightbulbs, hover/explain UI, the Memory/TypeDisciplines extensions, a second aggregate in Typed Builder, BCL summaries, typed write targets, whole-solution incremental analysis (the unit is one project), Marketplace publishing, analysis of a brand-new file that was never saved (the input set is the project's files on disk; their contents come from the editor), columns for state-protocol findings (#393 / the facts), live analysis before the first design-time build of a project.

## 14. Verdict

`GO_OWEN_VISUAL_STUDIO_ALPHA` only if all hold: an unsaved edit goes through the one extractor and the authoritative core to OWN002, a squiggle, an Error List row with navigation to the reported location, and disappears when the line is deleted — in a real Visual Studio; the parity gate passes; K1–K8 pass where registered; thresholds of §8 hold; mutations M1–M6 go red. Otherwise `NO_GO_OWEN_VISUAL_STUDIO_ALPHA` with the exact measured blocker. After GO: STOP.
