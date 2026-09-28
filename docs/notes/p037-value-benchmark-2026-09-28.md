# P-037 value/research benchmark — 2026-09-28

Tests R2 of the #304 freeze only ("a real production defect class with
measurable value the current predicates don't cover") via a cross-tool
precision/recall benchmark. Not B2.1a, not a #368 fix, not implementation —
zero production/frontend/ownlang/rust/formal LOC changed. Machine-readable
data: [`docs/evidence/p037-value-benchmark/manifest.json`](../evidence/p037-value-benchmark/manifest.json).

**Correction (this revision).** An independent review caught that the first
version of this note over-read issue #278 as satisfying R2's materiality
branch (see "Real-world materiality" and "DECISION" below) and that this
note understated its own manifest's chronology. Both are corrected in
place; no measurement changed. Original decision was `REOPEN_CANDIDATE_R2`,
corrected to `CAPABILITY_GAP_ONLY`.

**Preregistration status: retrospective, not prereg-frozen.** This
benchmark did not preregister a new ground-truth manifest before execution.
Its expected labels were pre-existing committed corpus truth
(`corpus/p036-bakeoff/*/expected-diagnostics.txt`, authored before this task
existed) and were not edited by this task; the manifest retrospectively
binds those pre-existing labels, source hashes, and measured tool
identities into one evidence record. The risk this creates is small — the
labels predate the benchmark — but the distinction is named rather than
implied: expected labels are pre-existing/pre-measurement, the manifest
binding them to hashes and results is retrospective.

## What this reused (nothing new built)

- `.github/workflows/oracle.yml` + `scripts/oracle_compare.py` — the existing
  cross-tool (Own.NET vs Infer#/CodeQL) leak-class comparator.
- `scripts/benchmark.py` + the `corpus-benchmark` CI job — the existing
  first-party real-C# recall/specificity harness (own-python-reference only,
  hardcoded; default corpus is `real-world`+`wpf`+`di`, gated at
  `--min-recall 25`; `corpus/p036-bakeoff` is **not** in that default set).
- `scripts/own-check.sh` directly, both `--engine python` and `--engine rust`.
- `corpus/p036-bakeoff/guarded-consume-*` (4 families) and
  `corpus/real-world/ownership-handoff-consume` — pre-existing fixtures, read
  as-is; their `expected-diagnostics.txt` is pre-existing ground truth this
  benchmark never touched.
- `PhysShell/OwnAudit` (separate repo, cloned read-only) for the Tier-2
  tooling question.
- GitHub issue #278 for real-world materiality.

**Benchmark-only glue written: 0 LOC.** Every measurement below is a direct
invocation of an existing script or workflow; no new harness, parser, or
classifier was built.

## Live-run infrastructure note

`workflow_dispatch` on `oracle.yml` returned `403 Resource not accessible by
integration` for this session's GitHub access on all three attempted
dispatches — confirming empirically what the workflow's own comment already
states ("the automation token can't `workflow_dispatch`"), and matching the
53 historical runs (2026-06-27 through 2026-07-10), all push-triggered, none
`workflow_dispatch`. The documented push-trigger dev-loop fallback **does**
work: `corpus/oracle-target.txt` was pointed at `local:corpus/p036-bakeoff`
and `.github/workflows/oracle.yml`'s `push.branches` temporarily carried
`claude/p037-value-benchmark` (commit `1efbdf1`), which fired a real run
(`36408630758`) inside ~3 minutes. Both temporary edits were reverted
(commit `7920732`) immediately after the report was captured from the run's
job log.

Because of this constraint and the session time budget, the three named
historical controls were **not** all re-run live this session:

- **systemevents-console** — reproduced **locally** (own-check only, both
  engines): identical 3/3 dispose leaks (`OWN001` at `Program.cs:43,54,77`)
  plus the documented `OWN050` advisory on the unresolved `SystemEvents`
  subscription (degrades from `OWN014` without the materialized WindowsDesktop
  ref pack — expected, not a regression). Harness not disqualified.
- **Dapper / Polly** — relied on the committed record
  (`docs/notes/oracle.md`, `docs/notes/precision-remeasure-2026-07-12.md`),
  not re-measured live. Flagged as a scope reduction, not a silent gap.

## Capability corpus and result matrix

4 families, each `before.cs` (buggy) / `after.cs` (fixed), real C# through
the actual Roslyn extractor + core — never a `.own` reduction:

| family | edge | own-python | own-rust | codeql | infer# |
|---|---|---|---|---|---|
| guarded-consume-early-return | const (early return) | 0/4→miss, clean | miss, clean | miss, clean | untested |
| guarded-consume-flag-branch | const (literal arg) | miss, clean | miss, clean | miss, clean | untested |
| guarded-consume-negation-wrapper | neg | miss, clean | miss, clean | miss, clean | untested |
| guarded-consume-wrapper-forward | id | miss, clean | miss, clean | miss, clean | untested |

