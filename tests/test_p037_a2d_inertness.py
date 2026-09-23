#!/usr/bin/env python3
"""P-037 A2.2-D: a fast, in-process regression for the inertness control.

The authoritative proof that door-registering `guarded_facts`/
`guarded_functions[]` moved no engine's answer is the existing dual-engine
witness, `scripts/p037_sidecar_inertness.py` (real extractor input, both
engines, `lowered`/`summaries`/`verdicts` compared) — that script must pass
unmodified after this treatment, and it is the result this file supplements,
never replaces.

This file is the cheap, no-`dotnet`, single-engine version for fast local
iteration: one hand-written facts document with a real finding, run through
`load()` and `check_facts()`/`dump_summaries()` four ways --

  stripped        no guarded_facts, no guarded_functions[] at all
  valid           a schema-valid sidecar and orphan, referencing the
                  function's real locals and parameters
  contradictory   a schema-valid sidecar and orphan that is wrong about
                  everything it can be wrong about relative to the actual
                  body (a guard on a parameter ordinal the function does not
                  have, a `var` naming a local that does not exist) -- valid
                  vocabulary, false content
  vocabulary-bad  one arg of an unknown `kind` -- must be REFUSED by load()

`check_facts()`/`dump_summaries()` must agree byte-for-byte across the first
three; the fourth must raise `OwnIRError`.

Run:  python tests/test_p037_a2d_inertness.py
      python tests/run_tests.py                  (in the suite)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.ownir import OwnIRError, check_facts, dump_summaries, load

_failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global _failures
    if ok:
        print(f"ok[{name}]")
    else:
        _failures += 1
        print(f"FAIL[{name}]: {detail}")


def _load(document: dict[str, Any]) -> dict[str, Any]:
    """`load()` takes a path; round-trip through a temp file, as every other
    test of the strict door does."""
    directory = tempfile.mkdtemp(prefix="p037-a2d-inertness-")
    path = os.path.join(directory, "facts.ownir.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(document, f)
        return load(path)
    finally:
        if os.path.exists(path):
            os.unlink(path)
        os.rmdir(directory)


def _base_document() -> dict[str, Any]:
    """One real function: a pooled buffer acquired and never returned (a
    genuine OWN001-family finding), a by-value bool parameter, and a
    disposable-typed second parameter -- enough surface for a sidecar to
    plausibly (or, for the contradictory variant, implausibly) reference."""
    return {
        "ownir_version": 0,
        "module": "M",
        "functions": [{
            "name": "C.M",
            "file": "a.cs",
            "params": [{"name": "flag", "line": 1}],
            "body": [
                {"op": "acquire", "var": "buf", "line": 2, "kind": "pool"},
                {"op": "use", "var": "buf", "line": 3},
            ],
        }],
    }


def _valid_sidecar() -> dict[str, Any]:
    return {
        "version": 1,
        "calls": [{
            "site": {"line": 3, "column": 5}, "statement_line": 3,
            "form": "statement", "callee": None, "sig": None,
            "first_party": False,
            "args": [{"param": 0, "kind": "var", "name": "buf"}],
        }],
        "guards": [{
            "site": {"line": 2, "column": 5}, "param": 0,
            "predicate": "truth", "negated": False,
        }],
    }


def _contradictory_sidecar() -> dict[str, Any]:
    """Schema-valid, and wrong about everything it can be wrong about: a
    guard on parameter ordinal 4 (the function has exactly one, ordinal 0),
    a `var` naming a local the body never declares, and a fabricated
    resolved callee/sig that names nothing in this document."""
    return {
        "version": 1,
        "calls": [{
            "site": {"line": 3, "column": 5}, "statement_line": 3,
            "form": "statement", "callee": "Nowhere.Fabricated", "sig": "",
            "first_party": True,
            "args": [{"param": 0, "kind": "var", "name": "no_such_local"}],
        }],
        "guards": [{
            "site": {"line": 2, "column": 5}, "param": 4,
            "predicate": "is_null", "negated": True,
        }],
    }


def _orphan(sidecar: dict[str, Any]) -> dict[str, Any]:
    return {"name": "C.Orphan", "file": "a.cs", "guarded_facts": sidecar}


def run() -> int:
    stripped = _base_document()

    valid = _base_document()
    valid["functions"][0]["guarded_facts"] = _valid_sidecar()
    valid["guarded_functions"] = [_orphan(_valid_sidecar())]

    contradictory = _base_document()
    contradictory["functions"][0]["guarded_facts"] = _contradictory_sidecar()
    contradictory["guarded_functions"] = [_orphan(_contradictory_sidecar())]

    loaded = {}
    for name, doc in (("stripped", stripped), ("valid", valid),
                      ("contradictory", contradictory)):
        try:
            loaded[name] = _load(doc)
            check(f"load-accepts-{name}", True)
        except OwnIRError as e:
            check(f"load-accepts-{name}", False, str(e))
            return 1

    facts = {name: check_facts(d) for name, d in loaded.items()}
    summaries = {name: dump_summaries(d) for name, d in loaded.items()}

    check("valid-sidecar-moves-no-findings",
          facts["valid"] == facts["stripped"],
          f"{facts['valid']} != {facts['stripped']}")
    check("contradictory-sidecar-moves-no-findings",
          facts["contradictory"] == facts["stripped"],
          f"{facts['contradictory']} != {facts['stripped']}")
    check("valid-sidecar-moves-no-summaries",
          summaries["valid"] == summaries["stripped"],
          "dump_summaries() differed with a valid sidecar present")
    check("contradictory-sidecar-moves-no-summaries",
          summaries["contradictory"] == summaries["stripped"],
          "dump_summaries() differed with a contradictory sidecar present")
    check("stripped-has-a-real-finding-to-move",
          len(facts["stripped"]) > 0,
          "the base document must carry at least one finding, or the "
          "equality checks above are vacuous")

    bad = _base_document()
    bad["functions"][0]["guarded_facts"] = {
        "version": 1,
        "calls": [{
            "site": {"line": 3, "column": 5}, "statement_line": 3,
            "form": "statement", "callee": None, "sig": None,
            "first_party": False, "args": [{"param": 0, "kind": "bogus"}],
        }],
        "guards": [],
    }
    try:
        _load(bad)
        check("load-refuses-unknown-vocabulary", False, "accepted")
    except OwnIRError:
        check("load-refuses-unknown-vocabulary", True)

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print(f"RESULT: guarded-fact door registration moves no finding and no "
          f"summary over {len(facts['stripped'])} baseline finding(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
