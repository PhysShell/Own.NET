# P-037 Phase B / B1 baseline manifest (R_B)

epoch: `b`

T_B (terminal-green, the measurement-instrument head): `718a673c01641883df433b89cb76d5e3942d8815`

population_commit (every take): `718a673c01641883df433b89cb76d5e3942d8815`

environment: `P037_B_MEASUREMENT_M3`

This is the same measurement environment the whole B1 line has used since
its own qualification. It is not `P037_A2D_MEASUREMENT_M2` by another name
-- M2's own records (R_D, D_after) stay historical a2d evidence, neither
retaken nor a control of M3. No a2/a2d evidence is the baseline of Phase B;
the a2d T/R/S records are historical predecessors only and are not
retaken, compared, or treated as a control here (`docs/evidence/p037-b-
epoch.json`'s own `predecessor`/`environment` sections state this
precisely).

## This is the fourth R_B, not the first, second, or third

The instrument this take measures against is not the one `a02ccf1`/
`df9a433`, `cfe7e19`/`069d5bc`, or `fdde0a026d264ceff0e44f8c86e7d059207f67e6`
(the previous, third `R_B`, recorded in this file's own prior content and
still readable via `git log -p -- docs/evidence/p037-b-baseline-manifest.md`)
measured against. B1-F2-F4 and B1-F2-F4-R1 (`docs/notes/p037-formal-
kernel.md` #10.8h/#10.8i) each changed the Phase-B measurement instrument
itself, not production semantics:

- **B1-F2-F4** made `scripts/p037_mos_snapshot.py` epoch-aware (so a real
  post-treatment Rust MOS divergence, classified by
  `scripts/p037_b_classifier.py`'s frozen three-class rule, counts as
  evidence instead of automatic failure); closed the classifier's
  `GAP_REAL_WITNESS_SOURCE` real-witness adapter; widened
  `rust/crates/own-bridge/src/dump.rs` from frozen to item-level mutable
  (`fn dump_summaries` only, so `guarded_functions[]` is not silently
  invisible to a future summary dump); narrowed the extractor production-
  diff gate's `mutable_methods` back to `EmitFlowExpr` alone (uniform
  delegation replacing the two-role design B1-F2-F2 had authorized); and
  added `scripts/p037_delegation_closure.py`, a new, standalone,
  machine-derived control (not itself an instrument path).
- **B1-F2-F4-R1** closed three defects an independent owner review found in
  the B1-F2-F4 head before any retake was taken against it: (1)
  `p037_mos_snapshot.py`'s `compare()` classified intra-after
  Python-vs-Rust divergence but still used bare, epoch-blind inequality for
  its OWN before/after per-engine axis -- fixed by factoring the decision
  into a new, directly unit-tested `_compare_documents()`, applying the
  SAME whole-document classifier discipline to the Rust before/after axis
  and a facts-hash-gated rollback rule to the Python axis (see "Python
  rollback movement is mechanical, not semantic" below); (2)
  `scripts/p037_delegation_closure.py`'s claim was re-scoped from
  "mechanically proves every legacy-fabricated release has a sidecar call
  fact" (provenance, which a `{var, line}`-only release vocabulary cannot
  support) to "mechanically proves a correlation closure" (see "Delegation
  closure is correlation, not provenance" below); (3) the epoch record's
  own `ci_transition_plan.current_ci_unaffected` field claimed today's CI
  keeps passing unmodified through B2.1a, directly contradicted by the
  epoch record's own `facts_expectation` -- corrected and renamed
  `current_ci_transition`.

Neither task moved a byte of `Program.cs`, `rust/crates/own-bridge/`'s
production semantics, `ownlang/`, or OwnIR vocabulary -- both production
diff gates report `IDENTICAL` against `ad55df46de07b9de1c026b804c0c8c73e5bdb35d`
(the closed B1-F2-F4 naming head), reconfirmed directly as part of this
retake's own preflight, not assumed from the commit messages.
`a02ccf1`, `df9a433`, `bfa8647`, `cfe7e19`, `069d5bc`, `5579d80`/`f8ffd42`,
`fdde0a026d264ceff0e44f8c86e7d059207f67e6`, and `9418f575b42c2e03734bd97968a904950e86e2cf`
are kept exactly as committed -- honest records of the instrument and its
baseline at the boundary each held at the time -- superseded here, not
rewritten: `git log` on this file's path still shows their content, and
`docs/evidence/p037-b-epoch.json`'s own supersession chain names them
explicitly, machine-readable, with the reason. Full investigation detail is
in `docs/notes/p037-formal-kernel.md` #10.8h/#10.8i and
`docs/evidence/p037-b-epoch.json`'s `treatment.b1_f2_f4_findings`/
`treatment.b1_f2_f4_r1_findings` -- not duplicated here.

## Instrument identity

```
2b401fc72cc58c0f49e1d002c14a666f9863f657077f39467335e7ab8ec704ba
```

Read from each take's own `instrument_identity` field (computed by
`p037_evidence_b.evidence_fields()`/`instrument_identity()`, over Phase B's
own `INSTRUMENT_PATHS`/`INSTRUMENT_CARVE_OUTS`), and independently
recomputed directly via `p037_evidence_b.instrument_identity(T_B)` before
any take started, per this retake's own preflight discipline (never
invented or predeclared). All four takes below agree on it, byte-for-byte.
This differs from the value the superseded baseline recorded
(`d93e34e0a6e740ad4ffaa6c1894f32c14fbded79b50b5fc2f678da860d2108d7`) --
expected and confirmed by direct measurement, not assumed: B1-F2-F4/R1
changed `scripts/p037_mos_snapshot.py` and `scripts/p037_b_classifier.py`,
both tracked `INSTRUMENT_PATHS`, so this digest had to move, and it does.

