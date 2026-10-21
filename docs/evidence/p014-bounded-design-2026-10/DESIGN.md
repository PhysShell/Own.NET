# P-014 bounded design — reference resolution without false confidence

**Verdict: `GO-P014-TINY-POC`** (§7).
- The GO covers a coverage-only PoC in a research instrument, outside the extractor.
- It does **not** allow production code, extractor changes or any change to public verdicts.

Rules: [`00-preregistration.md`](00-preregistration.md), commit `a8f3ea37` (07:00 +05, 2026-10-21), written before the
audit and the falsifiers. Base: `main` `ad17d7b2`. #420 (`bf0b4e0a`, open, CI green) was read and not changed.
Work: 06:55–07:10 +05, inside the 0.5 agent-day budget.

No production, OwnIR, core, extractor, CI or golden change. No restore, build or MSBuild evaluation of a
third-party project, and no package download. The only things built are my own falsifier program (§2.2), offline
and with no package feed, and in-memory synthetic assemblies inside it.

Each statement below is marked as one of:
- **[code]**: read in the source at `ad17d7b2`;
- **[run]**: measured by a falsifier in this folder;
- **[#419]**: frozen #419 data, not re-scored;
- **[doc]**: taken from the dotnet/sdk or NuGet source or documentation;
- **[inference]**: my reasoning, not verified.

## 1. Current-state audit (`main` `ad17d7b2`, `frontend/roslyn/OwnSharp.Extractor/Program.cs`)

| Mechanism | What the code does | Where |
|---|---|---|
| Compilation | **One** `CSharpCompilation.Create("own", …)` over every parsed input tree, default `CSharpCompilationOptions(DynamicallyLinkedLibrary)` | `:5983-5985` [code] |
| Parse options | `CSharpSyntaxTree.ParseText(text, path)`: default options, no defines, no generated global usings | `:5867` [code] |
| Framework set | The extractor **process's** `TRUSTED_PLATFORM_ASSEMBLIES`. The extractor targets `net8.0`, so this is the .NET 8 runtime implementation, not the project's TFM reference pack | `:5889-5894` [code] |
| `OWN_EXTRA_REF_DIRS` | Non-recursive; a DLL whose **file name** is already in the set is skipped | `:5901-5910` [code] |
| `--ref-dir` | Recursive, ordinal-sorted, **first file name wins**, failed loads skipped | `:5917-5934` [code] |
| `bin/` auto-reference | For `.csproj`/`.sln` inputs, `<projdir>/bin` is added to the `--ref-dir` list unless `--no-project-refs` | `:426-451`, `:543-549` [code] |
| `.csproj` source set | Text read of the XML: default compile items, `EnableDefaultCompileItems`, `<Compile Include/Remove>`, concrete out-of-tree links; `bin`/`obj`/`*.g.cs`/`*.Designer.cs` skipped. No MSBuild, no `Directory.Build.props` | `:276-370`, `:218-229` [code] |
| `.sln` | Text parse of `Project(...)` lines, fans out to `ProjectCsFiles`; **all projects still go into the one compilation** | `:391-424`, `:471-477` [code] |
| Event fact | `+=` is a subscription iff `GetSymbolInfo(a.Left).Symbol is IEventSymbol`. `Symbol == null` **and** `IsHandler(a.Right)` gives the `unresolved-subscription` marker (OWN050) | `:6155-6156`, `:6368-6379` [code] |
| `IsHandler` | Only `IdentifierName` or `MemberAccess` on the right | `:571-572` [code] |
| Disposable type | `IsOwnedDisposableType` uses the resolved type's real `IDisposable`; **if the type is unresolved it falls back to the name heuristic** `IsDisposableType` | `:5343-5357`, `:5318-5323` [code] |
| `stats` | `facts["stats"]` = `{methods_with_local, methods_flow_analysed, methods_skipped_unmodelled}`, always written; the stderr line is printed only with `--stats`, which requires `--flow-locals` | `:5997`, `:7578-7583`, `:7611`, `:7635-7638`, `:206-209` [code] |
| `stats` consumers | Not read by `ownlang/ownir.py` or by `rust/crates` (grep finds nothing). Not described in the `spec/OwnIR.md` envelope | grep [code] |

**Three gaps relevant to "no false confidence"** (code reading only; not run on a project):

1. **G1. Silent drop of unresolved lambda subscriptions.** For `x.Unknown += (s, e) => …` or `+= new EventHandler(H)`
   with an unresolved left side, `IsHandler(a.Right)` is false, because the right side is not normalised at
   `:6368`. So **neither a fact nor OWN050** is emitted, and nothing counts the site.
2. **G2. Name-heuristic disposables with no marker.** An unresolved field or parameter type such as `FooStream` is
   treated as an owned disposable by name (`:5347`). The resulting fact carries no "type unresolved" mark. Correct
   references therefore **remove** such facts as well as add them. This is consistent with the #419 R3 diffs, but
   that is my inference.
3. **G3. Coverage is invisible to verdicts.** `stats` is producer-only. A run that binds a third of its calls
   produces the same "0 findings" exit as a fully bound one.

## 2. Necessary conditions, cheap falsifiers, KILL ledger

### D1 — achievable correctness: `PASS-NARROWED`

**Necessary condition.** For a bounded input class, the exact compile-time reference set can be derived from data
on disk.

| Sub-question | Finding |
|---|---|
| SDK-style + existing `obj/project.assets.json` | `project.restore.projectStyle` and `targets` give per-TFM package `compile` assets. `_._` means nothing [run, P4/P5 structure dump] |
| Chosen TFM | `targets` has one RID-less key per TFM. RID keys (`net10.0-windows…/win-x64`, P5) carry runtime assets only and must be **ignored for compile** [run]. More than one RID-less TFM: **no guessing**; an explicit `--tfm` is required, otherwise `UNSUPPORTED(multi-tfm)` |
| Runtime vs reference assemblies | Use only `compile` items and the reference pack's `ref/<tfm>`; never `runtime`, `runtimeTargets`, `native` or the process TPA. TPA is today's source of the P1 `TimeSpan.FromHours` net8-overload binding [#419] |
| Reference pack version | Assets record the exact pack version **only** when the SDK had to download it (`downloadDependencies`: P1 `Microsoft.NETCore.App.Ref [9.0.20]`). P4 and P5 have no such entry: the SDK's bundled pack was used and its patch is not recorded [run]. Rule: same `major.minor` pack present, so `tfm_status = PACK_MAJOR_MINOR`. Missing, so `REFERENCE_MISSING(pack)`, **no substitution** (P1's 10.0-for-9.0 becomes `REFERENCE_MISSING`, not `TFM-APPROX`). That a servicing patch does not change the reference API is [inference], not verified |
| Packages | Exact id/version from `targets`; identity via `libraries[*].sha512` = the cache's `.nupkg.metadata` `contentHash` [#419 §8.2]. Absent, so `REFERENCE_MISSING(package)` |
| Project-to-project | Compile asset is `bin/placeholder/X.dll`, **not usable** [run, P1/P4]. Closure is listed in `libraries[type=project].msbuildProject`, and the selected framework in the target entry's `framework` [run, P4: 3 projects, each with its own assets on disk]. So it is resolvable as **source compilations**, not as DLLs |
| Framework vs package conflicts | **Falsifier found, see below** |
| Same simple name, different identity | In one compilation, CS1704, and one side's calls are lost [run F2.2]. Per project, no conflict |

**Falsifier F-D1a: the #419 "framework-first" rule picks the wrong assembly** [run, `falsifiers/d1_conflicts.out.txt`].
- **Input.** `nats-io/nats.net` @ `176e52b`, `sandbox/MicroBench2`, `net8.0`, assets already on disk.
- **The case.** The project references package `System.Collections.Immutable` 9.0.0 and `System.Reflection.Metadata`
  9.0.0. Both are in the cache with AssemblyVersion `9.0.0.0`, against `8.0.0.0` in the 8.0.31 pack.
  `PackageOverrides.txt` covers only versions up to 1.4.0 and 1.5.0.
- **What a real build does.** dotnet/sdk `ConflictResolver.ResolveConflict` applies, in order: package overrides,
  then the higher assembly version, then the higher file version, then package rank, then the platform item [doc].
  So the package wins.
- **What the #419 rule does.** It skips the package, so the compilation binds the 8.0 API.
- **Effect on the #419 data.** For P2, P4 and P5 the rule happens to agree: the framework is newer or covered by
  an override in every conflict. P1 cannot be judged, because its exact pack is missing. **This is not a reason
  to re-score #419.**
- **Resolution.** Replace the rule with the dotnet/sdk order. Its inputs are `PackageOverrides.txt`,
  `FrameworkList.xml` and the DLLs' metadata versions: all on disk, no MSBuild. A pair that the order leaves
  undecided is `CONFLICT_UNRESOLVED`, and the project is not `COMPLETE`.

**Still outside the class** (detected cheaply, never guessed):
- `<Reference HintPath>` and `<COMReference>`;
- `packages.config` or non-PackageReference projects;
- `extern alias` (`Aliases=`);
- source generators and XAML code generation;
- `Directory.Build.props/targets` that set compile options.

Each one sets `UNSUPPORTED` or `SOURCE_SET_INCOMPLETE` (§4), never a silent pass. Generator presence is visible
only from the package folder (`analyzers/dotnet/cs`); the assets target entries carry no `analyzers` key [run, key
dump]. WPF and WinForms code generation (`UseWPF`/`UseWindowsForms`, x:Name fields in `obj/*.g.cs`) is
source-set, not reference.

**No KILL**: no wrong pick in this class needs a project-system clone to avoid.

### D2 — project isolation: `KILL` for one shared compilation, `PASS` for one compilation per project

`falsifiers/Program.cs`, Roslyn 4.9.2 (the extractor's version), `Microsoft.NETCore.App.Ref` 8.0.31. In-memory
synthetic projects: "merged" is today's shape, "per-project" is one compilation per project, with project
references as `CompilationReference`. Output: [`falsifiers/d2_isolation.out.txt`](falsifiers/d2_isolation.out.txt)
[run].

| Case | Merged (today's shape) | Per-project |
|---|---|---|
| F2.1 `Dup.T` in P1 (`One()`) and P2 (`Two()`) | CS0101 once, at compilation level. **P2's `new Dup.T().One()` binds with no site error**: silent false certainty | P2 `One()`: unresolved + CS1061 (correct). P3 referencing both: **CS0433 at the site**, so site-level conflict becomes representable |
| F2.2 `Lib` 1.0 in P1, 2.0 in P2 | first-name-wins: P2's `V2Only()` unresolved; with both: CS1704, P1's `V1Only()` unresolved | both bind to their own version |
| F2.3 ImplicitUsings on in P1, off in P2 | **P2's `File.Exists` binds**: the #407 leak, silent | P2: unresolved + CS0103 (correct) |
| F2.4 `Timer`: P1 implicit usings (`System.Threading`), P2 `using System.Timers` | P2: CS0104; `t.Elapsed` unresolved **with no site error** | P2 binds `System.Timers.Timer.Elapsed` (`IEventSymbol`) |
| F2.5 P3 lacks dependency `Dep`, P1 has it | **P3's `s.Changed += H` binds to `Dep`'s event**: an event fact the project could never compile | P3: unresolved, CS0246 (correct) |

Two observations for the design:
- **Ambiguity is often not a candidate list.** In F2.1/P3 the site has `Symbol == null` and **no**
  `CandidateSymbols`; the conflict is visible only as CS0433 on the site span. F2.4's `Elapsed` has neither.
  Site status must therefore combine `SymbolInfo` with the error diagnostics whose span intersects the site
  (§4).
- **The boundary.** A compilation is exactly one MSBuild project, at one TFM, with that project's own:
  - source set;
  - generated global usings;
  - parse options;
  - reference manifest.

  Project references are `CompilationReference`s to the referenced project's own compilation, at the framework
  its target entry names.

**Cost of the three shapes** (no timing measured; see §6):
- **A.** One compilation with an exact union reference set. Cannot represent F2.2 and has no per-project usings,
  so F2.1, F2.3 and F2.5 stay. **KILL.**
- **B.** One compilation per project over the whole input. N compilations, shared `MetadataReference` objects.
  Correct, but needs every project's assets.
- **C.** One root `.csproj`.
  - **C0, no closure.** Correct **only** for a project with no project references (P5). Any project reference
    makes the root `SOURCE_SET_INCOMPLETE`: P4 and P1 both have three.
  - **C1, the root plus its assets closure.** B restricted to one root. Correct for P4 when all four assets are
    present.

### D3 — honest coverage: `PASS` (design, §4)

**Falsifier attempted.** Can the record call something "resolved" or "complete" while it is not?
- **The trap.** Today's `stats` would report `methods_flow_analysed` for a method whose disposable type was
  matched by name (G2).
- **The fix.**
  - A record that counts name-heuristic disposable sites separately, never as resolved.
  - A per-unit status in which `UNSUPPORTED`, `SKIPPED` and `INCOMPLETE` exclude a unit from "checked".

**Placement.** A separate sidecar file, like `--heap-effects`, written by the PoC instrument, so the facts
document stays byte-identical. No new OwnIR fact and no version bump. A core never reads it.

### D4 — diagnostic precision: `PASS` for coverage-only; `KILL` for full activation; opt-in deferred

See §5. The 6 FPs are not binding errors: their events are real and correctly bound. Any policy that feeds new
event facts into the default verdicts brings them along.

### D5 — operational cost: `PASS` by construction, cost unmeasured

Inputs needed:
- the existing assets;
- the cache packages, read-only;
- the local `dotnet/packs` (`FrameworkList.xml`, `PackageOverrides.txt`, `ref/<tfm>`);
- the `.csproj` text.

No restore, network, MSBuild targets or `MSBuildWorkspace`. Directory mode and `--ref-dir` are unaffected: they stay
on today's path, labelled `legacy-merged`. Missing inputs give `REFERENCE_MISSING`/`UNSUPPORTED`, never a
substitute.

**Expected cost drivers** [inference, to be measured in the PoC]:
- metadata loading of 166–251 references per project [#419 `refs_B`];
- N compilations for N projects in a closure;
- `GetDiagnostics()` for site-level conflicts, which is the expensive part.

**No benefit is claimed.**

## 3. Supported and unsupported inputs

| Input | Status in the recommended mode |
|---|---|
| SDK-style `PackageReference` `.csproj`, assets present, one RID-less TFM (or `--tfm`), all compile assets in the cache with matching content hash, `major.minor` ref packs present, no project references | **supported, `COMPLETE` reference set** (P5) |
| Same, with project references whose closure members each have assets and the target named by the root's entry | **supported via closure (C1)** (P4) |
| Project reference member without assets or source | root `SOURCE_SET_INCOMPLETE(p2p)` |
| Multi-TFM without `--tfm` | `UNSUPPORTED(multi-tfm)` |
| Missing ref pack of the TFM's `major.minor` | `REFERENCE_MISSING(pack)` (P1 net9) |
| Package compile assets missing from cache | `REFERENCE_MISSING(package)` (P1–P3) |
| Framework/package pair undecided by the dotnet/sdk order | `CONFLICT_UNRESOLVED` |
| `<Reference HintPath>`, `<COMReference>`, `Aliases=` | `UNSUPPORTED(reference-kind)` |
| `packages.config`, legacy non-SDK `.csproj` | `UNSUPPORTED(project-style)` |
| Source generators in packages, XAML/WinForms code generation, `Directory.Build.*` setting options, unknown `DefineConstants` | reference set may be `COMPLETE`, but `SOURCE_SET_INCOMPLETE(<reason>)` |
| Directory input, `.sln`, `--ref-dir`, `bin/` auto-reference | unchanged `legacy-merged`, coverage recorded as `APPROXIMATE` |

## 4. `binding coverage` specification (sidecar, version 1)

**Scope.** One record per **unit**, where a unit is a project at a TFM, or the whole merged compilation in
`legacy-merged`. Sites are counted only in source files of that unit's source set. Generated and skipped files
are counted under `files`, never under `sites`.

**Two levels, never merged.**
- **Site status:**
  - `SYMBOL_RESOLVED`: `Symbol != null`, its containing type is not an error type, and no error diagnostic
    intersects the site span;
  - `SYMBOL_AMBIGUOUS`: `CandidateReason` is `Ambiguous` or `OverloadResolutionFailure` with ≥ 2 candidates,
    **or** CS0104, CS0121, CS0229 or CS0433 intersects the site;
  - `UNRESOLVED`: otherwise.
- **Unit status:**
  - `COMPLETE`;
  - `REFERENCE_MISSING`;
  - `SOURCE_SET_INCOMPLETE`;
  - `UNSUPPORTED`;
  - `ANALYSIS_SKIPPED`, also used per method for an unmodelled construct or an unreadable file.

  An `UNRESOLVED` site in a non-`COMPLETE` unit is reported as "unresolved, attributed to `<unit cause>`". It is
  an attribution, not a proof.

**Record.** Deterministic: sorted keys, sorted lists, no timestamps, paths relative to the root.

```json
{
  "binding_coverage_version": 1,
  "mode": "exact-project | legacy-merged",
  "units": [{
    "project": "src/App/App.csproj", "tfm": "net10.0",
    "tfm_status": "PACK_EXACT | PACK_MAJOR_MINOR | REFERENCE_MISSING | NOT_APPLICABLE",
    "unit_status": "COMPLETE | REFERENCE_MISSING | SOURCE_SET_INCOMPLETE | UNSUPPORTED | ANALYSIS_SKIPPED",
    "reasons": ["p2p-no-assets:../Lib/Lib.csproj", "generator:communitytoolkit.mvvm/8.4.0"],
    "manifest": [{"kind": "pack|package|project", "id": "…", "version": "…", "path": "<nuget>/…",
                  "assembly": "Name, Version=…, PublicKeyToken=…", "sha256_16": "…"}],
    "missing": ["package:Foo/1.2.3"],
    "conflicts": [{"name": "System.Collections.Immutable.dll", "winner": "package", "rule": "assembly-version"}],
    "sites": {
      "invocation": {"total": 0, "resolved": 0, "ambiguous": 0, "unresolved": 0},
      "type":       {"total": 0, "resolved": 0, "error": 0},
      "event_assign": {"total": 0, "event": 0, "non_event": 0, "unresolved": 0,
                       "unresolved_no_marker": 0},
      "disposable_type": {"total": 0, "resolved": 0, "name_heuristic": 0}
    },
    "compiler_errors": {"CS0246": 0, "CS0433": 0},
    "files": {"in_source_set": 0, "parsed": 0, "unreadable": 0, "generated_excluded": 0},
    "methods": {"total": 0, "all_relevant_sites_resolved": 0, "skipped": 0}
  }]
}
```

- **Invariants**, each machine-checked:
  - `total = resolved + ambiguous + unresolved` for each site kind;
  - `event_assign.total = event + non_event + unresolved`;
  - `unresolved_no_marker ≤ unresolved` (G1);
  - `name_heuristic` is never in `resolved` (G2);
  - a unit is "checked" only if `unit_status = COMPLETE`, and a method only if it is not skipped and all its
    relevant sites (event `+=`, disposable types, `new` of disposables) are resolved.
- **"Relevant site"** = a site that feeds an existing detector. **"Checked" ≠ "clean".**
- **`--stats` compatibility.**
  - The facts `stats` block and the stderr line are left exactly as they are.
  - A future one-line stderr summary would print **per unit** `resolved/total` for calls and events, plus the
    unit status, and would not require `--flow-locals`.
  - That is an implementation decision, not part of the PoC.

## 5. Precision risk from the real #419 findings

The 9 new findings of R3 (A-ext → B-ext) [#419 §5]:

| Finding | Verdict [#419] | Is it a binding error? | Would recur in exact-project mode? [inference] |
|---|---|---|---|
| P5 OWN014 `SettingsManager.Current.PropertyChanged` | **TP, actionable** | no | yes, if the event's declaring type binds |
| P5 OWN001 `mediaManager` | TP-benign | no | yes |
| P1 OWN001 `OpenFileDialog dlg` | TP-minor | no | **unknown**: P1 becomes `REFERENCE_MISSING`; the finding must not be credited to a complete unit |
| P1 `ProgressBar.IsVisibleChanged`, P1 `link.Click`, P5 `window.SourceInitialized`, P4 `dialog.Closed` | FP, same lifetime | no: correctly bound events | yes |
| P4 `desktop.Startup` / `desktop.Exit` | FP, app-lived source | no | yes |

So the precision problem is in the **lifetime model** (P-004; #407's own FP classes), not in references.

| Policy | Regression risk | Compatibility | Cost | Benefit | Gates |
|---|---|---|---|---|---|
| **1. Coverage-only** | none: facts and verdicts byte-identical | full; additive sidecar | resolver + counter | visible "how much was checked", honest `unit_status`, wrong-TFM and wrong-assembly bindings surfaced | facts byte-identical; deterministic record; controls K1–K12 |
| **2. Opt-in semantic resolution** | for opt-in users the sample gives 1 actionable : 6 FP | new flag; default unchanged | policy 1 + fact wiring + Python/Rust parity on changed facts | the 1 actionable TP becomes reachable | the hard gate below, plus a frozen sample |
| **3. Full activation** | 6 FPs into default verdicts on 5 projects; also removes G2 name-heuristic facts | changes default output | as 2 + golden churn | as 2 | — **KILL now**: fails the hard gate on existing data |

**Hard gate for any future activation** (owner wording, restated):
- every new diagnostic carries source-level evidence;
- zero regressions on existing true findings and on known negative controls;
- no new suppressions aimed at the 6 known FPs.

**Proposed thresholds for a future activation pre-registration.** These are my proposal, **not accepted
thresholds**:
- on ≥ 5 `COMPLETE` units from ≥ 3 repositories, chosen by rule;
- **≥ 3 actionable TPs in ≥ 2 repositories**;
- **precision of the added findings ≥ 50%** (actionable + minor TP over all added), with UNCLEAR counted as FP;
- 0 lost TPs;
- 0 findings on K-controls.

Today's data would give 1 actionable TP in 1 repository and 3/9 = 33%. That **fails**, which is consistent with
#407's deferral until OWN001/event lifetime precision improves.

## 6. Architectures compared (at most three)

| | **A. one compilation, exact union set** | **B. per-project graph over the whole input** | **C1. one root `.csproj` + assets closure, coverage-only** |
|---|---|---|---|
| Scope | any multi-project input | `.sln`/directory with assets everywhere | one SDK-style root (§3) |
| Inputs | all assets | all assets + packs + cache | root + closure assets, packs, cache |
| TFM / refs | one union, cannot be per-project | per project: RID-less target, packs by `major.minor`, compile assets, dotnet/sdk conflict order | same as B |
| Identity | simple-name collisions (CS1704) | per project | per project |
| Missing / ambiguous | merged and invisible | per unit | per unit + site-level CS0433/CS0104 |
| Isolation | **fails F2.1, F2.3, F2.5 silently** | passes F2.1–F2.5 | passes F2.1–F2.5 |
| Fallback | — | `legacy-merged` | `legacy-merged`; anything outside §3 gets its status |
| Extractor interaction | replaces today's compilation | replaces today's compilation | **none**: a separate research instrument; extractor facts unchanged |
| OWN050 / OWN001 / events | changes verdicts | changes verdicts | **none** (policy 1) |
| Old CLI | changes semantics | needs a mode switch | untouched |
| Future implementation | — | project graph, N compilations, mode flag, parity | §8 files, if the PoC passes and the owner says so |
| Rough cost [inference] | — | several agent-days + perf work | PoC ≈ 0.5 agent-day |

**Recommendation: C1 under policy 1.** B is C1 applied to many roots, and is a later decision once C1's cost is
measured. A is killed by D2.

## 7. Verdict

**`GO-P014-TINY-POC`.**
- D1 `PASS-NARROWED`: the conflict rule must be the dotnet/sdk order, not framework-first.
- D2 `PASS` for per-project compilation; `KILL` for A.
- D3 `PASS`.
- D4 `PASS` only for coverage-only; full activation killed now.
- D5 `PASS` by construction; cost unmeasured.

**What this does not allow:**
- production code;
- extractor or OwnIR changes;
- diagnostic activation;
- reopening #407 or P-037.

**No new OwnIR fact is needed for the PoC.** If a later stage wants the core to treat a `SOURCE_SET_INCOMPLETE`
or `REFERENCE_MISSING` unit differently, for example to refuse "clean", that is a **new fact family and a
separate design decision**. It must not be encoded through `release`, `use` or escape.

## 8. Contract for the next PoC (not implemented)

**Form.** A research instrument under `docs/evidence/p014-tiny-poc-<date>/instrument/`, the same pattern as #419's
`P014Bind`, built offline. It reads assets, packs and the cache, and writes the §4 sidecar. It never touches the
extractor.

**Budget.** 0.5 agent-day, not extended.

**Fixtures:**
- **Synthetic.**
  - F2.1–F2.5 from this folder, re-expressed as on-disk mini projects with hand-written assets.
  - #419 K1–K7.
  - New:
    - **K8**: a package with a newer AssemblyVersion than the framework, so the package wins; plus a variant
      covered by `PackageOverrides.txt`, so the framework wins;
    - **K9**: multi-TFM without `--tfm`, expected `UNSUPPORTED`;
    - **K10**: a project-reference member without assets, expected `SOURCE_SET_INCOMPLETE`;
    - **K11**: an unresolved lambda subscription, expected `unresolved_no_marker = 1` (G1);
    - **K12**: an unresolved `FooStream` field, expected `name_heuristic = 1` (G2).
- **Real.**
  - P5 FluentFlyout: C0, `COMPLETE` reference set, source set incomplete because of WPF code generation.
  - P4 BB84.IPTV: C1, a closure of 3.
  - nats.net `sandbox/MicroBench2`: manifest only.
  - P1: expected `REFERENCE_MISSING(pack)`.

**Expected reference manifest:**
- **Synthetic fixtures.** Exact, written by hand before the run.
- **P4/P5.** #419's `manifest_B_P4/P5.tsv` plus closure members. Any difference must be explained by a rule
  change (conflict order, P2P).
- **MicroBench2.** `System.Collections.Immutable`/`System.Reflection.Metadata` from the package; DiagnosticSource
  9.0.1 `REFERENCE_MISSING`.

**Expected binding:**
- Every #419 B-resolved site in P4/P5 is `SYMBOL_RESOLVED` with the same symbol, or the difference is listed and
  read.
- No resolved symbol's containing assembly is outside its unit's manifest.
- K4 shows CS0101 at compilation level, as before. F2.1/P3 shows **CS0433 at the site**, so the status is
  `SYMBOL_AMBIGUOUS`: the per-site conflict check.

**Baseline equivalence.** Extractor facts for P4/P5 are byte-identical before and after. This holds trivially,
because the extractor is not touched, and it is checked anyway. Python/Rust parity: **not applicable**, because
no fact or verdict changes; recorded as such.

**#419 controls.** For the 1 actionable TP and the 6 FPs, record each site's status under C1:
- **expected:** all are `SYMBOL_RESOLVED` events;
- **the six FPs:** they are lifetime cases and stay outside P-014;
- **verdicts:** no change.

**Cost.** Cold and warm wall time and peak working set, 3 runs each, for P4 and P5, for both `legacy-merged`
(today's extractor) and `exact-project`. These are reported. Proposed KILL: exact-project warm time > 3× legacy on
P5.

**KILL if any of:**
- any synthetic fixture shows a silent false resolution;
- a manifest mismatches its hand-written expectation;
- a resolved symbol comes from an assembly outside its unit's manifest;
- two runs give different records;
- a forbidden action is needed;
- the budget runs out.

## 9. Components a future implementation would touch (no change made)

| Component | Change it would need |
|---|---|
| `frontend/roslyn/OwnSharp.Extractor/Program.cs` `:5889-5934`, `:5983` | reference set and compilation per unit instead of one TPA-first merged compilation, behind a mode flag |
| `Program.cs` `:276-451` | assets reader, closure, unit statuses; `ProjectBinDirs` stays for legacy only |
| `Program.cs` `:5867` | per-unit parse options (defines from TFM, LangVersion) and generated global usings: a source-set step, decided separately (#407) |
| `Program.cs` `:6368`, `:5343-5357` | count G1 and G2 in coverage; no behaviour change without a precision gate |
| `Program.cs` `:7578-7638` | sidecar writer; `--stats` line per unit |
| new `OwnSharp.Extractor/ReferenceResolution.cs` | assets, packs and conflict order (dotnet/sdk) |
| `scripts/own-check.sh`, `scripts/own-check.ps1`, `action.yml` | pass the mode flag and sidecar path |
| `spec/OwnIR.md` | none for the sidecar; a fact family only after its own design |
| `ownlang/ownir.py`, `rust/crates/*` | none under policy 1 |
| `tests/`, `tests/check_fix_candidates_facts.py` | facts byte-identity with the new flag on and off |
| `docs/proposals/P-014-semantic-resolution.md` | status, Tier B text (first-name-wins → per-unit manifest) |

## 10. Files

- `00-preregistration.md`, `DESIGN.md`
- `falsifiers/Program.cs`, `falsifiers/P014Iso.csproj`: the D2 program (offline build:
  `-p:RoslynDir=<Microsoft.CodeAnalysis 4.9.2 netstandard2.0>`). Output: `falsifiers/d2_isolation.out.txt`
- `falsifiers/d1_conflicts.py`: the read-only conflict check (assets, packs, cache). Output:
  `falsifiers/d1_conflicts.out.txt`.
  - P1's 51 rows are counted per file across two packs and are not comparable with #419's 47.
  - P2's 3 and P4's 1 match #419.

## 11. Open questions

- Does C1's binding on P4 rise above #419 B's 59 recovered calls once the project-reference sources compile as
  their own units? Expected, not measured.
- Are reference-pack APIs really identical across servicing patches? This is the `PACK_MAJOR_MINOR` assumption,
  and it is documented intent, not checked here.
- Should generated global usings and TFM defines enter the PoC as a separately reported source-set axis, or wait
  for the owner's #407 rule (implicit usings are a separate feature with a census)? This packet keeps them out.
