# P-037 Phase B / B1 baseline manifest (R_B)

epoch: `b`

T_B (terminal-green, the measurement-instrument head): `fdde0a026d264ceff0e44f8c86e7d059207f67e6`

population_commit (every take): `fdde0a026d264ceff0e44f8c86e7d059207f67e6`

environment: `P037_B_MEASUREMENT_M3`

This is the same measurement environment the whole B1 line has used since
its own qualification. It is not `P037_A2D_MEASUREMENT_M2` by another name
-- M2's own records (R_D, D_after) stay historical a2d evidence, neither
retaken nor a control of M3. No a2/a2d evidence is the baseline of Phase B;
the a2d T/R/S records are historical predecessors only and are not
retaken, compared, or treated as a control here (`docs/evidence/p037-b-
epoch.json`'s own `predecessor`/`environment` sections state this
precisely).

## This is the third R_B, not the first or second

The instrument this take measures against is not the one `a02ccf1`/
`df9a433` or `cfe7e19`/`069d5bc` measured against. B1-F2-F2
(`docs/notes/p037-formal-kernel.md` #10.8f) found the B1-F2-corrected
extractor seam -- `ConsumeReleaseArgs`/`ConsumesParam`/`CallReleasesReceiver`
alone -- was itself mechanically too narrow for the future B2.1a semantic
treatment: `ConsumeReleaseArgs`'s answer is read by two different
consumers, `EmitFlowExpr` (to fabricate the unconditional `release`) and
the escape/tracking admission check (`consumedArg`, deciding whether a
local stays tracked at all). A scratch prototype (never committed --
`git diff f8ffd42 -- frontend/roslyn/OwnSharp.Extractor/Program.cs` is
empty at this head) proved that changing `ConsumeReleaseArgs`'s answer
to stop the fabrication also starves the tracking admission check: 7 of
the 8 named acceptance fixtures had their caller orphaned out of
`functions[]` entirely, and the 8th lost tracking of an unrelated,
genuinely-owned local. B1-F2-F2 widened `mutable_methods` to include
`EmitFlowExpr` as a fourth, separately-authorized method -- the seam that
actually owns release-*emission*, decoupled from `ConsumeReleaseArgs`'s
tracking role, which stays frozen and unchanged. This is a governance-
boundary widening, not a semantic one: no byte of `Program.cs` moved
(confirmed against `f8ffd42`), `p037_controls.py --post-a1` stays fully
RED (reconfirmed below), and the fix is purely about which existing
methods a future B2.1a commit is authorized to change. `a02ccf1`,
`df9a433`, `bfa8647`, `cfe7e19`, `069d5bc`, and `5579d80`/`f8ffd42` are
kept exactly as committed -- honest records of the instrument and its
baseline at the boundary each held at the time -- superseded here, not
rewritten: `git log` on this file's path still shows their content, and
`docs/evidence/p037-b-epoch.json`'s own `superseded_by_b1_f2` section
(plus the B1-F2-F2 treatment note) names them explicitly, machine-
readable, with the reason. Full investigation detail (Finding A/B/C, the
scratch-measured blast radius, the chosen not-yet-implemented direction)
is in `docs/notes/p037-formal-kernel.md` #10.8f and
`docs/evidence/p037-b-epoch.json`'s `treatment.b1_f2_f2_seam_investigation`
-- not duplicated here.

## Instrument identity

```
d93e34e0a6e740ad4ffaa6c1894f32c14fbded79b50b5fc2f678da860d2108d7
```

Read from each take's own `instrument_identity` field (computed by
`p037_evidence_b.evidence_fields()`, over Phase B's own
`INSTRUMENT_PATHS`/`INSTRUMENT_CARVE_OUTS`, unchanged by B1-F2-F2 -- only
the extractor diff-gate's own `mutable_methods` registration moved). All
four takes below agree on it, byte-for-byte. This differs from the value
the superseded baseline recorded
(`3591d8056a1debabca046ad1faa1715c71516f0ef37d2037da817a3bde2c5d2d`) --
expected and confirmed by direct measurement, not assumed: widening
`scripts/p037_b_extractor_diff_gate.py`'s `MUTABLE_METHODS` is exactly the
kind of instrument-definition change that must move this digest, and it
does.

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
prior `R_B` manifests' own recorded profile, is the evidence for that):

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
not touched by B1-F2-F2):

