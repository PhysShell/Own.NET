# corpus/p036-bakeoff — synthetic conformance cases for the P-036 bakeoff

Provenance class **4 (synthetic conformance)**: every case here was derived
from proposal text — the P-037 §8 worked cases and the P-036 §Phase 2 fixture
list (families 4–7) — and written **before** any comparator ran on it (see
`docs/notes/p036-bakeoff.md` §0). They are deliberately minimal, single-file
(`before.cs` buggy / `after.cs` fixed), and use only in-box BCL types so every
comparator can compile them without a reference pack.

They are **not** scanned by `scripts/benchmark.py`'s default corpus set and
are **not** part of `tests/test_corpus.py` (no `case.own` reductions): they are
bakeoff inputs, not regression anchors. Several are expected to be MISSED by
Owen at `70189a3` — that is the point of the comparison, not a defect to fix in
this research phase (repository-work rule: no P-036 implementation before the
decision).

| case | family | source of the shape | expected on `before.cs` |
|---|---|---|---|
| `guarded-consume-flag-branch` | F3 | P-037 §8 row 1 (`Teardown(true)` / `Teardown(false)`) | leak of the stream passed with `keep: true` |
| `guarded-consume-early-return` | F3 | P-037 §8 row 2 (early-return spelling) | same leak |
| `guarded-consume-wrapper-forward` | F3 | P-037 §8 row 7 (`id` edge through a wrapper) | same leak one hop up |
| `guarded-consume-negation-wrapper` | F3 | P-037 §8 row 8 (`neg` edge) | same leak through `!stop` |
| `nullguard-helper-use-after` | F3 | P-037 §8 row 4 (self-null split) | use after the helper disposed it |
| `mixed-release-forward-use-after` | F3 | P-037 §8 row 12 (unanimous `must`) | use after a helper that consumes on both arms |
| `enrollment-dispose-without-idisposable` | F4 | audit attack D / P-036 LifecycleEnrollment | subscription never released: `Dispose` is a name nobody calls |
| `enrollment-owner-drops-subscriber` | F4 | P-036 LifecycleEnrollment (RAII form) | owner drops the IDisposable subscriber |
| `subscription-release-skipped-by-throw` | F5 | P-036 §Phase 2 fixture 7 | `-=` skipped on the exceptional path of `Dispose` |
| `release-through-delegate-target` | F6 | P-036 §Phase 2 fixture 6 | cleanup reached only through a delegate/interface |
| `obligation-barrier-through-helper` | F7 | #272 / #274 | forbidden notification inside a helper while the obligation is open |
| `loop-no-progress-through-helper` | F8 | #275 | back-edge without progress when the helper returns false |

## Post-hoc controls (provenance class 5)

Added **after** the preregistered run, in answer to the owner's audit of
`c57a919`: `enrollment-dispose-without-idisposable`'s fixed side changes two
things at once (the type gains `IDisposable` and the owner gains a `using`),
so a tool that is silent on the fix may be tracking the interface convention
rather than the lifecycle. The two controls hold one variable and toggle the
other; together with the original case they form a 2×2 factorial
(I = implements `IDisposable`, O = owner enrolls/disposes). They are excluded
from every preregistered decision predicate and read only in
`docs/notes/p036-bakeoff.md` §8.4.

| case | family | cell(s) | expected on `before.cs` |
|---|---|---|---|
| `enrollment-control-interface-owner-drops` | F4 | I+O− (bug) → I+O+ (fixed, = the original fix) | the dropped `IDisposable` cache still leaks its subscription |
| `enrollment-control-dispose-without-interface` | F4 | I−O− (bug, = the original bug) → I−O+ (fixed: explicit `cache.Dispose()`, still no interface) | same leak; the fix releases it without ever adding `IDisposable` |

## G-V4 / trusted-input negative controls and the class-3 shape (class 4)

Not bug fixtures and not bakeoff cases: each `control.cs` carries an honest
defensive dispose that a *fabricated* `must` would charge a false OWN003.
Each directory holds `expected.json` with **both** the `current` record
(measured on Owen at `70189a3`) and the `post_a1` acceptance, plus a
`classification` — three are `KNOWN_FALSE_POSITIVE`, the class-3 shape is
`VERDICT_COMPATIBLE_VALUE_DIFFERENCE` — so the evidence lies about neither
today nor the target. `scripts/p037_controls.py` verifies them on two layers
(the fabricated `release` op at the call site in the emitted facts; the
finding codes at `--severity warning`): the default mode must pass today,
`--post-a1` is the acceptance A1 discharges after P-022 Stage 3 and fails
until then. They are the executable form of P-037 §8 rows 18–19 and G-T2b
class 3, and A1's acceptance items 5 and 8
(`docs/notes/p037-formal-kernel.md` §8.1). Owner ruling (2026-09-18): the
three false positives are pre-A1 regression anchors, **not** authorization
for a pre-cutover `ConsumesParam` fix — the P-022 freeze is on
verdict-changing inference, and the shared-extractor location is no
exception. Measured today:

| control | P-037 | today | why |
|---|---|---|---|
| `gv4-control-mutated-guard` | §8 row 18a | **OWN003 (false)** on `r.Dispose()` | the extractor's flow-insensitive `ConsumesParam` lowers `Inner(p, g)` to a release because `Inner` disposes on *some* path — the may-as-must hole, A1's first bug; the mutated guard never even gets a say |
| `gv4-control-ref-alias-guard` | §8 row 18b | **OWN003 (false)** | same mechanism |
| `gv4-control-aliased-self-null` | §8 row 19 | **OWN003 (false)** on `s.Dispose()` | `q.Dispose()` somewhere in `Close` ⇒ the call is a release of the caller's argument, which the alias write makes untrue |
| `legacy-honesty-else-unresolved-forward` | G-T2b class 3 | 0 findings at warning severity — but the facts layer shows the same fabricated release at the call site, which today also suppresses the OWN051 advisory | verdict-compatible today and after A1; after A1 the call is plain + OWN051 with no release op; the value-level pin (`unknown`, never repaired to `may`) is the kernel test `k11_finding_release_priority_drops_an_unresolved_forward` |

Three of four are therefore **red today** on the end-to-end layer and all
four on the facts layer: they pin a production false-positive class that
A1's first target removes, and they must turn green on both layers without
any of them turning into a fabricated consume elsewhere. Nothing in the
extractor, the engines or the launcher surfaces changes before P-022 Stage
3; these anchors wait with A1.

