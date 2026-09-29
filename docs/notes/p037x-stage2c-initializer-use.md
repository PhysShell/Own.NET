# P-037-X Stage 2c — initializer-form argument use (EXPLORATORY)

> Status: **EXPLORATORY research record, research branch `research/p037-max-v1` only.** Pre-registered
> BEFORE the code in Own.NET-paperwork `paper-eval/p037-max/stage2c-prereg-v1.json` (commit `f28e9dd`);
> nothing in the Stage-2 or 2b records is re-expected. Not a production migration, not a reopen of
> #304 (frozen 2026-09-28, unchanged). Stage commits: `d844fa8` (R5, the controls, the control test)
> and the one carrying this note. Evidence: `paper-eval/p037-max/stage2c-initializer-use-v1.json`.

## 1. Why

Stage 2b stopped at case 4 with `NO_GUARDED_EVIDENCE(no_body_op)`: the sidecar records the delegate
invocation `cngKeyAlgFunc(key)` in a `using` initializer, but the legacy body carried no op for `key`
on that line. A probe over six initializer forms showed the legacy lowering emits `use` for a tracked
handle passed to a non-canonical call in statement form and nothing in a declaration or `using`
initializer, invocation or object creation alike. A carrier gap, independent of P-037.

## 2. The rule (REPOSITORY FACT; stated generically)

**R5** (`Program.cs`, `EmitInitializerArgUses`): for the invocation or object creation that initializes
a local declaration, a `using` declaration or a `using` statement (looked at through `await` and
`.ConfigureAwait`), every tracked handle that is a direct argument — after the A2.2 value-preserving
unwrap; `out` arguments are pure writes — gets the same legacy `use` op the same call gets in statement
form, at the enclosing statement's line, the coordinate the sidecar keys the call by. Handles an op of
that statement already carries (an adopted alias source, a first-party factory call's args) are
excluded. No new op kind, no schema change, no engine change; the canonical-call rule untouched.

**Scope, measured.** A *local* handed to an initializer-form call escapes by the pre-existing legacy rule
("a `var n = Consume(s)` initializer stays an escape rather than a false leak"), so R5 is observable on
parameters — the coordinates the guarded vocabulary reads. A nested call argument (`Outer(Inner(s))`)
is not a direct argument and is not covered; recorded, not pursued.

**Controls, as realized.** The first realization of C1–C4 used expression-bodied helper callees (no record)
and a local as the handle; the local escaped and the callees answered `callee_no_record`, so the controls
did not exercise R5 where it matters. They were re-realized with parameters as handles and block-bodied
callees before the recorded measurement; the frozen shapes name a handle and a call, not their kinds.
`tests/test_p037x_controls.py` pins all ten 2b/2c controls on the real extractor (Python reference, Rust
opt-in off for parity, opt-in on for the frozen guarded outcome).

## 3. Results (MEASURED OBSERVATION)

| row | expectation | measured | held |
|---|---|---|---|
| everything frozen at 2b (F3, B1 36, XB-1…10, XD-1…9, X2B-C1…C7) | unchanged | unchanged; flag off == Python on 56/56 | yes |
| legacy (flag-off) movement 2b → 2c | a new `use` may add a TRUE OWN002 only | **none**: 0/46 challenge documents, 0/137 corpus (off and on), repository tree 158 findings and 16 summary coordinates unchanged | yes |
| X2C-C1 use after handoff | OWN002 on both engines | OWN002 on both engines (silent with the 2b extractor: mutant M2 red) | yes |
| X2C-C2 use before dispose | clean; `Keep = Uncond(no)` | clean; `Keep.s` EQUAL `uncond [no, no]` (use-as-release: OWN002 fabricated on both legacy engines: mutant M1 red) | yes |
| X2C-C3 leaked fresh result | OWN001 for the result only | OWN001 for `w` only | yes |
| X2C-C4 guarded callee, initializer use only | placeable, `Uncond(no)` | `Peek.s` EQUAL `uncond [no, no]`; caller clean | yes |
| XC-4 VerifyPersistedKey.key | `Split(disposeKey, must, no)` | **`NO_GUARDED_EVIDENCE(multi_action)`** — placeable now, one rule later (§4) | **no** |
| XC-2 | recorded | `GetXxxAsyncCore.request` placeable, then `expression_form` (an `await` initializer call is an expression-form sidecar call); `FinishSend.cts` unchanged | recorded |

## 4. Where it stops now (MEASURED + INFERENCE)

The B1 walker reads any op at a sidecar call line as a forward, whatever its kind; the callee of
`cngKeyAlgFunc(key)` is external; the same path then carries the release under `if (disposeKey)`: two
"actions" on one path, refused fail-closed as `multi_action`. The frozen protocol's own row XD-4 states
the carrier's value for exactly this situation — an unresolved forward is the legacy **borrow** `(must, no)`,
not the kernel's `unknown` — and the driver does not apply it: XD-4's control reads
`NO_GUARDED_EVIDENCE(callee_no_record)` for `Guarded.M.p` instead of `(must, no)`. One driver rule, two
rows. A pre-registered sub-stage 2d (R6: a `use` at a call line whose callee has no coordinate for reasons
of absence contributes the borrow of its path, never a forward) is the next rung.

## 5. Result

**Stage 2c: KEEP.** One generic legacy-lowering rule, no engine or schema change, zero population movement,
a true-positive class (use after handoff inside an initializer) now visible, and case 4 advanced to the
last driver rule between it and the vocabulary. Not claimed: that XC-4 is recovered.
