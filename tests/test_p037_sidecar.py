#!/usr/bin/env python3
"""P-037 A2.1: the guarded-fact sidecar's vocabulary is ONE vocabulary.

Three places spell it: the JSON Schema (`spec/ownir.schema.json`), the producer
(`frontend/roslyn/OwnSharp.Extractor/Program.cs`, the closed sets its
self-check validates against) and the prose (`spec/OwnIR.md` §5.2). The core is
zero-dependency, so documents are not validated against the schema here; the
spellings are pinned against each other instead, the way tests/test_ownir.py
pins the resource-kind and flow-op enums. A kind added to the producer without
the schema, or to the schema without the producer, reddens this build.

Run:  python tests/test_p037_sidecar.py
      python tests/run_tests.py            (in the suite)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "spec" / "ownir.schema.json"
EXTRACTOR = ROOT / "frontend" / "roslyn" / "OwnSharp.Extractor" / "Program.cs"
PROSE = ROOT / "spec" / "OwnIR.md"

failures = 0


def check(name: str, condition: bool, detail: str) -> None:
    global failures
    if condition:
        print(f"ok[{name}]")
    else:
        failures += 1
        print(f"FAIL[{name}]: {detail}")


def csharp_set(source: str, field: str) -> set[str]:
    """The string literals of `static readonly HashSet<string> <field> = new(...) {...};`."""
    pattern = rf"HashSet<string> {field} = new\(StringComparer\.Ordinal\)\s*\{{([^}}]*)\}}"
    m = re.search(pattern, source)
    if not m:
        return set()
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def main() -> int:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    defs = schema.get("$defs", {})
    source = EXTRACTOR.read_text(encoding="utf-8")
    prose = PROSE.read_text(encoding="utf-8")

    fn_props = defs.get("function", {}).get("properties", {})
    check("function-carries-guarded_facts",
          fn_props.get("guarded_facts", {}).get("$ref") == "#/$defs/guardedFacts",
          "functions[].guarded_facts must reference $defs/guardedFacts")
    gf = defs.get("guardedFacts", {})
    check("sidecar-is-closed",
          gf.get("additionalProperties") is False
          and set(gf.get("required", [])) == {"version", "calls", "guards"}
          and gf.get("properties", {}).get("version", {}).get("const") == 1,
          "guardedFacts must be a closed object {version: 1, calls, guards}")

    arg = defs.get("guardedArg", {})
    schema_kinds = set(arg.get("properties", {}).get("kind", {}).get("enum", []))
    producer_kinds = csharp_set(source, "GuardedArgKinds")
    check("arg-kinds-schema-equals-producer",
          schema_kinds == producer_kinds and bool(producer_kinds),
          f"schema {sorted(schema_kinds)} != producer {sorted(producer_kinds)}")
    branches = arg.get("oneOf", [])
    branch_kinds = [b.get("properties", {}).get("kind", {}).get("const") for b in branches]
    check("arg-kinds-each-have-one-closed-branch",
          sorted(k for k in branch_kinds if k) == sorted(schema_kinds)
          and all(b.get("additionalProperties") is False for b in branches),
          f"oneOf branches {branch_kinds} must cover every kind exactly once, each closed")
    guard = defs.get("guardedGuard", {})
    schema_preds = set(guard.get("properties", {}).get("predicate", {}).get("enum", []))
    producer_preds = csharp_set(source, "GuardPredicates")
    check("guard-predicates-schema-equals-producer",
          schema_preds == producer_preds and bool(producer_preds),
          f"schema {sorted(schema_preds)} != producer {sorted(producer_preds)}")
    check("guard-is-closed",
          guard.get("additionalProperties") is False
          and set(guard.get("required", [])) == {"site", "param", "predicate", "negated"},
          "guardedGuard must be a closed object {site, param, predicate, negated}")
    call = defs.get("guardedCall", {})
    schema_forms = set(call.get("properties", {}).get("form", {}).get("enum", []))
    producer_forms = csharp_set(source, "CallForms")
    check("call-forms-schema-equals-producer",
          schema_forms == producer_forms and bool(producer_forms),
          f"schema {sorted(schema_forms)} != producer {sorted(producer_forms)}")
    schema_kinds_call = set(call.get("properties", {}).get("call_kind", {}).get("enum", []))
    producer_call_kinds = csharp_set(source, "CallKinds")
    check("call-kinds-schema-equals-producer",
          schema_kinds_call == producer_call_kinds and bool(producer_call_kinds),
          f"schema {sorted(schema_kinds_call)} != producer {sorted(producer_call_kinds)}")
    check("call-kind-is-optional",
          "call_kind" not in call.get("required", []),
          "call_kind must stay optional: an invocation carries none, "
          "so A2.1 records keep their bytes")
    check("call-is-closed-and-keyed",
          call.get("additionalProperties") is False
          and set(call.get("required", [])) == {"site", "statement_line", "form", "callee",
                                                 "sig", "first_party", "args"}
          and call.get("properties", {}).get("args", {}).get("minItems") == 1,
          "guardedCall must be closed, fully required, with at least one argument")

    # The raw-fact boundary (P-037 §10.2) in the vocabulary itself: no P-037
    # interpretation and no synthetic freshness may be spellable.
    forbidden = {"const-pos", "const_pos", "const-neg", "const_neg", "id", "neg", "fresh_owned",
                 "fresh", "stable"}
    leaked = forbidden & (schema_kinds | schema_preds | schema_forms
                          | {k for b in branches for k in b.get("properties", {})})
    check("raw-fact-boundary-holds", not leaked,
          f"interpretation vocabulary leaked into the sidecar: {sorted(leaked)}")

    check("prose-documents-the-sidecar",
          "### 5.2" in prose and all(k in prose for k in schema_kinds | schema_preds),
          "spec/OwnIR.md §5.2 must name every kind and predicate")

    if failures:
        print(f"RESULT: {failures} sidecar vocabulary check(s) failed")
        return 1
    print("RESULT: guarded-fact sidecar vocabulary is one vocabulary "
          "across schema, producer and prose")
    return 0


def run() -> int:
    """Entry point required by tests/run_tests.py's test_*.py census."""
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
