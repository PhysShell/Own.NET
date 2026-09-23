# P-037 A2.2-D baseline manifest (R_D)

epoch: `a2d`

T_D (terminal-green, fixed by the owner): `44b405c2003b1d68965fe6346c2506d51ed52def`

population_commit (every take): `44b405c2003b1d68965fe6346c2506d51ed52def`

environment: `P037_A2D_MEASUREMENT_M2`

This is a NEW measurement environment for a NEW instrument epoch. It is not
`P037_A2_MEASUREMENT_M1`, and this record is not compatible with, and does
not extend, the retired A2 baseline. No A2 evidence is the baseline of this
epoch; the A2 T/R/S records are historical predecessors only and are not
retaken, compared, or treated as a control here.

## Instrument identity

```
31deed777db8ffb49f2eeacf1c3bcfe9742b77a6bd5509951c5ba35224cd40b5
```

Derived by `python3 scripts/p037_evidence.py identity --commit 44b405c2003b1d68965fe6346c2506d51ed52def`
at T_D, and re-verified as identical on all four takes below.

## Execution profile (M2, identical across all four takes)

- Python: CPython 3.11.15 (main, Mar 3 2026, 09:26:23) [GCC 13.3.0]
- .NET SDK: 8.0.425, runtimes: Microsoft.AspNetCore.App 8.0.31, Microsoft.NETCore.App 8.0.31
- Rust: rustc 1.94.1 (e408947bf 2026-03-25), cargo 1.94.1 (29ea6fb6a 2026-03-24), host x86_64-unknown-linux-gnu
- Platform: Linux / x86_64

Captured verbatim via `python3 scripts/p037_evidence.py profile`:

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

Re-captured after the fourth take and diffed byte-for-byte identical against
the pre-sequence capture above; profile did not drift during the run.

Eligibility checked with the measurement tooling's own rule
(`profiles_consistent` in `scripts/p037_cumulative_evidence.py`): all four
records agree on every execution-profile key they share, and all four share
at least `python`, `dotnet` and `platform`; `verdict-python` correctly omits
`rust` by the instrument's own design (a Python-engine take records no Rust
identity) and that is not a mismatch under the tool's rule.

## Machine qualification

Measurement environment `P037_A2D_MEASUREMENT_M2`, provisioned as an isolated
toolchain (no container runtime available on this host):

- CPython: pinned to the host interpreter, `/usr/bin/python3.11` (3.11.15),
  verified identical under every `python`/`python3` alias resolved from PATH.
- .NET SDK: installed isolated at `/root/p037-a2d-m2-toolchain/dotnet`
  (outside any OS package manager), pinned exact version 8.0.425, wired onto
  PATH via `/usr/local/bin/dotnet`.
- Rust: the pre-existing rustup-managed user toolchain at `/root/.cargo`,
  `/root/.rustup` (not an OS package), rustc/cargo 1.94.1.

recipe sha256:

```
5fe4ece4c24b720f659a49bbc68b8438080c9e4b8ba554ee40f6eea94c66eb26
```

Recipe: `provision.sh`, retained outside this repository at
`/root/p037-a2d-m2-recipe/provision.sh` on the qualified machine. This is a
new recipe for a new environment; it does not have to and does not claim to
equal the retired M1 recipe. The environment/toolchain was not changed after
the first governed take began.

## Workspace

One preserved measured workspace checkout root is used for T_D, R_D, and is
required to be used again for every future a2d treatment/after run (several
recorded fields are path-sensitive):

```
/home/user/Own.NET
```

## Takes

Four sequential governed takes, each independently `verify`d against T_D
before the next was started. None ran concurrently.

1. MOS repo snapshot
2. MOS corpus snapshot
3. verdict/python snapshot
4. verdict/rust snapshot

All four takes and verifies exited 0. The checkout was clean at
`44b405c2003b1d68965fe6346c2506d51ed52def` before the first take and remained
at that exact commit, clean, after the fourth verify.

| p037-a2d-baseline-mos-repo.json | `dfd1b2f60cf2615295ccf32b57d2bed2d7c01c015e2e0bf26efde9dc6b87a9be` |
| p037-a2d-baseline-mos-corpus.json | `df7ef01eac17559c17135fc14f402950358220643019b48bff633c86f0de124e` |
| p037-a2d-baseline-verdict-python.json | `2e61808387439c9c83f7fe170a2e062c2a7bd4763cfc168a7ad55cb8009c7f0f` |
| p037-a2d-baseline-verdict-rust.json | `20b61651d22f6ea4ff86e51ee612abefe53e80f55bbb010c289e617a0d012a26` |

Every record above carries, and all four agree on:

- `source_commit`: `44b405c2003b1d68965fe6346c2506d51ed52def`
- `population_commit`: `44b405c2003b1d68965fe6346c2506d51ed52def`
- `epoch`: `a2d`
- `environment_id`: `P037_A2D_MEASUREMENT_M2`
- `dirty`: `false`
- `is_evidence`: `true`
- `instrument_identity`: `31deed777db8ffb49f2eeacf1c3bcfe9742b77a6bd5509951c5ba35224cd40b5`

Run time/date: 2026-09-23, 01:07-01:26 UTC, operator run.

This commit is evidence-only: it adds exactly five files under
`docs/evidence/` (these four JSON artifacts plus this manifest) and nothing
else. No instrument, treatment, spec, tooling, or CI file is touched.
