#!/usr/bin/env python3
"""
Metamorphic testing for the Own.NET OwnIR bridge (`check_facts`) — analyzer QA.

The sibling of `scripts/metamorphic.py`, one level down: instead of mutating `.own`
source it mutates the **OwnIR facts** (the JSON the C# extractor emits) and asserts
the bridge's diagnostics are invariant. The facts are *sets of records* — components,
their resources, DI services, contracts — so reordering them, or consistently
renaming an identifier, cannot change *which* leaks exist. If `check_facts`'s
verdict moves, the bridge is order/name-sensitive where it must not be. Higher
signal than the core harness: the bridge carries the incidental complexity (the DI
captive-dependency graph, finding dedup, source-lifetime tiering).

Sound transforms (v1), each meaning-preserving:
  - **reverse**: reverse a list of records — the top-level component/service/function
    lists, a component's resource list, a service's deps. Independent records commute.
  - **rename**: consistently rename a component/service identifier everywhere it
    appears as a full string value (references in `deps`/`source_type`/… move with
    it) — alpha-equivalence over the fact graph.

Compared on the **multiset of diagnostic codes** (not lines — same reasoning as the
core harness: a record's line is intrinsic, but order/name must not move a *code*).

dotnet-free: drives the same bridge (`ownlang.ownir.check_facts`) the CLI uses.

Usage:
  metamorphic_facts.py <file-or-dir> ...   # sweep *.facts.json; report non-invariance
  metamorphic_facts.py --selftest
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ownlang.ownir import OwnIRError, check_facts

if TYPE_CHECKING:
    from collections.abc import Iterator

_LIST_KEYS = ("components", "services", "functions")


def code_key(facts: dict[str, Any]) -> tuple[str, ...]:
    """The sorted multiset of diagnostic codes `check_facts` produces — the property
    a meaning-preserving fact rewrite must not change."""
    return tuple(sorted(d.code for d in check_facts(facts)))


def _strings(node: Any) -> set[str]:
    """Every string value anywhere in the facts (to pick a guaranteed-fresh rename)."""
    if isinstance(node, str):
        return {node}
    if isinstance(node, dict):
        return set().union(set(), *(_strings(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(set(), *(_strings(v) for v in node))
    return set()


def _rename(node: Any, old: str, new: str) -> Any:
    """A deep copy of `node` with every string *equal to* `old` replaced by `new`.
    Exact-match (not substring), so it is a consistent rename of one identifier
    across the whole fact graph — a reference in `deps`/`source_type` moves with it,
    while an unrelated string (a `.cs` file, an event name) is left alone."""
    if isinstance(node, str):
        return new if node == old else node
    if isinstance(node, dict):
        return {k: _rename(v, old, new) for k, v in node.items()}
    if isinstance(node, list):
        return [_rename(v, old, new) for v in node]
    return node


def reverse_variants(facts: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Reverse each list of records: the top-level component/service/function lists,
    each component's resource list, and each service's deps. Records are a set, so
    their order is not meaning."""
    for key in _LIST_KEYS:
        seq = facts.get(key)
        if isinstance(seq, list) and len(seq) > 1:
            v = copy.deepcopy(facts)
            v[key] = list(reversed(v[key]))
            yield (f"reverse {key}", v)
    comps = facts.get("components")
    if isinstance(comps, list):
        for i, c in enumerate(comps):
            subs = c.get("subscriptions") if isinstance(c, dict) else None
            if isinstance(subs, list) and len(subs) > 1:
                v = copy.deepcopy(facts)
                v["components"][i]["subscriptions"] = list(reversed(subs))
                yield (f"reverse components[{i}].subscriptions", v)
    svcs = facts.get("services")
    if isinstance(svcs, list):
        for i, s in enumerate(svcs):
            deps = s.get("deps") if isinstance(s, dict) else None
            if isinstance(deps, list) and len(deps) > 1:
                v = copy.deepcopy(facts)
                v["services"][i]["deps"] = list(reversed(deps))
                yield (f"reverse services[{i}].deps", v)


def _identifiers(facts: dict[str, Any]) -> list[str]:
    """Component + service names — the identifiers safe to consistently rename."""
    out: list[str] = []
    for key in ("components", "services"):
        seq = facts.get(key)
        if isinstance(seq, list):
            out += [r["name"] for r in seq
                    if isinstance(r, dict) and isinstance(r.get("name"), str)]
    return out


