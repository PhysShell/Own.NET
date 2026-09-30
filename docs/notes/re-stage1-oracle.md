# resource-effects Stage 1 — the answer-key upper bound (EXPLORATORY)

Research branch `research/resource-effects-v1` (from the frozen P-037-X head e05d98d0; that branch is never
modified). Pre-registered in Own.NET-paperwork `paper-eval/resource-effects/prereg-v1.json` (frozen before
any code of this track); evidence in `paper-eval/resource-effects/stage1-oracle-v1.json`; the Stage 0 baseline
and the prior-art matrix in `stage0-baseline-v1.json` / `prior-art-matrix-v1.json`. #304 is frozen and
unchanged; #382 is open and untouched; nothing here is a production result and nothing here is inference.
Wording: *the answer-key arm recovered 2 of the 3 frozen real precision witnesses (W4 at the verdict level,
W2 at the selection level with verdict sensitivity)*. Never "case 2 recovered".

## 1. The question (REPOSITORY FACT)

Stage 0 found that both frozen real witnesses blocked by a resource effect are blocked by an EXTERNAL effect
of exactly one BCL callable each: `CancellationTokenSource.CreateLinkedTokenSource` (a fresh owned return,
case 2) and `CngKey.Delete` (a terminal release of the receiver, case 4). RQ-E1 asks whether perfect knowledge
of just those two effects moves either witness at the instance level. Stage 1 supplies that knowledge through
an ANSWER KEY — `OWEN_RE_ORACLE=<file>`, a two-row JSON model matched by the RESOLVED symbol identity
(`{ContainingType}.{Name}`), never by syntax text or a name prefix — and measures. No inference reads the key.

## 2. The arm (REPOSITORY FACT; +93/-7 handwritten lines in Program.cs, opt-in, byte-identical off)

- `return_fresh_owned`: the local bound to the call is a candidate with an `acquire`, exactly an
  IsOwningFactory hit (hooks beside the two IsOwningFactory call sites).
- `receiver_terminal_release`: `x.M()` / `x?.M()` on a tracked local is a `release`, exactly a `Dispose()`
  hit; the same entry counts as a definite consume signal in the consumer inference (DisposesLocal), so a
  first-party wrapper around the release composes. NOT a claim that `Delete` equals `Dispose`; the
  exception-edge rule (IsDisposeShaped) is untouched.
- Sub-stage 1b (`OWEN_RE_MINTED_RETURN=1`, pre-registered as the follow-up if the case-2 record failed to
  form): a candidate minted by a FACTORY acquire in this body (curated table or key) that is returned bare or
  inside a tuple literal is the D5.2 transfer out, like a `new`ed candidate — a rule over the fact vocabulary.

Every binary was rebuilt from the research head first and reproduced the sealed Stage 4 baseline byte for
byte (facts) and code for code (verdicts) on every document (NC1), so no baseline was regenerated silently.

## 3. Results (MEASURED; every "key" row uses the answer key)

| witness | before | answer key | sensitivity twin |
|---|---|---|---|
| W4 case 4 (verdict) | on: OWN001 x4 (:36 :74 :87 :355); off: OWN001 x2 + OWN051 x2 | on: 0; off: OWN051 x2 | twin4 keeps OWN001 at :36 |
| W2 case 2 (Stage 1 proper) | silent (no producer record) | key fired once, local ESCAPED through the tuple return: NC3 failed (representation residue, as pre-registered) | — |
| W2 case 2 (+ sub-stage 1b) | silent | producer record (acquire :819, `fresh_iff(1)`), RELATIONAL_DISCHARGE at C02 :234, C03 :311, C04 :357, C05 :513; C06 :568 (local function) not discharged; 0 findings in every arm | twin2: OWN001 x4 at the callers |
| W5 case 5 (negative control) | silent | unchanged | — |

KILL GATE 1 is NOT triggered: headroom exists. Both effect-blocked witnesses move under perfect knowledge of
two callables; W2 additionally needs the 1b representation rule (+9 lines), not more effect knowledge.

Hostile oracle controls (`corpus/re-controls`, three keys each; `tests/test_re_controls.py` pins them):
H1–H4 are clean under the identity key; the NAME-RULE MUTANT keys fail as required on H1 (false OWN001),
H2 (the true leak hidden, false OWN002) and H4 (false OWN002 + OWN003); on H3 the M1 mutant produced no
false verdict (the fabricated fresh result is absorbed by the argument-escape optimism) — recorded
NOT_DISCRIMINATING, the expectation is not rewritten. H5 composes (Run clean, RunUseAfter OWN002) — and
exposed that the BASELINE reports two FALSE OWN001 there (the canonical forward keeps the key tracked while
the wrapper's summary is `no`), where the prereg expected silence. H6 is silent under Stage 1 for both the
key and the production File.OpenRead twin (the bare-return rule is gated on `new`ed candidates) and gives
the truth under 1b (both callers leak).

Population: the 137-document corpus, the 82-file tree and the 62 historical/P-037-X control documents do
not move at all — no fact and no verdict — under the key, nor under the 1b rule (the only flag-only movement
in the whole Stage 1 set is H6b, which is the truth). Python == Rust off the seam on every document.

## 4. Observations recorded, not fixed (per the anti-goodhart rules)

1. The production release name set makes `h.Close(false)` an unconditional release (H4b: false OWN002 +
   OWN003 on a conditional `Close(bool)`).
2. A statement-form canonical forward to a first-party wrapper whose body only calls an unmodelled release
   keeps the handle tracked with a `no` summary (H5 baseline: two false OWN001).
3. A curated-table factory result returned bare from a first-party wrapper escapes instead of making the
   wrapper fresh (H6b silent in production); the 1b opt-in is the exploratory fix.
4. A tuple-deconstructed resource forwarded into a local function is not discharged (C06).

## 5. What this does and does not say

It says the frontend's scope limit at the two witnesses is a KNOWLEDGE limit of exactly two callables (plus
one representation gate for W2). It does not say how that knowledge should be obtained: Stage 4 competes the
explicit two-row model (the same mechanism, re-labelled with its cost) against dependency-source inference,
documentation, mining and naming candidates, under the provenance policy of the prereg. Stage 5's held-out
set was frozen immediately after this record, before any Stage 2 code.
