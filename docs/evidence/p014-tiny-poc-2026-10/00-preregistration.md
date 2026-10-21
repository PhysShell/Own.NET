# P-014 Tiny PoC — pre-registration

Written 2026-10-21 11:10 +05, before the instrument exists and before any measuring run. Base: `main` `228e38d7`
(merge of #421). Owner decision: `GO-P014-TINY-POC`, with production still NO-GO.

**Budget.** 0.25 agent-day, counted from 11:00. STOP at 13:00, not extended. When the budget runs out, I commit
the evidence I have and the verdict is `INCONCLUSIVE-P014-TINY-POC`, unless a KILL condition has already been
met.

**Verdict.** Exactly one of `PASS-P014-TINY-POC`, `KILL-P014-TINY-POC`, `INCONCLUSIVE-P014-TINY-POC`. After a
KILL I stop and keep the evidence. Conditions are not changed to reach a PASS.

## 0. Environment change, recorded before the first run

The host's .NET installation was replaced at about 10:59–11:00 today. I did not make this change.

| | Before (#419, #421) | Now |
|---|---|---|
| SDK | 10.0.401 | **11.0.100-rc.2.26504.105** only |
| `Microsoft.NETCore.App.Ref` / `WindowsDesktop.App.Ref` / `AspNetCore.App.Ref` | 8.0.31, 10.0.12 | **8.0.32, 10.0.13**, 11.0.0-rc.2 |

Consequences, fixed now:
- **P4 and P5** resolve against 10.0.13. Their assets record no pack patch, so their status is
  `PACK_MAJOR_MINOR` (DESIGN §2 D1).
- **The #419 B manifests** (10.0.12) are no longer reproducible byte for byte, and their pack-DLL hashes are
  expected to differ. The comparison with #419 is therefore made by **assembly simple name**, not by hash.
- **API identity between 10.0.12 and 10.0.13** cannot be checked, because 10.0.12 is gone. That remains an open
  question.

## 1. The mechanism under test (research instrument only)

A new research program in `instrument/`, built offline. It never touches the extractor, the core, OwnIR, CI or
goldens.

**Unit.** One SDK-style `PackageReference` project at one target. Each unit gets:
- its own `CSharpCompilation`;
- its own source set, which is the extractor's text resolution (`ProjectCsFiles` rules, ported);
- default `CSharpParseOptions`, the same as the extractor: **no defines and no implicit usings in any real
  project**;
- its own references.

Project references become `CompilationReference`s to the referenced unit's compilation, built first.

**Target selection.** Use the RID-less key of `targets` in `obj/project.assets.json`.
- One key: that key.
- More than one: `--tfm` is required, otherwise `UNSUPPORTED(multi-tfm)`.
- RID keys are ignored for compile.
- For a referenced project, take the target whose framework equals the root's target entry `framework`. If there
  is no unique match, the result is `SOURCE_SET_INCOMPLETE(p2p-target)`.

### Framework references (contract: dotnet/sdk `ResolveTargetingPackAssets`)

- **Targeting packs.** Each name in `project.frameworks[alias].frameworkReferences` maps to a targeting pack:
  - `Microsoft.NETCore.App` → `Microsoft.NETCore.App.Ref`;
  - `Microsoft.AspNetCore.App` → `Microsoft.AspNetCore.App.Ref`;
  - `Microsoft.WindowsDesktop.App[.WPF|.WindowsForms]` → `Microsoft.WindowsDesktop.App.Ref`, profile
    `WPF`/`WindowsForms`;
  - `Microsoft.Windows.SDK.NET.Ref.Windows` → NuGet `Microsoft.Windows.SDK.NET.Ref`, profile `Windows`.

  Any other name gives `UNSUPPORTED(framework-reference)`.
- **Pack version.**
  - The exact version in `downloadDependencies` if listed (`PACK_EXACT`).
  - Otherwise the highest installed patch of the target's `major.minor` (`PACK_MAJOR_MINOR`).
  - None installed: `REFERENCE_MISSING(pack)`, with no substitution.
- **Files** come from the pack's `data/FrameworkList.xml`:
  - skip `Type="Analyzer"` and `ReferencedByDefault="false"`;
  - when a profile is requested, take only files whose `Profile` list contains it (files with no `Profile` are
    skipped);
  - with no profile, take all;
  - the path is the pack root plus `Path`.
- **Conflict item.** `AssemblyVersion` and `FileVersion` come from FrameworkList; the package id is the pack id.
- **Overrides.** The pack's `data/PackageOverrides.txt` makes the **pack id** override each listed package up to
  its version, inclusive.

### Package references

- Every `type: package` entry of the chosen target, `compile` items only, `_._` excluded, from the global
  packages folder.
- Absent: `REFERENCE_MISSING(package)`.
- Content hash differs from `.nupkg.metadata` `contentHash`: `REFERENCE_MISSING(package-identity)`.
- `AssemblyVersion` and `FileVersion` are read from the DLL itself.

### Conflict rule (contract: dotnet/sdk `ResolvePackageFileConflicts` + `ConflictResolver`)

References conflict when their **file names** are equal, case-insensitive. A pair is decided by the first rule
that applies:
1. package override, as above;
2. if one file is missing: unresolved;
3. higher `AssemblyVersion`; if only one has one: unresolved;
4. higher `FileVersion`; if only one has one: unresolved;
5. package rank. The SDK's `PackageConflictPreferredPackages` list is not on disk in a form I read, so a framework
   item beats a package item here **as an assumption**, labelled `TIE_FRAMEWORK_ASSUMED` and counted;
6. platform item (not reached for compile references from targeting packs);
7. otherwise `CONFLICT_UNRESOLVED`. The unit is then not `COMPLETE`.

Two package items with equal versions are `CONFLICT_UNRESOLVED`. The copy-local tie-break is a runtime rule and is
not used.

### Source-set completeness (separate axis, never merged with references)

`SOURCE_SET_INCOMPLETE(<reason>)` is set when any of these hold:
- `UseWPF`/`UseWindowsForms` with `.xaml`/`.resx` designer generation;
- a package with `analyzers/dotnet/cs`;
- framework generator attributes in the sources: `LibraryImport`, `GeneratedRegex`, `JSImport`/`JSExport`,
  `GeneratedComInterface`;
- `Directory.Build.props` or `Directory.Build.targets` above the project;
- a non-empty `DefineConstants`;
- `ImplicitUsings` set to `enable` or `true` (reported, **not applied**);
- a project-reference member without assets.

### Coverage sidecar (DESIGN §4)

- **Per unit:**
  - status, reasons and manifest (with chosen conflict winners);
  - site counts for invocations, types and event `+=`, with `unresolved_no_marker` (G1);
  - disposable-type sites, with `name_heuristic` (G2);
  - compiler errors by id;
  - file counts.
- **Site status:**
  - `SYMBOL_RESOLVED`: `Symbol != null`, no error type in the containing type, and no error diagnostic
    intersecting the site;
  - `SYMBOL_AMBIGUOUS`: `CandidateReason` ambiguous with ≥ 2 candidates, or CS0104/CS0121/CS0229/CS0433 at the
    site;
  - `UNRESOLVED`: otherwise.
- **Format.** Deterministic JSON: sorted, relative paths, no timings.

**Built-in isolation check.** Every `SYMBOL_RESOLVED` symbol must have a containing assembly that is either:
- the unit itself;
- an assembly of the unit's own manifest; or
- a unit in its own closure.

Every other case is counted as `foreign_binding`.

**Modes.**
- `exact-project` (above).
- `legacy-merged`: today's extractor shape. One compilation over all units' sources; references are the running
  process's TPA, first file name wins. It is used as the cost baseline and the comparison.

## 2. Controls (expected results fixed now)

**In-memory, unit level** (the boundary and site classification; real Roslyn, synthetic references):

| # | Control | Expected in exact-project |
|---|---|---|
| K1 | consistent BCL-only unit | `foreign_binding = 0`; no change vs legacy at its sites |
| K2 | `Lib` 1.0 in U1, 2.0 in U2 | each unit binds its own version; no CS1704 |
| K4 | `Dup.T` in U1 and U2; U3 → U1, U2 | legacy-merged: CS0101. U3's site `SYMBOL_AMBIGUOUS` via CS0433. U2's `One()` `UNRESOLVED` (CS1061) |
| K5 | external `event` and `int` field, both `+=` | event counted `event`, field `non_event` |
| K6 | type from an absent assembly | `UNRESOLVED`; `foreign_binding = 0` |
| K7 | `#if NET8_0 … #else … #endif` | `#else` branch seen (no defines); reported as a source-set limit |
| K-iso F2.3 | implicit usings in U1 only | U2 `File.Exists` `UNRESOLVED` |
| K-iso F2.4 | `Timer` | U2 binds `System.Timers.Timer.Elapsed` (event) |
| K-iso F2.5 | U3 lacks `Dep` | U3 site `UNRESOLVED`; `foreign_binding = 0` |
| K11 | unresolved `x.E += (s, e) => {}` and `+= new EventHandler(H)` | `unresolved_no_marker = 2` |
| K12 | unresolved `FooStream` field | `name_heuristic = 1`, not counted resolved |

**On disk, assets level.**
- Synthetic projects under `fixtures/`, restored **offline** by the local SDK with the global packages folder as
  the only source.
- These are my own fixtures, not third-party code.
- The SDK's own resolved compile references (`ReferencePathWithRefAssemblies` after `ResolveAssemblyReferences`)
  are the **oracle**. The oracle is used only to judge the instrument; it is not part of the mechanism.

| # | Control | Expected |
|---|---|---|
| K3 | `net8.0` + `System.Collections.Immutable` 9.0.0 (has `lib/net8.0` and `lib/netstandard2.0`) | compile asset `lib/net8.0` |
| **K8a** | `net8.0` + `System.Collections.Immutable` 9.0.0 and `System.Reflection.Metadata` 9.0.0 | **package wins** both (AssemblyVersion 9 > 8). Instrument == oracle |
| **K8b** | `net8.0` + `System.Text.Json` 8.0.5 | instrument == oracle (override list or version decides). Expected framework wins, by override or version |
| **K8c** | `net10.0-windows` with `UseWPF` only | no `System.Windows.Forms.dll` in the manifest (profile). Instrument == oracle on the framework file set |
| K9 | `net8.0;net10.0` | `UNSUPPORTED(multi-tfm)` without `--tfm`; with `--tfm net8.0` the manifest == oracle for that TFM |
| K10 | root → child project reference, child's `obj` removed after restore | root `SOURCE_SET_INCOMPLETE(p2p-no-assets)`; child types `UNRESOLVED`, not invented |

**K8 pass condition.** The instrument's set of reference **file names**, with the chosen **assembly identity**
(name + version), equals the oracle's for K8a, K8b, K8c, K9 and K3. Analyzers are excluded on both sides.

## 3. Real projects (#419 anchors)

**P4** BB84.IPTV `BB84.IPTV.M3U.Editor` (closure of 3) and **P5** FluentFlyout, from the same on-disk trees as
#419. No restore and no build.

Measured per project:
- unit statuses and reasons;
- manifest;
- binding coverage;
- compiler errors;
- `foreign_binding`;
- for each #419 R3 site of these projects (P5 OWN014 `SettingsManager.Current.PropertyChanged`, P5 OWN001
  `mediaManager`, P5 `window.SourceInitialized`, P4 `dialog.Closed`, P4 `desktop.Startup`/`desktop.Exit`), its
  binding status.

**Comparison with #419 B** (by simple name, §0):
- call sites bound in #419 B and not in exact-project are listed;
- each of the first 10 such sites, in sorted order, is read.

**Cost.**
- 3 separate processes per mode × project.
- Each process does a **cold** iteration (first in process) and a **warm** iteration (a second full build of all
  units, same process).
- Recorded: wall time per iteration and the process peak working set.
- Reported: medians.
- Context only, not a criterion: today's extractor on the same `.csproj`, built offline from `228e38d7`.

## 4. Decision (thresholds fixed now)

**`PASS-P014-TINY-POC`** only if all of the following hold:
1. **Isolation.**
   - `foreign_binding = 0` in every control and in P4/P5.
   - K2, K4, F2.3, F2.4 and F2.5 as expected.
   - No silent false binding in any control.
2. **References.** K8a, K8b, K8c, K9 and K3 equal the oracle. `TIE_FRAMEWORK_ASSUMED` is never needed in K8. K10
   as expected.
3. **Honest coverage.**
   - K5, K6, K7, K11 and K12 as expected.
   - Every sidecar invariant (DESIGN §4) holds.
   - Two runs of the same input give byte-identical sidecars.
4. **Real projects.**
   - P4 and P5 complete without a crash.
   - Each unit's reference status is `COMPLETE` with `PACK_MAJOR_MINOR`, or a named non-`COMPLETE` reason.
   - Every #419-B-bound, exact-unbound site that was read has a stated cause.
   - No such site is a wrong binding of exact-project.
5. **Cost.**
   - P5 exact-project **warm** median ≤ 3 × legacy-merged warm median.
   - Peak working set ≤ **2.0 GB** and ≤ 3 × legacy-merged peak, for P4 and P5.
6. **Boundary.** No change under `frontend/`, `ownlang/`, `rust/`, `spec/`, `tests/`, `.github/` or `scripts/`.

**`KILL-P014-TINY-POC`** if any of:
- a `foreign_binding` or a silent false binding in any control or real project;
- an instrument/oracle mismatch in K8a/K8b/K8c/K9/K3 that the contract rule above cannot explain;
- the cost limits in item 5 are exceeded;
- a forbidden action is needed (third-party restore or build, network, MSBuild evaluation of a third-party
  project, production change).

**`INCONCLUSIVE-P014-TINY-POC`** if:
- the budget runs out first; or
- a criterion cannot be decided because an input is unavailable (for example, the SDK oracle cannot restore a
  fixture offline).

## 5. What I will not claim

- Correctness of symbols that were not read.
- That `PACK_MAJOR_MINOR` equals the pack the project was built with.
- Any diagnostic or verdict effect: the extractor is not run with the new mechanism, and no finding is produced by
  it.
- Generality beyond P4/P5 and the fixtures.

## Amendment 1 (11:15 +05, before the instrument exists and before any run)

The #419 per-site B lists were never committed (only `r0_r1_summary_P*.json` / `r2_summary.tsv`), and the #419 work
folder no longer exists. The per-site comparison in §3 and the item-4 reading are therefore replaced as follows:
- **Against #419 B.** Counts only: resolved calls and types per project, compared with `r0_r1_summary_P4/P5.json`
  B.
- **Per-site regression check.**
  - Every call or type site that is `SYMBOL_RESOLVED` in this instrument's `legacy-merged` mode and **not** in
    `exact-project` is listed (`lost_sites`).
  - The first 10 in sorted order per project are read. Each must have a stated cause: the legacy binding was
    wrong (net8 implementation, a foreign unit, etc.), or the exact binding is missing for a named reason.
  - **An unexplained lost site counts against item 4.**

No threshold, control or KILL condition changes.
