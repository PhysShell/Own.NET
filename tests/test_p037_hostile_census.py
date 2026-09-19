#!/usr/bin/env python3
"""P-037 A2.2-4: the hostile census and the findings ledger are what they say.

Runs no tool. Pins that the committed corpus/p037-hostile files equal a
regeneration (the generator is the source of truth), that the pairwise
coverage the README claims actually holds over the generated cases, that every
designed verdict uses only frozen vocabulary (the eleven exclusions, the three
site kinds, the three representations), that the named compositions, the
shadowing witnesses and the member-kind probes exist, and that every expected
RED names a finding the ledger classifies by a §10.1 class.
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import p037_hostile_census as census  # noqa: E402

REGISTRY = ROOT / "corpus" / "p037-relevance" / "registry.json"
FINDINGS = ROOT / "corpus" / "p037-relevance" / "oracle_findings.json"
EXPECTED = ROOT / "corpus" / "p037-hostile" / "expected.json"
SITE_KINDS = {"invocation", "object_creation", "delegate_invocation", "constructor_initializer"}
REPRESENTATIONS = {"var", "param", "opaque"}
CLASSES = {"case 1", "case 3", "case 4", "case 5"}

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"ok[{name}]")
    else:
        _failures.append(name)
        print(f"FAIL[{name}]: {detail}")


def run() -> int:
    check("hostile-census-equals-regeneration", census.check() == 0,
          "run `python scripts/p037_hostile_census.py generate`")
    expected: dict[str, Any] = json.loads(EXPECTED.read_text(encoding="utf-8"))
    registry: dict[str, Any] = json.loads(REGISTRY.read_text(encoding="utf-8"))
    ledger: dict[str, Any] = json.loads(FINDINGS.read_text(encoding="utf-8"))
    exclusions = set(registry["exclusions"])
    cases: dict[str, Any] = expected["cases"]

    # Pairwise: every feasible value pair of every factor pair appears in some generated case.
    factors: dict[str, list[str]] = expected["factors"]
    names = list(factors)
    feasible = [t for t in itertools.product(*(factors[n] for n in names))
                if census.feasible(*t)]
    pairs_of = itertools.combinations(range(4), 2)
    idx = list(pairs_of)
    wanted = {((i, t[i]), (j, t[j])) for t in feasible for i, j in idx}
    generated = [tuple(c["composition"][n] for n in names)
                 for c in cases.values() if "composition" in c]
    covered = {((i, t[i]), (j, t[j])) for t in generated for i, j in idx}
    missing = sorted(wanted - covered)
    check("pairwise-coverage-holds", not missing,
          f"{len(missing)} feasible value pair(s) uncovered, e.g. {missing[:3]}")
    check("pairwise-count-recorded", expected["pairwise"]["cases"] == len(generated),
          f"recorded {expected['pairwise']['cases']}, generated {len(generated)}")

    problems: list[str] = []
    for name, c in cases.items():
        if c.get("carrier") not in {"functions", "guarded_functions", "none"}:
            problems.append(f"{name}: carrier {c.get('carrier')!r}")
        for o in c["occurrences"]:
            v = o.get("verdict")
            if v == "captured":
                if o.get("site_kind") not in SITE_KINDS \
                        or o.get("expected") not in REPRESENTATIONS:
                    problems.append(f"{name}: captured occurrence outside the vocabulary: {o}")
                if any(e != "nested_call_result" for e in o.get("enclosing", [])):
                    problems.append(f"{name}: enclosing other than nested_call_result: {o}")
            elif v == "excluded":
                if o.get("explanation") not in exclusions:
                    problems.append(f"{name}: exclusion {o.get('explanation')!r} is not frozen")
            elif v == "not_call_related":
                if not o.get("explanation"):
                    problems.append(f"{name}: not_call_related without a context name")
            elif v == "red":
                if not str(o.get("explanation", "")).startswith("unclassified_"):
                    problems.append(f"{name}: a designed RED must be an unclassified_* kind: {o}")
            else:
                problems.append(f"{name}: verdict {v!r}")
        if c.get("red") and c.get("finding") not in ledger.get("findings", {}):
            problems.append(f"{name}: expects RED but names no classified finding")
        if not c.get("red") and c.get("finding"):
            problems.append(f"{name}: names a finding but expects no RED")
    check("designs-use-frozen-vocabulary", not problems, "; ".join(problems[:8]))

    named = {n for n in cases if not n.startswith("pw-")}
    for prefix, minimum in (("comp-", 7), ("shadow-", 4), ("member-", 7), ("vocab-", 4),
                            ("ext-", 2), ("ctorinit-", 2)):
        have = sorted(n for n in named if n.startswith(prefix))
        check(f"named-cases-{prefix.rstrip('-')}", len(have) >= minimum,
              f"{len(have)} < {minimum}: {have}")
    # A2.2-4R1 repaired F-SHADOW: every shadowing witness is designed green, and the oracle's
    # fact_binds_other_symbol check (a var fact on a same-spelled non-candidate) is what would
    # turn it RED again.
    shadow = [n for n in named if n.startswith("shadow-")]
    check("shadow-witnesses-green-by-symbol",
          len(shadow) >= 4 and all(not cases[n].get("red") for n in shadow),
          f"shadow cases and their expected RED: { {n: cases[n].get('red') for n in shadow} }")

    # Open findings must be classified; an EMPTY open map is the completeness phase's goal
    # (every RED repaired or consciously frozen), reached at A2.2-4R6, and the closed map keeps
    # the record of what was found and how each closed.
    findings: dict[str, Any] = ledger.get("findings", {})
    closed: dict[str, Any] = ledger.get("closed", {})
    bad = [fid for fid, f in list(findings.items()) + list(closed.items())
           if f.get("class") not in CLASSES or not f.get("title") or not f.get("evidence")
           or not f.get("status") or not f.get("red")]
    check("findings-classified", bool(closed) and not bad,
          f"findings lacking a §10.1 class / title / evidence / status / red: {bad}")
    check("closed-findings-say-how",
          all(str(f.get("status", "")).startswith("closed") for f in closed.values()),
          "every closed finding's status must start with `closed`")
    used = {c.get("finding") for c in cases.values() if c.get("finding")}
    used |= {e.get("finding") for e in ledger.get("expected_red", {}).values()}
    check("every-finding-has-a-witness", set(findings) <= used,
          f"findings without a witnessing case or ledger input: {sorted(set(findings) - used)}")
    check("ledger-expected-red-names-findings",
          all(e.get("finding") in findings and e.get("red")
              for e in ledger.get("expected_red", {}).values()),
          "every expected_red entry needs a finding and a non-empty red map")

    if _failures:
        print(f"RESULT: {len(_failures)} hostile-census check(s) failed")
        return 1
    print(f"RESULT: hostile census consistent over {len(cases)} case(s) "
          f"({len(generated)} pairwise + {len(named)} named), "
          f"{len(findings)} classified finding(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
