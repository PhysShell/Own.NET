# N3 bounded pilot, gate G0 (scope identity) — report

**Result: `PASS-G0`, by the pre-registered rules.** Three limits below bind G1.

Rules: [`00-preregistration-g0.md`](00-preregistration-g0.md), committed in `14be6c33` before the filter was
written or run. No rule was changed after the first run.

Nothing in production, OwnIR, CI or goldens was touched. The script reads saved `facts.json` files, `.csproj` files
and the unchanged core (`ownlang/di.py`).

## 1. What was run

- **Script.** [`scripts/g0_scope_identity.py`](scripts/g0_scope_identity.py).
- **Facts.** The facts saved by the direction research (private), produced by the Own.NET `e7d33e33` Release
  extractor:
  - 15 holdout repositories;
  - 13 design-B sweep repositories;
  - corpus pair rrr-pi-rate#60, `base` and `fix`.

  `frontend/roslyn/samples/DiCaptiveSample.cs` was extracted with the same binary. `di.py` and the sample are
  unchanged between `e7d33e33` and `main` (`76bc4222`).
- **Baseline.** The current core, `find_captive_dependencies`, over the same facts.
- **Self-check.**
  - With all three rules switched off, the script's walk reproduces the core's findings in all 30 inputs, with 0
    differences.
  - A second run produced identical output files.

Command:

```
python -I docs/evidence/n3-pilot-2026-10/scripts/g0_scope_identity.py --ownnet . \
    --research <direction-research root> --out <dir> \
    --extra "sample/DiCaptiveSample=<facts of DiCaptiveSample.cs>@."
```

## 2. Verdict, criterion by criterion

| Criterion | Result |
|---|---|
| All 7 known OrchardCore FPs gone, each by a named rule | yes, 7/7 (§3) |
| `DiCaptiveSample`: exactly four DI001, silence on `Metrics -> Clock` and `PublicCtorOnly` | yes: `EmailSender -> AppDbContext`, `ReportService -> UnitOfWork -> AppDbContext`, `CacheService -> IRepo`, `PrimaryCtorService -> AppDbContext`; nothing else |
| rrr-pi-rate#60: DI001 on `base`, none on `fix` | yes: `IDiscordBotMessageReceiver -> ITriggerReportService` on `base`; 0 on `fix` |
| New findings over 27 holdout and sweep repositories, all triaged, none FP or `UNCLEAR` | 0 new findings |
| Within 0.25 agent-day | yes |

## 3. Which rule removed which FP (ablation)

[`data/g0_ablation.tsv`](data/g0_ablation.tsv) records every subset of rules 2, 3 and 4. A `1` means the finding is
still reported.

| Known FP (OrchardCore) | none | 2 | 3 | 4 | 2+3 | 2+4 | 3+4 | 2+3+4 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `IShellHost -> IExtensionManager` | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| `ICompositionStrategy -> IExtensionManager` | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| `IShellContainerFactory -> IExtensionManager` | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| `IShellDescriptorManager -> IExtensionManager` | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| `IPageApplicationModelProvider -> IExtensionManager` | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| `MediaCommandParser -> IMediaTokenService` | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| `IDeploymentTargetProvider -> RemoteInstanceService` | 1 | 1 | 0 | 1 | 0 | 1 | 0 | 0 |

- Rule 3 (walk from the registration's own implementation) removes the implementation-merge FP. Nothing else
  removes it.
- Rule 4 (proven lifetime only) removes the six test-registration FPs.
- Rule 2 (drop test registrations) removes none of the seven (limit 1).
- Partial subsets add findings: rule 3 alone gives 2 new ones, rules 3+4 give 1. All of them are in nopCommerce test
  code (`src/Tests/Nop.Tests/BaseNopTest.cs:482`, `ITaskScheduler`). With all three rules on, there are 0.

## 4. Limits that bind G1

1. **The test-project rule missed the project that holds the FP source.** `test/OrchardCore.Tests` references
   `xunit.v3.mtp-v2`, which is not in the fixed package list, so rule 1 classed it as product.
   - The `StubExtensionManager` and `MediaTokenTests` registrations stayed in the graph. They were neutralised only
     because product code registers the same names as singleton, so rule 4 saw mixed lifetimes.
   - A scoped registration that exists only in an unrecognised test project would still read as proven scoped.
   - One existing DI001 on a test-file registration also stays: `AttachedMediaFieldFileService ->
     IUserAssetFolderNameProvider`, `ViewMediaFolderAuthorizationHandlerTests.cs:461`.
   - Over all inputs, rule 1 marks 603 of 4,503 registrations as test, and the comparison path regex marks 1,682.
     The regex also covers samples, docs and benchmarks, so the two numbers do not measure the same thing.
   - Package-name matching is brittle. G1 must not treat "not in a recognised test project" as proof of product
     code.
2. **Rule 4 trades recall for precision.** Names with mixed lifetimes become unknown: 48 over all inputs: 23 in
   OrchardCore, 11 in Orleans, 6 in bitwarden, 8 in eShop, grpc-dotnet, Quartz.NET and nopCommerce. For N3 this direction is acceptable:
   unknown means silence.
3. **A known FP survives G0.** In Orleans, `DhtGrainLocator -> IGrainContext` (`DefaultSiloServices.cs:156`) was
   triaged FP in the sweep: the singleton is built by a factory lambda that never resolves `IGrainContext`. It is not
   one of the seven targets, and G0 does not fix it. The two nopCommerce `ElFinderService` findings that remain were
   triaged true but benign in the sweep.
4. **G0 does not cover where N3's scoped objects mostly come from.** In the Phase 0 instances these are
   `HttpContext`, `DbContext` registered by `AddDbContext`, and controllers or other per-request framework types.
   Their lifetime is set by the framework, not by an `Add*` call in the repository, so the registration graph alone
   cannot prove them scoped. G1 has to settle this first, and a framework lifetime table must be fixed before any
   run.

## 5. Files

- [`00-preregistration-g0.md`](00-preregistration-g0.md): the rules, committed before the run.
- [`scripts/g0_scope_identity.py`](scripts/g0_scope_identity.py): the filter and the ablation.
- [`data/g0_summary.tsv`](data/g0_summary.tsv): per input, the registrations, test-project and path-regex counts,
  mixed-lifetime names, and DI001 counts for the current core and for G0.
- [`data/g0_findings.tsv`](data/g0_findings.tsv): every current-core finding, marked `kept` or `removed`, and any
  `NEW` finding.
- [`data/g0_ablation.tsv`](data/g0_ablation.tsv): every finding under every rule subset.

The input facts and the third-party source trees are in the direction-research repository (private) and are not
committed here.
