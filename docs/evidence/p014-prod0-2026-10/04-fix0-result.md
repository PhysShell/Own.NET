# P-014 FIX0 — result

**Local verdict: `PASS-P014-FIX0`** (items 1–4 of `03-fix0-preregistration.md`). Item 5, CI on the pushed head, is
checked after the push.

This PASS belongs to the **FIX0 head** only. History, kept unrewritten:

| Step | Result |
|---|---|
| `REPORT.md` | issued `PASS-P014-PROD0` for `f84943d` |
| `02-review-result.md` | that PASS was **refuted** by adversarial review: `KILL-P014-PROD0` for `f84943d`, final |
| this file | FIX0 is a separate, bounded experiment on a new head |

Rules: `03-fix0-preregistration.md`, commit `f60f35f` (15:16:52 +05), before any production change. The code fix is
commit `af18f0b`. Work 15:16 to about 15:30 +05, within the 0.25 agent-day budget.

## 1. What changed (only the three defects) [read, `af18f0b`]

- **`#if`/`#elif`.**
  - `Assets.Compile` checks each parsed tree with Roslyn's directive trivia (`ContainsDirectives`, then
    `IfDirectiveTrivia`/`ElifDirectiveTrivia`), not a substring search.
  - Any hit gives `SOURCE_SET_INCOMPLETE(preprocessor-conditional)`.
  - `GetDirectives` is not public in Roslyn 4.9.2, so the trivia API is used instead.
- **Unreadable sources.** A read failure in `Assets.Compile`, or in the source-set scan, gives
  `SOURCE_SET_INCOMPLETE(unreadable-source)`.
- **Propagation (the owner's trap).** Project-reference statuses now propagate in `Assets.Compile`, **post-order,
  after each member's sources are read**. Before, it happened in `Assets.Load`, before reading. The sidecar is built
  only after the whole closure is compiled.
- **Probe markers.** `Coverage.Measure` parses `/*probe:…*/` only when the caller passes `recordProbes: true`, with
  a bounds check. The production `Runner` never passes it; the evidence harness does.

## 2. Falsifiers on the FIX0 build [run, `data/fix0/review_fix0.log`]

| # | `f84943d` | FIX0 |
|---|---|---|
| F-PROD0-1 `#if NET8_0`, no `DefineConstants` | `COMPLETE` | **`SOURCE_SET_INCOMPLETE [preprocessor-conditional]`** |
| F-PROD0-2 `"/*probe:"` in a source | no sidecar (`ArgumentOutOfRangeException`) | **sidecar written** (`COMPLETE`, no reason) |
| F-PROD0-3 unreadable `B.cs` | `unreadable = 1` + `COMPLETE` | **`SOURCE_SET_INCOMPLETE [unreadable-source]`**, `unreadable = 1` |
| F-PROD0-4 `Root → Child`, `Child/B.cs` unreadable | Child **and Root** `COMPLETE` (`data/fix0/review_f84943d_F4.log`) | **Child `SOURCE_SET_INCOMPLETE [unreadable-source]`; Root `SOURCE_SET_INCOMPLETE [p2p-unit-source_set_incomplete:Child]`** |

## 3. G0–G3 re-run [run, `data/fix0/run_prod0.log`, `data/fix0/compare_fix0.log`]

| Check | Result |
|---|---|
| Facts byte-identity, `main` 22b29d5b vs FIX0 without the flag vs FIX0 with it | identical: P4 `AD528B8A…`, P5 `5F0EA76D…`, samples `F82A32D8…`; also across 6 off/on runs |
| In-memory controls against the production code | all PASS; `controls.json` **identical** to the `f84943d` run |
| Oracle fixtures through the flag | K8a 163 = 163, K8b 163 = 163, K8c 206 = 206, G0 209 = 209, K9 163 = 163 and 167 = 167, no tie; K9 without TFM `UNSUPPORTED`; K10 as before |
| Comparison with the `f84943d` run (12 sidecars, controls) | **PASS.** Every field identical (manifest, conflicts, sites, errors, files, methods, foreign) except reasons. The only added reason is `preprocessor-conditional`, on P4's root project and on P5. Nothing removed, and no status moved except within the allowed direction |
| G1 | all P4/P5 units still `SOURCE_SET_INCOMPLETE` |
| Determinism | sidecar byte-identical across 3 runs (P4, P5) |
| Cost (median of 3 processes) | P5: the flag adds **1578 ms** (4067 vs 2489), limit 3 × legacy-merged warm in the same session = 3 × 907 = **2721 ms**; peak about 297 MB. P4: +1580 ms, limit 3 × 1527 = 4581 ms; about 258 MB |
| Build | only warning is the existing `Program.cs` CS8620 |
| `ruff check .` | passes |
| `python tests/run_tests.py` (cargo on PATH, clean tree at `af18f0b`) | exit 1, **identical FAIL set to the `main` baseline**: 87 `test_cli_ownir_fixtures` CRLF cases. A first run on a dirty working tree also failed `fresh-record-valid` ("evidence was taken on a dirty tree"); the re-run on the committed tree does not |

## 4. Limits (unchanged from `REPORT.md` §6, plus the review's point)

1. A complete reference set is not a complete compilation. P4/P5 stay `SOURCE_SET_INCOMPLETE`.
2. **`preprocessor-conditional` is conservative.** Any `#if`, including `#if DEBUG`, makes a unit incomplete. That
   is fail closed, and it means few real projects will ever be `COMPLETE`.
3. **`foreign_binding = 0`** is a guard against leaks **between units**. It is not proof that the manifest is right:
   its allowlist comes from the same compilation. Manifest correctness rests on the SDK-oracle comparisons.
4. The conflict-resolver qualification is unchanged: equal-version package-vs-package, rank and platform are not
   qualified.
5. The environment is SDK 11.0.100-rc.2 with packs 8.0.32/10.0.13. The CRLF golden-test issue is a separate
   problem and is not addressed here.
