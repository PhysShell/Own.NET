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