## Execution profile (M3, identical across all four takes)

- Python: CPython 3.11.15 (main, Mar 3 2026, 09:26:23) [GCC 13.3.0]
- .NET SDK: 8.0.425, runtimes: Microsoft.AspNetCore.App 8.0.31, Microsoft.NETCore.App 8.0.31
- Rust: rustc 1.94.1 (e408947bf 2026-03-25), cargo 1.94.1 (29ea6fb6a 2026-03-24), host x86_64-unknown-linux-gnu
- Platform: Linux / x86_64

Captured verbatim via `python3 scripts/p037_evidence_b.py profile` before
the first take (this retake reuses the same qualified M3 environment every
prior Phase-B take in this session used; only the instrument definition
changed, not the toolchain, so a fresh before/after pair was not repeated
-- the one capture below, byte-for-byte identical to all three prior `R_B`
manifests' own recorded profile, is the evidence for that):

```json
{
 "dotnet": {
  "runtimes": [
   "Microsoft.AspNetCore.App 8.0.31",
   "Microsoft.NETCore.App 8.0.31"
  ],
  "sdk": "8.0.425"
 },
 "platform": {
  "machine": "x86_64",
  "system": "Linux"
 },
 "python": {
  "implementation": "CPython",
  "version": "3.11.15 (main, Mar  3 2026, 09:26:23) [GCC 13.3.0]"
 },
 "rust": {
  "cargo": "cargo 1.94.1 (29ea6fb6a 2026-03-24)",
  "host": "x86_64-unknown-linux-gnu",
  "rustc": "rustc 1.94.1 (e408947bf 2026-03-25)\nbinary: rustc\ncommit-hash: e408947bfd200af42db322daf0fadfe7e26d3bd1\ncommit-date: 2026-03-25\nhost: x86_64-unknown-linux-gnu\nrelease: 1.94.1\nLLVM version: 21.1.8"
 }
}
```

Byte-for-byte identical to all three prior `R_B` manifests' own recorded
profile (and, in turn, to `docs/evidence/p037-a2d-baseline-mos-repo.json`'s
recorded M2 profile) -- the same physical workspace and toolchain,
re-verified rather than assumed unchanged.

## Machine qualification

Measurement environment `P037_B_MEASUREMENT_M3`, unchanged since B1's own
qualification (this retake re-measures the instrument's definition, not
the environment):

- CPython: pinned to the host interpreter (3.11.15).
- .NET SDK: 8.0.425, installed isolated outside any OS package manager.
- Rust: rustc/cargo 1.94.1.

recipe sha256 (unchanged since qualification; the environment itself was
not touched by B1-F2-F4/R1):

```
5fe4ece4c24b720f659a49bbc68b8438080c9e4b8ba554ee40f6eea94c66eb26
```

Recipe: `provision.sh`, retained outside this repository at
`/root/p037-a2d-m2-recipe/provision.sh` on the qualified machine. The
environment/toolchain was not changed by B1-F2-F4/R1 -- only the
instrument's own tooling did.

## Workspace

The same preserved measured workspace checkout root used throughout this
epoch:

```
/home/user/Own.NET
```

## Takes

Four sequential governed takes, each independently `verify`d against the
new T_B before the next was started. None ran concurrently. Every take
first wrote to a fresh scratch directory (`/tmp/p037-b-rb-718a673/`,
containing no stale files from any prior baseline) before being copied
into this tracked location.

1. MOS repo snapshot (`--epoch b --source repo`)
2. MOS corpus snapshot (`--epoch b --source corpus`)
3. verdict/python snapshot (`--epoch b --engine python`)
4. verdict/rust snapshot (`--epoch b --engine rust`)

All four takes and verifies exited 0. The checkout was clean at
`718a673c01641883df433b89cb76d5e3942d8815` before the first take and
remained at that exact commit, clean, after the fourth verify (reconfirmed
by `git status --short` immediately before and after the sequence).

| p037-b-baseline-mos-repo.json | `c2467bbc8a752a0354ad6d33fe2250f6d3f77cb15d705c62e8b85a160768239f` |
| p037-b-baseline-mos-corpus.json | `3f6eddb7bf5e0d833d77c5b2eba31dcf2dbc6b26e52a5b7491030ea5d241107a` |
| p037-b-baseline-verdict-python.json | `e752b93b3ded26d970d22d2793b5e29ec2a356c7f6b2bbcfb4dd879995eeabad` |
| p037-b-baseline-verdict-rust.json | `8506c26f8a0b11cd5f72f9344bbadd4b8d0417532fb245f46224ea9fa065707b` |

Every record above carries, and all four agree on:

- `source_commit`: `718a673c01641883df433b89cb76d5e3942d8815`
- `population_commit`: `718a673c01641883df433b89cb76d5e3942d8815`
- `epoch`: `b`
- `environment_id`: `P037_B_MEASUREMENT_M3`
- `dirty`: `false`
- `is_evidence`: `true`
- `instrument_identity`: `2b401fc72cc58c0f49e1d002c14a666f9863f657077f39467335e7ab8ec704ba`

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

`scripts/p037_mos_snapshot.py` only writes a `cross_engine_mismatches` (or
`classified_divergences`) key at all when that list is non-empty (confirmed
by reading the tool's own source, not assumed from its absence); neither
MOS snapshot below carries either key, and both takes' own console output
recorded `cross-engine mismatches=0, classified divergences=0` explicitly.
Independently, a scratch, uncommitted, read-only comparison script
mechanically re-verified `python == rust` for every one of the 193 MOS
documents (1 repo-tree + 192 corpus) directly from the two snapshot files'
own `documents[*].python`/`documents[*].rust` fields -- 0 mismatches on
either snapshot, matching the take output rather than merely trusting it.

The verdict snapshots do not have a built-in cross-engine comparator by
design (`p037_verdict_snapshot.py compare` explicitly refuses a
cross-engine pair: "measures the engine, not the change"), so parity was
checked directly with the same kind of scratch, read-only, uncommitted
comparison: all 192 corpus files carry identical `(line, code, level)`
finding sets and identical exit codes on both engines -- 105 findings each
side, 0 mismatching files, exactly matching all three prior `R_B` takes'
own numbers.

This is the empirical form of the frozen `first_semantic_hypothesis.
facts_expectation` claim (`docs/evidence/p037-b-epoch.json`): nothing about
the pre-treatment facts or verdict surface moved -- not on any prior
instrument boundary, and not on the B1-F2-F4/R1-corrected instrument
boundary either, because neither task changed production semantics.

## P-037 conformance baseline at T_B

Re-run fresh at `718a673c01641883df433b89cb76d5e3942d8815`, both as part of
this retake's preflight (before the four takes) and again afterward (still
at the same clean commit) -- both passes agree exactly, `OWEN_RUST_CORE`
pointed at the qualified `own-cli` release build:

- `python scripts/p037_controls.py --engine both`: `RESULT: all match` (the
  three G-V4 known-false-positive controls and the one legacy-honesty
  control all agree between engines and against the recorded record).
- `python scripts/p037_fact_shapes.py check --engine both`: `RESULT: all 55
  shape(s) match their recorded facts and verdicts`.

Identical results to all three prior `R_B` takes' own recorded conformance
state. Also reconfirmed at this same head: `python scripts/p037_controls.py
--post-a1 --engine rust` stays fully RED (`RESULT: mismatch`, exit code 1,
all four controls disagreeing with the post-A1 target) -- no semantic
treatment occurred as part of this instrument fix. Note the engine scope
here is `rust` alone, not `both`: B1-F2-F4 corrected `ci_transition_plan.
b2_1b_c_gate` so the FINAL mandatory post-A1 gate is `--engine rust` only,
Python being measured separately under the rollback/reference rule (below)
-- reusing the old manifest's `--engine both` wording for this check would
itself now be stale, so it is not repeated here.

`python scripts/p037_b_production_diff_gate.py check --reference
ad55df46de07b9de1c026b804c0c8c73e5bdb35d --head
718a673c01641883df433b89cb76d5e3942d8815 --require identical`:
`IDENTICAL`. `python scripts/p037_b_extractor_diff_gate.py check
--reference ad55df46de07b9de1c026b804c0c8c73e5bdb35d --head
718a673c01641883df433b89cb76d5e3942d8815 --require identical`: `IDENTICAL`.
`python scripts/p037_proof_boundary.py`: `GREEN` (harnesses=23,
assumptions=16).

### Delegation closure is correlation, not provenance

`python scripts/p037_delegation_closure.py check` at this T_B: `documents=
193, total=40, covered=40, missing=0, ambiguous=0` (`orphan-hosted calls
(structurally excluded)=5`), independently reproducing every prior
measurement of this population exactly. This number is recorded here as a
CORRELATION census, not as proof of causal provenance, per B1-F2-F4-R1's
own correction (`docs/evidence/p037-b-epoch.json`'s `treatment.
b1_f2_f4_r1_findings.delegation_closure_claim_corrected`;
`scripts/p037_delegation_closure.py`'s own module docstring): a release op
carries only `{var, line}`, no provenance tag, so a genuinely direct
dispose sharing its statement line with an unrelated, eligible,
same-variable call is structurally indistinguishable from a call-fabricated
one under this vocabulary (`scripts/p037_delegation_closure.py`'s own
hostile selftest constructs and proves exactly this collision). The 40
correlation matches are real, independently reproducible, and strongly
corroborate the delegation architecture's own hypothesis -- they are NOT
the authoritative changed-site population for a future B2.1a-after
evidence take. That population will be established, once and honestly, by
a governed BEFORE/AFTER RAW-FACT DIFF the moment B2.1a itself lands
(`first_semantic_hypothesis.facts_expectation.verified_by`), diffing this
same frozen population's raw facts byte-for-byte against the pre-B2.1a
baseline this manifest records. This number is not to be cited elsewhere
as an exact or final site count.

### Python rollback movement is mechanical, not semantic

This baseline records the PRE-treatment state, where Python and Rust agree
everywhere (above) and there is nothing yet to roll back from. The
distinction below is recorded here anyway because it is load-bearing for
how the future B_after take must be read, and B1-F2-F4-R1 requires it to
survive into that write-up rather than being rediscovered there: at
B_after time, Python's own before/after MOS movement (relative to THIS
baseline) is admitted as evidence ONLY when the same document's raw facts
hash ALSO moved between the two takes -- never independently, and never
merely because Rust is expected to move under treatment
(`scripts/p037_mos_snapshot.py`'s `_compare_documents()`, the Python axis).
This is a MECHANICAL acceptance rule, not a semantic classification: unlike
Rust's own before/after axis (which must be explained in full by
`scripts/p037_b_classifier.py`'s structured divergence classifier, the
identical whole-document discipline already required for intra-take
Python-vs-Rust divergence), a Python movement is never run through that
classifier at all. Its legitimacy rests entirely on two independently
closed boundaries, not on anything Python itself proves: (1) `ownlang`'s
own Python summarization logic stays frozen throughout B2.1a/B2.1b/c, so it
cannot drift on its own; (2) B2.1a's own raw-fact movement is independently
restricted, by `first_semantic_hypothesis.facts_expectation`'s closed
allowed/never rule, to the governed `release(var, line)` -> `use(var, the
SAME line)` delegation rewrite alone. Squeezed from both sides, "Python's
MOS moved because the shared raw facts moved" cannot mean anything else --
but the rule itself proves nothing semantic, and the future B_after
write-up must say so explicitly rather than treat "Python moved" as if it
had been classified the way Rust's own movement is.

## R_B evidence commit / naming commit

This manifest is written as part of the evidence-only commit that replaces
the four baseline JSON artifacts above; `docs/evidence/p037-b-epoch.json`'s
`named_later.T_B`/`R_B` are updated only in a SEPARATE, later naming
commit, once this evidence commit is itself terminal-green on CI (exact
commit SHAs and CI/Kani results recorded there, not invented here ahead of
either commit existing) -- mirroring exactly how `df9a433` preceded
`bfa8647`, `069d5bc` preceded `5579d80`/`f8ffd42`, and `9418f575...`
preceded `a319a9501b32e6e6900efb880080d2f8c198bc39` before it.

This commit is evidence-only: it updates exactly five files under
`docs/evidence/` (these four JSON artifacts plus this manifest, all
already tracked from the earlier `R_B` takes) and nothing else. No
instrument, treatment, spec, tooling, or CI file is touched.

Run time/date: 2026-09-26, operator run.
