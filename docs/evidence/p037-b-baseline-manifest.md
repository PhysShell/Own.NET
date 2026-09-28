# P-037 Phase B / B1 baseline manifest (R_B)

epoch: `b`

T_B (terminal-green, the measurement-instrument head): `cf0f95f3f9af85df46d5506a87de806cf3f00c46`

population_commit (every take): `cf0f95f3f9af85df46d5506a87de806cf3f00c46`

environment: `P037_B_MEASUREMENT_M3`

This is the same measurement environment the whole B1 line has used since
its own qualification. It is not `P037_A2D_MEASUREMENT_M2` by another name
-- M2's own records (R_D, D_after) stay historical a2d evidence, neither
retaken nor a control of M3. No a2/a2d evidence is the baseline of Phase B;
the a2d T/R/S records are historical predecessors only and are not
retaken, compared, or treated as a control here (`docs/evidence/p037-b-
epoch.json`'s own `predecessor`/`environment` sections state this
precisely).

## This is the fifth R_B, not the first through fourth

The instrument this take measures against is not the one `a02ccf1`/
`df9a433`, `cfe7e19`/`069d5bc`, `fdde0a026d264ceff0e44f8c86e7d059207f67e6`,
or `718a673c01641883df433b89cb76d5e3942d8815` (the previous, fourth `R_B`,
recorded in this file's own prior content and still readable via `git log
-p -- docs/evidence/p037-b-baseline-manifest.md`) measured against. An
independent pushed-byte review of the B1-F2-F4-R1 head found four rounds of
narrower, purely instrument-side attribution and provenance defects,
closed here across four commits before this retake, none of them touching
production semantics:

- `20b09c9` (docs, governance only): froze the run-level
  `p037_call_site_witnesses[]` SARIF transport (schema
  `p037-verdict-snapshot/5`, superseding `/4`'s per-result design, which
  AR2's own measured shape -- a correct removal with `results == []` --
  could not carry a witness on at all) and the observation-binding
  `_verify_call_site_witness()`/`classify_call_site()` machinery.
- `b31e7a0` ("fix(p037): tighten call-site evidence attribution"): closed
  four defects an independent review found in `20b09c9` -- a fabricated
  `selection_license` could reach `APPLICATION_REFINEMENT` unchecked
  (fixed via `licensed_selection()`, grounded in the held R1 treatment's
  own production mapping); AR2's removal binding accepted any code/level
  at the acquire line (narrowed to an exact `(code, level)` anchor); the
  `_AFTER_ANCHOR`/removal-anchor severity was hand-typed `"error"` instead
  of the governed `--severity warning` (now one named
  `_RUN_ONE_SEVERITY` constant, confirmed against a real scratch
  measurement); `witness.site.file` was never checked against the file
  actually being compared.
- `460557e` ("fix(p037): bind witnesses to exact observations"): closed two
  more narrow defects -- resource/callee correlation was a bare substring
  check, unsound for AR1/AR2's own real single-letter resource name `"s"`
  (fixed via `_quoted_identifier()`, grounded in the frozen diagnostic
  templates' own quoted-token syntax); `witness.site.file == rel` was not
  the spelling a real producer would emit (mechanically re-derived from
  the extractor's `Rel()`/`own-check.sh`'s cwd behavior/`run_one()`'s
  materialized path to be `<materialization_root>/<rel>`).
- `84c06a2` ("fix(p037): close Phase B evidence provenance"): scrutinizing
  `materialization_root`'s trustworthiness exposed a pre-existing, more
  fundamental defect -- `p037_evidence_b.record_problems()` claimed, in its
  own docstring, to check "the same clauses" as the generic
  `p037_evidence.record_problems()`, but actually implemented only a small
  subset (instrument/treatment/subject path equality, input_roots,
  instrument_identity cross-check, population ancestry, manifest
  re-derivation and digest checks, execution/reference profile, and
  artifact attestation were none of them checked). Ported the full
  contract clause for clause; removed the dead `materialized_root`/
  `population_intact()` branch (a typo'd field name verdict snapshots
  never write, so the branch never ran) in favor of the durable
  manifest/digest re-derivation already ported; bound
  `p037_verdict_snapshot.py`'s witness file-identity check to a
  deterministically re-derived `canonical_root =
  ev.materialization_root(population_commit, analysis_manifest_sha256)`,
  never to the AFTER snapshot's own recorded `materialization_root` field
  directly (which a manually altered snapshot could forge alongside
  `witness.site.file` to still pass the prior exact-equality check).
- `cf0f95f` ("fix(p037): reject stale Phase B treatment evidence"): one
  final parity gap -- `provenance_problems()`'s own docstring already
  promised "neither instrument nor treatment moved in between", but the
  body only ever checked the instrument half. Load-bearing because
  `TREATMENT_PATHS` is exactly `INSTRUMENT_CARVE_OUTS`: a treatment-only
  change between a record's source commit and a later `against` HEAD moves
  neither `instrument_identity` nor the instrument-pathspec diff, so a
  stale AFTER record could otherwise stay "fresh" past a real future
  analyzer change. Added the missing `TREATMENT_PATHS` check via a new
  `_path_freshness_problems()` helper, deliberately NOT mirrored into
  `comparison_problems()`'s own before/after pair (a differential's whole
  point is the treatment moving between before and after).

None of these five commits moved a byte of `Program.cs`,
`rust/crates/own-bridge/`'s production semantics, `ownlang/`, or OwnIR
vocabulary -- all three production diff gates (rust, extractor, cli)
report `IDENTICAL` for `cf0f95f` against BOTH the immediately-previous
named T_B (`718a673c01641883df433b89cb76d5e3942d8815`) AND the long-standing
pre-B2.1a production reference
(`e4199ec4aa8d8f95c1b7e881f1ce3ba85f6ba58c`), reconfirmed directly as part
of this retake's own preflight, not assumed from the commit messages; a
mechanical `git diff --exit-code e4199ec4aa8d8f95c1b7e881f1ce3ba85f6ba58c
cf0f95f3f9af85df46d5506a87de806cf3f00c46 -- rust/ frontend/ ownlang/`
shows nothing. `a02ccf1`, `df9a433`, `bfa8647`, `cfe7e19`, `069d5bc`,
`5579d80`/`f8ffd42`, `fdde0a026d264ceff0e44f8c86e7d059207f67e6`,
`9418f575b42c2e03734bd97968a904950e86e2cf`, and
`718a673c01641883df433b89cb76d5e3942d8815` are kept exactly as committed --
honest records of the instrument and its baseline at the boundary each
held at the time -- superseded here, not rewritten: `git log` on this
file's path still shows their content, and `docs/evidence/p037-b-
epoch.json`'s own supersession chain names them explicitly,
machine-readable, with the reason.

## Instrument identity

```
c953acda915859449a69ef2866bd947591d48a6d8c302d8955e356f370788c69
```

Read from each take's own `instrument_identity` field (computed by
`p037_evidence_b.evidence_fields()`/`instrument_identity()`, over Phase B's
own `INSTRUMENT_PATHS`/`INSTRUMENT_CARVE_OUTS`), and independently
recomputed directly via `p037_evidence_b.instrument_identity(T_B)` before
any take started AND again afterward against every one of the four
committed records (both produced the identical value above), per this
retake's own preflight discipline (never invented or predeclared). All
four takes below agree on it, byte-for-byte. This differs from the value
the superseded baseline recorded
(`2b401fc72cc58c0f49e1d002c14a666f9863f657077f39467335e7ab8ec704ba`) --
expected and confirmed by direct measurement, not assumed: the five
commits above changed `scripts/p037_evidence_b.py` and
`scripts/p037_verdict_snapshot.py`, both tracked `INSTRUMENT_PATHS`, so
this digest had to move, and it does.

## Execution profile (M3, identical across all four takes)

- Python: CPython 3.11.15 (main, Mar 3 2026, 09:26:23) [GCC 13.3.0]
- .NET SDK: 8.0.425, runtimes: Microsoft.AspNetCore.App 8.0.31, Microsoft.NETCore.App 8.0.31
- Rust: rustc 1.94.1 (e408947bf 2026-03-25), cargo 1.94.1 (29ea6fb6a 2026-03-24), host x86_64-unknown-linux-gnu
- Platform: Linux / x86_64

Captured verbatim via `python3 scripts/p037_evidence_b.py profile` before
the first take. Byte-for-byte identical to all four prior `R_B` manifests'
own recorded profile (and, in turn, to `docs/evidence/p037-a2d-baseline-mos-repo.json`'s
recorded M2 profile): the same qualified toolchain, re-verified rather
than assumed unchanged.

## Machine qualification

Measurement environment `P037_B_MEASUREMENT_M3`, unchanged since B1's own
qualification (this retake re-measures the instrument's definition, not
the environment):

- CPython: pinned to the host interpreter (3.11.15).
- .NET SDK: 8.0.425, installed isolated outside any OS package manager.
- Rust: rustc/cargo 1.94.1.

recipe sha256 (unchanged since qualification):

```
5fe4ece4c24b720f659a49bbc68b8438080c9e4b8ba554ee40f6eea94c66eb26
```

Recipe: `provision.sh`, retained outside this repository at
`/root/p037-a2d-m2-recipe/provision.sh` on the qualified machine.

## Workspace (deviation from prior R_B takes, recorded explicitly)

Every prior `R_B` in this epoch measured from one preserved checkout root,
`/home/user/Own.NET`. This retake does not: that path now holds unrelated,
pre-existing, in-progress work-in-progress for a separate task (an R1
kernel-integration branch), which this retake's own governing instructions
explicitly forbid touching, committing, or replaying. The four takes below
were measured instead from a dedicated worktree of the SAME repository
(`git worktree add --detach`, sharing the same object store, on the SAME
physical machine, at the SAME qualified toolchain -- confirmed identical
by the execution profile above, not merely assumed), detached at exactly
`cf0f95f3f9af85df46d5506a87de806cf3f00c46`, with `git status --short`
empty before the first take and after the fourth verify. The environment
record's own qualification note anticipates exactly this: "reusing
[the workspace] is not a claim of an independent machine, only of an
unchanged, reverified toolchain on it" -- the toolchain identity is what
`P037_B_MEASUREMENT_M3` actually qualifies, and it is unchanged; the
inode path it happens to run from is not part of that claim.

## Takes

Four sequential governed takes, each independently `verify`d against the
new T_B before the next was started. None ran concurrently. Every take
first wrote to a fresh scratch directory (this session's own scratchpad,
`.../scratchpad/p037-b-rb-cf0f95f/`, containing no stale files from any
prior baseline) before being copied byte-for-byte into this tracked
location (hashes below recomputed post-copy and confirmed to match).

1. MOS repo snapshot (`--epoch b --source repo`)
2. MOS corpus snapshot (`--epoch b --source corpus`)
3. verdict/python snapshot (`--epoch b --engine python`)
4. verdict/rust snapshot (`--epoch b --engine rust`)

All four takes and verifies exited 0. The measurement worktree was clean at
`cf0f95f3f9af85df46d5506a87de806cf3f00c46` before the first take and
remained at that exact commit, clean, after the fourth verify (reconfirmed
by `git status --short` immediately before and after the sequence).

| p037-b-baseline-mos-repo.json | `48d9d881846a22128366b5cb4b6c039be56fd4412040a99acf31b41c4817b34f` |
| p037-b-baseline-mos-corpus.json | `85d3d8f3a084cfc994c57c97e55181692088d780f2eac7c67a64dbde5eec5477` |
| p037-b-baseline-verdict-python.json | `a7214885d1c257491a337853a636508d6fa80992f8f5db610cc356d9ecead219` |
| p037-b-baseline-verdict-rust.json | `e674c689de6138369a3f72284ecd5ec1cdb6f1e50a5d43c1daaa11abcf8ed5e9` |

Every record above carries, and all four agree on:

- `source_commit`: `cf0f95f3f9af85df46d5506a87de806cf3f00c46`
- `population_commit`: `cf0f95f3f9af85df46d5506a87de806cf3f00c46`
- `epoch`: `b`
- `environment_id`: `P037_B_MEASUREMENT_M3`
- `dirty`: `false`
- `is_evidence`: `true`
- `post_run_population_intact`: `true`
- `instrument_identity`: `c953acda915859449a69ef2866bd947591d48a6d8c302d8955e356f370788c69`

Every one of the four records above was also mechanically checked, not
merely assumed, against the newly-hardened
`p037_evidence_b.record_problems()`/`provenance_problems(against=T_B)` (the
CH3-12/CH3-13 repair this retake exists to validate): all four return `[]`
-- the honest, real form of the falsifier this whole repair arc was run
for ("can a freshly hardened instrument actually accept four
mutually-consistent baseline artifacts, and then honestly accept them
itself"). Every verdict file's `call_site_witnesses` is `[]` throughout
both snapshots, as required pre-treatment (no B2.1b/c producer exists yet
to populate one; a non-empty array here would itself have been a STOP
condition).

Observed population/finding counts, matching every prior `R_B` take
exactly (no drift, as expected -- no production semantics moved):

- MOS repo: 1 document (`repo-tree`), 82 source file(s), cross-engine
  mismatches = 0, classified divergences = 0.
- MOS corpus: 192 documents, cross-engine mismatches = 0, classified
  divergences = 0.
- verdict/python: 192 files, 105 findings.
- verdict/rust: 192 files, 105 findings.

No Phase-B classified divergence is expected, or was observed, at this
pre-treatment baseline: B2.1a/B2.1b/c have not landed, so there is nothing
yet for `scripts/p037_b_classifier.py` to classify. A classified divergence
appearing here would itself have been treated as a STOP condition, not
quietly accepted.

## Cross-engine parity at baseline

Independently, a scratch, uncommitted, read-only comparison script
mechanically re-verified `python == rust` for every one of the 193 MOS
documents (1 repo-tree + 192 corpus) directly from the two snapshot files'
own `documents[*]["python-ownlang"]["document"]`/
`documents[*]["rust-own-bridge"]["document"]` fields, requiring both
engines' `status` to be `"produced"` (never merely absent) -- 0 mismatches
on either snapshot, matching the take output rather than merely trusting
it.

The verdict snapshots do not have a built-in cross-engine comparator by
design (`p037_verdict_snapshot.py compare` explicitly refuses a
cross-engine pair: "measures the engine, not the change"), so parity was
checked directly with the same kind of scratch, read-only, uncommitted
comparison: all 192 corpus files carry identical `(line, code, level)`
finding sets and identical exit codes on both engines -- 105 findings each
side, 0 mismatching files, exactly matching all four prior `R_B` takes'
own numbers.

This is the empirical form of the frozen `first_semantic_hypothesis.
facts_expectation` claim (`docs/evidence/p037-b-epoch.json`): nothing about
the pre-treatment facts or verdict surface moved -- not on any prior
instrument boundary, and not on this repair arc's own five-commit instrument
boundary either, because none of the five commits changed production
semantics.

## P-037 conformance baseline at T_B

Re-run fresh at `cf0f95f3f9af85df46d5506a87de806cf3f00c46`, both as part of
this retake's preflight (before the four takes) and again afterward (still
at the same clean commit) -- both passes agree exactly, `OWEN_RUST_CORE`
pointed at the qualified `own-cli` release build:

- `python scripts/p037_controls.py --engine both`: `RESULT: all match` (the
  three G-V4 known-false-positive controls and the one legacy-honesty
  control all agree between engines and against the recorded record).
  Methodological note, recorded honestly: the FIRST attempt at this check
  in the fresh measurement worktree (see "Workspace" above) showed all
  four controls DISAGREEING, rust reporting no findings at all -- traced
  immediately to the fresh worktree never having built a Rust binary nor
  had `OWEN_RUST_CORE` set (own-check.sh's own documented, by-design
  behavior: "there is no discovery of any kind"), not a real semantic gap.
  `python scripts/p037_evidence.py artifacts` qualified `own-cli`/`own-
  shadow-engine` at this exact source commit, `OWEN_RUST_CORE` was
  exported to the qualified build, and the check was re-run clean before
  being trusted for this record.
- `python scripts/p037_fact_shapes.py check --engine both`: `RESULT: all 55
  shape(s) match their recorded facts and verdicts`.

Identical results to all four prior `R_B` takes' own recorded conformance
state. Also reconfirmed at this same head: `python scripts/p037_controls.py
--post-a1 --engine rust` stays fully RED (`RESULT: mismatch`, exit code 1,
all four controls disagreeing with the post-A1 target) -- no semantic
treatment occurred as part of this instrument fix.

`python scripts/p037_b_production_diff_gate.py check --reference
718a673c01641883df433b89cb76d5e3942d8815 --head
cf0f95f3f9af85df46d5506a87de806cf3f00c46 --require identical`:
`IDENTICAL`. `python scripts/p037_b_extractor_diff_gate.py check
--reference 718a673c01641883df433b89cb76d5e3942d8815 --head
cf0f95f3f9af85df46d5506a87de806cf3f00c46 --require identical`: `IDENTICAL`.
`python scripts/p037_b_cli_diff_gate.py check --reference
718a673c01641883df433b89cb76d5e3942d8815 --head
cf0f95f3f9af85df46d5506a87de806cf3f00c46 --require identical`: `IDENTICAL`.
(All three also report `IDENTICAL` against the longer-standing
`e4199ec4aa8d8f95c1b7e881f1ce3ba85f6ba58c` reference -- see above.)
`python scripts/p037_proof_boundary.py`: `GREEN` (harnesses=23,
assumptions=16).

### Delegation closure is correlation, not provenance

`python scripts/p037_delegation_closure.py check` at this T_B: `documents=
193, total=40, covered=40, missing=0, ambiguous=0` (`orphan-hosted calls
(structurally excluded)=5`, `calls without a release (informational, not a
failure)=18`), independently reproducing every prior measurement of this
population exactly. This number is recorded here as a
CORRELATION census, not as proof of causal provenance, per B1-F2-F4-R1's
own correction (`docs/evidence/p037-b-epoch.json`'s `treatment.
b1_f2_f4_r1_findings.delegation_closure_claim_corrected`;
`scripts/p037_delegation_closure.py`'s own module docstring): a release op
carries only `{var, line}`, no provenance tag, so a genuinely direct
dispose sharing its statement line with an unrelated, eligible,
same-variable call is structurally indistinguishable from a call-fabricated
one under this vocabulary. These correlation matches are real,
independently reproducible, and strongly corroborate the delegation
architecture's own hypothesis -- they are NOT the authoritative
changed-site population for a future B2.1a-after evidence take. This
number is not to be cited elsewhere as an exact or final site count.

### Python rollback movement is mechanical, not semantic

This baseline records the PRE-treatment state, where Python and Rust agree
everywhere (above) and there is nothing yet to roll back from. The
distinction below is recorded here anyway because it is load-bearing for
how the future B_after take must be read: at B_after time, Python's own
before/after MOS movement (relative to THIS baseline) is admitted as
evidence ONLY when the same document's raw facts hash ALSO moved between
the two takes -- never independently, and never merely because Rust is
expected to move under treatment (`scripts/p037_mos_snapshot.py`'s
`_compare_documents()`, the Python axis). This is a MECHANICAL acceptance
rule, not a semantic classification: unlike Rust's own before/after axis
(which must be explained in full by `scripts/p037_b_classifier.py`'s
structured divergence classifier, the identical whole-document discipline
already required for intra-take Python-vs-Rust divergence), a Python
movement is never run through that classifier at all. Its legitimacy rests
entirely on two independently closed boundaries, not on anything Python
itself proves: (1) `ownlang`'s own Python summarization logic stays frozen
throughout B2.1a/B2.1b/c, so it cannot drift on its own; (2) B2.1a's own
raw-fact movement is independently restricted, by
`first_semantic_hypothesis.facts_expectation`'s closed allowed/never rule,
to the governed `release(var, line)` -> `use(var, the SAME line)`
delegation rewrite alone.

## R_B evidence commit / naming commit

This manifest is written as part of the evidence-only commit that replaces
the four baseline JSON artifacts above; `docs/evidence/p037-b-epoch.json`'s
`named_later.T_B`/`R_B` are updated only in a SEPARATE, later naming
commit, once this evidence commit is itself terminal-green on CI (exact
commit SHAs and CI/Kani results recorded there, not invented here ahead of
either commit existing) -- mirroring exactly how `df9a433` preceded
`bfa8647`, `069d5bc` preceded `5579d80`/`f8ffd42`, `9418f575...` preceded
`a319a9501b32e6e6900efb880080d2f8c198bc39`, and `9d914e33f67f922da2218dd3e276252fa83a3638`
preceded `3ac13fd` (naming `718a673`, the T_B this manifest supersedes)
before it.

This commit is evidence-only: it updates exactly five files under
`docs/evidence/` (these four JSON artifacts plus this manifest, all
already tracked from the earlier `R_B` takes) and nothing else. No
instrument, treatment, spec, tooling, or CI file is touched.

Run time/date: 2026-09-28, operator run.
