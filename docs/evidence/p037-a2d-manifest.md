# P-037 a2d cumulative evidence (evidence)

epoch = `a2d` · environment = `P037_A2D_MEASUREMENT_M2` · measurement policy
fact_diff = `unchanged`
T = `44b405c2003b1d68965fe6346c2506d51ed52def` (population)
R = `91a267991ba82648ecf4abd472e7ff24c39edab1` (baseline evidence)
treatment = `4ba49c14d8777dc94554e5ec4208a9607fb89908` (measurement head `4ba49c14d8777dc94554e5ec4208a9607fb89908`)

Result: FACTS UNCHANGED · MOS UNCHANGED · VERDICTS UNCHANGED · accepted=True
· is_evidence=True · state=accepted · eligibility all met
Production-diff gate (T_D -> treatment): WITHIN_ALLOWLIST (allowed 34,
violations 0, gate blob `0b1a5e11ca0e4d35105023b865cf12f6c366b9fe`)

## Four governed takes at the treatment, population held at T

| artifact | sha256 | compare against R |
|---|---|---|
| p037-a2d-after-mos-repo.json | `4f084383f40a69891b3327499e88d145750681f558833fbb2d7ee2f9fe3f5bce` | verdict: UNCHANGED — source=repo, population=44b405c2003b, documents=1, facts_moved=0, python_mos_moved=0, rust_mos_moved=0, after_parity_moved=0 |
| p037-a2d-after-mos-corpus.json | `e5a3d185dc85f52b5769eb3c5a44777806f27cec33836ac7ef00d924ba43b6e9` | verdict: UNCHANGED — source=corpus, population=44b405c2003b, documents=137, facts_moved=0, python_mos_moved=0, rust_mos_moved=0, after_parity_moved=0 |
| p037-a2d-after-verdict-python.json | `a4601b11cbf9398042b59be53f91751fa9ca1f6187c9628db1ae9d24f5a77ad7` | verdict: UNCHANGED — 137 file(s), no verdict moved at level=verdict; all: UNCHANGED — 137 file(s), no verdict moved at level=all |
| p037-a2d-after-verdict-rust.json | `e6150987bcde281527452229bbd1615fc41a007d84143b93684a9556bbb8f0aa` | verdict: UNCHANGED — 137 file(s), no verdict moved at level=verdict; all: UNCHANGED — 137 file(s), no verdict moved at level=all |

## Fact documents

changed=0 unchanged=138 unexpected=0
(every fact document identical between before and after)

## Layer differential (per-document digests, both engines)

| engine | lowered | summaries | verdicts |
|---|---|---|---|
| python mismatches | 0 | 0 | 0 |
| rust mismatches | 0 | 0 | 0 |
| python/rust disagreements (treatment) | 0 | 0 | 0 |

Verdict-snapshot cross-engine disagreements: {"verdict": 0, "all": 0, "exit": 0}

Cumulative artifact: p037-a2d-cumulative.json sha256 `5aeaf5e149f26a5467f52896256cff2e16e3e5e5c4c9f11e2d85bd8aaa29cd0b`
Evidence orchestrator: commit `44b405c2003b1d68965fe6346c2506d51ed52def`, blob `af6674b1cf29c3e6d4925db9fcf57fede3a4fa37`,
sha256 `d8a2cbde007a9aaaf9cb0495e7dec5ec18ac09ffe2dd89bdf39b6715996518bb`, pinned to `44b405c2003b1d68965fe6346c2506d51ed52def`
Measured checkout: head `4ba49c14d8777dc94554e5ec4208a9607fb89908`, authenticated before import
Instrument identity: `31deed777db8ffb49f2eeacf1c3bcfe9742b77a6bd5509951c5ba35224cd40b5` over 127 file(s)
(roots minus carve-outs ["ownlang/ownir.py", "rust/crates/own-ir/"]), identical at T_D, R_D and the
treatment
