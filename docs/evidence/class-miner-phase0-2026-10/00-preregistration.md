# Class miner Phase 0 — pre-registration

Written 2026-10-20, before any record of the corpus was read for this purpose. Only the ledger schema
(`evidence/ledger/SCHEMA.md`) has been looked at.

Authority: owner decision `GO-CLASS-MINER-PHASE-0`, given after the `KILL-DICTIONARY-REF-PILOT` ruling. This is
not a GO on implementing an analyzer.

## Question

Does a fix corpus of real, confirmed defects contain a **narrow, recurring** defect mechanism? To qualify, Own.NET
must miss it today, and it must justify the next investment.

## Inputs (reuse only, no new miner)

- **Corpus 1.** The 58 bug/fix pairs of the Own.NET direction research, a private repo. Its records are in
  `evidence/ledger/records.jsonl` (`source_type = github_pr_fix`), and per-pair facts and Own.NET runs are in
  `evidence/pairs/`.
- **Existing tools.** `scripts/` of that repo; `triage_pairs.py` and the `gh` query scripts of #412.
- **Deep check.** At most **12 new PRs** outside corpus 1. They are read through the GitHub API (diff, description,
  tests). Nothing is built and no package is downloaded.
- **Budget.** 0.5 agent-day.

## Definitions

- **Narrow class.** One mechanism that can be stated as one rule: the same code shape plus the same failure, for
  example "a pooled buffer is not returned on the exception path". A C01–C18 category is too broad to be a class.
- **Confirmed defect.** All three must hold:
  1. a merged fix;
  2. the diff establishes the mechanism (`ground_truth_level` ≥ `patch_supported`, or the same on reading a
     deep-check PR);
  3. there is evidence of an observable effect: an issue report, a profiler or dump result, a regression test, or a
     maintainer statement. `impact_evidence = none` does not count.
- **Product code only.** Tests, samples and benchmarks do not count.
- **Independent.** Different repository owners. Two defects in one repo count as one.

## Excluded classes (already decided; not reopened)

- C01: event subscription retention (R5 killed).
- C18: SemaphoreSlim.
- The D10 design.
- #382 shape A (canonical first-party calls) and #406 shape B (closure capture): NO-GO within budget.
- #400 stale dictionary ref: KILL.
- #402 CTS inversion (blocked by #407, deferred).

The Meziantou exception-safety defect C-1b (a `default` value is inserted before the factory runs and stays when
the factory throws) **is** eligible. It already has one confirmed instance.

## Recorded per candidate class

- the independent repos and the defects counted;
- the observable effect and its evidence;
- whether a regression test exists;
- the current Own.NET result, taken from the ledger's `ownnet_result`/`ownnet_detail` (no new run unless the
  ledger says `not_run`);
- the expected implementation cost (S/M/L), with the existing Own.NET capability it would reuse.

## Decision rules

- **GO-CANDIDATE.** At least **2 independent confirmed defects** of one narrow class, and Own.NET does not detect
  them: `not_detected_*`, `unsupported`, or `detected_partial` where the warning does not identify the mechanism.
  The output is a recommendation for the owner, not an implementation.
- A class that Own.NET already detects on all its instances is not a gap, and is reported as such.
- Two or more qualifying classes are ranked by the number of independent confirmed defects, then by evidence
  strength, then by cost. Ranking does not lower the threshold.
- **STOP.** No class reaches 2 within the corpus plus the 12 deep-check PRs. The search is not widened.
- A class is defined from the fix mechanisms before its Own.NET result is looked up. Classes are not redefined
  after the count to reach the threshold. Any merge or split of a class is recorded with its reason.

## Known biases

- Corpus 1 was assembled by queries aimed at resource-lifetime categories (design A), so it over-represents
  them.
- One researcher classifies. Ledger levels marked `reviewer_verified(llm)` were set by an earlier agent.
