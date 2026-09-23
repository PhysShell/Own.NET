# P-037 Phase B / B1 baseline manifest (R_B)

epoch: `b`

T_B (terminal-green, the measurement-instrument head): `349c7bcf456bdd33ce3efe7a19da43790c186145`

population_commit (every take): `349c7bcf456bdd33ce3efe7a19da43790c186145`

environment: `P037_B_MEASUREMENT_M3`

This is a NEW measurement environment for a NEW instrument epoch. It is not
`P037_A2D_MEASUREMENT_M2` by another name -- M2's own records (R_D, D_after)
stay historical a2d evidence, neither retaken nor a control of M3. No a2/a2d
evidence is the baseline of Phase B; the a2d T/R/S records are historical
predecessors only and are not retaken, compared, or treated as a control
here (`docs/evidence/p037-b-epoch.json`'s own `predecessor`/`environment`
sections state this precisely).

## Instrument identity

```
04525002af5383fcdda0c4f0d77c9b647cc2c5f6be759b4ec733067013e8a559
```

Read from each take's own `instrument_identity` field (computed by
`p037_evidence_b.evidence_fields()` from `p037_evidence.instrument_manifest`/
`_manifest_digest` over Phase B's own `INSTRUMENT_PATHS`/`INSTRUMENT_
CARVE_OUTS`) -- not a separate CLI call: unlike `p037_evidence.py identity`,
`p037_evidence_b.py`'s own `identity` subcommand does not print this digest
directly, so the authoritative value is the one each piece of evidence
actually carries. All four takes below agree on it, byte-for-byte.

## Execution profile (M3, identical across all four takes)

- Python: CPython 3.11.15 (main, Mar 3 2026, 09:26:23) [GCC 13.3.0]
- .NET SDK: 8.0.425, runtimes: Microsoft.AspNetCore.App 8.0.31, Microsoft.NETCore.App 8.0.31
- Rust: rustc 1.94.1 (e408947bf 2026-03-25), cargo 1.94.1 (29ea6fb6a 2026-03-24), host x86_64-unknown-linux-gnu
- Platform: Linux / x86_64

Captured verbatim via `python3 scripts/p037_evidence_b.py profile` immediately
before the first take, and re-captured after the fourth take:

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

Byte-for-byte identical to `docs/evidence/p037-a2d-baseline-mos-repo.json`'s
own recorded M2 profile -- expected and stated as such in
`docs/evidence/p037-b-epoch.json`'s `environment.qualification`: M3 is a
genuine requalification of M2's exact toolchain, on the same physical
workspace, not an independent machine claim.

## Machine qualification

Measurement environment `P037_B_MEASUREMENT_M3`, requalified rather than
reprovisioned:

- CPython: pinned to the host interpreter (3.11.15) -- reverified byte-for-
  byte against M2's own recorded profile.
- .NET SDK: 8.0.425, installed isolated outside any OS package manager --
  same reverification.
- Rust: rustc/cargo 1.94.1, exact commit hashes equal to M2's recorded
  profile -- same reverification.

recipe sha256 (identical to M2's, independently re-hashed at B1 time, not
copied from the old manifest):

```
5fe4ece4c24b720f659a49bbc68b8438080c9e4b8ba554ee40f6eea94c66eb26
```

Recipe: `provision.sh`, retained outside this repository at
`/root/p037-a2d-m2-recipe/provision.sh` on the qualified machine. M3 reuses
M2's exact recipe because it independently requalified byte-for-byte, per
`docs/evidence/p037-b-epoch.json`'s own `environment.m2_rule`: M2 takes
nothing for this epoch and is not a control of M3; this is a new epoch's own
environment record, never a silent inheritance. The environment/toolchain
was not changed after the first governed take began.

## Workspace

The same preserved measured workspace checkout root M2 used, reused here
because the toolchain on it was independently reverified, not assumed:

```
/home/user/Own.NET
```

## Takes

Four sequential governed takes, each independently `verify`d against T_B
before the next was started. None ran concurrently.

1. MOS repo snapshot (`--epoch b --source repo`)
2. MOS corpus snapshot (`--epoch b --source corpus`)
3. verdict/python snapshot (`--epoch b --engine python`)
4. verdict/rust snapshot (`--epoch b --engine rust`)

All four takes and verifies exited 0. The checkout was clean at
`349c7bcf456bdd33ce3efe7a19da43790c186145` before the first take and remained
at that exact commit, clean, after the fourth verify.

| p037-b-baseline-mos-repo.json | `3abb0a25ca0c60efc2882d5d8695517e65ce53398370f7d97d6366dea5ac0be7` |
| p037-b-baseline-mos-corpus.json | `ebbb84d9e45a761eec5260dad7143f8b625b4f68b832f97d295d5608ef06f2f0` |
| p037-b-baseline-verdict-python.json | `5668d59f9df041841c7d40a26b5fe6c56b7e0bc385297d82b84e517657143a43` |
| p037-b-baseline-verdict-rust.json | `60ea9b11b060045f632e172971c1ffae511052e614f216db7db0a013cdd84d6a` |

Every record above carries, and all four agree on:

- `source_commit`: `349c7bcf456bdd33ce3efe7a19da43790c186145`
- `population_commit`: `349c7bcf456bdd33ce3efe7a19da43790c186145`
- `epoch`: `b`
- `environment_id`: `P037_B_MEASUREMENT_M3`
- `dirty`: `false`
- `is_evidence`: `true`
- `instrument_identity`: `04525002af5383fcdda0c4f0d77c9b647cc2c5f6be759b4ec733067013e8a559`

## Cross-engine parity at baseline

The MOS snapshots (repo and corpus) each record their own `cross_engine_
mismatches` field internally: empty on both, over 82 and 192 documents
respectively -- Python and Rust MOS agree completely at T_B. The verdict
snapshots do not have a built-in cross-engine comparator by design
(`p037_verdict_snapshot.py compare` explicitly refuses a cross-engine pair:
"measures the engine, not the change"), so parity was checked directly: all
192 corpus files carry identical `(line, code, level)` finding sets and
identical exit codes on both engines -- 105 findings each side, 0
mismatches. This is the empirical form of the frozen `facts_expectation`
claim (`docs/evidence/p037-b-epoch.json`'s `measurement_policy`): nothing
about the pre-treatment facts or verdict surface moved.

## P-037 conformance baseline at T_B

Both re-run fresh at `349c7bcf456bdd33ce3efe7a19da43790c186145`, `OWEN_RUST_
CORE` pointed at the qualified `own-cli` release build:

- `python scripts/p037_controls.py --engine both`: `RESULT: all match` (the
  three G-V4 known-false-positive controls and the one legacy-honesty
  control all agree between engines and against the recorded record).
- `python scripts/p037_fact_shapes.py check --engine both`: `RESULT: all 55
  shape(s) match their recorded facts and verdicts`.

Recorded here as the P-037 conformance state at T_B, per the B1 brief's own
instruction to measure and record it, not to chase or repair it as part of
this baseline.

Run time/date: 2026-09-23, ~19:50-20:35 UTC, operator run (the mos-repo and
mos-corpus takes were first measured at the interim head `d5f9134`, then
discarded and re-measured in full at `349c7bc` once that head's own
allowlist-completeness fix was confirmed terminal-green; the times above are
for the accepted run).

This commit is evidence-only: it adds exactly five files under
`docs/evidence/` (these four JSON artifacts plus this manifest) and nothing
else. No instrument, treatment, spec, tooling, or CI file is touched.
