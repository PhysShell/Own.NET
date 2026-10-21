# P-014 PROD0 (coverage only) — report

**Verdict: `PASS-P014-PROD0`.** G0–G3 hold (§5).

What the PASS covers: an **opt-in, observation-only** extractor flag, `--binding-coverage FILE`.
- **No default behaviour changes.** No OwnIR change, no finding, no SARIF and no exit-code change.
- **PROD1 is not authorised.** PROD1 would feed the new symbols to diagnostics.

Rules: [`00-preregistration.md`](00-preregistration.md), commit `6ec551f` (12:36:03 +05; the "12:40" in its header
is my clock reading, the commit time is authoritative). Base `main` `22b29d5b`. Work 12:35–12:50 +05, within
the 0.5 agent-day budget.

Labels:
- **[run]** measured here;
- **[read]** checked in code or diagnostics;
- **[doc]** dotnet/sdk source.

## 1. What changed in production code

| File | Change |
|---|---|
| `frontend/roslyn/OwnSharp.Extractor/BindingCoverage.cs` (new) | the #422 instrument's resolver and coverage code, moved into namespace `OwnSharp.BindingCoverage` with public types, plus the sidecar `Runner`. Behavioural differences from #422 are listed below |
| `frontend/roslyn/OwnSharp.Extractor/Program.cs` (+17 lines) | two flags (`--binding-coverage FILE`, `--binding-coverage-tfm TFM`), usage text, and one call **after** the facts and the H0 file are written. A failure is reported on stderr and **never changes the exit code** |
| `.github/workflows/ci.yml` (one step in `wpf-extractor`) | facts are `cmp`-identical with and without the flag, for project and directory input; directory and unrestored-project inputs are recorded `UNSUPPORTED`; a restored copy of `project-input-sample` is measured, deterministic, `foreign_binding = 0`, and COMPLETE exactly when no reason is present |
| `frontend/roslyn/README.md`, `docs/proposals/P-014-semantic-resolution.md` | the flag documented; PROD1 marked as not authorised |

**Differences from the #422 instrument.** All are stricter or needed to run on other hosts:
1. **A project-reference member that is not `COMPLETE` makes its parent `SOURCE_SET_INCOMPLETE`.** In #422 only an
   unsupported or reference-missing member did.
2. **A package with MSBuild `build`/`buildMultiTargeting` assets makes the unit `SOURCE_SET_INCOMPLETE`**
   (`package-msbuild-assets:<id>/<ver>`). Such assets can change the compilation.
3. **The dotnet root comes from `DOTNET_ROOT`**, or else from the running runtime's location, instead of a
   hard-coded Windows path. The packages folder comes from `NUGET_PACKAGES`, or else `~/.nuget/packages`.
4. **A targeting pack recorded in `downloadDependencies` is looked up in `dotnet/packs`, then in the packages
   folder**, which is where the SDK puts a downloaded pack [doc, `ResolveTargetingPack` behaviour]. Without this, a
   restored project on a host whose packs lack the exact patch would be a false `REFERENCE_MISSING`. That is fail
   closed, but wrong.

## 2. G0 — package-vs-package conflict `Wpf.Ui.dll` against the SDK oracle [run]

**Fixture.** `fixtures/G0`, my own project, `net10.0-windows` with WPF, referencing `unchihugo.WPF-UI` 4.4.2 and
`WPF-UI.Tray` 4.3.0, restored offline from the global packages folder only. This reproduces P5's conflict:
`unchihugo.WPF-UI/4.4.2`, AssemblyVersion 4.4.1.0 and PublicKeyToken `null`, against the transitive `WPF-UI/4.3.0`,
AssemblyVersion 4.3.0.0 and PublicKeyToken `11f9f5cc97b3ffd6`.
- **The oracle** chose `unchihugo.wpf-ui/4.4.2/lib/net10.0-windows7.0/Wpf.Ui.dll`.
- **The #422 instrument** and **the production flag** chose the same file, by rule `assembly-version`.
- **The full manifests are identical:** 209 = 209 (`data/G0.instrument422.compare.json`, `data/G0.compare.json`).
- **No narrowing was needed.**
- **Scope.** This qualifies one package-vs-package form: different AssemblyVersions, decided by the second rule.
  Package-vs-package conflicts with equal versions are still `CONFLICT_UNRESOLVED` by construction, and are not
  oracle-checked.

## 3. G1 — P4/P5 are not reported as fully checked [run, `data/P*.cost.1.sidecar.json`]

All 5 units, the 4 of P4 and P5, have reference status `COMPLETE`, `PACK_MAJOR_MINOR`, and
**`unit_status = SOURCE_SET_INCOMPLETE`**, with named reasons. No unit is `COMPLETE`.
- **Site counts and manifests** are identical to #422's for every unit.
- **The only difference** is the added fail-closed reasons from §1:
  - `package-msbuild-assets:*`, e.g. `communitytoolkit.mvvm/8.4.2` in P5;
  - `p2p-unit-source_set_incomplete:*` in P4.