def rename_variants(facts: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """One variant per component/service name, consistently renamed to a fresh name
    across the whole fact graph. The verdict must not depend on the identifier."""
    used = _strings(facts)
    for name in _identifiers(facts):
        fresh = f"{name}_mr"
        while fresh in used:
            fresh += "x"
        yield (f"rename {name}->{fresh}", _rename(facts, name, fresh))


_TRANSFORMS = (reverse_variants, rename_variants)


def violations(facts: dict[str, Any]) -> list[str]:
    """Every metamorphic violation for one fact set: a meaning-preserving variant
    whose code multiset differs from the original. Empty == invariant."""
    try:
        base = code_key(copy.deepcopy(facts))
    except OwnIRError:
        return []  # malformed facts are out of scope, not a finding
    out: list[str] = []
    for transform in _TRANSFORMS:
        for label, variant in transform(facts):
            try:
                got = code_key(variant)
            except Exception as e:  # a crash on a valid variant is itself a finding
                out.append(f"{label}: variant raised {type(e).__name__}: {e}")
                continue
            if got != base:
                out.append(f"{label}: base={list(base)} variant={list(got)}")
    return out


def sweep(paths: list[str]) -> int:
    """Run the harness over every *.facts.json under the given files/dirs. Returns a
    0/1 exit status (0 == every fact set invariant)."""
    files: list[Path] = []
    for p in paths:
        pp = Path(p)
        files.extend(sorted(pp.rglob("*.facts.json")) if pp.is_dir() else [pp])
    bad = 0
    for f in files:
        try:
            facts = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"{f}: cannot load ({e})")
            continue
        vs = violations(facts)
        if vs:
            bad += 1
            print(f"\n{f.name}: {len(vs)} violation(s):")
            for v in vs:
                print(f"  - {v}")
    n = len(files)
    print(f"\nmetamorphic-facts: {n - bad}/{n} fact set(s) invariant under "
          f"{len(_TRANSFORMS)} transform class(es).")
    return 1 if bad else 0


def _selftest() -> int:
    fails: list[str] = []
    repo = Path(__file__).resolve().parent.parent

    # 1) Robustness: every committed fact fixture must load and be invariant.
    fix = repo / "tests" / "fixtures" / "ownir"
    files = sorted(fix.rglob("*.facts.json")) if fix.exists() else []
    bad: list[str] = []
    for f in files:
        try:
            facts = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            bad.append(f"{f.name}: load {e}")
            continue
        vs = violations(facts)
        if vs:
            bad.append(f"{f.name}: {vs[0]}")
    if not files:
        fails.append("no .facts.json fixtures found to sweep")
    elif bad:
        fails.append(f"fixtures not all invariant: {len(bad)} file(s), e.g. {bad[0]}")

    # 2) Teeth: the code key must distinguish a leak from a clean run.
    leak = {"module": "M", "components": [{"name": "Vm", "file": "Vm.cs",
            "subscriptions": [{"event": "b.X", "handler": "h", "line": 5, "released": False}]}]}
    clean = {"module": "M", "components": [{"name": "Vm", "file": "Vm.cs",
             "subscriptions": [{"event": "b.X", "handler": "h", "line": 5, "released": True}]}]}
    if code_key(leak) == code_key(clean):
        fails.append("teeth: code key does not distinguish a leak from a clean run")
    if "OWN001" not in code_key(leak):
        fails.append("teeth: expected OWN001 on the leak fixture")

    # 3) The transforms fire on a fact set that admits them, and a two-component +
    #    multi-service (captive-DI) set is invariant under reorder and rename.
    multi = {"module": "M",
             "components": [
                 {"name": "A", "file": "A.cs", "subscriptions": [
                     {"event": "b.X", "handler": "hx", "line": 5, "released": False},
                     {"event": "b.Y", "handler": "hy", "line": 6, "released": False}]},
                 {"name": "B", "file": "B.cs", "subscriptions": [
                     {"event": "b.Z", "handler": "hz", "line": 7, "released": True}]}],
             "services": [
                 {"name": "Sender", "lifetime": "singleton", "file": "S.cs", "line": 1,
                  "deps": ["Db"]},
                 {"name": "Db", "lifetime": "scoped", "file": "S.cs", "line": 2, "deps": []}]}
    if sum(1 for _ in reverse_variants(multi)) < 2:
        fails.append("expected >=2 reverse variants")
    if sum(1 for _ in rename_variants(multi)) < 2:
        fails.append("expected >=2 rename variants")
    if violations(multi):
        fails.append(f"multi-component/service set should be invariant: {violations(multi)}")

    for msg in fails:
        print(f"METAMORPHIC-FACTS SELFTEST FAIL: {msg}")
    total = 6
    print(f"metamorphic-facts selftest: {total - len(fails)}/{total} checks passed "
          f"(swept {len(files)} fixture(s))")
    return 1 if fails else 0


def main(argv: list[str]) -> int:
    if argv == ["--selftest"]:
        return _selftest()
    if not argv or any(a.startswith("-") for a in argv):
        print(__doc__)
        return 2
    return sweep(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
