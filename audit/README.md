# Own.NET Audit

> **Status (2026-06-26): active development lives in the `OwnAudit` repo.**
> This `audit/` subtree is the *base* the OwnAudit audit was taken from and
> "brought to completion" — `OwnAudit` was scaffolded 2026-06-25 as an
> "STS audit orchestrator"; its `fix/` (fix-arm), `arch/`, `oracle/` and
> GitHub-facing `report/` layers plus the P-015 reachability-evidence work are
> ahead of this copy. The CoStrict-integration track (`ownnet` CLI,
> `ownnet.finding.v1` schema, fix-arm wiring) is being built there too —
> see `OwnAudit/docs/costrict-integration-plan.md`.
>
> **Intent:** Own.NET is the destined home for the consolidated audit *and* the
> `ownnet` CLI. The OwnAudit/Own.NET split is a temporary convenience (the
> `audit/` subtree is decoupled and liftable, `Plan.md §7`), not the target
> architecture. Consolidation back into Own.NET is **deferred** until the
> OwnAudit refinements settle — until then, do not treat this subtree as the
> current source of truth; the live audit is in `OwnAudit`.

An audit **orchestrator** for a legacy .NET Framework 4.7.2 / WPF / DevExpress
desktop application. It runs a fleet of mature, ready-made analyzers over the
target, normalizes every tool's output to SARIF, scores findings by cross-tool
agreement, and produces a categorized **health report ranked by where it hurts
most** — the "anamnesis" of the codebase.

Full design: [`../Plan.md`](../Plan.md). This subtree is the first deliverable —
the **static layer** (build-free tier) plus the **aggregation pipeline**. The
runtime layer and the AI-reviewer layer are later phases.

## Principles (why this is an orchestrator, not a new analyzer)

