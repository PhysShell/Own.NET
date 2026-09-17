# docs/evidence/p036-bakeoff — machine-readable record of the P-036 bakeoff

Companion to `docs/notes/p036-bakeoff.md`. Produced by
`scripts/p036_bakeoff.py` at `70189a3` on 2026-09-17 (Linux container,
.NET SDK 8.0.425, WindowsDesktop ref pack 8.0.31, CodeQL 2.27.0 bundle,
CodeQL bundle 20221211 for RLC#, Infer# v1.5, NetAnalyzers 8.0.9,
IDisposableAnalyzers 4.0.8).

- `corpus.json` — the preregistered case manifest (`cases`: 45 cases; family,
  provenance class, source, expected codes, subject, why it matters to P-036,
  tools declared NOT_APPLICABLE by documented rule scope, stubs) plus, under
  `posthoc_cases`, the two provenance-5 controls added after the owner's audit
  of `c57a919` (F4-C1 / F4-C2, the 2×2 factorial around F4-S1; note §1.1).
- `results.json` — every (case, side, tool, config) result: status from the
  preregistered vocabulary, leak-family findings, other findings, elapsed
  seconds, notes; the per-tool discrimination summary (preregistered cases
  only); and `decision_inputs` with (a) the preregistered mechanical block
  (D1/D2/D4, provenance ≤ 4 only, unchanged since the run), (b)
  `literal_contract` — D1/D4 recomputed from the §0.6 wording literally,
  every reading defined inline, and (c) `posthoc` — the controls' statuses,
  the F4 factorial reading per tool, duplicate-cell agreement with F4-S1's
  original rows, and a de-confounded D2. Blocks (b) and (c) never replace (a).
- `summary.md` — the generated status matrix.
- `raw/<tool>/<case>.<side>.<config>.json` — the tool's findings as parsed
  from its native output (SARIF / CSV / build log), verbatim messages. Full
  SARIF files are not committed (they are dominated by tool metadata); the
  harness regenerates them.
- `custom-codeql/` — the two bakeoff-written CodeQL queries (expressiveness
  probe; never scored as stock).

Every `elapsed_s` value carries the label
`EXPLORATORY ONLY / NON-ADMISSIBLE FOR #263 / NON-PUBLICATION-GRADE /
UNCONTROLLED SHARED HOST`: the run shared four cores with three parallel
workers and no warm-up policy. Use it to spot a 100× disaster, never to rank.