## 4. G2 — compatibility [run, `data/run_prod0.log`]

| Check | Result |
|---|---|
| Facts byte-identity: P4, P5 (`.csproj`, `--flow-locals --no-project-refs`) and `frontend/roslyn/samples` (directory) | **identical** across `main` 22b29d5b, this branch without the flag, and this branch with it (P4 `AD528B8A…`, P5 `5F0EA76D…`, samples `F82A32D8…`) |
| Facts with the flag on and off, 6 runs per project | identical |
| Directory input | sidecar `UNSUPPORTED (input-kind:directory)` |
| In-memory controls against the **production** code (harness references the built `ownsharp-extract.dll`) | K1, K2, K4 (CS0101 merged; CS0433 at the site, separately compiled), K5, K6, K7, F2.3, F2.4, F2.5, K11, K12 and the guard: **all PASS**, same observations as #422 |
| Fixtures through the production flag vs the SDK oracle | K8a 163 = 163, K8b 163 = 163, K8c 206 = 206, G0 209 = 209, K9 net8.0 163 = 163, K9 net10.0 167 = 167; no tie assumption. K9 without TFM: `UNSUPPORTED(multi-tfm)`. K10: with child assets, two `COMPLETE` units; without, `SOURCE_SET_INCOMPLETE(p2p-no-assets:Child)`, event unresolved, foreign = 0 |
| `foreign_binding` | 0 in every control and in all P4/P5 units |
| Sidecar determinism | byte-identical across 3 runs for P4 and P5 |
| Build | only warning, before and after: the existing `Program.cs` CS8620, shifted 10 lines. No new warning |
| `ruff check .` | passes |
| `python tests/run_tests.py` | runs to the end (about 318 s) with the rustup `cargo` 1.98.1 on PATH. **One module fails, identically on `main`:** `test_cli_ownir_fixtures`, 87 cases. Its frozen CLI bytes were recorded with `
`, and Python on this Windows host writes `
`. The same 87-case FAIL set appears on a tree identical to `main` `22b29d5b`, so it is a host artifact, not this branch. All other modules pass. No Python file is changed by this branch. CI (Linux) is authoritative |
| New CI step, rehearsed locally (offline restore) | facts identical; `UNSUPPORTED` for the unrestored and directory inputs; restored sample `COMPLETE`, `PACK_MAJOR_MINOR`, event bound, deterministic |

## 5. G3 — cost [run]

Medians of 3 separate processes (`data/run_prod0.log`, `data/P*.legacy.*.timing.json`).

| | flag off | flag on | added by the flag | limit: 3 × legacy-merged warm (same session) | peak working set, on |
|---|---|---|---|---|---|
| P4 | 1103 ms | 2944 ms | 1841 ms | 3 × 1783 = 5349 ms | about 258 MB |
| **P5** | 2844 ms | 4234 ms | **1390 ms** | **3 × 1021 = 3063 ms** | **about 302 MB** (limit 2.0 GB) |

**Verdict.** G0 PASS (no narrowing needed), G1 PASS, G2 PASS, G3 PASS: **`PASS-P014-PROD0`.**

## 6. Limits that stay attached

1. **A complete reference set is not a complete compilation.** Real projects come out `SOURCE_SET_INCOMPLETE`
   (implicit usings, generators, XAML, package MSBuild assets). The coverage numbers measure binding under that
   incomplete source set; they are not a share of verified code.
2. **The conflict resolver is qualified on these forms:**
   - framework vs package, decided by override, AssemblyVersion or FileVersion;
   - targeting-pack profiles;
   - target selection;
   - package vs package with **different** AssemblyVersions (G0).

   Not qualified: equal-version package-vs-package conflicts (left `CONFLICT_UNRESOLVED`), the rank and platform
   steps, and the full SDK contract.
3. **Environment.** The host .NET is SDK 11.0.100-rc.2 with packs 8.0.32/10.0.13. The #419 packs (8.0.31/10.0.12)
   are gone, as recorded in #422.
4. **Configuration outside the repository.** Any `Directory.Build.*` above a project, including a host file, is
   reported and makes the unit incomplete. It is not evaluated, and there is no guarantee about it.
5. **The Python suite fails one module on this Windows host** (`test_cli_ownir_fixtures`, CRLF vs frozen LF bytes), with the same 87 cases on `main` (§4). CI is authoritative.

## 7. Files

- `00-preregistration.md`, `REPORT.md`
- `fixtures/`: G0, plus copies of #422's K8a, K8b, K8c, K9, K10
- `harness/`: the in-memory controls, compiled against the built extractor
- `scripts/run_prod0.ps1`: build main and branch, facts identity, controls, oracle fixtures, determinism, cost
- `data/`: control results, oracle comparisons, sidecars, timing, log. Local paths are replaced by `<nuget>`,
  `<dotnet>`, `<research>` and `<work>`.
