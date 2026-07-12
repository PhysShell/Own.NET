# P-022 step 4 (#214) — diagnostics parity, checkpoint 1: frozen fixture + comparison design

> Status: **checkpoint-1 deliverable** (frozen fixture and comparison design,
> *before* the semantic port). This is the first of #214's three review
> checkpoints; the worklist solver + the ownership/lifetime analyses are
> deliberately **not** implemented here — they land at checkpoint 2 after this
> design is reviewed. Follows the #203 CFG-parity ratchet
> (`tests/test_cfg_fixtures.py` + `own-cfg/tests/parity.rs`), one layer up.

## Precondition check (do not freeze an untrustworthy reference)

#214's brief inherits the P-022 rule: freeze the Python reference only if the
latest full oracle remeasure on `main` is clean; if it shows **unexplained
disappearing findings**, do not freeze and do not start the semantic port.

Trace of the evidence on current `main` (`4c5a86b`):

- The latest documented remeasure,
  [`precision-remeasure-2026-07-11.md`](precision-remeasure-2026-07-11.md)
  (measured at `b1ee961`), found a **263-finding unsound over-exemption** in
  ClosedXML: an empty source `XLWorkbook.Dispose()` that `Janitor.Fody`
  IL-weaves real cleanup into at build time was read as a no-op and every
  `XLWorkbook` local exempted. Those disappearing findings were **explained in
  full** in that note (not unexplained), and a 3-site explicit-interface
  coverage gap alongside them.
- They were then **fixed on `main`** by #238 (`0c1c2f3`, "confine the
  empty-Dispose exemption to enumerators — source emptiness is not a runtime
  no-op") plus soundness follow-ups (`0d1411c`, `40756e3`, `607773f`).
- Crucially, those findings lived in the **C# Roslyn extractor** surface (the
  OSS-repo sweep), **not** the `ownlang` core `.own`/OwnIR path — which is the
  exact surface this fixture freezes. The Python reference suite
  (`python tests/run_tests.py`) is **100% green** on `4c5a86b`
  (132/132 analysis, 3000-iter codegen fuzzer clean, CFG/syntax parity in sync).

**Caveat, recorded honestly:** `dotnet` is unavailable in the port environment,
so a *fresh* full extractor remeasure on `4c5a86b` (post-#238) could not be run
to re-confirm the sweep with no new regressions; the latest remeasure that
exists predates the fix. The literal gate ("unexplained disappearing findings")
does not trip — the findings were explained and fixed, and the `.own` reference
frozen here is independently green — but a reviewer who wants the extractor
sweep re-confirmed should run it in a `dotnet`-capable environment before the
semantic port begins. **The freeze here is cheap to revert:** it is a single
regenerable command over the green core, and nothing is built on it until
checkpoint-1 review passes.

## The comparison surface

The frozen contract is `tests/fixtures/diag_parity.json`: for every `.own`
input, the **ordered list of `[line, code]` pairs** the `check` surface emits.
The oracle key is `(path, line, code)` — `path` = the case's input identity, and
each case's list is compared **in emission order**, so list position pins the
deterministic intra-location (same-line, same-code) ordering #214 asks for. No
sorting, no dedup on top of Python's own output (the parity policy forbids
sorting away meaningful duplicates).

- **Authoritative side (Python):** `tests/test_diag_fixtures.py`. It runs the
  *real* `check` surface — exactly `ownlang.__main__._collect` — over the same
  corpus the CFG ratchet sweeps (`corpus/`, `examples/`, `tests/fixtures/`) plus
  seven curated single-file cases whose outcomes are **computed, never
  hand-written**. Regenerate with `python tests/test_diag_fixtures.py --write`;
  the in-suite `run()` (auto-discovered by `tests/run_tests.py`) fails if the
  committed file is stale. Steady state runs zero Rust; the Rust side runs zero
  Python.
- **Replay side (Rust):** `rust/crates/own-diagnostics` provides the verdict
  data types and the `DiagKey`/case-loading harness; `tests/fixture.rs` locks
  the comparison *plumbing* now (the fixture parses into `(name, source,
  expected: Vec<DiagKey>)`, every frozen code is a known `TITLES` entry,
  emission order is preserved). The actual replay — parse → lower → analyse →
  compare `produced == expected` — is a `TODO(#214, checkpoint 2)` in that file,
  waiting on `own-analysis`.

