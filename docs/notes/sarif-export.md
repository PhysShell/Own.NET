# SARIF export — own-check as a standard analyzer

`own-check … --format sarif` emits a **SARIF 2.1.0** log. SARIF is the OASIS
standard interchange format for static-analysis results; this is the first step
of the `SARIF exporter` backlog item from `docs/notes/research-landscape-2026.md`.

## Why SARIF earns its place (three payoffs, internal one first)

1. **It kills the bespoke own-check text parser in the oracle.** Until now
   `scripts/oracle_compare.py` was asymmetric: Infer# and CodeQL were read with
   `parse_sarif`, but *our own* findings went through a regex over human text
   (`mine_report.parse`), which carries an explicit "unparsed-line" failure
   bucket — the class of bug that silently dropped 38 of ~36 findings on the
   ScreenToGif run (`real-world-mining.md`). With own-check emitting SARIF, the
   oracle reads **all three tools through one reader**. The fragile parser stops
   being on the critical path.
2. **GitHub code-scanning native.** A SARIF log uploads straight to code scanning
   (inline PR annotations, the Security tab) — no bespoke `::warning` emitter
   needed for that surface.
3. **Reproducibility.** A frozen, diffable run artifact: the rule set + every
   result with a stable location, for benchmark/regression use.

## What was built (two slices, one PR)

- **Slice 1 — the emitter (`ownlang/ownir.py`).** `build_sarif(findings,
  severity)` returns one SARIF `run`: `tool.driver` is **Own.NET** with a `rules`
  catalogue of the OWN codes present (titles from `diagnostics.TITLES`), and one
  `result` per finding — `ruleId` = the OWN code, the C# file/line as a
  `physicalLocation`, the message (with its `[resource: …]` tag), and the
  resource kind + subscription triple in `properties`. Wired as a fourth
  `--format` alongside `human`/`github`/`msbuild`; like the other machine formats
  the JSON goes to stdout and the summary to stderr, and the exit code is
  unchanged.
- **Slice 2 — the oracle reads it (`scripts/oracle_compare.py`).** `build_own`
  sniffs the input: a leading `{` → SARIF → `parse_sarif(text, "own", …)`; else
  the legacy text path. `_oracle_class` classifies `tool == "own"` by OWN code
  (`_own_class`), so the two own input formats bucket **identically** (OWN001/014
  → leak, OWN002/009 → use-after, OWN003 → double, everything else → other). The
  selftest pins a hand-built own-SARIF case; `tests/test_ownir.py` pins the real
  round-trip (`build_sarif` → `parse_sarif` → classed as a leak).

## One design decision: the `note` level

SARIF has four levels (`error`/`warning`/`note`/`none`); the flat surfaces have
only error/warning. The mapping (`_sarif_level`) keeps the CLI's per-finding
severity but uses **`note`** for advisory OWN050 ("declaring type unresolved —
analysis skipped"). That is the honest SARIF semantics — a *coverage skip* is not
a *warning-tier leak* — and it lets a consumer (incl. our own oracle) tell them
apart, which error/warning cannot. Leak verdicts still map error / warning
(intrinsic-warning, e.g. an injected-source subscription) / and downgrade under a
`--severity warning` host.

## Follow-ups (recorded, not done here)

- **Flip the `oracle.yml` workflow to feed SARIF.** The comparator now accepts
  both formats, so this is a backward-compatible 2-line CI edit (own-check
  `--format sarif` → `own.sarif`, `--own own.sarif`). Left out of this PR to
  avoid changing CI blind; the capability + selftests land first.
- **`mine_report.py`: parser → aggregator-over-SARIF.** The aggregation/triage
  half (counts by code/severity/kind, noisiest files, triage list) stays useful;
  re-point it at SARIF input so the regex parser is retired everywhere, not just
  in the oracle.
- **GitHub code-scanning upload.** Add a CI step that uploads the SARIF, and
  decide whether to keep the bespoke `::warning` annotation emitter or drop it.
- **Per-rule `helpUri`.** Once a stable per-code docs anchor exists, point each
  `rules[]` entry at it (intentionally omitted now rather than link a 404).
