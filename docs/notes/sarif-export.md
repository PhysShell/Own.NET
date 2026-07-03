# SARIF export — own-check as a standard analyzer

`own-check … --format sarif` emits a **SARIF 2.1.0** log. SARIF is the OASIS
standard interchange format for static-analysis results; this is the first step
of the `SARIF exporter` backlog item from `docs/notes/research-landscape-2026.md`.

## Why SARIF earns its place (three payoffs, internal one first)

1. **It kills the bespoke own-check text parser in the oracle.** Until now
   `scripts/oracle_compare.py` was asymmetric: Infer# and CodeQL were read with
   `parse_sarif`, but *our own* findings went through a regex over human text
   (`mine_report.parse`), which carries an explicit "unparsed-line" failure
   bucket — the class of bug that silently left 38 lines unparsed, so only 3 of
   ~36 findings reached the diff on the ScreenToGif run (`real-world-mining.md`).
   With own-check emitting SARIF, the
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

## Follow-up pass — SARIF is now the live path

The two internal follow-ups are done (a second slice):

- **`mine_report.py` reads SARIF.** `parse()` sniffs a `{`-leading `runs` log and
  yields the same finding dicts as the text path (level → severity: `error` →
  error, `warning`/`note` → advisory, so OWN050 stays advisory and an
  injected-source warning stays advisory; kind from `properties.resourceKind`; the
  trailing `[resource: …]` split off the message), so the aggregation is identical
  between formats. The regex parser is now off the default path for **both**
  consumers — the oracle (slice 2 above) and the miner. Pinned by a SARIF selftest
  (14/14) and a human-vs-SARIF aggregation-parity check.
- **The producers emit SARIF.** `mine.sh` now defaults to `--format sarif` and
  `oracle.yml` runs own-check `--format sarif`; the intermediate (`findings.txt` /
  `own.txt`) carries a SARIF log and the human-facing output stays the rendered
  `report.md`. Both consumers sniff the format, so it is backward-compatible (a
  text intermediate still parses). This retires the documented parser-drift bug on
  the **live** eval paths, not just in capability. (Filenames kept to keep the CI
  edit minimal; the content, not the extension, is what the consumers read.)

## Shipped — code-scanning upload (the consumer surface)

The composite action now has a **fourth surface, `format: sarif`**: it writes a
SARIF 2.1.0 log to a file and exposes the path as the **`sarif-file` output**, so a
consumer hands it straight to code scanning. Code scanning *subsumes* the `github`
PR-annotation format — it renders inline PR annotations **and** the Security tab —
so this stays a single own-check run, not two. A consumer wires it in three steps:

```yaml
permissions:
  contents: read
  security-events: write          # to upload to code scanning
steps:
  - uses: actions/checkout@v4
  - uses: PhysShell/Own.NET@main  # pin to a tag or SHA in production
    id: ownnet
    with:
      path: src
      format: sarif
      fail-on-finding: "false"    # let code scanning be the gate, not the step
  - uses: github/codeql-action/upload-sarif@v4
    with:
      sarif_file: ${{ steps.ownnet.outputs.sarif-file }}
      category: own-net
```

### Why it is dog-fooded here (the deferral reversed)

The earlier draft deferred this — *"this repo's C# is test fixtures, so uploading
to its own Security tab is low-value."* That weighed the *findings* (intentional
fixture leaks — yes, low news value). It mis-weighed the *integration*: the repo is
**public**, so code scanning is free, and a live upload is the one thing a local
schema check cannot give — **proof that GitHub itself accepts the SARIF**
(`upload-sarif` waits for processing and fails the job if the log is rejected). So
CI validates the exporter on two levels:

- **structure** (`own-check-surface`): a `jq` contract over a freshly-emitted log —
  `version 2.1.0`, the `Own.NET` driver, and *every* result carrying a catalogue
  ruleId and a located file (the shape GitHub's ingest enforces). No upload, no
  permissions — runs everywhere.
- **end-to-end** (`own-check-codescan`): the composite action `format: sarif` over
  the sample tree, then `upload-sarif` under a *scoped* `security-events: write`
  (the only non-`contents:read` job in CI). The sample alerts ride a dedicated
  `own-net-samples` category and are real-if-intentional — they double as the live
  demo of the Security-tab surface this exporter was built for.

Still open:

- **Per-rule `helpUri`.** Once a stable per-code docs anchor exists, point each
  `rules[]` entry at it (intentionally omitted now rather than link a 404).

## The `.own` flow-diagnostic SARIF surface

Everything above is the **C# / OwnIR** path (`ownir --format sarif` over
`ownir.Finding`). The direct `.own` checker (`python -m ownlang check`) grew its
own SARIF surface once the flow diagnostics started carrying structured evidence
(the execution-surfaces ADR, §3.1): `check file.own --format sarif` emits the same
SARIF 2.1.0 shape — one `Own.NET` `run`, a `rules[]` catalogue of the OWN codes
present, one `result` per diagnostic — via `ownlang/diag_sarif.py`.

The point of the surface is the **evidence slice**: each diagnostic's
`Diagnostic.evidence` is projected through the *shared* `ownlang.evidence`
builders (`related_locations` / `code_flow`), so an OWN015 buffer escape rides a
`codeFlows` trace `allocated here -> escapes by return here`, an OWN001 leak points
at `acquired here`, and so on — the same `relatedLocations` + `codeFlows`
vocabulary the OwnIR path already speaks. A diagnostic with no evidence carries
neither key; a step with no resolvable line or file is dropped, so the log never
carries an empty `artifactLocation.uri`. `github`/`msbuild` stay OwnIR-only —
those are per-finding line renderers that need a `Finding`, not a `Diagnostic`.
