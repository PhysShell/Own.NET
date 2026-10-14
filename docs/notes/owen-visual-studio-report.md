# OX-02 report: one generic `Owen.VisualStudio` host

Preregistration: `owen-visual-studio-preregistration.md` (committed before product code, plus
Amendment 1). Base `main` = `e889f8b` (OX-01). Verdict at the end.

## 1. What was built

| piece | where | what it is |
|---|---|---|
| extractor as a library | `OwnSharp.Extractor/InProcess.cs` (+ 2 resets and the overlay look-up in `Program.cs`) | `InProcessExtractor.Run(args, cwd, overlay)`: the ONE extractor program run inside a long-lived process; an unsaved buffer is read instead of its file |
| shared host contract | `OwnSharp.Cli/OwenHost.cs` | descriptor validation, input set, refusals, manifest: one implementation for `build-check` (byte-identical output) and `serve` |
| the live service | `OwnSharp.Cli/ServeCommand.cs`, `LiveAnalysis.cs` | `owen serve`, protocol `owen-live/1` (framed, versioned, fatal on malformed input, newest-per-project wins); findings are the Rust core's, via its SARIF renderer |
| the live request | `Owen.Build/build/Owen.Build.targets` (`OwenLiveRequest`) | `obj/owen/live.txt` from the SAME request lines as the build, written by design-time builds too |
| the VS host | `frontend/roslyn/Owen.VisualStudio` (VSIX, one project, knows no extension) | workspace snapshots (unsaved open documents + Roslyn's in-memory generated documents) → supervised service → version gate → `IErrorTag` squiggles + `ITableDataSource` Error List rows |
| synthetic extension #2 | `tests/owen-extensions/Owen.TestProtocol` | its own generator and protocol (a turnstile): K8 and M4 |
| gates | `tests/check_extractor_in_process.py`, `scripts/owen_live_gate.py`, `tests/owen-live/LiveClientTests`, `scripts/owen_live_mutations.py`, `scripts/vs/*` | see §3 |

No change to OwnIR, H0/H1, the state protocol, T0/P-022, diagnostic meanings or OX-01
capability semantics. The Rust core is untouched.

## 2. Two coordinate facts (preregistration §6)

- **No column for state-protocol findings.** The protocol lowering emits lines only, so OWN002 carries none. The VS host applies the registered contract: the span is the reported line without surrounding whitespace, and the column shown is its first character. In VS the Error List row navigates to `Use.cs` 10:9, exactly that.
- **Where OWN002 points (#393, unchanged).** The core reports a stale state token at the region entry (`OrderProtocol.WithDraft(order, draft =>`, line 10). Its witness step "used here after it was released/returned" is the stale use (the inserted `draft.Submit(now);`, line 13). The Error List shows the finding once, at the core's location, as the build does. The squiggle is drawn at both: the one on the inserted line is the core's witness step, not a location the VSIX derived.

## 3. Evidence

### 3.1 Extractor as a library (P1/P2) — `tests/check_extractor_in_process.py`, 198/198
- 98 extractor jobs: every sample, every protocol case, 6 flag sets, OrderBackend.
- Run in ONE process, forward and reversed: facts and exit codes are byte-identical to the command line's (E1/E2).
- An overlay equal to the disk changes nothing (E3).
- An overlay that differs is read instead of the disk and equals the command line over the same contents on disk (E4).
- CI `owen-live`: green on Ubuntu and Windows.

### 3.2 The service (Linux and Windows CI) — `scripts/owen_live_gate.py`, 27/27
- **L0:** a design-time build writes `live.txt` naming the package's service. No `bin/`, no build request, no manifest: nothing analysed. Generated sources stay in memory only.
- **S:**
  - stdout carries frames only;
  - a bad protocol, a bad header, a non-JSON body or an unknown type each gives a `fatal` frame and exit 3;
  - clean shutdown exits 0.
- **Scenarios:**
  - K1 clean, unsaved;
  - K2 OWN002 at the region entry with a witness on the inserted line, disk still clean;
  - K3 gone;
  - K5 broken syntax answered, next edit recovers;
  - K4s queued 6/7/8 → `ok, superseded, ok`, cancel → `cancelled`;
  - K7 an unknown capability gives OWENB004 live;
  - K8 Typed Builder + Owen.TestProtocol, both protocols' OWN002, no host change.
- **P10 parity:** build lines == live diagnostics on (file, line, severity, code, message) for clean / stale (OWN002) / copy (OWN005) / raw entity (OWN013) / refused (OWENB010).
- **T (Linux):**
  - warm round trip p50 105 ms, p95 208 ms (threshold 750); in the service extract ≈ 88 ms and core ≈ 2 ms;
  - cold start 1.7 s;
  - working set 432 MB after 10 analyses, 455 MB after 100 (threshold 2×).
- **C (client half, against a real `owen serve`), 13/13:**
  - coordinates;
  - one Error List row plus a witness squiggle;
  - K4 (a late answer is never published; M1 control);
  - bursts coalesce (20 edits 30 ms apart → 1 analysis);
  - K6 (a crash is shown, the next request restarts, after 3 restarts in the window it stays off and says so);
  - M2 control.
- **G:** neither the service nor the VSIX names an extension.

### 3.3 Mutations (M1–M6) — `scripts/owen_live_mutations.py`, 6/6 caught
| | mutation | caught by |
|---|---|---|
| M1 | publish every answer | K4-stale-dropped |
| M2 | swallow a service that cannot start | M2-cannot-start |
| M3 | coordinates off by one | coord-no-column, coord-column |
| M4 | route only Typed Builder's generator | K8-two-extensions |
| M5 | live forms its own severity | P10-parity-stale/copy/raw |
| M6 | read the unsaved document from disk | K2-unsaved-own002 (and E4) |

### 3.4 Real Visual Studio (P14) — CI job `owen-visual-studio`, Visual Studio Enterprise 2026 18.10 on `windows-2025-vs2026`
**19/19 on the final product head `fbdc978`** (run 37175674769; evidence kept in
`evidence/ox02-visual-studio/`). The solution is restored and never built. The VSIX is
installed with `VSIXInstaller` into the image's `Exp` hive. The IDE is driven as a user would
drive it:
- edits go through DTE `EditPoint`, never saved;
- the Error List is read through UI Automation;
- navigation is a double-click on the row;
- squiggles come from Owen's own tagger trace and are visible in the screenshots.

| check | result |
|---|---|
| vsix-loaded | Owen.VisualStudio composed in devenv (its trace: `Owen live analysis loaded`) |
| L0 | Visual Studio's own design-time build wrote `obj/owen/live.txt`; no build ran |
| K1 | first publication: 0 entries; an unsaved clean edit: analysed, 0 OWN entries |
| **K2 squiggle** | `10:9+39 'OrderProtocol.WithDraft(order, draft =>'` (finding) and `13:13+18 'draft.Submit(now);'` (witness, the inserted line), `Use.cs` unsaved |
| **K2 Error List** | `OWN002 \| IDisposable local 'draft' is used after it is disposed [resource: disposable] \| LiveFixture \| Use.cs \| 10` |
| **K2 navigation** | double-click → `Use.cs` line 10 column 9 = the registered coordinate |
| P9 | `CS0029 … Use.cs 10` beside the OWN002 row |
| **K3** | line deleted → no OWN002 tag after 344 ms; the row is gone |
| edit → squiggle | 10/10, p95 **349 ms** (threshold 1000); 328–349 ms with the 250 ms debounce included |
| edit → disappearance | 10/10, p95 **347 ms** (threshold 1000) |
| UI thread | longest Owen handler **3.3 ms** (threshold 50) |
| service in VS | 26 analyses; cold (first) 4.9 s; warm median **58 ms**, p95 76 ms, max 150 ms; working set 169 → 203 MB |
| no-build / never-saved | no `LiveFixture.dll`, no build request; `Use.cs` on disk byte-identical to the fixture |
| no-orphan | `owen serve` did not outlive a killed devenv (job object) |

The same product code also passed 19/19 on `90bd419` (run 37174835723: p95 399/413 ms, UI
4.8 ms). Run 37174809967 on `7cdf529` (same product code) failed one check,
K2-navigation, with the caret at exactly 10:9 = expected. The driver's path comparison is
now normalised and prints both paths; it passed on `fbdc978`. Not counted as a pass.

**What the IDE run took** (Amendment 1): the Error List read through UI Automation (DTE
`ErrorItems` returned 0 in VS 2026), the `Exp` hive plus first-run dialog dismissal, a MEF
cache rebuilt after install, and the editor kept in front. One product fix came out of it:
`TagsChanged` now raises on the UI thread and the tagger reports its exceptions.

## 4. Gates kept green
Final head, CI run 37175674769: **every job green**, Ubuntu and Windows. That includes:
- lint (ruff + mypy --strict);
- tests on Python 3.11/3.12/3.13 (`run_tests.py`, P-037 pins included);
- rust fmt/clippy/tests;
- the state-protocol gate, the heap-effects gate and the typed-builder gate;
- `owen_extension_gate` (55/55 on both platforms);
- Owen.Cli gate A on both platforms, and the Stage-1 engine controls;
- Rust-default dogfood;
- the new `owen-live` job (Ubuntu + Windows) and `owen-visual-studio`.

Locally `run_tests.py` shows the same two pre-existing local-only Stage-1 controls as on the
base (Amendment 1).

## 5. Snipper reuse
`owen-visual-studio-snipper-reuse.md`: four ADAPTed chunks (VSIX project shape, manifest, the
real-IDE smoke's instance/hive/relaunch shape, link-compiled tests). Nothing copied verbatim;
the LSP spine, PATH fallback, commands and lifecycle are not reused.

## 6. Verdict
**GO_OWEN_VISUAL_STUDIO_ALPHA.**

In a real Visual Studio 2026, an unsaved edit goes through the shared Roslyn frontend (the ONE
extractor, in-process, over the editor's text and Roslyn's in-memory generated sources) to the
authoritative Rust core. The result is OWN002: a live squiggle on the inserted
`draft.Submit(now);` (the core's witness step) and at the finding's location, and an Error List
row with exact navigation to the reported location. Deleting the line removes them. No save,
no build.

For the same saved source, build and live agree on code, severity, message, file and line
(P10, five sources). K1–K8, M1–M6 and the §8 thresholds hold. The VS host and the service
name no extension; Owen.TestProtocol, a second extension with its own generator, works with
no host change.

Known and registered:
- OWN002 points at the region entry, with the stale use as its witness step (#393, unchanged);
- state-protocol findings have no column (the narrowest coordinate contract applies);
- a never-saved new file is not in the input set;
- live analysis starts after the project's first design-time build;
- proven on VS 2026 18.10 only; VS 2022 17.14 is declared by the manifest but was not run.

STOP here, per the brief.
