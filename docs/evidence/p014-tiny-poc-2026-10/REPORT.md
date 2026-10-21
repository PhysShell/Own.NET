# P-014 Tiny PoC — report

**Verdict: `PASS-P014-TINY-POC`.** All six pre-registered criteria hold (§6).
- This is a PASS for a **research instrument** that measures binding. It is not a PASS for any change to the
  extractor, OwnIR or public diagnostics, and it produces no findings.
- Production stays NO-GO.

Rules: [`00-preregistration.md`](00-preregistration.md).
- Commit `5a9bb32`, 11:04:52 +05. The "11:10" in its header is my clock reading; the commit time is
  authoritative.
- Amendment 1 is commit `207ef84`, 11:06:54. Both were committed before the instrument existed.

Base `main` `228e38d7`. Work: 11:00 to about 11:25 +05 on 2026-10-21, inside the 0.25 agent-day budget.

Labels used below:
- **[run]** measured here;
- **[read]** checked by reading code or diagnostics;
- **[doc]** dotnet/sdk source;
- **[inference]** not verified.

## 1. What was built

`instrument/` contains a research program (Roslyn 4.9.2, the extractor's version), built offline. For one root
`.csproj` it does the following:
- **Graph.** It reads the existing `obj/project.assets.json` of the root and of every project-reference member,
  and builds **one `CSharpCompilation` per project**. Project references become `CompilationReference`s.
- **References.** Each unit's references are selected by the pre-registered contract (§1 of the
  pre-registration):
  - targeting-pack `FrameworkList.xml` with profiles;
  - package `compile` assets with the content-hash identity check;
  - conflicts keyed by file name, decided in the dotnet/sdk order: overrides → AssemblyVersion → FileVersion →
    (rank/platform).
- **Output.** It writes the deterministic coverage sidecar (DESIGN §4), with a built-in isolation guard.
- **Source set.** It uses the extractor's own text rules, with default parse options. **No implicit usings and no
  defines are applied to any real project.** They are only reported.

No restore or build of third-party code, no network, no MSBuild evaluation of P4/P5. The SDK was run only as an
**oracle on my own synthetic fixtures**, restored offline with the global packages folder as the only source.

## 2. Environment change (recorded before the first run)

The host's .NET was replaced at about 11:00, and I did not make the change:
- SDK 10.0.401 became 11.0.100-rc.2;
- packs 8.0.31/10.0.12 became 8.0.32/10.0.13.

P4/P5 therefore resolve as `PACK_MAJOR_MINOR` against 10.0.13. Whether 10.0.12 and 10.0.13 have the same API
cannot be checked any more.

## 3. Controls

**In memory** [run, `data/fixtures/controls.json`]: K1, K2, K4, K5, K6, K7, F2.3, F2.4, F2.5, K11, K12 and the guard
self-test all **PASS**.

| Control | Observed |
|---|---|
| K2 | `Lib` 1.0 / 2.0: each unit binds its own version; no CS1704 |
| K4 | merged: CS0101. Per unit: U2's `One()` unresolved + CS1061. U3 referencing U1 and U2: type site **ambiguous via CS0433** |
| F2.3 | U2's `File.Exists` unresolved (no leaked implicit usings) |
| F2.4 | U2 binds `System.Timers.Timer.Elapsed` (event) |
| F2.5 | U3 without `Dep`: unresolved, foreign = 0 |
| GUARD | the merged shape's binding of U3's event, judged against U3's own manifest: flagged (3 foreign symbols) |
| K11 / K12 | `unresolved_no_marker = 2` (lambda, `new EventHandler`); `name_heuristic = 1`, not counted resolved |

**On disk, against the SDK oracle** [run, `data/fixtures/*.compare.json`]. The SDK oracle is
`FindReferenceAssembliesForReferences` → `ReferencePathWithRefAssemblies`. Both sides are compared by path and
assembly version.

| Control | Instrument vs oracle | Conflicts decided |
|---|---|---|
| K8a (`net8.0` + SCI/SRM 9.0.0) | **163 = 163**, identical | both packages win, rule `assembly-version` (9.0.0.0 > 8.0.0.0) |
| K3 (same fixture) | compile asset `lib/net8.0`, same as oracle | — |
| K8b (`net8.0` + System.Text.Json 8.0.5) | **163 = 163** | framework wins, rule `file-version` (equal AssemblyVersion 8.0.0.0) |
| K8c (`net10.0-windows`, WPF only) | **206 = 206**; no `System.Windows.Forms.dll` | `WindowsBase.dll` pack copy by `assembly-version` |
| K9 (`net8.0;net10.0`) | without `--tfm`: `UNSUPPORTED(multi-tfm)`; with `--tfm`: 163 = 163 and 167 = 167 | — |
| K10 (project reference) | with child assets: two `COMPLETE` units, event resolved; child `obj` removed: root `SOURCE_SET_INCOMPLETE(p2p-no-assets:Child)`, event unresolved, foreign = 0 | — |