"miss" = `before.cs` produced 0 verdicts (expected `OWN001`); "clean" =
`after.cs` produced 0 verdicts (correctly no false positive). own-python and
own-rust were measured directly (`scripts/benchmark.py` and direct
`own-check.sh --engine {python,rust}` per file — byte-identical output on
all 8 files, no engine-parity problem). CodeQL was measured live (run
`36408630758`, `security-and-quality` suite, `build-mode: none`): its one
leak-class finding anywhere in the `p036-bakeoff` scan was
`cs/dispose-not-called-on-throw` in the unrelated
`gv4-control-aliased-self-null` case — an exceptional-path gap, same class
as the historical Dapper oracle-only findings — not in any of the 4 measured
families. Infer# could not build (no `.csproj` for these loose reduction
files) and is honestly recorded as **untested**, not "0 findings".

**PAIR_CORRECT = bug half detected AND safe half clean.** Result: **0/4
families are pair-correct, for every tool measured.** Every tool fails the
pair the same way — a clean miss (silent on both halves), not a false
alarm — so this is a recall gap, not a "traded one error class for another"
result on its own.

## Reference control: a different mechanism, already solved

`corpus/real-world/ownership-handoff-consume` (unconditional ownership
transfer via D5 / `ConsumesParam` — not guarded, not P-037) fires **both**
arms on both engines: `OWN001` on `Leak()`, `OWN002` on `Run()`, silent on
`RunOk()`. This matches `docs/notes/corpus-benchmark.md`'s "9/11" ratchet
exactly. The fixture's own `notes.md` ("the use-after-handoff arm is still
extractor-future") is **stale** relative to that ratchet and to this
measurement — flagged for a docs fix, not touched here (out of scope).

## Tier 2 / prior art

- **OwnAudit `Run-Roslyn.ps1`** (IDisposableAnalyzers, NetAnalyzers,
  Roslynator, Meziantou, AsyncFixer, …): hard-wired to PowerShell 7 + VS2022
  BuildTools (`vswhere`/`MSBuild.exe`) and a hardcoded proprietary target
  (`C:\Repos\STS_new\Broker.sln`). None of this exists on this Linux sandbox,
  and reproducing it would itself be building a new harness. **ROSYLN_BASELINES
  = NOT_ESTABLISHED_IN_GATE_A**, per the task's own anticipated fallback.
- **RLC#** (arXiv 2312.01912): a CodeQL-query-based must-call/typestate
  checker, interprocedural via **method-boundary resource-management
  specifications** (C# attributes) rather than call-site argument tracking.
  No packaged/runnable implementation was found; this is a **documented**
  architectural read, not a measurement, and per the task's own rule does
  not enter the benchmark score. It does inform NOVELTY_KILL below.
- **Infer# / Pulse**: described in its own docs as combining interprocedural
  analysis with a "branch-merging path-sensitive typestate engine," which is
  at least architecturally closer to call-site sensitivity than RLC# — but
  this is unverified for this exact pattern (bounded search found no
  specific 2025/2026 answer), and Infer# could not be run against this
  corpus (see above). Recorded as an open uncertainty, not a clearance.

## Real-world motivation (existing evidence only, no new mining) — does NOT establish current materiality

**Issue #278** (closed, fixed by merged PR #293): a **P1, heap-proven**
production defect on the project's own SectorTS reference codebase —
`GTD.cs:5192` subscribes to a static publisher; the only matching `-=` sits
behind `if (!UnregOnlyGoodys)` in `UnregisterEventHandlers(bool
UnregOnlyGoodys = false)`; the real callers (`GTDService.cs`, AutoMapper
`DocCloud` profiles) pass `true` or never call it at all. ClrMD heap
forensics after 31 documents: 66.3% of a 223MB heap genuinely retained,
traced through the static publisher's invocation list to the document
graph. This is **structurally the same pattern** as
`guarded-consume-flag-branch`/`early-return` (a boolean-parameter-guarded
release, callers passing the constant that skips it) — on subscription
release (`-=`) rather than `IDisposable.Dispose()`.

**Scored against the frozen threshold honestly, this does not pass.** The
threshold requires "1 material production incident **current** production
predicates still miss." #278 is real (YES), material (YES), heap-proven
(YES), same semantic family (YES, very relevant) — but **currently missed?
NO**. It is closed, fixed by merged PR #293 (part of the #293/#302/#306
slice), so current production predicates do *not* miss it. #278 is real-world
**motivation** that the pattern class is dangerous and expensive, and (below)
a concrete counterexample to one cheap mitigation for it — it is not a
currently-uncovered incident, and must not be counted as one.

