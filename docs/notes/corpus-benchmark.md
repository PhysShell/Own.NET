# Corpus benchmark — recall + specificity on real C# (P-012 slice 1)

The labeled corpus (`corpus/<area>/<case>/`) was already half a benchmark: every
case carries `before.cs` (buggy), `after.cs` (fixed), `expected-diagnostics.txt`
and a `case.own` reduction. But the only thing scoring it — `tests/test_corpus.py`
— checks the **`.own` reduction**, and its own note conceded *"not that the tool
scanned real C#."* That note is now stale: the P-001 extractor exists.

`scripts/benchmark.py` closes the gap. It runs the **actual C#** through the
extractor + core (`own-check.sh --format sarif`) and measures the two things the
`.own` check cannot:

- **recall** — the bug is *caught* in the real `before.cs` (≥ 1 verdict);
- **specificity** — the real `after.cs` (the fix) is *silent* (0 verdicts — no
  false alarm on correct code).

The aggregate is one defensible line. The **first measurement** (9 cases):

```text
benchmark: 3/9 bugs caught in real C# · 9/9 fixes clean · 0 false positive(s) on fixes
```

That is the honest day-one number, and it is *sharp*: **specificity is perfect**
(every real fix is silent, zero false positives — the checker does not cry wolf on
correct code), and **recall is 3/9** — the three caught are exactly the
subscription/region class the extractor is strongest at (`zombie-viewmodel` →
OWN001, two static-event escapes → OWN014). The six missed
(`arraypool-double-return`, `arraypool-use-after-return`, `ownership-handoff-consume`,
`screentogif-loaded-subscription`, `handler-use-after-dispose`,
`viewmodel-escapes-to-app`) are cases the `.own` reductions *all* catch but the C#
**frontend** does not yet extract — pool double-return/use-after-return,
ownership-handoff, and a few dispose/escape shapes. The benchmark just quantified
the frontend's recall debt and turned it into an itemized to-do list.

## Why catch/clean, not exact-code match

The metric is deliberately **code-agnostic**: a leak reported as `OWN001` (token
leak) vs `OWN014` (region escape) both count as "caught". `test_corpus.py` pins the
exact code on the `.own` reduction; the real-C# benchmark answers the blunter, more
honest product question — *did we catch the real bug, and did we stay silent on the
real fix?* — which survives a sound reclassification of the leak that an exact-code
assertion would spuriously fail. (`expected-diagnostics.txt` is still reported as a
secondary `expected_hit` signal, just not part of the gate.)

A **verdict** is any SARIF result at error/warning level. The advisory `note` level
(`OWN050` "resolution skipped") is coverage honesty, not a verdict, so it is
neither a catch nor a false positive — a `before.cs` whose framework type didn't
resolve reads as a *miss*, not a fake catch.

## Validated two ways (the harness pattern)

- **`--selftest` (no SDK)** — the SARIF-parsing and scoring/aggregation logic is
  pinned on embedded fixtures (verdict levels counted, `note` excluded, malformed
  input safe, the catch/clean/FP arithmetic), wired into the lint job alongside the
  miner/oracle/metamorphic selftests. Keeps the harness honest on every push.
- **`corpus-benchmark` CI job (dotnet)** — runs the real benchmark. Some cases
  subscribe to framework events (WPF `Window`, `Microsoft.Win32.SystemEvents`), so
  it materializes the WindowsDesktop ref pack and exports `OWN_EXTRA_REF_DIRS` (the
  same mechanism as the oracle/mine jobs) — else a `+=` to an unresolved event is an
  `OWN050` note, not a leak. The gate is **asymmetric and honest**: precision is
  absolute (**every** `after.cs` silent, **zero** false positives — a regression
  there means crying wolf on correct code), while recall is pinned at a **floor**
  (`--min-recall`, currently 3) that ratchets up as the frontend's extraction
  coverage grows. We do *not* hard-assert 9/9 the tool cannot yet deliver — the
  benchmark *reports* the recall number and forbids it regressing, which is exactly
  what a measurement spine should do.

## Why it matters

This is the **measurement spine**. Until now "does Own.NET work?" was answered by
the `.own` logic check and anecdotal oracle overlaps; now there is a reproducible
recall/specificity number over real C#, pinned against regression. It is also the
**verifiable reward** for any future learning loop (RLVR): a deterministic verifier
over labeled real-C# data is exactly the clean reward signal — built *before* any
proposer/LLM layer, never trusting a source.

## Next

- Grow the corpus (P-012 stage 1 mining) — every new mined `before`/`after` pair is
  a new benchmark row for free; the number gets more defensible as N grows.
- Stage 2 prevalence scan (hits per 1k LOC across 50–100 repos) feeding the
  `docs/ROADMAP.md` priority matrix — replacing the proxy estimates with counts.
- Per-code recall and a precision breakdown once the corpus is large enough for the
  rates to mean something.
