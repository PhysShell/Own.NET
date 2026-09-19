# P-037 A2 baseline manifest

Terminal-green SHA T: `4a8e6582e10222403cd40adc9e95db7e0228a1c2`

Four sequential baseline snapshots taken at T in measurement environment
`P037_A2_MEASUREMENT_M1`, each independently `verify`d against T before the
next was taken.

| artifact | sha256 |
|---|---|
| p037-a2-baseline-mos-repo.json | `bd07e87fee7c5d9607acd3c267fec39424dee1e51662a7bba1e4949c7c5837dd` |
| p037-a2-baseline-mos-corpus.json | `49f788f961b46f7884cde5bb06e2d35525e8ce27731d98bb5588dc550478db0b` |
| p037-a2-baseline-verdict-python.json | `04c2fd6c75493bf90e36ac0c6c8acfbf7e692ab9a20a9d3a5591eb9be5be2d36` |
| p037-a2-baseline-verdict-rust.json | `b9271bf7c4de111d5632a544f8d6d0710a6612aa36f682ea3a2b29dda71ac78e` |

Execution profile (identical across all four takes, and identical before vs.
after the whole sequence):

- Python: CPython 3.11.15 (main, Sep 19 2026, 00:18:08) [GCC 16.1.1 20260625]
- .NET SDK: 8.0.425, runtimes: Microsoft.AspNetCore.App 8.0.31, Microsoft.NETCore.App 8.0.31
- Rust: rustc 1.94.1 (e408947bf 2026-03-25), cargo 1.94.1 (29ea6fb6a 2026-03-24), host x86_64-unknown-linux-gnu
- Platform: Linux / x86_64

Measurement environment identity: `P037_A2_MEASUREMENT_M1`, provisioned as an
isolated toolchain directory (no container runtime available on the VPS);
provisioning recipe `recipe/provision.sh` sha256
`18fcc8f20f4032e73813a2f215f9d7440d2a7f83e4325b818df576f4ee3ad0be`, retained
outside this repository.

Taken: 2026-09-19 (UTC), operator run.

This commit is evidence-only: it adds files under `docs/evidence/` and
nothing else. No instrument, treatment, spec, or CI file is touched.