`TIE_FRAMEWORK_ASSUMED` was never needed.

**Not covered by the oracle:** a **package-vs-package** conflict. P5 has one (`Wpf.Ui.dll`, decided by
`assembly-version`), and it was not checked against a real build.

## 4. Real projects P4, P5 (#419 anchors)

**Status** [run, `data/real/P*.exact.sidecar.json`]. All 5 units (P4 root + 3 project-reference members, P5)
have:
- reference status `COMPLETE`;
- `PACK_MAJOR_MINOR`;
- `foreign_binding = 0`;
- no failed invariants;
- no CS0433/CS1704/CS0012/CS0518.

All are `SOURCE_SET_INCOMPLETE`, with named reasons:

| Reason | Units |
|---|---|
| `package-analyzers:*` (generators from packages, e.g. `bb84.sourcegenerators`, `communitytoolkit.mvvm`) | all 5 |
| `directory-build:*` | all 5 (P4 sets `ImplicitUsings` in its own `Directory.Build.props`; P5's only hit is a **host** file above all repositories, `source/repos/Directory.Build.targets`, so the detector is conservative) |
| `wpf-xaml-codegen`, `define-constants`, `implicit-usings-not-applied`, `framework-generator:LibraryImport` | P5 |
| `framework-generator:GeneratedRegex` | P4 Application |

**Binding coverage, `exact-project` vs `legacy-merged`** (today's shape inside the same instrument) [run]:

| | P4 (4 units) | P5 |
|---|---|---|
| invocations resolved | **1798 / 2901 (62.0%)** vs 729 / 2901 (25.1%) | **1284 / 2003 (64.1%)** vs 643 / 2003 (32.1%) |
| type sites resolved | 1597 / 2341 vs 1183 / 2341 | 775 / 1049 vs 299 / 1049 |
| `+=` bound to an event | 23 of 34 (1 unresolved) vs 7 (17 unresolved, 13 with no OWN050 marker) | 33 of 65 (8 unresolved, all without marker) vs 7 (34 unresolved, 19 without marker) |
| disposable-type sites | 24 resolved, 0 by name vs 0 | 13 resolved + 3 by name vs 3 + 3 |
| methods whose relevant sites all resolve | 20 / 23 | 23 / 37 |
| error diagnostics | 1667 vs 2595 | 1352 vs 2741 |

**Comparison with #419 B** (counts only, per Amendment 1):
- **P5.** Same denominator, 2003 calls. #419 B resolved 1272; exact-project resolves 1284, under the stricter rule
  that no error may sit on the site. #419 B had 59 × CS0433 "between two framework references"; exact-project has
  0. The cause is probably the WPF profile filter [inference].
- **P4 root.** #419 counted 353 calls over 23 files. The extractor's rules, and so this instrument, exclude
  `Properties/Resources.Designer.cs`, which holds 129 `GetString`/`GetObject` calls [read]. Hence 223. Type-site
  definitions differ between the instruments, so type counts are not compared.

**Sites resolved in legacy and not in exact (`lost`)** [run, `data/real/P*.lost.json`, `P4.lost.diag.txt`]:
- **Counts.** P5: 0. P4: 22. All 22 were read, more than the 10 required.
- **Cause.**
  - `ImplicitUsings=enable` is set in P4's `Directory.Build.props` and is not applied (owner rule). So `Task`,
    `Exception`, `IDisposable` and `IHttpClientFactory` are error types **in the Application unit's own
    declarations**.
  - Across the `CompilationReference`, the root reports them **at the use site**: CS0246 at 15 call and type
    sites. In Infrastructure, the interface signatures no longer match their implementations: CS0535 at 7 base-list
    sites.
  - The legacy merged compilation binds the same methods and types, but reports the error only once, at the
    declaration, so it counts a call whose signature contains error types as "resolved".
- **Verdict.** In every case exact-project's result is **unresolved, not a different symbol**. None is a wrong
  binding. The difference is an **over-count in legacy**: a source-set limit shows up honestly per project instead
  of being hidden.

**The 7 #419 R3 sites** [run, `data/real/R3.sites.txt`] are all `+=` sites bound to an `IEventSymbol` in
exact-project:

| Site | Bound event |
|---|---|
| P5 actionable OWN014 | `CommunityToolkit.Mvvm.ComponentModel.ObservableObject.PropertyChanged` |
| P5 FP | `Window.SourceInitialized` |
| P4 FPs | `IControlledApplicationLifetime.Startup`/`.Exit`, `TopLevel.Closed` |
| P5 TP-benign `mediaManager` field | type `WindowsMediaController.MediaManager`, resolved |

The six FPs are therefore correctly bound events, which confirms DESIGN §5: their precision problem is the
lifetime model, not references. No finding was computed and none changed: the extractor was not run with this
mechanism.

## 5. Cost

[run, `data/real/*.timing.json`]. Each figure is the median of 3 separate processes; each process runs a cold
iteration (first build in the process) and a warm iteration (second full build, metadata cache kept). Peak is the
highest process peak working set.

| | legacy cold / warm | exact cold / warm | exact / legacy warm | peak (legacy / exact) |
|---|---|---|---|---|
| P4 (4 units) | 2260 / 1611 ms | 2031 / 1642 ms | 1.02× | 232 / 202 MB |
| **P5** | 1548 / 969 ms | 1776 / 1386 ms | **1.43×** (limit 3×) | 209 / 208 MB (limit 2.0 GB, 3×) |

**Context only** [run, `data/real/extractor_context.log`]. Today's extractor, built offline from `228e38d7`, with
`--flow-locals --no-project-refs`:
- P4: about 1.0 s, about 171 MB;
- P5: about 2.5 s, about 202 MB.

**Its facts are byte-identical across 3 runs** (P4 `AD528B8A1E92F4C8…`, P5 `5F0EA76DA86C623A…`). The instrument never
touches them.

## 6. Verdict against the pre-registered criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Isolation: `foreign_binding = 0` everywhere; K2, K4, F2.3, F2.4, F2.5 | **holds**; guard self-test catches the merged-shape binding |
| 2 | References: K8a/b/c, K9, K3 = oracle; no tie assumption; K10 | **holds** |
| 3 | Honest coverage: K5, K6, K7, K11, K12; invariants; byte-identical sidecars on rerun | **holds**: sidecars identical across 3 processes for every mode × project |
| 4 | Real projects: complete without crash; named statuses; every lost site read has a cause, none a wrong binding | **holds**: 22/22 read, one cause |
| 5 | Cost: P5 warm ≤ 3× legacy; peak ≤ 2.0 GB and ≤ 3× legacy | **holds**: 1.43×; about 208 MB |
| 6 | Boundary: nothing outside `docs/evidence/p014-tiny-poc-2026-10/` | **holds** (`git diff --stat 228e38d7`) |

**`PASS-P014-TINY-POC`.**

## 7. Deviations and defects (disclosed)

1. **Amendment 1.** The #419 per-site B lists were never committed. Per-site comparison was replaced by legacy →
   exact lost sites, before any run.
2. **Instrument defects, fixed before any real-project run:**
   - a type node inside `new T()` has no `TypeInfo`, so `GetSymbolInfo` is used;
   - the K1 check depended on probe order (the observation was already correct);
   - the comparator read the oracle's package version from `AssemblyVersion` metadata, which is empty for
     packages; `FusionName` is used instead.
3. **A first fixture run used a stale binary.** The fixtures had been copied inside the instrument's build folder,
   so the build picked up their `.cs` files and failed. That run was discarded. Every reported fixture result comes
   from `scripts/run_fixtures.ps1` on a clean folder.
4. **The `diag` mode** (errors and sites on one line) was added after the real runs, for cause analysis only. The
   measured `project`/`lost` code is unchanged from commit `35e2c8c`.
5. **Source-set detection is conservative and coarse:**
   - any `Directory.Build.*` above the project counts, including a host file;
   - `ImplicitUsings` set in `Directory.Build.props` is reported only as `directory-build`.

## 8. What this does not show

- Any effect on findings, precision or OwnIR: nothing was emitted or judged.
- Package-vs-package conflict correctness, the rank/platform steps, and RID-specific or `netstandard`/.NET Framework
  targets.
- That `PACK_MAJOR_MINOR` (10.0.13) equals the pack P4/P5 were built with.
- Generality beyond P4, P5 and the fixtures. P1–P3 were not run.
- The cost of very large closures. P4 has 4 units.

## 9. Files

- `00-preregistration.md`, `REPORT.md`
- `instrument/`: `Units.cs` (assets, packs, conflicts, source set), `Coverage.cs`, `Controls.cs`, `Program.cs`,
  `P014Poc.csproj`
- `fixtures/`: K8a, K8b, K8c, K9, K10, my own synthetic projects
- `scripts/`: `run_fixtures.ps1`, `run_real.ps1`, `run_extractor_context.ps1`, `compare_oracle.py`
- `data/fixtures/`: controls, sidecars, oracle comparisons, log
- `data/real/`: sidecars (run 1 of each mode), all timing files, lost sites, diagnostics at lost sites, R3 sites,
  logs

Local paths are replaced by `<nuget>`, `<dotnet>`, `<research>` and `<work>`. The oracle JSON files themselves are
not committed; their comparison results are.
