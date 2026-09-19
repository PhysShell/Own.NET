#!/usr/bin/env python3
"""P-037 A2.2-0: the relevance taxonomy is frozen in three places that must agree.

docs/notes/p037-formal-kernel.md §10.6 is the ruling, corpus/p037-relevance/
registry.json is its machine-readable form, and corpus/p037-relevance/probe/
expected.json classifies one probe method per argument shape against it. This
test runs no tool: it pins that every probe method is classified, that every
class, wrapper, form and exclusion is both frozen and exercised, that the prose
names what the registry names, and that the one sentence the freeze hangs on is
byte-identical everywhere it appears.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
NOTE = ROOT / "docs" / "notes" / "p037-formal-kernel.md"
REGISTRY = ROOT / "corpus" / "p037-relevance" / "registry.json"
PROBE_CS = ROOT / "corpus" / "p037-relevance" / "probe" / "case.cs"
PROBE_EXPECTED = ROOT / "corpus" / "p037-relevance" / "probe" / "expected.json"

FROZEN_SENTENCE = (
    "Completeness means every candidate occurrence at a call-related syntax site is "
    "either represented by the raw guarded-call vocabulary or assigned exactly one named "
    "exclusion. Occurrence alone does not establish ownership flow to the enclosing callee."
)
CLASSES = {"direct", "transparent", "may_value", "call_like", "indirect"}
A2_1_HEAD = "dce26ed1f5d831e36f78f02e307b8b772c8a8800"

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"ok[{name}]")
    else:
        _failures.append(name)
        print(f"FAIL[{name}]: {detail}")


def _section_10_6(note: str) -> str:
    start = note.index("### 10.6 ")
    return note[start:]


def _prose_words(text: str) -> str:
    stripped = "\n".join(re.sub(r"^> ?", "", line) for line in text.splitlines())
    return " ".join(stripped.split())


def run() -> int:
    registry: dict[str, Any] = json.loads(REGISTRY.read_text(encoding="utf-8"))
    expected: dict[str, Any] = json.loads(PROBE_EXPECTED.read_text(encoding="utf-8"))
    source = PROBE_CS.read_text(encoding="utf-8")
    section = _section_10_6(NOTE.read_text(encoding="utf-8"))

    check("registry-schema", registry.get("schema") == "p037-relevance-taxonomy/1",
          f"schema is {registry.get('schema')!r}")
    check("completeness-sentence-frozen", registry.get("completeness") == FROZEN_SENTENCE,
          "registry.completeness differs from the frozen sentence")
    check("completeness-sentence-in-note", FROZEN_SENTENCE in _prose_words(section),
          "§10.6 does not carry the frozen sentence verbatim")

    classes = registry.get("classes", {})
    check("classes-closed", set(classes) == CLASSES,
          f"registry classes {sorted(classes)} != frozen {sorted(CLASSES)}")
    exclusions: dict[str, Any] = registry.get("exclusions", {})
    bad = [n for n, e in exclusions.items()
           if e.get("class") != "indirect" or not e.get("definition") or not e.get("example")]
    check("exclusions-well-formed", bool(exclusions) and not bad,
          f"exclusions lacking class=indirect/definition/example: {bad}")

    helpers = set(expected.get("helpers", []))
    declared = set(re.findall(r"static \S+ (\w+)\(", source))
    probes = set(re.findall(r"static void (\w+)\(", source)) - helpers
    methods: dict[str, Any] = expected.get("methods", {})
    check("helpers-exist-in-probe", helpers <= declared,
          f"helpers not declared in case.cs: {sorted(helpers - declared)}")
    check("probe-methods-all-classified", probes == set(methods),
          f"unclassified {sorted(probes - set(methods))}, "
          f"phantom {sorted(set(methods) - probes)}")

    wrappers = set(registry.get("transparent_wrappers", []))
    may_forms = set(registry.get("may_value_forms", []))
    call_forms = set(registry.get("call_like_forms", []))
    observed_vocab = set(expected.get("observed_vocabulary", {}))
    problems: list[str] = []
    used_w: set[str] = set()
    used_m: set[str] = set()
    used_c: set[str] = set()
    used_x: set[str] = set()
    for name, entry in methods.items():
        cls = entry.get("class")
        if cls not in CLASSES:
            problems.append(f"{name}: class {cls!r}")
            continue
        has_x = "exclusion" in entry
        if (cls == "indirect") != has_x:
            problems.append(f"{name}: indirect <=> exclusion violated")
        if has_x:
            if entry["exclusion"] not in exclusions:
                problems.append(f"{name}: unknown exclusion {entry['exclusion']!r}")
            used_x.add(entry["exclusion"])
        if cls == "transparent":
            if entry.get("wrapper") not in wrappers:
                problems.append(f"{name}: wrapper {entry.get('wrapper')!r} not frozen")
            used_w.add(entry.get("wrapper", ""))
        elif cls == "may_value":
            if entry.get("form") not in may_forms:
                problems.append(f"{name}: may-value form {entry.get('form')!r} not frozen")
            used_m.add(entry.get("form", ""))
        elif cls == "call_like":
            if entry.get("form") not in call_forms:
                problems.append(f"{name}: call-like form {entry.get('form')!r} not frozen")
            used_c.add(entry.get("form", ""))
        elif "wrapper" in entry or "form" in entry:
            problems.append(f"{name}: {cls} carries a wrapper/form")
        if entry.get("a2_1_observed") not in observed_vocab:
            problems.append(f"{name}: a2_1_observed {entry.get('a2_1_observed')!r}")
    check("classification-valid", not problems, "; ".join(problems))
    check("registry-non-vacuous",
          used_w == wrappers and used_m == may_forms and used_c == call_forms
          and used_x == set(exclusions),
          f"unexercised wrappers {sorted(wrappers - used_w)}, forms "
          f"{sorted(may_forms - used_m)}, call forms {sorted(call_forms - used_c)}, "
          f"exclusions {sorted(set(exclusions) - used_x)}")
    check("observed-at-a2-1-head", expected.get("observed_at") == A2_1_HEAD,
          f"observed_at is {expected.get('observed_at')!r}; re-observe deliberately, by step")

    prose = section
    missing = [x for x in exclusions if x not in prose]
    missing += [c for c in CLASSES if c not in prose and c.replace("_", "-") not in prose]
    check("note-names-every-class-and-exclusion", not missing,
          f"§10.6 never mentions {missing}")
    rulings = " ".join(registry.get("production_representation_rulings", []))
    check("production-rulings-recorded",
          "mentions" in rulings and "pseudo-ordinal" in rulings and "losure" in rulings,
          "registry must record the no-mentions, no-pseudo-ordinal and closure rulings")

    if _failures:
        print(f"RESULT: {len(_failures)} relevance-freeze check(s) failed")
        return 1
    print(f"RESULT: relevance taxonomy frozen consistently over {len(methods)} probe "
          f"method(s), {len(exclusions)} named exclusion(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
