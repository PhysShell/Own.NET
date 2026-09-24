# P-037 Phase B / B1 baseline manifest (R_B)

epoch: `b`

T_B (terminal-green, the measurement-instrument head): `a02ccf17d22eaf62c046fb95ba5060e6d66ffeae`

population_commit (every take): `a02ccf17d22eaf62c046fb95ba5060e6d66ffeae`

environment: `P037_B_MEASUREMENT_M3`

This is a NEW measurement environment for a NEW instrument epoch. It is not
`P037_A2D_MEASUREMENT_M2` by another name -- M2's own records (R_D, D_after)
stay historical a2d evidence, neither retaken nor a control of M3. No a2/a2d
evidence is the baseline of Phase B; the a2d T/R/S records are historical
predecessors only and are not retaken, compared, or treated as a control
here (`docs/evidence/p037-b-epoch.json`'s own `predecessor`/`environment`
sections state this precisely).

## This is a retake, not the first R_B

The instrument this take measures against is not the one `349c7bc`/`40cb9b4`
measured against. Between that take and this one, B1-F1 instrument
hardening fixed four defects in the instrument itself (formal-kernel.md
§§10.8b-10.8d): two found by owner review (a classifier precedence bug
that could silently resolve an overlap the frozen contract requires
`UNCLASSIFIED`; a production-diff-gate self-authorization hole that read
its own policy boundary from the head it was validating), and two
self-found (`instrument_identity` was computed by calling
`p037_evidence.py`'s own epoch-coupled function directly, so it measured
a2d's eight-path closure instead of Phase B's own nine-path closure; then,
once fixed, the fix commit's own "consequence" prose mislabeled which
commit its "all three fixes" digest actually belonged to, because the fix
commit itself edits an in-scope instrument file and moves the identity a
second time). None of the four touched `mos.rs`/`lower.rs` or any
production semantics; all four are documented in
`docs/notes/p037-formal-kernel.md`. `349c7bc`, `40cb9b4` and `2ed4d92` are
kept exactly as committed -- honest records of the instrument and its
first (flawed) `R_B` -- superseded here, not rewritten: `git log` on this
file's path still shows their content.

## Instrument identity

```
75764c81ac49185adad6a02657b373a7453fc03ba337bb61b86d4694bd8d5065
```

Read from each take's own `instrument_identity` field (computed by
`p037_evidence_b.evidence_fields()`, now calling this module's OWN
correctly-scoped `instrument_manifest`/`instrument_identity` over Phase
B's own `INSTRUMENT_PATHS`/`INSTRUMENT_CARVE_OUTS` -- the §10.8c fix) --
not a separate CLI call: unlike `p037_evidence.py identity`,
`p037_evidence_b.py`'s own `identity` subcommand does not print this
digest directly, so the authoritative value is the one each piece of
evidence actually carries. All four takes below agree on it,
byte-for-byte. This differs from the value the first `R_B` recorded
(`04525002af5383fcdda0c4f0d77c9b647cc2c5f6be759b4ec733067013e8a559`) --
expected and confirmed by direct measurement, not assumed: that value was
a2d's instrument identity, mislabeled as Phase B's own (§10.8c).

## Execution profile (M3, identical across all four takes)

- Python: CPython 3.11.15 (main, Mar 3 2026, 09:26:23) [GCC 13.3.0]
- .NET SDK: 8.0.425, runtimes: Microsoft.AspNetCore.App 8.0.31, Microsoft.NETCore.App 8.0.31
- Rust: rustc 1.94.1 (e408947bf 2026-03-25), cargo 1.94.1 (29ea6fb6a 2026-03-24), host x86_64-unknown-linux-gnu
- Platform: Linux / x86_64

Captured verbatim via `python3 scripts/p037_evidence_b.py profile` after
the fourth take (this retake reuses the same qualified M3 environment the
first `R_B` established a few hours earlier in the same session; only the
instrument changed, not the toolchain, so a fresh before/after pair was
not repeated -- the one capture below, cross-checked against the first
`R_B`'s own recorded profile, is the evidence for that):

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

Byte-for-byte identical to the first `R_B`'s own recorded profile (and, in
turn, to `docs/evidence/p037-a2d-baseline-mos-repo.json`'s recorded M2
profile) -- the same physical workspace and toolchain, re-verified rather
than assumed unchanged.

## Machine qualification

Measurement environment `P037_B_MEASUREMENT_M3`, unchanged since B1's own
qualification (this retake re-measures the instrument, not the
environment):

- CPython: pinned to the host interpreter (3.11.15).
- .NET SDK: 8.0.425, installed isolated outside any OS package manager.
- Rust: rustc/cargo 1.94.1.

recipe sha256 (re-hashed at this retake, not copied from the earlier
manifest -- confirmed unchanged):

```
5fe4ece4c24b720f659a49bbc68b8438080c9e4b8ba554ee40f6eea94c66eb26
```

