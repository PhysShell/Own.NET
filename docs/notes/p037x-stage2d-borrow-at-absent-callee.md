# P-037-X Stage 2d — the legacy borrow at a call line without a coordinate (EXPLORATORY)

> Status: **EXPLORATORY research record, research branch `research/p037-max-v1` only.** Pre-registered
> BEFORE the code in Own.NET-paperwork `paper-eval/p037-max/stage2d-prereg-v1.json` (commit `fa4e2b6`);
> nothing in the Stage-2, 2b or 2c records is re-expected. Not a production migration, not a reopen of
> #304 (frozen 2026-09-28, unchanged). Stage commits: `6704185` (R6, the controls, the re-recorded
> pins) and the one carrying this note. Evidence: `paper-eval/p037-max/stage2d-borrow-at-absent-callee-v1.json`.

## 1. Why

The frozen protocol's row XD-4 states the carrier's value for a guarded release whose other branch forwards
to an unresolved callee: `(must, no)` → collapse `may` — the unresolved forward is the legacy **borrow**,
the optimistic assumption every production engine makes, not the kernel's `unknown`; representing
unresolved callees as calls is deliberately not made in P-037-X. The B1 driver did not apply that decision:
it read any op at a sidecar call line as a forward, resolved the callee, and answered NO_GUARDED_EVIDENCE
when no coordinate existed. So XD-4's own control read `callee_no_record` instead of `(must, no)`, and
case 4 — an external delegate call in a `using` initializer, then the guarded release — read `multi_action`.

## 2. The rule (REPOSITORY FACT; stated generically)

**R6** (`own-guarded/src/facts.rs`): a body op at a sidecar call line whose callee has **no coordinate for
reasons of absence** (`callee_external`, `callee_no_record`, `callee_unresolved`) contributes by its own
kind — a `use` is the borrow of its path (kept, not an action), a `release` its release — never a forward.
The call stays placeable (A15) and its sidecar facts are unchanged. A canonical `call` op whose callee
vanished is still a forward and fails closed. An identity conflict (`callee_sig`, `callee_overloaded`) is
not absence and keeps B1's answer; two forwards to coordinates on one path stay `multi_action`.

Why this is not "reading absence as a value": the value comes from the *present* legacy op, which the
production engines read the same way; absence only selects which rule applies — exactly what XD-4 states.
Since Stage 1 a first-party forward to a record-carrying callee is a canonical `call` op, so a `use` at a
call line is a degraded or external call; B1 A11's ambiguity (a folded forward indistinguishable from a
use) no longer exists on this carrier.

Two B1 acceptance pins move as R6 implies and are re-recorded with the rule named: `Absence.ToBodied`
(callee_no_record → `Uncond(must)`, read off the fixture's B1-era legacy release; the site keeps
`callee_no_record`) and `Pass.KeepIt` with a nulled callee (callee_unresolved → `Uncond(must)`; the site
keeps `callee_unresolved`).

**Controls, as realized.** X2D-C3 was first realized with callees whose bodies lowered to no op — no record,
so R6 applied instead of `multi_action`; re-realized with record-carrying callees. X2D-C5 was first
realized on X2B-C3's caller-side site, which the identity mutant cannot reach; then as a parameter forwarded
into a third overload reached with an int literal, which B1 A15 refuses as `opaque_slot` before any identity
question; and last as a forward reached with bool constants so the identity conflict is the only reason left.
All before the recorded measurement; the frozen shapes are unchanged. The three mutants kill exactly their
controls (M1 → C5; M2 → C1, C2, C4; M3 → C1, C2, C4).

## 3. Results (MEASURED OBSERVATION)

| row | expectation (frozen) | measured with the flag on | held |
|---|---|---|---|
| everything frozen at 2c (F3, B1 36, XB-1…10, XD-1…3, XD-5…9, X2B, X2C) | unchanged | unchanged; flag off == Python on every document | yes |
| XD-4 legacy-honesty control | `Guarded.M.p = Split(g) [must, no]`, collapse `may`, EQUAL; the opaque site plain + OWN051 | exactly that; verdict OWN051 unchanged | **yes** |
| XC-4 VerifyPersistedKey.key | `Split(disposeKey, must, no)`; C12/C13 select the negative cell → borrow; the two OWN051 disappear; NO OWN009; an OWN001 MAY appear where the kept key is never disposed | `split(7) [must, no]` EQUAL; the sites at `:51` and `:370` select **neg → borrow**; the two OWN051 are gone; no OWN009; two OWN001 appear at `SymmetricCngTestHelpers.cs:36` and `:355` — the kept key ends in `CngKey.Delete()`, which the analyzer does not model as a release (the pre-existing gap named in the prereg; never fixed by an API-name rule); the pre-existing OWN001 ×2 stay | **yes** |
| XC-2 | recorded | `FinishSend.response = Uncond(no)`, `StartSend.request = Uncond(no)`, the four `GetXxxAsyncCore → StartSend` sites EQUAL borrow; `FinishSend.cts` unchanged `Split(2) [must, no]`; no verdict moves | recorded |
| XC-3 / XC-6 | unchanged | unchanged (`CreateModule` `split(1) [no, must]`; `SendResponseAsync.listener` `split(3) [must, no]`) | yes |
| X2D-C1 | `Split(g) [must, no]`; true consumes, false borrows, opaque plain + OWN051 | exactly that (legacy: OWN051 ×3; flag on: OWN051 ×1) | yes |
| X2D-C2 (the case-4 shape) | `Split(dispose) [must, no]`; false → borrow, true → consume | exactly that; both callers clean | yes |
| X2D-C3 | `multi_action` stays | `Two.p` NGE `multi_action`; caller clean | yes |
| X2D-C4 | `Uncond(must)`; the callee's own OWN002 unchanged | `RelThenUse.p` `uncond [must, must]`; OWN002 inside on both engines | yes |
| X2D-C5 | `callee_sig` stays | `Fwd.s` NGE `callee_sig`; no name-only fallback | yes |
| corpus, flag on vs off | the same 8 F3 documents; UNEXPLAINED 0; more coordinates may form summaries, each EQUAL or one of the three classes | the same 8 documents; no finding differs from 2c, flag off or on; one more coordinate solved (summary EQUAL 32 → 33, NGE 8 → 7), UNEXPLAINED 0; repository tree: 158 / 154 findings and 16 coordinates unchanged | yes |

## 4. Result

**Stage 2d: KEEP.** One reader rule that applies the protocol's own carrier decision, no extractor, engine
or schema change, and the last driver rule between case 4 and the vocabulary falls: the guarded selection
at C12/C13 is **supported exactly** by the frozen P-037 vocabulary on the honest carrier; what the reader
then reports there is the analyzer's pre-existing `CngKey.Delete` gap, outside this track. XD-4's stated
value is realized. Not claimed: that #304 is reopened, or parity with the flag on.
