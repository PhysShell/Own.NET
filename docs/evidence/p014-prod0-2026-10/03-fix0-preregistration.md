# P-014 FIX0 — pre-registration

Written 2026-10-21 15:20 +05, before any production-code change. Owner decision:
`GO-FIX0 / REVIEW-EVIDENCE-PRESERVED / #423-MERGE-BLOCKED`.
- **What FIX0 is.** A **new, bounded experiment**. It is not a continuation of the refuted `PASS-P014-PROD0`.
- **Where that stands.** The KILL for `f84943d` (`02-review-result.md`) is final.

**Budget.** 0.25 agent-day, counted from 15:18. STOP at 17:18, not extended.
- Budget runs out: `INCONCLUSIVE-P014-FIX0`.
- `KILL-P014-FIX0`: stop, publish the review evidence and the negative result, and do not merge the production
  changes.

## 1. Changes allowed (only these three defects)

| Defect | Change |
|---|---|
| F-PROD0-1 conditional compilation | `Assets.Compile` inspects each parsed tree with Roslyn's directive API (`GetDirectives`, `#if`/`#elif` kinds), not a substring search. Any such directive gives `SOURCE_SET_INCOMPLETE(preprocessor-conditional)` |
| F-PROD0-3 unreadable source | a read failure in `Assets.Compile` gives `SOURCE_SET_INCOMPLETE(unreadable-source)`. The source-set scan's own silent skip records the same reason |
| Propagation (the owner's trap) | statuses that become known only while compiling must reach parents. The project-reference propagation moves from `Assets.Load` to `Assets.Compile`, **after** the children are compiled (post-order): a parent gets `p2p-unit-<status>:<id>` for every child whose final status is not `COMPLETE`. The sidecar is built only after `Compile` has finished for the whole closure |
| F-PROD0-2 probe markers | removed from the production path. `Coverage.Measure` parses `/*probe:…*/` only when the caller passes `recordProbes: true` (the evidence harness does; `Runner` does not), and then with a bounds check |

**Unchanged:**
- reference resolution and the manifest rules;
- the site counting rules;
- OwnIR, diagnostics, facts, SARIF and exit codes;
- defines and implicit usings, which are still not applied (#407 stays separate);
- the old `REPORT.md` and `00-preregistration.md`.

## 2. Acceptance (all on the FIX0 head)

1. **The review falsifiers on the new build.** Fixtures F1–F3 as in `01-review-falsifiers.md`, plus a new F4.

   | # | Expected |
   |---|---|
   | F-PROD0-1 | `SOURCE_SET_INCOMPLETE`, reasons include `preprocessor-conditional` |
   | F-PROD0-2 | the sidecar is written and `unit_status` is present |
   | F-PROD0-3 | `SOURCE_SET_INCOMPLETE`, reasons include `unreadable-source` |
   | **F-PROD0-4** (`Root → Child`, a file in `Child` unreadable) | Child `SOURCE_SET_INCOMPLETE(unreadable-source)`; **Root `SOURCE_SET_INCOMPLETE` with `p2p-unit-source_set_incomplete:Child`** |

2. **G0–G3 from `00-preregistration.md` re-run unchanged** with `scripts/run_prod0.ps1`:
   - facts byte-identical across `main` and the branch with and without the flag;
   - controls K1, K2, K4, K5, K6, K7, K11, K12, F2.3–F2.5 and the guard;
   - the oracle fixtures K3, K8a–c, K9 and G0, plus K10;
   - P4/P5 not `COMPLETE`;
   - sidecar determinism;
   - cost: P5 added time ≤ 3 × legacy-merged warm in the same session; peak ≤ 2.0 GB.
3. **Allowed differences from the `f84943d` evidence:**
   - added reasons `preprocessor-conditional`, `unreadable-source` and `p2p-unit-*` that follow from them;
   - fixtures whose sources contain `#if` change status. K7 is in-memory and has no unit status.

   Site counts, manifests and conflicts of P4/P5 and of the fixtures must be **identical** to the `f84943d` run.
   Any other difference is a FAIL.
4. **Repository gates:**
   - no new build warning;
   - `ruff check .` passes;
   - `python tests/run_tests.py` with `cargo` on PATH shows no failure beyond the baseline 87
     `test_cli_ownir_fixtures` CRLF cases.
5. **CI** is green on the new head after the push. The only accepted exception is `Owen: NEUTRAL`.

## 3. Verdict

- **`PASS-P014-FIX0`.** Items 1–4 hold locally. The push follows (review evidence → this pre-registration → the
  fixes → the results), and item 5 is then checked.
- **`KILL-P014-FIX0`.** Any of:
  - a falsifier still holds;
  - facts change;
  - an unexpected difference appears;
  - a new test failure appears.
- **`INCONCLUSIVE-P014-FIX0`.** The budget runs out.
