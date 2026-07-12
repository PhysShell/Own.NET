#!/usr/bin/env python3
"""Fact-level differential parity for the effect (EFF001) and DI (DI001-005)
analyses (P-022 step 4, issue #214).

These two families are OwnIR-fact sidecar analyses — the bridge feeds them facts,
so there is no `.own` surface. Python remains the reference: this generator
builds normalized effect/DI **fact inputs** and freezes the expected
`(path, line, code)` verdicts (computed by the *real* `ownlang.effects` /
`ownlang.di` finders plus the bridge's primary-anchor selection) into
`tests/fixtures/di_eff_fact_parity.json`. The Rust side
(`rust/crates/own-analysis/tests/fact_parity.rs`) deserializes the same facts,
runs its ported analyses, and must reproduce the exact ordered verdict list with
**zero Python**.

The primary anchor matches the bridge (`ownlang/ownir.py`):

* DI001/DI002/DI003 → the singleton **registration** site;
* DI004 → the **root-resolution call site** of the entry type (registration
  fallback when unknown) — `_di004_primary`;
* DI005 → the **field-store site** of the cached entry (registration fallback)
  — `_di005_primary`;
* EFF001 → the effect's own `(file, line)`.

Run:  python tests/test_di_eff_fact_parity.py            (verify)
      python tests/test_di_eff_fact_parity.py --write    (regenerate)
      python tests/run_tests.py                          (runs it as part of the suite)
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.di import (
    Service,
    find_captive_dependencies,
    find_captured_transient_disposables,
    find_explicit_root_resolutions,
    find_scope_cached_captives,
    find_weak_captive_dependencies,
)
from ownlang.effects import Binding, Effect, find_effect_storms

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "di_eff_fact_parity.json")


# ---- effect fact cases -------------------------------------------------------

def _effect_from_json(e: dict) -> Effect:
    return Effect(
        component=e["component"],
        deps=tuple(e["deps"]),
        io=e["io"],
        bindings=tuple(
            Binding(name=b["name"], init=b["init"], refs=tuple(b.get("refs", [])),
                    line=b.get("line", 0))
            for b in e.get("bindings", [])
        ),
        file=e.get("file", "?"),
        line=e.get("line", 0),
    )


def _bind(name: str, init: str, refs: list[str] | None = None, line: int = 1) -> dict:
    return {"name": name, "init": init, "refs": refs or [], "line": line}


def _eff(component: str, deps: list[str], io: bool, bindings: list[dict],
         file: str, line: int) -> dict:
    return {"component": component, "deps": deps, "io": io,
            "bindings": bindings, "file": file, "line": line}


_EFFECT_CASES: list[tuple[str, list[dict]]] = [
    ("fresh_object_storm",
     [_eff("A", ["opts"], True, [_bind("opts", "object")], "A.tsx", 10)]),
    ("memoised_clean",
     [_eff("A", ["opts"], True, [_bind("opts", "memo")], "A.tsx", 10)]),
    ("no_io_clean",
     [_eff("A", ["opts"], False, [_bind("opts", "object")], "A.tsx", 10)]),
    ("derivation_chain",
     [_eff("A", ["c"], True,
           [_bind("a", "object"), _bind("b", "ident", ["a"]),
            _bind("c", "ident", ["b"])], "A.tsx", 12)]),
    ("opaque_call_unknown",
     [_eff("A", ["x"], True, [_bind("x", "call")], "A.tsx", 10)]),
    ("plain_identifier_stable",
     [_eff("A", ["props.id"], True, [], "A.tsx", 10)]),
    ("identity_cycle_safe",
     [_eff("A", ["a"], True,
           [_bind("a", "ident", ["b"]), _bind("b", "ident", ["a"])], "A.tsx", 10)]),
    # multi-file ordering + equal lines: two storms on the SAME line in DIFFERENT
    # files must sort by file first (b.tsx before z.tsx).
    ("multi_file_equal_lines",
     [_eff("Z", ["o"], True, [_bind("o", "object")], "z.tsx", 7),
      _eff("B", ["o"], True, [_bind("o", "array")], "b.tsx", 7)]),
]


# ---- DI fact cases -----------------------------------------------------------

def _service_from_json(s: dict) -> Service:
    return Service(
        name=s["name"],
        lifetime=s["lifetime"],
        deps=tuple(s.get("deps", [])),
        disposable=s.get("disposable", False),
        file=s.get("file", "?"),
        line=s.get("line", 0),
        weak_deps=tuple(s.get("weak_deps", [])),
        root_resolves=tuple(s.get("root_resolves", [])),
        root_resolve_sites=tuple(tuple(t) for t in s.get("root_resolve_sites", [])),
        scope_cached=tuple(s.get("scope_cached", [])),
        scope_cache_sites=tuple(tuple(t) for t in s.get("scope_cache_sites", [])),
    )


def _svc(name: str, lifetime: str, file: str, line: int, **kw) -> dict:
    d = {"name": name, "lifetime": lifetime, "file": file, "line": line}
    d.update(kw)
    return d


_DI_CASES: list[tuple[str, list[dict]]] = [
    ("di001_direct",
     [_svc("App", "singleton", "reg.cs", 5, deps=["Db"]),
      _svc("Db", "scoped", "reg.cs", 6)]),
    ("di001_transitive",
     [_svc("App", "singleton", "reg.cs", 5, deps=["Mid"]),
      _svc("Mid", "transient", "reg.cs", 6, deps=["Db"]),
      _svc("Db", "scoped", "reg.cs", 7)]),
    ("di001_inner_singleton_not_double_reported",
     [_svc("A", "singleton", "reg.cs", 5, deps=["B"]),
      _svc("B", "singleton", "reg.cs", 6, deps=["Db"]),
      _svc("Db", "scoped", "reg.cs", 7)]),
    ("di001_duplicate_scoped_reported_once",
     [_svc("App", "singleton", "reg.cs", 5, deps=["M1", "M2"]),
      _svc("M1", "transient", "reg.cs", 6, deps=["Db"]),
      _svc("M2", "transient", "reg.cs", 7, deps=["Db"]),
      _svc("Db", "scoped", "reg.cs", 8)]),
    ("di_cycle_guard",
     [_svc("App", "singleton", "reg.cs", 5, deps=["T"]),
      _svc("T", "transient", "reg.cs", 6, deps=["T", "Db"]),
      _svc("Db", "scoped", "reg.cs", 7)]),
    ("di_unknown_lifetime_ignored",
     [_svc("App", "singleton", "reg.cs", 5, deps=["Mystery", "Db"]),
      _svc("Mystery", "prototype", "reg.cs", 6),  # unknown lifetime -> ignored
      _svc("Db", "scoped", "reg.cs", 7)]),
    ("di002_weak",
     [_svc("App", "singleton", "reg.cs", 5, weak_deps=["Db"]),
      _svc("Db", "scoped", "reg.cs", 6)]),
    ("di003_transient_disposable",
     [_svc("App", "singleton", "reg.cs", 5, deps=["Conn"]),
      _svc("Conn", "transient", "reg.cs", 6, disposable=True)]),
    ("di004_direct_call_site_anchor",
     [_svc("App", "singleton", "reg.cs", 5, root_resolves=["Conn"],
           root_resolve_sites=[["Conn", "call.cs", 42]]),
      _svc("Conn", "transient", "reg.cs", 6, disposable=True)]),
    ("di004_transitive_disposable_entry_call_site",
     [_svc("App", "singleton", "reg.cs", 5, root_resolves=["Mid"],
           root_resolve_sites=[["Mid", "call.cs", 42]]),
      _svc("Mid", "transient", "reg.cs", 6, deps=["Conn"]),
      _svc("Conn", "transient", "reg.cs", 7, disposable=True)]),
    ("di005_direct_cache_site_anchor",
     [_svc("App", "singleton", "reg.cs", 5, scope_cached=["Db"],
           scope_cache_sites=[["Db", "store.cs", 50]]),
      _svc("Db", "scoped", "reg.cs", 6)]),
    ("di005_transitive_scoped_entry_cache_site",
     [_svc("App", "singleton", "reg.cs", 5, scope_cached=["Mid"],
           scope_cache_sites=[["Mid", "store.cs", 50]]),
      _svc("Mid", "transient", "reg.cs", 6, deps=["Db"]),
      _svc("Db", "scoped", "reg.cs", 7)]),
    ("di_multi_file_ordering",
     [_svc("A2", "singleton", "z.cs", 3, deps=["Db2"]),
      _svc("Db2", "scoped", "z.cs", 4),
      _svc("A1", "singleton", "a.cs", 9, deps=["Db1"]),
      _svc("Db1", "scoped", "a.cs", 10)]),
]


# ---- bridge primary-anchor selection (ownir._di004_primary/_di005_primary) ---

def _di001_2_3_primary(c) -> tuple[str, int]:
    return (c.file, c.line)


def _di004_primary(c) -> tuple[str, int]:
    if getattr(c, "resolved_line", 0) >= 1:
        return (c.resolved_file, c.resolved_line)
    return (c.file, c.line)


def _di005_primary(c) -> tuple[str, int]:
    if getattr(c, "cached_line", 0) >= 1:
        return (c.cached_file, c.cached_line)
    return (c.file, c.line)


def _di_expected(services: list[Service]) -> list[list[object]]:
    """Every DI verdict as [file, line, code], sorted by (file, line, code) — the
    bridge's combined DI finding order after its final sort."""
    rows: list[tuple[str, int, str]] = []
    for c in find_captive_dependencies(services):
        f, ln = _di001_2_3_primary(c)
        rows.append((f, ln, "DI001"))
    for c in find_captured_transient_disposables(services):
        f, ln = _di001_2_3_primary(c)
        rows.append((f, ln, "DI003"))
    for c in find_weak_captive_dependencies(services):
        f, ln = _di001_2_3_primary(c)
        rows.append((f, ln, "DI002"))
    for c in find_explicit_root_resolutions(services):
        f, ln = _di004_primary(c)
        rows.append((f, ln, "DI004"))
    for c in find_scope_cached_captives(services):
        f, ln = _di005_primary(c)
        rows.append((f, ln, "DI005"))
    rows.sort(key=lambda r: (r[0], r[1], r[2]))
    return [[f, ln, code] for (f, ln, code) in rows]