- **No new heuristics.** We run existing tools; we do not invent regex detectors.
  A category with no reliable tool is marked `NO-TOOL` and deferred to the runtime
  layer — never faked. (Mirrors `own-check`'s honest-skip discipline.)
- **SARIF is the one normalized format.** Every tool's output is read through the
  *same* `parse_sarif` the oracle uses, then mapped to a category.
- **Honest coverage.** Suppressed third-party (DevExpress) findings are counted,
  not hidden. Unmapped rules are surfaced as pending taxonomy, not dropped.
  Tiers that did not run are labelled, not silently treated as "clean".
- **Determinism.** A run over a fixed commit is a stable, diffable artifact.

## Decoupling

This subtree lifts out as a standalone project (Plan.md §7). It imports **nothing**
from the `ownlang` core. Its only in-repo seams are:

- `scripts/oracle_compare.parse_sarif` / `norm_path` — a pure SARIF reader, reused
  (not duplicated) per Plan.md §3.4. Vendored on lift-out (Phase 4).
- `own-check` is consumed **only** via its CLI (`scripts/own-check.sh`).

The single third-party Python dependency is PyYAML (see `requirements.txt`),
scoped to this subtree so the zero-dependency core test suite stays untouched.

## Layout

```text
audit/
  aggregate/
    normalize.py     # SARIF -> categorized findings; OWN001 [resource:] split; DevExpress suppress
    score.py         # cross-tool agreement + severity + "where it hurts most" heatmap
    report.py        # markdown + json renderers (health report)
  static/
    run_static.py    # orchestrator: run build-free runners -> aggregate -> report
    tools/
      owncheck.py    # build-free runner: own-check.sh --format sarif  (needs dotnet)
      codeql.sh      # build-free runner: CodeQL build-mode=none, security-and-quality
      xaml_check.py  # build-free runner: markup-only XAML perf/lifetime pass (stdlib XML, no SDK)
      xaml_facts.py  # XAML facts extractor (resource graph + binding facts) -> xaml-facts.json (Phase-2 seam)
      xaml_join.py   # XAML<->C# Phase-2 join: xaml-facts.json + OwnIR -> XAML203 link findings (build-free)
      roslyn_pack.ps1 # build-required runner (local Windows): NetAnalyzers/Roslynator/... 
      infersharp.sh  # build-required runner: Infer# over built binaries
    inject/          # OwnAudit.Directory.Build.props/.targets (analyzer injection, gated)
    taxonomy/
      categories.yml # rule-id -> category knowledge base (Plan.md §2/§3.4)
  runtime/           # runtime layer (Plan.md §4) — see runtime/README.md
    ingest.py        # leak-harness JSON -> SARIF -> the unified pipeline (PURE PYTHON, CI-gated)
    scenarios/       # declarative leak-harness scenarios (+ schema)
    LeakHarness/     # C# harness (FlaUI + procdump + ClrMD), Windows/build-required, not CI-gated
  config/profiles/
    desktop-wpf.yml  # which packs / severity floor for the net472 WPF target
  requirements.txt   # PyYAML (audit-scoped)
```

## Tiers (Plan.md §3.2)

| Tier | Tools | Needs a successful build of the target? |
|---|---|---|
| **build-free** | own-check, CodeQL (`build-mode: none`), XAML markup pass | no — works on a solution that does not compile |
| **build-required** | Roslyn analyzer packs, Infer# | yes |

The entire audit of the target runs on a **local Windows machine** (VS Build Tools
+ DevExpress 12.2). There is no CI run of the target — Own.NET's Linux CI only
gates the Python aggregation selftests (this subtree), exactly as it gates
`oracle_compare --selftest` today.

## Running it

```bash
# Build-free tier + report (own-check needs a .NET SDK on PATH; codeql if installed):
python audit/static/run_static.py \
    --target /path/to/legacy/src \
    --profile desktop-wpf \
    --target-name acme/LegacyApp --commit "$(git -C /path/to/legacy rev-parse HEAD)" \
    --out artifacts/own-audit
# -> artifacts/own-audit/report.md and report.json

# Build-required tier runs on the Windows machine; drop its SARIF into the same
# --out directory and re-run run_static.py to fold it into the report:
pwsh audit/static/tools/roslyn_pack.ps1 -Solution ..\target-audit\Target.sln \
    -AnalyzerCache .\cache -Out artifacts\own-audit
```

The aggregation modules also run standalone:

```bash
python audit/aggregate/normalize.py --sarif own-check=own.sarif --sarif codeql=cq.sarif \
    --json findings.json
python audit/aggregate/report.py --findings findings.json --format markdown
```

## Selftests

Every aggregation module carries embedded-fixture selftests (the
`oracle_compare --selftest` discipline). They need no external tools and gate on
Linux CI:

```bash
python audit/aggregate/normalize.py --selftest
python audit/aggregate/score.py --selftest
python audit/aggregate/report.py --selftest
python audit/static/tools/xaml_check.py --selftest   # XAML rules + line preservation + SARIF round-trip
python audit/static/tools/xaml_facts.py --selftest   # XAML facts: binding parser + resource graph
python audit/static/tools/xaml_join.py --selftest    # XAML<->C# join: XAML203 view-subscription leak
python audit/static/run_static.py --selftest   # full pipeline end-to-end on fixtures
```

`run_static.py` writes all four report formats to its `--out` directory:
`report.md`, `report.json`, `report.sarif` (upload to GitHub code scanning), and
`report.html` (a self-contained heatmap page).

## Status

- **Static (Phase 1) — done:** build-free runners, normalization + taxonomy (incl.
  the OWN001 `[resource:]` split, OWN014 region-escape labelling, and OWN050 routed
  to the coverage ledger), DevExpress baseline-suppress, cross-tool agreement
  scoring, the pain heatmap, **all four renderers (markdown / json / merged SARIF /
  HTML)**, the analyzer-injection props/targets, and selftests.
- **XAML analyzer (Phase 1, markup-only) — done:** a build-free, stdlib-XML pass
  (`static/tools/xaml_check.py`) feeding the same pipeline as a second fact source —
  line-preserving parse, the canonical SARIF record, and rules XAML100/101/102/103/104/
  105/106/107/108/109/110/111/112/113 (resource hoisting, merged-dictionary key shadowing,
  virtualization-off, per-keystroke binding, template complexity, Freezable/x:Shared/
  DynamicResource/merged-dictionary perf, image decode-at-full-size, LayoutTransform cost,
  TemplateBinding opportunities, and inline Freezable duplication). This makes category 8 (broken virtualization) statically
  covered, not NO-TOOL. Design + the full rule catalogue, phasing, and the Phase-2
  binding-path join: [`../docs/notes/xaml-analyzer-design.md`](../docs/notes/xaml-analyzer-design.md).
- **XAML Phase-2 seam — done:** `static/tools/xaml_facts.py` emits `xaml-facts.json` (resource graph
  + binding facts: parsed binding paths / converters / handlers + `x:Class` + `x:Name`) from the same
  parsed tree, in an OwnIR-parallel envelope.
- **XAML Phase-2 join (first slice) — done:** `static/tools/xaml_join.py` links `xaml-facts.json` to the
  OwnIR facts own-check now persists (`--emit-facts` → `own-check.facts.json`) by the deterministic XAML
  naming convention (`x:Class`→type, handler→method) — **build-free, no `.g.cs`/build needed**. First
  rule **XAML203** (view subscribes from a load-lifecycle handler but the OwnIR verdict is
  `released=false` → closed view retained), anchored at the code-behind subscription site so it
  clusters with own-check's `OWN001` into one high-confidence finding (no double-report) and names the
  XAML view that wired it.
  `run_static.py` runs the join whenever both fact sources are present and folds its SARIF into the
  pipeline. Binding-path-hotness rules (XAML200/204, need the DataContext type) and an optional `.g.cs`
  ground-truth cross-check are documented build-tier follow-ups. Phase 3 (runtime correlation) deferred.
- **Runtime (Phase 2) — started:** the runtime→pipeline bridge (`runtime/ingest.py`,
  CI-gated), the leak-harness scenario schema + one scenario, runtime rule mappings
  in the taxonomy (categories 2/3/4/11), and the C# leak-harness skeleton. See
  `runtime/README.md`.
- **Deferred:** the ClrMD duplicate-immutable detector and PropertyChanged-storm
  profiler; the AI-reviewer layer; feeding confirmed findings back into the OwnLang
  corpus.
