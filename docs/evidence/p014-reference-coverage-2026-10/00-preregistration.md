# P-014 reference-resolution coverage — pre-registration

Written 2026-10-21 04:45 +05, before any measuring run. Budget: 0.25 agent-day to the first GO/KILL decision,
counted from 04:37. Not extended.

## 0. Current state, checked in code (`main` `c6e8a3c1`, `frontend/roslyn/OwnSharp.Extractor/Program.cs`)

| Claim | Verdict | Where |
|---|---|---|
| All inputs go into one `CSharpCompilation.Create("own", …)` with default options | confirmed | `:5983-5985` |
| The framework set is the extractor **process's** `TRUSTED_PLATFORM_ASSEMBLIES`; the extractor targets `net8.0`, so on this host that is the Microsoft.NETCore.App **8.0.31 implementation**, not the target TFM's reference pack | confirmed | `:5889-5894`; `OwnSharp.Extractor.csproj:5` |
| `--ref-dir` and the auto-added project `bin/` are loaded recursively, **first simple filename wins**, and any name already in TPA is skipped | confirmed | `:5911-5933`, `:536-547` |
| No MSBuild evaluation: a `.csproj` is resolved by text to a source set | confirmed | `:276-292` |
| No quantitative semantic-binding report; `--stats` counts flow-locals coverage only | confirmed | `:5993-5997` |
| Also seen: trees are parsed with default `CSharpParseOptions`, with no preprocessor symbols; SDK implicit/global usings are not generated | confirmed | `:5867` |

The last row is a **source-set** effect, not a reference effect. It is measured separately (mode C) and never
credited to references.

## 1. Inputs (fixed now; chosen by rule, not by expected gain)

**Rule.**
1. Take every corpus repository that has a `project.assets.json` already on disk and whose sources are present:
   the 3 design-B sweep repositories that have one, plus the direction-research pairs whose assets list packages
   that all exist by id/version in the local global cache.
2. From the sweep repositories take all 3. From the qualifying pairs take the 2 that are WPF/desktop
   applications (BB84.IPTV, FluentFlyout); the other qualifying ones are libraries (LiteDB, MarkView).
3. In each repository take the largest non-test, non-sample project by `.cs` count.

