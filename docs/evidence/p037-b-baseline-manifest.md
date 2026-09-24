# P-037 Phase B / B1 baseline manifest (R_B)

epoch: `b`

T_B (terminal-green, the measurement-instrument head): `cfe7e19c4f6a9f4d2d7606bcc6f288b52f196bcd`

population_commit (every take): `cfe7e19c4f6a9f4d2d7606bcc6f288b52f196bcd`

environment: `P037_B_MEASUREMENT_M3`

This is the same measurement environment the whole B1 line has used since
its own qualification. It is not `P037_A2D_MEASUREMENT_M2` by another name
-- M2's own records (R_D, D_after) stay historical a2d evidence, neither
retaken nor a control of M3. No a2/a2d evidence is the baseline of Phase B;
the a2d T/R/S records are historical predecessors only and are not
retaken, compared, or treated as a control here (`docs/evidence/p037-b-
epoch.json`'s own `predecessor`/`environment` sections state this
precisely).

## This is a retake, not the first or second R_B

The instrument this take measures against is not the one `a02ccf1`/
`df9a433` measured against. That earlier instrument was itself terminal-
green and honestly measured, but B1-F2 found a boundary defect in it:
`frontend/roslyn/OwnSharp.Extractor/` was classified as full measurement
INSTRUMENT with no carve-out at all, while the frozen A1 acceptance matrix
(`docs/notes/p037-formal-kernel.md` #8.1, items 5 and 8) requires an
extractor-side semantic change there -- a treatment surface cannot
simultaneously be frozen measurement instrument. B1-F2
(`docs/notes/p037-formal-kernel.md` #10.8e) corrected the boundary:
`scripts/p037_evidence_b.py`'s `INSTRUMENT_CARVE_OUTS`/`TREATMENT_PATHS`
now carve the whole extractor directory out (the same shape `mos.rs`/
`lower.rs` already had), policed at method granularity by a new, second
item-level gate, `scripts/p037_b_extractor_diff_gate.py`. This is a
governance-boundary correction, not a semantic one: no byte of
`mos.rs`/`lower.rs`/`Program.cs` moved, `p037_controls.py --post-a1`
stayed fully RED throughout (reconfirmed below), and the fix is purely
about what counts as instrument versus treatment in the provenance
closure. `a02ccf1`, `df9a433` and `bfa8647` are kept exactly as
committed -- honest records of the instrument and its baseline at the
boundary B1 originally drew -- superseded here, not rewritten: `git log`
on this file's path still shows their content, and
`docs/evidence/p037-b-epoch.json`'s own `superseded_by_b1_f2` section
names them explicitly, machine-readable, with the reason.

## Instrument identity

```
3591d8056a1debabca046ad1faa1715c71516f0ef37d2037da817a3bde2c5d2d
```

Read from each take's own `instrument_identity` field (computed by
`p037_evidence_b.evidence_fields()`, over Phase B's own, now-corrected
`INSTRUMENT_PATHS`/`INSTRUMENT_CARVE_OUTS` -- the B1-F2 fix). All four
takes below agree on it, byte-for-byte. This differs from the value the
superseded baseline recorded
(`75764c81ac49185adad6a02657b373a7453fc03ba337bb61b86d4694bd8d5065`) --
expected and confirmed by direct measurement, not assumed: widening
`INSTRUMENT_CARVE_OUTS` to include the whole extractor directory is
exactly the kind of instrument-definition change that must move this
digest, and it does.

## Execution profile (M3, identical across all four takes)

- Python: CPython 3.11.15 (main, Mar 3 2026, 09:26:23) [GCC 13.3.0]
- .NET SDK: 8.0.425, runtimes: Microsoft.AspNetCore.App 8.0.31, Microsoft.NETCore.App 8.0.31
- Rust: rustc 1.94.1 (e408947bf 2026-03-25), cargo 1.94.1 (29ea6fb6a 2026-03-24), host x86_64-unknown-linux-gnu
- Platform: Linux / x86_64

Captured verbatim via `python3 scripts/p037_evidence_b.py profile` after
the fourth take (this retake reuses the same qualified M3 environment
every prior Phase-B take in this session used; only the instrument
definition changed, not the toolchain, so a fresh before/after pair was
not repeated -- the one capture below, byte-for-byte identical to both
prior R_B manifests' own recorded profile, is the evidence for that):

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

Byte-for-byte identical to both prior `R_B` manifests' own recorded
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
not touched by B1-F2):

```
5fe4ece4c24b720f659a49bbc68b8438080c9e4b8ba554ee40f6eea94c66eb26
```

Recipe: `provision.sh`, retained outside this repository at
`/root/p037-a2d-m2-recipe/provision.sh` on the qualified machine. The
environment/toolchain was not changed by B1-F2 -- only the instrument's
own `INSTRUMENT_PATHS`/`INSTRUMENT_CARVE_OUTS` definition moved.

## Workspace

The same preserved measured workspace checkout root used throughout this
epoch:

```
/home/user/Own.NET
```

## Takes

Four sequential governed takes, each independently `verify`d against the
new T_B before the next was started. None ran concurrently.

1. MOS repo snapshot (`--epoch b --source repo`)
2. MOS corpus snapshot (`--epoch b --source corpus`)
3. verdict/python snapshot (`--epoch b --engine python`)
4. verdict/rust snapshot (`--epoch b --engine rust`)

All four takes and verifies exited 0. The checkout was clean at
`cfe7e19c4f6a9f4d2d7606bcc6f288b52f196bcd` before the first take and
remained at that exact commit, clean, after the fourth verify.

| p037-b-baseline-mos-repo.json | `bf8c6a9bb9595b2cfe53eeba368365a583dde561ceb174e843e92585e64e5e09` |
| p037-b-baseline-mos-corpus.json | `d4fd0f7e553c33b144656be8b4df3c5e82f8d4b28b86ed1324e6cd3a371e98db` |
| p037-b-baseline-verdict-python.json | `970f80ceb23215127ecd1838ff640ffd0b26294425523ba90e4b88a8688edc85` |
| p037-b-baseline-verdict-rust.json | `cbad406da85ffa71bc6028e2b9fc066c570ea62c5d5bfe86f40d7382bb72a311` |

Every record above carries, and all four agree on:

- `source_commit`: `cfe7e19c4f6a9f4d2d7606bcc6f288b52f196bcd`
- `population_commit`: `cfe7e19c4f6a9f4d2d7606bcc6f288b52f196bcd`
- `epoch`: `b`
- `environment_id`: `P037_B_MEASUREMENT_M3`
- `dirty`: `false`
- `is_evidence`: `true`
- `instrument_identity`: `3591d8056a1debabca046ad1faa1715c71516f0ef37d2037da817a3bde2c5d2d`

## Cross-engine parity at baseline

`scripts/p037_mos_snapshot.py` only writes a `cross_engine_mismatches` key
at all when that list is non-empty (confirmed by reading the tool's own
source, not assumed from its absence); neither MOS snapshot below carries
the key, and both takes' own console output recorded `cross-engine
mismatches=0` explicitly (82 and 192 documents respectively). The verdict
snapshots do not have a built-in cross-engine comparator by design
(`p037_verdict_snapshot.py compare` explicitly refuses a cross-engine
pair: "measures the engine, not the change"), so parity was checked
directly: all 192 corpus files carry identical `(line, code, level)`
finding sets and identical exit codes on both engines -- 105 findings
each side, 0 mismatches, exactly matching both prior `R_B` takes' own
numbers. This is the empirical form of the frozen `facts_expectation`
claim (`docs/evidence/p037-b-epoch.json`'s `measurement_policy`): nothing
about the pre-treatment facts or verdict surface moved -- not on the
first instrument, not on the B1-F1-corrected instrument, and not on the
B1-F2-corrected instrument boundary either, because B1-F2 changed no
production semantics.

## P-037 conformance baseline at T_B

Both re-run fresh at `cfe7e19c4f6a9f4d2d7606bcc6f288b52f196bcd`, `OWEN_
RUST_CORE` pointed at the qualified `own-cli` release build:

- `python scripts/p037_controls.py --engine both`: `RESULT: all match` (the
  three G-V4 known-false-positive controls and the one legacy-honesty
  control all agree between engines and against the recorded record).
- `python scripts/p037_fact_shapes.py check --engine both`: `RESULT: all 55
  shape(s) match their recorded facts and verdicts`.

Identical results to both prior `R_B` takes' own recorded conformance
state. Also reconfirmed at this same head: `python scripts/p037_controls.py
--post-a1 --engine both` stays fully RED (`RESULT: mismatch`) on all four
controls, both engines -- no semantic treatment occurred as part of this
boundary fix. Recorded here as the P-037 conformance state at the new
T_B, per the B1 brief's own instruction to measure and record it, not to
chase or repair it as part of this baseline.

Run time/date: 2026-09-24, ~04:26-05:10 UTC, operator run.

This commit is evidence-only: it updates exactly five files under
`docs/evidence/` (these four JSON artifacts plus this manifest, all
already tracked from the earlier `R_B` takes) and nothing else. No
instrument, treatment, spec, tooling, or CI file is touched.
`docs/evidence/p037-b-epoch.json`'s `named_later.T_B`/`R_B` are not
updated by this commit -- that is the naming commit's own, separate act,
after this evidence is itself terminal-green, mirroring exactly how
`df9a433` preceded `bfa8647` the first retake, and `40cb9b4` preceded
`2ed4d92` before that.
