# P-037 bounded real-world materiality gate — preregistration

Written and committed **before** any candidate is examined. Tests R2 of the
#304 freeze only. Not authorization to implement P-037; not B2.1a; not a
touch of held R1, #368, or Phase C.

U0 (unified research base, tests/test_p037_a2d_epoch.py green):
`1aec283` — `claude/p037-real-world-mining`, built by cherry-picking the
governance fix (`209dac9`) onto the corrected value-benchmark head
(`ae4f1c0`), plus one further carve-out (`1aec283` itself) the unification
surfaced for the value-benchmark's own evidence files.

## Accepted state coming in

- P-037 capability benchmark: `CAPABILITY_GAP_ONLY`.
- Own.NET Rust: 0/4 pair-correct on the guarded-consume corpus. Own.NET
  Python: 0/4. CodeQL: 0/4. Infer#: NOT ESTABLISHED. CA2000/IDisposableAnalyzers:
  NOT ESTABLISHED.
- #278 (SectorTS `GTD` guarded-`-=` leak): real, material, heap-proven —
  but closed by merged PR #293 (part of the #293/#302/#306 slice). Current
  production predicates cover that specific shipped slice. #278 is
  real-world **motivation** and a control, not current R2 materiality.
- #304 implementation freeze: still in force, unaffected by anything below.

## The question

Do real software defects exist, independently of our synthetic fixtures,
whose ownership/release semantics fit the already-frozen P-037
guarded-summary model, which **current** production Own.NET still gets
wrong?

Not: can we imagine a useful P-037 case (we already can). Asking: does
current real-world evidence justify paying for implementation?

## Necessary conditions (ALL must hold, or REJECT)

- **C1 REAL** — real production/OSS code, not a synthetic reduction.
- **C2 GROUND TRUTH** — independent evidence establishes bug/safe behavior:
  issue, fix PR/commit, runtime evidence, maintainer explanation, or a
  directly reviewable before/after semantic fix.
- **C3 P037-SHAPED** — the decisive semantic difference fits the frozen
  P-037 grammar (below).
- **C4 CURRENT GAP** — current Own.NET Rust still misclassifies the
  relevant pre-fix/current form.
- **C5 NOT ALREADY COVERED** — not already correctly handled by #293/#302/
  #306 or another current predicate.
- **C6 IMPLEMENTATION-RELEVANT** — frozen P-037 semantics has an
  unambiguous answer; no new semantics need inventing to claim the case.

## Frozen P-037 semantic scope

Allowed guard inputs: a `bool` method parameter; reference-parameter
nullness; one literal; method parameters only; entry-value-stable guards
only.

Allowed transforms: `const-pos`, `const-neg`, `id`, `neg`, `opaque`.

Representative admissible patterns: `if (!keep) resource.Dispose()`;
`if (dispose) resource.Dispose()`; `if (keep) return; resource.Dispose()`;
a wrapper forwarding its flag unchanged or negated; a wrapper hard-coding
`true`/`false` into an inner call.

**Reject** as P-037 materiality evidence if solving the case fundamentally
requires: conjunction/disjunction; a field/local/property as guard state;
arbitrary comparisons; path predicates outside the frozen grammar;
mutable/`ref`/`out`/aliased guard reasoning; exception-CFG reasoning as
the decisive feature; general points-to; collection ownership as the
decisive feature; async state-machine reasoning; a new alias semantics; a
new summary axis. Those may be interesting bugs; they are not evidence
for *this* frozen implementation.

## Threshold (frozen now, not adjusted after seeing N)

Met by **either**:

- A. ≥3 independent real incidents/bug-fix commits satisfying C1–C6, or
- B. ≥1 material production incident with independently demonstrated
  runtime/user impact satisfying C1–C6.

**Closed does not automatically mean "does not count."** A historical
merged bug-fix counts if its pre-fix code is real, current Own.NET Rust
still gets that pre-fix shape wrong today, and the fix provides
independent ground truth. Issue status is not the criterion — current
analyzer capability is. (This is exactly why #278 doesn't count: current
predicates now catch its relevant pre-fix slice, not because the issue is
closed.)

## Independence

One PR fixing five sites is 1 incident. A duplicated bug across generated
or copy-pasted files in one fix is 1 incident. Independent means separate
causal bug/fix evidence. ≥2 repositories preferred, not mandatory if
multiple same-repo incidents are clearly independent in time, code path,
and fix provenance — record the independence argument explicitly per case.

