# N3 bounded pilot, gate G0 (scope identity) — pre-registration

Written 2026-10-20, before the G0 filter was written or run. What had been read before this file:

- the D11 triage of the 7 holdout DI001 findings (`evidence/holdout/ownnet/di_sample.tsv` of the direction
  research, private), which names the cause of each FP;
- `ownlang/di.py` (`find_captive_dependencies`);
- the field names of one `services` fact in the OrchardCore holdout facts. No DI001 result was recomputed.

Authority: owner decision `ACCEPT-PHASE0 / GO-N3-BOUNDED-PILOT / NO-PRODUCTION`, given on PR #414. G0 budget:
0.25 agent-day. G1–G4 start only after a G0 PASS, and get one agent-day in total. The first failed mandatory gate
stops the pilot (`KILL-N3-PILOT`). The budget is not extended.

## Question

Can product registrations be told apart from test registrations, and can each registration be resolved through its
own implementation, using only the facts the extractor already emits and the repository's project files? The DI
graph must not be rebuilt.

N3 needs this because its warning must rest on a proven scoped lifetime of a concrete object. If the registration
graph cannot say "scoped" without the 7/7 FP of D11, a detached-work rule built on it inherits them.

## Known failure (the target)

7 of 7 product DI001 findings on OrchardCore (holdout, target `5ddc4594`, Own.NET `e7d33e33`) are FP. The D11 triage
gives two causes:

- **test registrations merged in (6).** `IExtensionManager` (5 findings) and `IMediaTokenService` (1) are
  `AddSingleton` in product code. The `scoped` lifetime comes from test registrations (`StubExtensionManager`,
  `MediaTokenTests.cs`). The core keys the graph by service name, and the last registration wins.
- **implementations merged by service name (1).** `IDeploymentTargetProvider`: the singleton implementation
  `FileDownloadDeploymentTargetProvider` takes only `IStringLocalizer`. The scoped dependency belongs to another
  implementation of the same interface. The core starts each walk from `by_name[s.name]`, not from the registration
  `s` itself.

## Method (fixed now)

A research script outside the product tree reads saved `facts.json` files and the repository sources. Production
code, OwnIR, CI and goldens are not changed. The script applies four rules:

1. **Test project.** A registration belongs to the project whose `.csproj` is in the nearest ancestor directory of
   its `file`. The project is a test project when its `.csproj` sets `<IsTestProject>true</IsTestProject>` or
   references one of `Microsoft.NET.Test.Sdk`, `xunit`, `xunit.v3`, `NUnit`, `MSTest.TestFramework`, `MSTest`,
   `TUnit` or `BenchmarkDotNet`. Path names are not used for this decision. The path regex of the direction
   research (`sweep_summary.py`) is reported next to it, as a comparison only.
2. **Drop test registrations.** Registrations in test projects are removed. A registration with no owning
   `.csproj` is kept and counted.
3. **Own implementation at the root.** The walk for a singleton registration starts from that registration's own
   `deps`, not from the node of the same service name.
4. **Proven lifetime only.** A dependency name counts as scoped only when every remaining registration of that
   name is scoped. It is followed as transient only when every remaining registration is transient. Mixed
   lifetimes make the name unknown, and unknown adds no edge. The number of mixed names is reported.

The DI001 rule itself (singleton → scoped, through transients) does not change.

## Inputs

- **Target.** OrchardCore holdout facts as saved by D11 (Own.NET `e7d33e33`). They are not re-extracted.
- **Positive controls (must keep firing).**
  - `frontend/roslyn/samples/DiCaptiveSample.cs`: exactly four DI001 (`EmailSender -> AppDbContext`,
    `ReportService -> UnitOfWork -> AppDbContext`, `CacheService -> IRepo`, `PrimaryCtorService -> AppDbContext`)
    and silence on `Metrics -> Clock` and `PublicCtorOnly`, as its CI assertions pin today.
  - Corpus pair `rrr-pi-rate/StockPriceSheetPrintService#60` (C10): DI001 present on `base`, absent on `fix`, as in
    the D6 ledger.
- **New-finding check.** The other 14 holdout repositories and the 13 design-B sweep repositories, all from saved
  facts. Rule 3 can add findings that the current core does not report, so every finding that the current core
  does not report is listed and triaged by reading the code.

## Verdict rules

`PASS-G0` needs all of:

- all 7 known OrchardCore FPs are gone, each by a rule named above;
- both positive controls hold exactly;
- every new finding is triaged, and none is a FP. An `UNCLEAR` counts as a FP;
- elapsed work within 0.25 agent-day.

`KILL-N3-PILOT` at G0 if any of the following:

- a known FP survives the four rules and removing it needs another mechanism;
- a positive control is lost;
- a new finding is a FP or `UNCLEAR`;
- the budget runs out before a verdict.

No rule may be added or changed after the first run. A fifth rule invented after the run is a G0 failure, not a
fix.

## Out of scope for G0 (input to G1)

- Framework registrations (`AddDbContext`, `AddHttpClient`, controllers, Razor components). Their lifetime comes from
  the framework, not from an `Add*` call in the repo. G1 must say how N3 gets "scoped" for them; G0 does not test it.
- Open generics, factory lambdas, assembly scanning: unknown, as today.
