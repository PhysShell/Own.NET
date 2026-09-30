# ownership-semantics-lab (research/ownership-semantics-lab-v1, EXPLORATORY)

Research-only fixtures and tooling of the ownership-semantics-lab track. Nothing here is part of a
production test or build; every analyzer change on this branch sits behind an opt-in environment
flag (`OWEN_LAB_NULLINIT`, `OWEN_LAB_NULLGUARD`, `OWEN_LAB_THROWEXIT`) and is byte-identical off.
Records: Own.NET-paperwork `paper-eval/ownership-lab/` (taxonomy, prior-art map, hypothesis register,
probes, discovery protocol and results).

| dir | what |
|---|---|
| `adoption-probe/` | the four fixture variants of the RLC# held-out wrapper (classification probe) |
| `depid/` | LibA/LibB/LibC/App: the runtime-effective dependency identity falsifier |
| `h01/` | F0 (null-guard control), F1 (H-01 null-initialised locals), F2 (H-19 twins) with observed outputs |
| `h09/` | the MVID-pinned row falsifier inputs (consumer, keys) |
| `h16/` | the Z3 symbolic probe and the complementary-guard fixture |
| `h20/` | F3 (throw-exit versus bare return) with observed outputs off/on |
| `witness/` | the runtime-witness generator (`gen.py`), its ten rows and results |
| `discovery/` | the discovery-experiment pipeline scripts (acquire, API surface, fetch, derive, compare, consumers, scan, triage, record) |
| `discovery/records/` | the per-library S1..S8 artefacts of the 22 completed libraries (acquire/identity, API surface, LLM candidates written before bodies, pinned source digests, derivation summary, applied rows, consumer file digests, OFF/KEY scan results), the ledger, the triage file and the witness rows/results |
| `discovery/repros/` | one minimal repro per new finding class with the expected outputs of Own.NET OFF/KEY, IDisposableAnalyzers and CA2000 |

Tools: `frontend/roslyn/OwnSharp.AsmId` (assembly identity facets), `frontend/roslyn/OwnSharp.ApiList`
(public resource-bearing API surface). Scratch paths inside the scripts point at the session
container and are recorded as such.