## Budget

Hard wall-clock cap: ≤4 hours total, no extension. Sub-gates (ceilings,
not additional budget): M0 setup+prereg+existing-data inventory ≤45 min;
M1 targeted external search (only if S1–S3 yield <3 candidates) ≤30 min;
M2/M3 adjudication + before/after confirmation + report = remaining
budget. At 4 hours: stop with whatever evidence exists.

## Code budget

Production LOC: 0. Analyzer semantic LOC: 0. New mining-framework LOC: 0.
New generic harness LOC: 0. Prefer zero executable code. If a tiny one-off
evidence conversion is truly unavoidable: ≤40 LOC, research-only, no
semantic classification logic — and only after existing tools are tried.

## Source order (cheapest first, no new mass mining campaign)

S1 — existing `PhysShell/OwnAudit` mining data (`docs/leakfix-mine.md`,
`leakmine/**`, any already-existing corpus/dataset/summary/candidate
artifacts). No new broad `leakmine mine` campaign. Use its own
discovery/classification vs. before/after-confirm separation.

S2 — existing Own.NET/oracle evidence, re-read specifically for this
question (not trusting old triage labels): `docs/notes/oracle.md`,
`oracle-known-fps.md`, `oracle-sweep-2026-07-10.md`,
`precision-remeasure-2026-07-12.md`, `corpus/real-world/`, `corpus/wpf/`,
and Own.NET's own issue/PR history beyond #278.

S3 — public bug-fix evidence already known/indexed in project notes.

Only if S1–S3 yield fewer than 3 plausible candidates: a bounded (≤30 min)
targeted GitHub/web search leading to a primary issue/commit — never a
mass campaign, never hundreds of repos, never a new dataset. Open the
actual issue/PR/commit; never treat a search snippet as evidence.

## Cheap falsifiers (reject without running analyzers)

Exception-only bugs; a forgotten local `Dispose` with no guarded
interprocedural behavior; a fix that is only "add `using`"; a bool that
controls object *creation* rather than ownership/release; an ownership
contract that is external/manual-annotation only; a guard that is
field/property/local mutable state; unestablishable resource identity; a
fix that changes unrelated architecture so no ground truth survives; a PR
that merely says "memory leak" without establishing the mechanism; current
Own.NET already catching the exact pre-fix shape; #293/#302/#306 already
solving the exact case.

## Ground-truth standard (established without analyzer output)

Strongest first: runtime/heap/repro proof; maintainer bug report + a
targeted fix; a directly-reviewable before/after fix; tests added
specifically for the leak/lifetime defect. A bare "fix memory leak" title
alone is weak evidence, not sufficient alone. Confidence recorded as HIGH
or MEDIUM; LOW does not count toward the threshold.

## Decision rule (frozen)

N = independent HIGH/MEDIUM-ground-truth real incidents satisfying C1–C6.

If one material-impact incident satisfies C1–C6: `REOPEN_CANDIDATE_R2`.
Else if N ≥ 3: `REOPEN_CANDIDATE_R2`. Else: `CAPABILITY_GAP_ONLY`. The
threshold is not moved after seeing N — N=2 is still `CAPABILITY_GAP_ONLY`.

Either way, `REOPEN_CANDIDATE_R2` does not lift #304; the next action is
an owner ruling on #304 only, never implementation.

## Kill conditions (stop early; remaining budget is not a reason to continue)

K1: after S1–S3 there are zero plausible P037-shaped candidates AND the
30-min targeted search also yields zero. K2: all plausible candidates are
already handled by current Own.NET. K3: all candidates require semantics
outside the frozen grammar. K4: ground truth cannot be established without
a new large experiment. K5: remaining time is insufficient to
independently verify enough candidates to reach the threshold — **if the
mathematical maximum of remaining candidates cannot reach the threshold,
stop**, regardless of remaining budget.

## Repository changes allowed in this gate

Preregistration note (this file); a candidate inventory
(`docs/evidence/p037-real-world-mining/candidates.json`); a small
evidence JSON; a final research note. Nothing under `frontend/`,
`ownlang/`, `rust/` production semantics, `formal/p037-kernel/`,
`formal/p037-rocq/` semantics, the OwnIR schema, `ConsumesParam`, any
guarded solver/application code, #368, B2.1a, or Phase C. Temporary
external checkouts live outside this repository; nothing mined is
vendored in.
