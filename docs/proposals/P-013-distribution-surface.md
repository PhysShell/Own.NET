# P-013 — Distribution surface: how people actually run Own.NET on C#

- **Status:** v0 built (CI/Action + dotnet tool)
- **Depends on:** P-001 (the C# → OwnIR extractor) and the core CLI
  (`python -m ownlang ownir`). Sibling of **P-011** (editor tooling for the
  `.own` DSL — a *different* direction; see "Not the same as P-011" below).
  Feeds **P-012** (the mining pipeline reuses the same repo-scan).

## Motivation

The pipeline `*.cs → extractor → facts.json → core → finding @ C# line` has
worked end-to-end in CI since P-001, but only against a hardcoded list of sample
files. Nobody outside this repo can *run* it. The question "how will people use
this?" has three candidate answers, and they cost wildly different amounts — so
the first job is to pick the one that fits the architecture, not the one that
sounds most impressive.

The load-bearing constraint is the ROADMAP's **"one checker"**: the Python core
is the single source of truth, and every frontend only *produces or consumes*
OwnIR facts. That rule decides the surface for us.

## The three surfaces (cost order)

| Surface | What the user sees | Cost | Fits "one checker"? |
| --- | --- | --- | --- |
| **CI / CLI gate** | a red check + PR annotations | low (≈ done in CI) | ✅ ideal — Python already runs here |
| **MSBuild diagnostics → VS Error List** | findings in VS, no extension | low–medium | ✅ text in a parseable format |
| **Native Roslyn `DiagnosticAnalyzer`** | live squiggles in the IDE | high | ❌ conflicts (see below) |

A native analyzer runs **in-process** inside `dotnet build` / the IDE. It would
have to either (a) reimplement the analysis in C# — a *second checker* that
drifts, the project's own meta-irony — or (b) shell out to Python on every
keystroke, which is slow, fragile, and needs a Python runtime on every dev
machine. So the obstacle to the IDE-native path is **architectural, not effort**.
The CI/CLI surface, by contrast, is where Python already lives and where "one
checker" is free.

Decision: **ship the CI/CLI surface first**, expose the same findings in the
MSBuild format so they *also* light up the VS Error List without an analyzer,
and defer the native analyzer until (if ever) the core itself moves to .NET.

## Scope (v0 — built)

- **`python -m ownlang ownir facts.json --format {human,github,msbuild}`.** The
  finding renderer lives in the core (`ownlang/ownir.py`), so the wrappers stay
  thin and there is exactly one place that decides what a finding says:
  - `human` — the existing CLI line (unchanged; the default).
  - `github` — a `::error file=…,line=…,title=OWN001::…` workflow command;
    GitHub renders it inline on the PR diff. Metacharacters are escaped.
  - `msbuild` — `file(line): error OWN001: …`, which `dotnet build` and the VS
    Error List parse — in-IDE findings with no extension.
- **Repo-walk in the extractor.** `ownsharp-extract <dir>` now recurses for
  `*.cs`, skipping `bin`/`obj`/`.git`/`node_modules`/`packages` and generated
  files (`*.g.cs`, `*.Designer.cs`, `*.AssemblyInfo.cs`). Finding paths are
  reported relative to the working directory (forward slashes) so annotations
  point at the right file even when names collide.
- **`scripts/own-check.sh`** (+ a PowerShell twin **`scripts/own-check.ps1`** for
  Windows/VS users without bash). One command that chains both stages (extractor
  → core) with `--format`, `--severity`, and `--fail-on-finding`. The body of the
  Action and a standalone local command.
- **`action.yml`** — a composite GitHub Action (`uses: PhysShell/own.net@…`):
  sets up Python + .NET, runs `own-check.sh` over the consumer's checkout,
  annotates the PR. Example consumer workflow in `examples/ci/own-check.yml`.
- **`dotnet tool`** — the extractor csproj is `PackAsTool`
  (`dotnet tool install --global OwnSharp.Extractor` → `ownsharp-extract`).
  Honest caveat: the tool is only the C# *extractor*; the verdict is still the
  Python core. The script/Action are the complete product.
- **`OwnSharp.Cli`** (alpha gate A, issue #202) — the single-install answer to
  that caveat: `dotnet tool install --global OwnSharp.Cli` → `ownsharp check
  <path|.sln>` wraps both stages in one tool. It bundles the *unmodified*
  extractor (`ProjectReference`, invoked as a child process) and vendors the
  *unmodified* `ownlang/` core (run on the machine's own Python, resolved via
  `OWN_PYTHON`/`py -3`/`python3`, `>=3.11`, fail-fast otherwise — never an
  auto-download). See [`frontend/roslyn/OwnSharp.Cli/README.md`](../../frontend/roslyn/OwnSharp.Cli/README.md)
  for the packaging shape and the rejected alternatives on record in the issue.
  Not yet published to nuget.org (Non-goals below, unchanged) —
  build-and-install from source until then; `own-check.sh`/`.ps1`/`action.yml`
  are untouched and remain the supported surfaces alongside it.

## Not the same as P-011

P-011 makes the **`.own` DSL** a first-class editor language (coloring,
squiggles for `.own` diagnostics) — input *to* the checker. P-013 is the
opposite direction: feed **C#** in, get findings out. Easy to conflate; they do
not overlap.

## Non-goals

- **A native Roslyn analyzer in v0** — deferred for the architectural reason
  above, not the effort. Revisit only if the core moves to .NET.
- **Wiring a 100-repo scan as a blocking gate** — that is P-012's offline job,
  not this per-repo check.
- **A second checker anywhere.** The wrappers never decide a verdict.
- Publishing to the GitHub Marketplace / NuGet.org, SHA-pinning, signed releases
  — packaging hardening, deferred to a release pass.

## Open questions

1. ~~MSBuild severity: emit findings as `error` or `warning`?~~ **Resolved:**
   a `--severity {error,warning}` flag (default `error`) is threaded through the
   core renderer, `own-check.sh`/`.ps1`, and the Action's `severity` input, so a
   build can show findings advisory (warning) without failing. The Action's
   `fail-on-finding` still gates CI independently.
2. Should `own-check` grow a `--baseline`/diff mode (only new findings on a PR)
   so adopting it on a legacy repo isn't an immediate wall of red?
3. Action distribution: a moving `@main`, or tagged releases (`@v0.1.0`) +
   Marketplace listing? (Ties into the packaging-hardening pass.)
