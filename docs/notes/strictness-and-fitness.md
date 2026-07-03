# Strictness & architecture fitness — a cross-stack policy

Status: **notes / doctrine** (the tooling posture across the three stacks; companion to
`docs/proposals/P-022-rust-core-migration.md`, which carries the Rust specifics)

## The doctrine: ratchet, not a big bang

The prime directive is **a false positive is worse than a miss**. That has a direct
consequence for linting/analysis tooling: switching maximum strictness on *all at once*
over a live codebase produces thousands of findings, a week of firefighting, and a
learned habit of slapping `suppress` on without looking — and a linter you reflexively
silence is dead for real.

So the pattern is a **ratchet**, everywhere:

- **Baseline** the current violations (built in to ruff, SonarQube, NDepend; in .NET via
  editorconfig severities; in Rust via an allow-then-deny sweep).
- **New code** is held to the full bar.
- **Old code** may only get better, never worse.
- Tighten **half a turn per iteration**, not strip the thread in one evening.

This is the same ratchet we already run for **correctness** (the differential oracle,
P-022) and **performance** (the `iai-callgrind` instruction-count gate). Strictness is
the third axis of the same idea: a monotone gate that only ever tightens.

## Rust (007, sandboy, snipx, griff)

Lint config is declarative and workspace-inherited (Rust ≥ 1.74) — the concrete
`[workspace.lints]` block lives in **P-022 § "Compiler strictness"** (`unsafe_code =
forbid`, `unreachable_pub`/`rust_2018_idioms` deny, clippy `pedantic`/`nursery` as
`warn` with justified `#[allow]`, surgical deny of `unwrap_used`/`indexing_slicing`/
`arithmetic_side_effects`/`panic`/`dbg_macro`/`print_stdout`).

Supply-chain and structure:

- **`cargo-deny`** — licenses, advisories, duplicate versions, banned crates.
- **`cargo-udeps`** (nightly) / **`cargo-machete`** (stable) — dead dependencies.
- **`cargo-semver-checks`** — public-API break detection; critical for library-shaped
  crates (e.g. `snipx`).
- **`cargo-hack --feature-powerset`** — build/test the feature combos nobody compiled.
- **`cargo-modules`** — module-graph structure + acyclicity.
- **`cargo-mutants`** — mutation testing: do the tests *catch* a deliberately broken
  branch, or are they green-but-blind? The sharpest instrument here.

Honest limit: **no full NDepend-for-Rust** (no LCOM / instability / "zone of pain"
metrics). The language compensates partly (orphan rules, default privacy,
`unreachable_pub`); the rest is `cargo-modules` + hand-written `cargo metadata`
dependency tests.

## C# / .NET (enterprise WPF; the Roslyn extractor)

Base in the csproj:

```xml
<TreatWarningsAsErrors>true</TreatWarningsAsErrors>
<AnalysisLevel>latest-all</AnalysisLevel>
<AnalysisMode>All</AnalysisMode>
<EnforceCodeStyleInBuild>true</EnforceCodeStyleInBuild>
```

plus an `.editorconfig` that raises the IDE rules to `severity = error`. On Framework
4.7.2, `<Nullable>enable</Nullable>` (via `LangVersion`) annotates your own code only —
the BCL stays unannotated — still better than nothing.

Analyzers, ranked by value here:

- **IDisposableAnalyzers** — ownership/dispose discipline. This is literally the Own.NET
  philosophy applied to live C#: who owns, who releases, who leaked. Install first.
- **Microsoft.VisualStudio.Threading.Analyzers (VSTHRD)** — async rules written in the
  VS team's blood: `.Result`/`.Wait()` deadlocks in WPF, `async void`, `ConfigureAwait`.
  Mandatory for a WPF app.
- **Meziantou.Analyzer** — culture-dependent strings, forgotten `CancellationToken`s,
  allocations.
- **ErrorProne.NET** — struct-performance and exception hygiene.
- **SonarAnalyzer.CSharp** — broad, free bug detection.
- **BannedApiAnalyzers** — your own deny-list (`DateTime.Now`, `Task.Result`,
  `File.ReadAllText` without an encoding, …) in one `BannedSymbols.txt`.
- **Roslynator + StyleCop** — style, to taste.

Architecture as executable invariants (not a wiki page nobody reads):

- **NetArchTest.eNhanced** / **ArchUnitNET** — "ViewModels don't reference the DAL",
  "nothing depends on the UI assembly", "all repositories are internal" — as unit tests.
- **NDepend** (paid, only one in its class) — LCOM, afferent/efferent coupling,
  instability `I = Ce/(Ca+Ce)`, abstractness, distance-from-main-sequence (the
  zone-of-pain / zone-of-uselessness diagram), and CQLinq (LINQ queries over your own
  codebase as CI rules).
- **Stryker.NET** — mutation testing for .NET.

## Python (ownlang — the reference core)

`mypy --strict` is already in the gate. Tighten around it:

- **ruff** with `select = ["ALL"]` and a deliberate, commented ignore list — it includes
  the pylint design metrics (`too-many-branches`/`-arguments`/`-statements`), crude but
  workable proxies for low cohesion.
- **xenon** — fails the build when cyclomatic complexity exceeds a threshold
  (`xenon --max-absolute B`).
- **vulture** — dead code.
- **import-linter** — architectural contracts for Python: "lexer does not import
  codegen", "layers go strictly downward" — exactly the pipeline discipline ownlang
  needs (and the analogue of the Rust crate-DAG fitness test).
- **pyright** in strict as a second opinion to mypy — they catch different things.
- **Hypothesis** — property tests on lexer/parser; generative inputs find what the
  golden tests didn't imagine.

## Cross-stack

- **CodeQL** — free for public repos (ours are public). It is the Datalog-over-code we
  keep circling back to (P-022 § open questions), ready-made; turn it on in Actions.
- **Semgrep** — custom rules in YAML in ~10 minutes; ideal for project bans ("nobody
  calls `subprocess` outside our wrapper in 007").
- **SonarQube Community** — a dashboard, if wanted.

## The honest limit: SOLID is semantic

SRP and DIP are *semantic* properties; statically they are only approximated by proxy
metrics (size, coupling, LCOM). NDepend and ArchUnit give an approximation; the real
"this class does two things" judgement comes from **review — human or LLM**. The
CodeRabbit + Codex layer we already run on every PR is precisely that missing tier, so
that slice is already being built, not bought.

## Starting order (≈ a day's work, ~80 % of the value)

1. **IDisposableAnalyzers + VSTHRD** in the WPF app — a direct hit on the ownership
   theme.
2. **clippy `[workspace.lints]` + `cargo-deny`** in the Rust workspace.
3. **import-linter** in ownlang.
4. **CodeQL** in Actions across all public repos.

Then take **NDepend** on trial and run it once over the enterprise solution — the
main-sequence diagram on a legacy codebase is an experience after which people either
refactor or drink (occasionally both). Everything else is applied on the ratchet.