**The shipped fix is not P-037-shaped, and that is informative.** #293's
rule (`corpus/wpf/subscription-param-guarded-unregister`) is: *a release
guarded by a parameter of its enclosing method, outside a recognised
teardown context, is never credited — regardless of which value is actually
passed.* This is cheap and it correctly turns the SectorTS leak into a
flagged `OWN001`. But it is a **blanket, non-call-site-sensitive** rule, and
it was never tested against a safe call site that legitimately relies on
the guard — the fixture's own `after.cs` sidesteps the guard entirely
(moves the release to an unconditional `Dispose` in a real teardown) rather
than proving a guarded call site safe. Mechanically porting the same
blanket rule to the `Dispose()`-guarded corpus measured above would flip
recall (0/4 → 4/4) at the cost of specificity (4/4 clean → 0/4 clean):
`Fine()`/`RunOk()` call the *same* guarded method with the argument that
*does* release, and a blanket rule cannot tell that call site apart from
`Leak()`'s. That is a concrete instance — from this project's own shipped
code, not a synthetic argument — of exactly the "traded one error class for
another" failure the Dapper/Polly precision tripwires exist to catch. A
context/call-site-sensitive resolution (what P-037's guarded/Election
lattice is *for*) is the only one of the three options on the table (miss
both silently / blanket-flag both / resolve per call site) that can get
both halves right at once.

**Fair counter-consideration.** The incident's actual fix took a fourth,
non-analyzer path: refactor the guard away (move the release to an
unconditional `Dispose` in a real teardown). That is a legitimate general
engineering answer to this whole pattern class, and it shipped without any
analyzer improvement at all. This benchmark does not have evidence that a
smarter checker was *necessary* for #278 specifically — only that the
pattern class is real, material, and that the cheap analyzer-side mitigation
already tried for it cannot also stay precise.

## Mechanical decision gates

1. **HARNESS_KILL** — not triggered. `own-check.sh`, `scripts/benchmark.py`,
   and `oracle.yml` all function and reproduce correctly (systemevents-console
   locally; `ownership-handoff-consume` matches documented current
   capability exactly; the live p036-bakeoff run completed cleanly end to
   end). Caveat: Dapper/Polly/full-3-tool-systemevents-console were not
   re-run live this session (see above) — a scope reduction under the time
   budget, not a failure of what *was* run.
2. **NOVELTY_KILL** — not triggered. No tool is pair-correct on all 4 core
   families: own-python, own-rust, and CodeQL are measured misses; RLC#'s
   documented architecture (method-boundary specifications, no call-site
   tracking) gives no reason to expect it would do better without a
   hand-written per-method annotation (which would just relocate the
   problem, not solve it automatically); Infer#/Pulse is a genuine open
   question, not a clearance.
3. **INCREMENTAL_VALUE_KILL** — not triggered. Current Own.NET Rust
   (production default) is measured at 0/4 on the exact families, identical
   to the Python reference — no existing incremental capability already
   covers this.
4. **CAPABILITY_GAP determination** — met. 4 independent families (not just
   the required 2), each confirmed missed by 2 independent baselines
   (own-rust-production and CodeQL), spanning 3 of the 5 named transform
   edges (const via two call shapes, id, neg).
5. **Real-world materiality** (existing evidence only) — **NOT met**. Issue
   #278 is real, material, heap-proven, and same-family — but it is
   **closed**, fixed by merged PR #293 (part of the #293/#302/#306 slice),
   so current production predicates do *not* currently miss it. It supports
   real-world motivation for the pattern class and is a concrete
   counterexample to one cheap (blanket, non-call-site-sensitive) mitigation
   for it — it does not satisfy the frozen threshold's "current predicates
   still miss it" clause. No second, currently-open instance was searched
   for or found this session.

## DECISION: CAPABILITY_GAP_ONLY

Meaning, precisely:

- guarded conditional transfer is a demonstrated **current capability gap**;
- current Own.NET Rust misses all 4 measured families;
- CodeQL misses all 4 measured families;
- desired P-037 semantics has pre-existing, unambiguous ground truth for
  this corpus (the committed `expected-diagnostics.txt` files);
- real historical production evidence (#278) establishes that the pattern
  *family* matters and has been costly;
- **current, uncovered real-world materiality has NOT yet been
  established** — #278 is closed, and no second (or first currently-open)
  real instance was searched for or found this session.

This is deliberately weaker than the previous revision's
`REOPEN_CANDIDATE_R2`, which over-read #278's closed, historical incident as
satisfying the frozen "current predicates still miss it" clause. It did not.
The corrected reading: the mechanism is proven non-decorative (CodeQL does
not catch it either, and a cheap blanket mitigation for the closed analog
provably cannot stay precise) — what remains is showing that someone other
than this project's own synthetic corpus currently needs it.

**NEXT: P-037 implementation freeze is STILL IN FORCE.** Next research
action, if the owner chooses to pursue it: **owner may authorize a bounded
real-world mining gate** — not a ruling to lift #304, not B2.1a, not a
guarded-solver design, not a #368 fix, not a production change. The freeze
is not reopened by this note.

## Budget

Investigation time: within the 4-hour budget (recon carried over from the
prior session turn; this turn's tool-execution portion was under 90
minutes wall clock, including one live CI round trip). Production LOC: 0.
Analyzer semantic LOC: 0. Benchmark-only glue LOC: 0 (fixtures/manifest/
generated evidence excluded from the cap in any case). New files: this
note, the manifest, and the two temporary/reverted `oracle.yml` /
`oracle-target.txt` edits (both reverted, net diff on those two files is
zero versus `06e3d78`).