| # | Project | SHA | Kind | TFM measured | Assets packages / present by id in global cache |
|---|---|---|---|---|---|
| P1 | Flow-Launcher/Flow.Launcher — `Flow.Launcher/Flow.Launcher.csproj` | `2efbf865` | WPF app, 3 project references | `net9.0-windows10.0.19041.0` | 165 / 89 |
| P2 | git-ecosystem/git-credential-manager — `src/Core/Core.csproj` | `e66693fa` | library | `net10.0` | 37 / 17 |
| P3 | nats-io/nats.net — `src/NATS.Client.JetStream/NATS.Client.JetStream.csproj` | `176e52bc` | multi-targeted library, 1 project reference | **`net8.0`** (fixed; of netstandard2.0/2.1/net8.0/net10.0) | 28 / 19 |
| P4 | BoBoBaSs84/BB84.IPTV — `src/BB84.IPTV.M3U.Editor/BB84.IPTV.M3U.Editor.csproj` (pair #36 base) | `e9ab4f28` | desktop app, 3 project references | `net10.0` | 87 / 87 |
| P5 | MERURUXD/FluentFlyout — `FluentFlyoutWPF/FluentFlyout.csproj` (pair #3 base) | `911dfda6` | WPF app | `net10.0-windows10.0.22000.0` (first listed) | 19 / 19 |

**Provenance of the artifacts** (recorded, not trusted):
- **P1–P3.** The assets were written on 2026-10-17 between 17:22 and 17:30 by CodeQL buildless extraction. That
  is before the D13 isolation (2026-10-18). Their `packageFolders` (`codeqldb/working/packages`, the VS shared
  folder) no longer hold the packages.
- **P4–P5.** The assets come from the isolated pair restores of 2026-10-18.
- **Package hashes.** For **every** package of all five, the `sha512` in the assets differs from the
  `.nupkg.sha512` in the global cache. Same id and version, different package file. Package identity is therefore
  **not provable**, and every mode-B reference is labelled `APPROXIMATION`.

**Local SDK/TFM.**
- Runtimes: NETCore.App 6.0.36 / 8.0.31 / 10.0.12; AspNetCore.App and WindowsDesktop.App 8.0.31 / 10.0.12.
- Reference packs: Microsoft.NETCore.App.Ref, AspNetCore.App.Ref and WindowsDesktop.App.Ref 8.0.31 and 10.0.12;
  NETStandard.Library.Ref 2.1.0.
- **There is no 9.0 reference pack**, so P1's exact TFM is `UNAVAILABLE_UNDER_D13`. P1's mode B uses the 10.0.12
  packs and is labelled `TFM-APPROX`.

## 2. Modes (one instrument, identical sources and options in every mode)

**Common to all modes.**
- **Sources.** All `.cs` files under the project directory, excluding `bin`/`obj`, as the extractor's `.csproj`
  path resolves them. The list is written to disk once and used by every mode.
- **Parse options.** `CSharpParseOptions.Default` (no defines), as the extractor uses.
- **Compilation options.** `new CSharpCompilationOptions(DynamicallyLinkedLibrary)`.

| Mode | References |
|---|---|
| **A, current** | every DLL of `shared/Microsoft.NETCore.App/8.0.31`, i.e. the extractor process's TPA. Plus the project's `bin/` (absent in all five), first filename wins |
| **B, project-specific (`APPROXIMATION`)** | the target TFM's reference pack(s): NETCore.App.Ref, plus AspNetCore/WindowsDesktop.App.Ref when the assets' `frameworkReferences` name them. Plus, for every package in `targets[<TFM>]`, its `compile` assets (excluding `_._`) from the global cache. A package missing from the cache is recorded, never substituted. No DLL from another TFM; no name-based replacement of a framework assembly |
| **C, source-set probe (not part of A/B)** | A plus one generated file of the SDK default global usings for the project's SDK. It measures how much binding loss is source-set rather than reference |

Project-to-project references are not built, so in every mode their types bind only if the project's own sources
declare them. This is recorded as a `source set` cause.

**R3 (extractor chain).** The unchanged extractor, built offline from `main` with packages from the local cache
only. It runs with `--flow-locals`, as in `own-check`:

- **A-ext:** as shipped.
- **B-ext:** `OWN_EXTRA_REF_DIRS` = the same framework reference packs as B, plus `--ref-dir` for each package
  `compile` folder of B.

  The extractor keeps its TPA first, so B-ext is the best that **today's** extractor can be given, and it is not
  identical to B. Both are reported.
- **Core:** the Python reference core (`python -m ownlang ownir`, the `own-check` default). No Rust core is built
  on this host, and building one needs cargo dependencies, so that is skipped.

## 3. Metrics (all with numerators and denominators)

Per project and mode:
- **Method binding.** `InvocationExpressionSyntax` sites counted as resolved (`Symbol` non-null),
  ambiguous/candidates (`CandidateSymbols` > 0, `Symbol` null), or unresolved.
- **Type binding.** `TypeSyntax` in declarations, `new`, base lists, parameters and fields, counted as resolved or
  `IErrorTypeSymbol`.
- **Event binding.** `+=`/`-=` whose left side is a member access, counted as `IEventSymbol`, other symbol, or
  unresolved.
- **Compiler errors** by code, with CS0012, CS0246, CS0234, CS1061, CS0103 and CS0117 broken out.
- **R2, per site.** Every site whose status differs between A and B, recorded with file:line, expression, both
  statuses, `SymbolKind`, containing type, signature and containing assembly.

  Classification:
  - `RECOVERED_CORRECT`;
  - `RECOVERED_WRONG`: B binds but to a symbol whose containing assembly is not the package or framework assembly
    that declares the named type, or A had a different symbol;
  - `STILL_UNRESOLVED`;
  - `AMBIGUOUS`;
  - `NOT_COMPARABLE`.

  A fixed random sample of 10 `RECOVERED` sites per project (seed `20261021`) is checked by reading the code.
- **Cause categories** for sites unresolved in A: fixed by B → `missing/mismatched reference`; fixed by C only →
  `source set (implicit usings)`; type declared in a referenced project → `source set (project reference)`;
  unresolved in all modes → `still unresolved` (unattributed). The B-vs-A difference attributable to TFM (8.0
  implementation vs target reference pack) is reported where B binds a framework-only member.
- **R3.** Extractor stats, OwnIR fact counts by kind (`functions`, `subscriptions`, `services`, flow `acquire`,
  OWN050), and core findings by rule, for A-ext vs B-ext. Every finding change is listed and triaged as TP / FP /
  UNCLEAR by reading the code. A chain `reference → symbol → fact → diagnostic` is written for each change, and
  where it breaks, the break point is named, including #382-type lowering.

## 4. Controls (synthetic, in `controls/`, run through the same instrument; written before the first run)

| # | Control | Expected |
|---|---|---|
| K1 | sources and references already consistent (BCL only) | A == B, no site changes |
| K2 | two emitted assemblies with the same filename `Lib.dll`, different identity/version, in two folders | A's first-filename-wins is recorded; B takes only the one its manifest names |
| K3 | one package with `lib/net8.0` and `lib/netstandard2.0` | B uses only the TFM the manifest selects |
| K4 | two source "projects" declaring the same FQN `Dup.T` | recorded as ambiguous/conflict, never `RECOVERED_CORRECT` |
| K5 | an external `event` and an external `int` field, both used with `+=` | B binds the event as `IEventSymbol` and the field not as an event |
| K6 | a type from an assembly that is not provided | unresolved in A and B; nothing invented |
| K7 | `#if NET8_0 … #else … #endif` | both modes see the same branch (no defines); recorded as a source-set limit |

## 5. Decision (thresholds fixed now)

**`GO-P014-BOUNDED-DESIGN` only if all of the following hold:**
1. **N1.** At least 2 independent projects show reference-caused binding loss in A, meaning sites fixed by B and
   not by C. The loss must be at least 5% of that project's invocation sites **and** at least 20 sites.
2. **N3.** In each of those projects, at least 9 of the 10 sampled `RECOVERED` sites are `RECOVERED_CORRECT`.
   K1–K6 pass.
3. **N4.** At least one triaged useful change in OwnIR facts or core findings, A-ext vs B-ext. That is: a new TP,
   or a removed FP, or an OWN050 replaced by a correct fact. A change in compiler diagnostics alone does not count.
4. **N2 and cost.** B's references come from on-disk artifacts without any build, restore or MSBuild evaluation,
   and the cost of shipping them is bounded without `MSBuildWorkspace`.

**`KILL-P014-REFERENCE-INVESTMENT`** if any of:
- fewer than 2 projects meet item 1;
- recovered sites are wrong (item 2 fails), or a control fails;
- the gain stops at compiler diagnostics (item 3 fails);
- B needs a forbidden action;
- the budget runs out.

**`INCONCLUSIVE-P014`** if item 1 holds for exactly one project and the reason the others cannot be measured is
input availability (packages missing from the cache, or the TFM pack absent), not a measured null effect. The
sample is not widened after the first run.