Recipe: `provision.sh`, retained outside this repository at
`/root/p037-a2d-m2-recipe/provision.sh` on the qualified machine. The
environment/toolchain was not changed between the first `R_B` and this
retake.

## Workspace

The same preserved measured workspace checkout root used throughout this
epoch:

```
/home/user/Own.NET
```

## Takes

Four sequential governed takes, each independently `verify`d against the
new T_B before the next was started. None ran concurrently. (The MOS
corpus take's first attempt hit its own timeout and was killed; the
resulting stale population lock, held by a PID confirmed no longer
running, was removed before the take was retried in full -- an
operational hiccup in this session's tooling, not a defect in the
measurement, and not a second concurrent take.)

1. MOS repo snapshot (`--epoch b --source repo`)
2. MOS corpus snapshot (`--epoch b --source corpus`)
3. verdict/python snapshot (`--epoch b --engine python`)
4. verdict/rust snapshot (`--epoch b --engine rust`)

All four takes and verifies exited 0. The checkout was clean at
`a02ccf17d22eaf62c046fb95ba5060e6d66ffeae` before the first take and
remained at that exact commit, clean, after the fourth verify.

| p037-b-baseline-mos-repo.json | `8d33712811f32e75c7d26dceab03a5a7829cf1f39c0c8139b6c647f46781313a` |
| p037-b-baseline-mos-corpus.json | `a26f8801869831afe4e06e15d449b5c4090c56312d4ceda47014b40a09532342` |
| p037-b-baseline-verdict-python.json | `5d7f9490abdbb2a7ca9faf855a9c35b93f3779351a963b6a0128feff4658d95b` |
| p037-b-baseline-verdict-rust.json | `f653d812679363aebea6b7015f1126c7647f75b608c2cf2ad1e57d34f129aa4a` |

Every record above carries, and all four agree on:

- `source_commit`: `a02ccf17d22eaf62c046fb95ba5060e6d66ffeae`
- `population_commit`: `a02ccf17d22eaf62c046fb95ba5060e6d66ffeae`
- `epoch`: `b`
- `environment_id`: `P037_B_MEASUREMENT_M3`
- `dirty`: `false`
- `is_evidence`: `true`
- `instrument_identity`: `75764c81ac49185adad6a02657b373a7453fc03ba337bb61b86d4694bd8d5065`

## Cross-engine parity at baseline

`scripts/p037_mos_snapshot.py` only writes a `cross_engine_mismatches`
key at all when that list is non-empty (`if parity_moved:` -- confirmed
by reading the tool's own source, not assumed from its absence); neither
MOS snapshot below carries the key, and both takes' own console output
recorded `cross-engine mismatches=0` explicitly (82 and 192 documents
respectively) -- reconfirmed directly by comparing the `python-ownlang`/
`rust-own-bridge` recorded documents for equality, not merely by the
key's absence. Python and Rust MOS agree completely at the new T_B. The
verdict snapshots do not have a built-in cross-engine comparator by
design (`p037_verdict_snapshot.py compare` explicitly refuses a
cross-engine pair: "measures the engine, not the change"), so parity was
checked directly: all 192 corpus files carry identical `(line, code,
level)` finding sets and identical exit codes on both engines -- 105
findings each side, 0 mismatches, exactly matching the first `R_B`'s own
numbers. This is the empirical form of the frozen `facts_expectation`
claim (`docs/evidence/p037-b-epoch.json`'s `measurement_policy`): nothing
about the pre-treatment facts or verdict surface moved, on the corrected
instrument any more than on the mislabeled one.

## P-037 conformance baseline at T_B

Both re-run fresh at `a02ccf17d22eaf62c046fb95ba5060e6d66ffeae`, `OWEN_
RUST_CORE` pointed at the qualified `own-cli` release build:

- `python scripts/p037_controls.py --engine both`: `RESULT: all match` (the
  three G-V4 known-false-positive controls and the one legacy-honesty
  control all agree between engines and against the recorded record).
- `python scripts/p037_fact_shapes.py check --engine both`: `RESULT: all 55
  shape(s) match their recorded facts and verdicts`.

Identical results to the first `R_B`'s own recorded conformance state.
Recorded here as the P-037 conformance state at the new T_B, per the B1
brief's own instruction to measure and record it, not to chase or repair
it as part of this baseline.

Run time/date: 2026-09-24, ~00:59-01:35 UTC, operator run.

This commit is evidence-only: it updates exactly five files under
`docs/evidence/` (these four JSON artifacts plus this manifest, all
already tracked from the first `R_B`) and nothing else. No instrument,
treatment, spec, tooling, or CI file is touched. `docs/evidence/p037-b-
epoch.json`'s `named_later.T_B`/`R_B` are not updated by this commit --
that is the naming commit's own, separate act, after this evidence is
itself terminal-green, mirroring exactly how `40cb9b4` preceded `2ed4d92`
the first time.
