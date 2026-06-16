# Corpus mining — stress-testing the analyser on real repos

A spot-check harness: take a public C# repo, run the Own.NET leak check over it,
and aggregate the result into a structured report. The goal is **evaluating the
analyser**, not crawling GitHub — one repo at a time, shallow and read-only.

## Why it's cheap

The Roslyn extractor (P-014 Tier A) builds a best-effort `SemanticModel` from the
runtime's trusted-platform assemblies and is error-tolerant: it reads symbols
without a `dotnet restore`/build of the target, and external (NuGet) types it
can't resolve become an honest `OWN050` "unchecked" marker rather than a guess.
So mining needs **no per-repo build setup** — just point it at the `.cs`.

## Run it

In CI (no local .NET needed) — Actions tab → **mine (corpus)** → *Run workflow*,
or via the API; the report lands in the run summary and as an artifact:

```
inputs: repo = DapperLib/Dapper   ref = (optional)   paths = (optional subdir)
```

Locally (needs `dotnet`, `git`, Python 3.11+):

```sh
scripts/mine.sh DapperLib/Dapper                 # whole repo
scripts/mine.sh --paths src JoshClose/CsvHelper  # focus a subdir
```

Output → `corpus/mined/<slug>/` (gitignored): `findings.txt`, `extract.log`,
`report.md`, `report.json`. Seed targets live in `corpus/targets.txt`.

## What the report says — and how to read it

`scripts/mine_report.py` aggregates the findings into: counts by OWN code, the
error/advisory split, resource kinds, the noisiest files, and a triage list of
the error-severity findings.

- **A clean run is a signal, not a dud.** On well-disciplined code (lots of
  `using`) zero findings is the *precision* result we want to see.
- **A pile of `OWN001`s** is either real leaks (reduce one to a minimal `.cs` and
  add it to `corpus/real-world/` as a regression) **or** a false-positive pattern
  — the cue to harden the extractor (a new exemption, better escape analysis, a
  new lowering).
- **A high `OWN050` count** is a *coverage* gap: the declaring types are
  unresolved external references. Not wrong, just not analysed.

## The loop

`mine → triage → (a) regressions in corpus/, (b) fixes in the extractor/exemptions`
→ repeat. The methodology matches the GTM triage (real leaks kept, dispose-optional
FPs exempted → 100% precision); mining stresses that on shapes we haven't seen.

## Honest gaps (v1)

- **No coverage/skip rate yet.** A method the extractor can't model (a `for`/`do`
  loop, `try`, …) is silently absent from the facts, so the report can't say
  "analysed N of M methods". Adding a `--stats` summary to the extractor is the
  planned next step.
- **One target, by hand.** Auto-discovery (GitHub code search for IDisposable
  patterns) is deliberately out of scope — keep it a deliberate spot-check.
- **Reporting upstream is a separate, manual step.** If a finding is a real bug
  worth disclosing, do it deliberately (and check the license); the miner never
  contacts the target project.