def _effect_expected(effects: list[Effect]) -> list[list[object]]:
    """Every EFF001 verdict as [file, line, "EFF001"] in finder order
    (sorted by (file, line, dep))."""
    return [[s.file, s.line, "EFF001"] for s in find_effect_storms(effects)]


def build() -> dict[str, object]:
    effect_cases = []
    for name, facts in _EFFECT_CASES:
        effects = [_effect_from_json(e) for e in facts]
        effect_cases.append(
            {"name": name, "effects": facts, "expected": _effect_expected(effects)})
    di_cases = []
    for name, facts in _DI_CASES:
        services = [_service_from_json(s) for s in facts]
        di_cases.append(
            {"name": name, "services": facts, "expected": _di_expected(services)})
    return {
        "comment": (
            "GENERATED by tests/test_di_eff_fact_parity.py --write; do not edit. "
            "Python (ownlang.effects / ownlang.di) is authoritative; "
            "rust/crates/own-analysis/tests/fact_parity.rs replays the same facts "
            "and must reproduce the (file, line, code) verdicts exactly (#214)."
        ),
        "effect_cases": effect_cases,
        "di_cases": di_cases,
    }


def _render(data: dict[str, object]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def run() -> int:
    expected = _render(build())
    if not os.path.exists(FIXTURE):
        print(f"FAIL: {FIXTURE} missing; regenerate with "
              f"'python tests/test_di_eff_fact_parity.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL: {FIXTURE} is stale (a finder or the anchor rule changed); "
              f"regenerate with 'python tests/test_di_eff_fact_parity.py --write' "
              f"and re-run the Rust side (cd rust && cargo test)")
        return 1
    data = json.loads(actual)
    n_eff = sum(len(c["expected"]) for c in data["effect_cases"])
    n_di = sum(len(c["expected"]) for c in data["di_cases"])
    print(f"DI/effect fact parity OK: {len(data['effect_cases'])} effect cases "
          f"({n_eff} verdicts), {len(data['di_cases'])} DI cases ({n_di} verdicts) "
          f"verified in sync")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