Compared on **code + line only**. Message text, evidence slices and SARIF are
later steps (5) and are deliberately not frozen here; the `own-diagnostics`
types carry the fields (message, subject, resource_kind, evidence) so those
seams are a pure addition, not a reshape.

## What the `.own` surface exercises — and what it cannot (scoping)

`check_module` (the `.own` pipeline) runs **buffer-policy validation +
`check_lifetimes` + per-function `analyze`**. So this fixture pins the
**ownership**, **lifetime/region**, and **buffer-policy** diagnostic families
(OWN001–OWN052 as they arise from source).

The **effects (EFF\*)** and **DI (DI\*)** families are **sidecar analyses the
OwnIR bridge routes facts to** (`ownlang/ownir.py::check_facts` calls
`ownlang/effects.py` and `ownlang/di.py`); `check_module` never invokes them, so
**no `.own` input exercises them**. #214 still asks to port all four analyses to
`own-analysis`, and that stands — but their end-to-end *diagnostic* parity needs
OwnIR **fact** fixtures flowing through `own-bridge` (migration step 6), which is
out of #214's `.own`-corpus fixture scope. Concretely, at checkpoints 2–3:

- ownership + lifetime parity is proven by this `.own` fixture (the four-analysis
  order in #214 still holds: ownership first, then lifetime);
- the ported effects/DI analyses are validated at the analysis level by
  curated unit tests (lattice laws, transfer functions), with full
  fixture-backed diagnostic parity deferred to the `own-bridge` step that feeds
  them facts.

This is surfaced explicitly rather than papered over, per the parity policy
("never weaken compared fields / map multiple Rust diagnostics to one code").

## Preserved Python quirk — the designated future issue

`_collect` maps a **lex/parse failure to a single synthetic `OWN020`** at the
error line:

```python
except (ParseError, LexError) as e:
    line = getattr(e, "line", 0)
    return [Diagnostic("OWN020", str(e).split(": ", 1)[-1], line)], None
```

`OWN020`'s title is *"unsupported construct (out of scope for the MVP)"* — so a
plain **syntax error** is reported under the "unsupported construct" code, not a
dedicated parse-error code. This is mildly suspicious (a malformed token is not
an "unsupported construct"), but it is the reference behaviour and the Rust
`check` surface **must match it** (emit `OWN020` at the error line). The curated
case `curated_parse_error_is_own020` pins it.

Per #214's guardrail ("if a Python behaviour looks like a bug mid-port, do NOT
fix it in Rust; note it and keep parity — a deliberate divergence is a separate,
Python-first change"), this is **matched, not fixed here**, and recorded as the
designated **future issue**: *"`check` reports syntax/lex errors under OWN020
('unsupported construct') rather than a dedicated parse-error diagnostic code."*
Any change is Python-first and independently reviewed; it must not be smuggled in
under the parity port.

## Deliverables in this checkpoint

| Artifact | Path |
| --- | --- |
| Python fixture generator (authoritative) | `tests/test_diag_fixtures.py` |
| Frozen golden set (69 cases, 66 `(line,code)` pairs) | `tests/fixtures/diag_parity.json` |
| Verdict data types (data-only port of `diagnostics.py`) | `rust/crates/own-diagnostics/src/diagnostic.rs` |
| Comparison harness plumbing + replay TODO | `rust/crates/own-diagnostics/tests/fixture.rs` |
| Architecture DAG edge test (`cargo metadata`) | `rust/crates/own-diagnostics/tests/dag.rs` |
| Suite wiring | auto-discovered by `tests/run_tests.py` |

Regenerate the fixture: **`python tests/test_diag_fixtures.py --write`** (the one
documented explicit command; a stale file fails the suite).

## Explicitly NOT done here (checkpoint boundary)

The generic worklist solver, the `Lattice`/`Analysis` traits, and any domain
analysis (ownership/lifetime/effect/DI) — those are checkpoint 2 (generic solver
+ ownership parity) and checkpoint 3 (full-analysis parity), each with its own
review. `own-analysis` is not yet a workspace member. Evidence/SARIF parity
(step 5) and the effects/DI fact-fixture surface (step 6) are later still.
