# resource-effects Stage 3 — first-party summary inference over the algebra (EXPLORATORY)

Research branch `research/resource-effects-v1`. Pre-registered in Own.NET-paperwork
`paper-eval/resource-effects/stage3-inference-prereg-v1.json`; evidence in `stage3-inference-v1.json`.
#304 frozen and unchanged; #382 untouched; nothing here is a production result.

## 1. E3 — the one engine rule (both engines, opt-in `OWEN_RE_MIXED_RETURN=1`, verdict-identical off)

INF-R3′: a MIXED return skeleton — every returned local acquired in this body on some paths and bound to
ONE first-party callee's result on the others (`if (b) return new R(); return Make();`) — is a forward to
that callee, fresh iff the callee is fresh at the fixpoint. Two different callees stay ambiguous (`none`);
a returned parameter is never fresh. Python `_infer_return_skeleton` (+17 lines) and the Rust bridge
`infer_return_skeleton` (+33) carry the same block; off the opt-in the R3/R4 separation is unchanged.

## 2. The 14-test suite (`corpus/re-inference/t-suite.cs`): 13 of 14 met, Python == Rust in every arm

| test | expected | measured (body + E3) |
|---|---|---|
| T01 direct factory | fresh | fresh |
| T02 wrapper (`return Make()`, `return new R()`) | fresh / fresh | fresh / fresh |
| T03 two-level (`=> Make2()`) | fresh | fresh |
| T04 receiver release (`c.Kill()`) | Run clean, RunUse OWN002 | as expected |
| T05 release wrapper (`Drop(c) { c.Kill(); }`) | c must | c must |
| T06 conditional / T07 negated guard | r may | r may / r may |
| T08 ambiguous branch (mixed) | fresh (none today) | none without E3, **fresh with E3**; the caller's leak appears |
| T09 forwarded ownership | r must | r must |
| T10 borrowed param | r no | r no |
| T11 returned param (`=> x`, `{ return x; }`) | never fresh | no record / `none` |
| T12 recursive / SCC (`A => b ? new R() : B(); B => A(false)`) | fresh (fixpoint) | **unknown**: INF-F5 resolves a forward-return CYCLE to `unknown` (fail-closed) — the expectation assumed an optimistic cycle policy the engine does not have; NOT MET, recorded, not repaired |
| T13 unresolved external | never fresh | no record; the caller is silent |
| T14 virtual / interface | never fresh; never a release | `unknown`; no release |

## 3. Fact-level mutants (each applied to the extracted facts; each MUST fail its target)

- **M3 ignore a branch** — fails as required: T06/T07 become a fabricated `must`, T12 becomes `fresh`, a new
  finding appears.
- **M5 ignore overload identity** — fails as required on the P-037-X control x2b-c3: both callers degrade to
  OWN051 and the guarded selection is lost.
- **M7 ignore virtual/interface** — fails as required: `Via` becomes fresh and its caller gets a false OWN001.
- **M4 ignore return aliasing** — NOT APPLICABLE at the fact level: the frontend never emits
  `return <parameter>` (the return is a bare exit) and the engine claims `fresh` only for a local it saw
  acquired, so the mutant cannot be expressed without fabricating an acquire. The aliasing rule holds by
  construction; the mutant is retired and the reason recorded.

## 4. Reading

The intra-body effects the algebra names are inferred as pre-registered. The additions of this track so
far are E1 (+ expression bodies), E2 and E3: no OwnIR field, no lattice value, one skeleton-derivation rule.
The two departures are policy, not effect failures (the fail-closed cycle rule; aliasing by construction).
Stage 4 now asks where the two EXTERNAL effects of the frozen witnesses can come from — the dependency
source through exactly these rules, or the explicit two-row model.