```
5fe4ece4c24b720f659a49bbc68b8438080c9e4b8ba554ee40f6eea94c66eb26
```

Recipe: `provision.sh`, retained outside this repository at
`/root/p037-a2d-m2-recipe/provision.sh` on the qualified machine. The
environment/toolchain was not changed by B1-F2-F2 -- only the extractor
diff-gate's own `mutable_methods` definition moved.

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
`fdde0a026d264ceff0e44f8c86e7d059207f67e6` before the first take and
remained at that exact commit, clean, after the fourth verify.

| p037-b-baseline-mos-repo.json | `9d06afd0471485c93979a4c1f9355a6fcd7f91408d1dd6293ded2bc6f8934c1c` |
| p037-b-baseline-mos-corpus.json | `c0421181f37c41b685f14cdf0c37f1251b3fbf7f34056ccd0eeaa87634b62423` |
| p037-b-baseline-verdict-python.json | `96623cf01d289ead9df0ee67aa0df1b8b77b0cd740d3a0e62630827d0cbfcaab` |
| p037-b-baseline-verdict-rust.json | `e98ff9b81a1c3aab7059a86495cf48a5169888f8512966450182af78ac4649d6` |

Every record above carries, and all four agree on:

- `source_commit`: `fdde0a026d264ceff0e44f8c86e7d059207f67e6`
- `population_commit`: `fdde0a026d264ceff0e44f8c86e7d059207f67e6`
- `epoch`: `b`
- `environment_id`: `P037_B_MEASUREMENT_M3`
- `dirty`: `false`
- `is_evidence`: `true`
- `instrument_identity`: `d93e34e0a6e740ad4ffaa6c1894f32c14fbded79b50b5fc2f678da860d2108d7`

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
each side, 0 mismatches, exactly matching all three prior `R_B` takes' own
numbers. Diffing the four new JSON artifacts against their immediately
preceding (`cfe7e19`-based) counterparts confirms the same thing from the
other direction: every changed line is a commit-identity field
(`source_commit`, `population_commit`, `materialization_root`,
`instrument_identity`, `blob`, an ephemeral `sealed_path` tmpdir) or a
population-commit substring embedded in a sampled file path -- zero
findings, facts, or verdict content differs. This is the empirical form
of the frozen `first_semantic_hypothesis.facts_expectation` claim
(`docs/evidence/p037-b-epoch.json`): nothing about the pre-treatment facts
or verdict surface moved -- not on the first instrument, not on the
B1-F1-corrected instrument, not on the B1-F2-corrected instrument
boundary, and not on the B1-F2-F2-widened extractor seam either, because
B1-F2-F2 changed no production semantics.

## P-037 conformance baseline at T_B

Both re-run fresh at `fdde0a026d264ceff0e44f8c86e7d059207f67e6`, `OWEN_
RUST_CORE` pointed at the qualified `own-cli` release build:

- `python scripts/p037_controls.py --engine both`: `RESULT: all match` (the
  three G-V4 known-false-positive controls and the one legacy-honesty
  control all agree between engines and against the recorded record).
- `python scripts/p037_fact_shapes.py check --engine both`: `RESULT: all 55
  shape(s) match their recorded facts and verdicts`.

Identical results to all three prior `R_B` takes' own recorded
conformance state. Also reconfirmed at this same head: `python
scripts/p037_controls.py --post-a1 --engine both` stays fully RED
(`RESULT: mismatch`, exit code 1, all four controls disagreeing with the
post-A1 target on both engines) -- no semantic treatment occurred as part
of this seam-widening fix. Recorded here as the P-037 conformance state at
the new T_B, per the B1 brief's own instruction to measure and record it,
not to chase or repair it as part of this baseline.

Run time/date: 2026-09-24, operator run.

This commit is evidence-only: it updates exactly five files under
`docs/evidence/` (these four JSON artifacts plus this manifest, all
already tracked from the earlier `R_B` takes) and nothing else. No
instrument, treatment, spec, tooling, or CI file is touched.
`docs/evidence/p037-b-epoch.json`'s `named_later.T_B`/`R_B` are not
updated by this commit -- that is the naming commit's own, separate act,
after this evidence is itself terminal-green, mirroring exactly how
`df9a433` preceded `bfa8647`, and `069d5bc` preceded `5579d80`/`f8ffd42`,
before it.
