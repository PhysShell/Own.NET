# Task — evidence coverage for flow diagnostics

Status: **spec, ready to implement**

Derived from the ADR `AGENTS.execution-surfaces.md` (§3 «Structured evidence»
and §5 «Acceptance criteria»). This is the executable task spec for the first
rung of that document's ladder: wire the already-built-but-idle evidence
machinery so flow diagnostics carry a structured reachability slice. It extends,
and does not replace, `docs/proposals/P-015-reachability-evidence.md`.

## 0. Goal

Make at least 3 flow diagnostics carry a non-empty `Diagnostic.evidence`
(a structured acquire→escape / move→use reachability slice), with a golden test
on the human render. Do **not** change analyzer semantics.

## 1. Scope

**In scope**
- Thread `evidence=` through `_Analyzer.err()`.
- Evidence for 3 concrete codes (see §3).
- A minimal per-RID provenance addition to `State`, solely for the move site
  (§3.3).
- A golden/snapshot test on the human render of evidence.
- README «Where it cheats»: an honest note on merge-point evidence being partial.

**Out of scope (explicitly do not do)**
- A SARIF bridge for `Diagnostic`. Today `build_sarif` exists only for
  `ownir.Finding`; building `Diagnostic → SARIF` is a separate PR. The golden
  test rides the human render — the ADR allows «SARIF **or** human-render».
- `check --show-evidence` / `trace` / query shell / registry — later per the ADR.
- New domain types (`Location`, `OwnershipState`), a second provenance type, or
  string facts — forbidden by the ADR.
- Any refactor of `analysis.py` branching for aesthetics.

## 2. The emit-site change (mandatory foundation)

`analysis.py` — `_Analyzer.err()` gains an optional parameter:

```python
def err(self, code: str, msg: str, line: int,
        subject: str | None = None,
        resource_kind: str | None = None,
        evidence: tuple[Evidence, ...] = ()) -> None:
    if self.silent:
        return
    self.diags.append(Diagnostic(code, msg, line, subject=subject,
                                 resource_kind=resource_kind, evidence=evidence))
```

`evidence` is declared last, so the positional constructor contract
`Diagnostic(code, msg, line, severity, subject, resource_kind)` is preserved
(`evidence` is already the last field of the dataclass). Import `Evidence` into
`analysis.py`. The evidence branch must not do work before the `self.silent`
early-return.

## 3. The three target diagnostics

Class coverage required by acceptance: two from escape/lifetime, one from
use-after-move.

### 3.1 OWN015 — stack-backed buffer escapes function *(escape / lifetime)*

Data is already available; no new bookkeeping. Acquire site is the buffer's
allocation line (`sym.buffer.line`); escape site is the return line.

```python
self.err("OWN015", <msg>, ins.line, subject=subj, evidence=(
    Evidence(line=ins.sym.buffer.line,
             label=f"'{ins.sym.name}' allocated here", role="acquired"),
    Evidence(line=ins.line,
             label="escapes the function by return here", role="escaped"),
))
```

### 3.2 OWN016 — stack-backed buffer moved to longer-lived owner *(escape / lifetime)*

Emitted in `_apply_effect` (`eff == CONSUME`). Same shape: acquire
`sym.buffer.line`, escape `line`, label «consumed by `'{callee}'` here»,
`role="consumed"`.

### 3.3 OWN005 — use / return after move *(use-after-move)*

Emitted from `_state_problem` and the return branch. This one needs the **move
site**, which `State` does not currently record. Minimal addition (the only new
state):

- In `State`: `moved_at: dict[int, int] = field(default_factory=dict)` — RID →
  line where `MOVED` was set.
- Record it wherever `{VarState.MOVED}` is set (`MoveInto` and the consume-like
  transitions): `st.moved_at[st.rid_of(ins.src)] = ins.line`.
- Thread it through `State.copy()`.
- In `join()`: union the map. When a RID is moved on both paths with **different**
  lines, do not fabricate a precise line — keep one and mark the label as
  approximate (see §5). Do **not** add an invariant `assert` like the `loans`
  one: multiple move paths are legitimate here.
- On the OWN005 emit:
  `evidence=(Evidence(line=st.moved_at.get(rid), label="moved here", role="step"),)`
  when present.

> OWN001 (leak, acquire site) is a **stretch**, not part of the mandatory
> minimum: it needs a symmetric `acquired_at` map built the same way as
> `moved_at`. Do it only if in scope.

## 4. Presentation

Nothing to change: `Diagnostic.human()` / `render_pretty()` already print one
`note:` line per step. The default CLI text output surfaces evidence
automatically. Do **not** introduce a `--show-evidence` flag here.

## 5. Merge-point honesty (README)

In README «Where it cheats» (and near the merge-union discussion): add 2–4
sentences — evidence for move/escape is exact on straight-line paths; at a
control-flow merge (state union) the move site may be one of several paths, so
such evidence is marked one-of-N, not exact. «Do not depict precision that isn't
there» (ADR §3.2).

## 6. Tests

New standalone `tests/test_evidence_coverage.py` (repo convention — not pytest),
folded into `tests/run_tests.py` (like `test_gallery` / `test_corpus`):

1. `.own` fixtures triggering OWN015, OWN016, OWN005; run `analyze`; assert each
   `Diagnostic.evidence` is non-empty and that roles/lines match the
   acquire/escape/move sites.
2. Golden human-render snapshot: `Diagnostic.render_pretty()` contains the
   expected `note:` lines in order. The pattern already exists in
   `tests/test_diagnostics.py`.
3. Do not break the «empty-evidence invariant» in `test_diagnostics.py`
   (diagnostics with no evidence still render byte-for-byte as before).

## 7. Gate (hard)

- `python tests/run_tests.py` green; `ruff check .` + `mypy ownlang` clean.
- **No new `# type: ignore`**; do not touch the repo mypy config.
- Do not «simplify» `analysis.py` branches.
- Do not add a second provenance type / string facts / new domain types.

## 8. Acceptance mapping (from ADR §5)

| ADR criterion | How it is met |
| --- | --- |
| ≥3 flow diagnostics with non-empty evidence | OWN015, OWN016, OWN005 |
| ≥1 escape / lifetime / leak | OWN015 (§5.1: lifetime/region escape) + OWN016 |
| ≥1 use-after-move / use-after-release | OWN005 |
| Codes named in the PR body, not «escape» | listed explicitly |
| Golden test on evidence | `test_evidence_coverage.py` human-render snapshot |
| `.ownreport.json` not overloaded | `build_report` untouched |
| gate green, no new ignores | §7 |
| README «Where it cheats» on merge | §5 |

## 9. PR shape

- Type: `feat` (new structured information on diagnostics), or `docs+feat`; name
  the codes **OWN015 / OWN016 / OWN005** explicitly in the PR body.
- Branch: the same feature branch, or a fresh follow-up branch off `main` if the
  ADR PR is already merged (per repo rules a merged PR is not reused).

## 10. Risks / pitfalls

- **`join()` invariant.** The `moved_at` union must not trip the existing
  `loans` / `handle_rid` asserts — it is a separate map added alongside, not
  inside that check.
- **`_sym_by_id` / RID resolution.** Evidence labels take the name via the
  existing `_sym_by_id` index — do not stand up a parallel index.
- **Positional `Diagnostic` constructor.** Only `evidence` goes last; do not
  reorder anything.
- **`silent` mode.** `err()` accumulates nothing when `self.silent` — the
  evidence branch must not do work before that check.
