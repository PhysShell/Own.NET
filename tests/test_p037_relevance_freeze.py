#!/usr/bin/env python3
"""P-037 A2.2-0: the relevance taxonomy is frozen in three places that must agree.

docs/notes/p037-formal-kernel.md §10.6 is the ruling, corpus/p037-relevance/
registry.json is its machine-readable form, and corpus/p037-relevance/probe/
expected.json classifies one probe method per argument shape against it. This
test runs no tool: it pins that every probe method is classified, that every
class, wrapper, form, conversion edge and exclusion is both frozen and
exercised, that the conversion rules are mutually exclusive (no row can be
transparent and a user-defined conversion at once; the `as` split is pinned),
that the prose names what the registry names, and that the one sentence the
freeze hangs on is byte-identical everywhere it appears.
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
CONVERSIONS = {"none", "identity", "reference_upcast", "may_fail_null",
               "user_defined_implicit", "user_defined_explicit", "not_applicable"}
VALUE_PRESERVING = {"none", "identity", "reference_upcast"}
USER_DEFINED = {"user_defined_implicit", "user_defined_explicit"}
# A' = the corrected A2.1 treatment (PR #363), the extractor main carries. The
# superseded A (dce26ed) is not a measurement point; re-observe by step, never by drift.
A_PRIME = "5a0de070af241a2612859153887ad6ae04afcce2"

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"ok[{name}]")
    else:
        _failures.append(name)
        print(f"FAIL[{name}]: {detail}")


def _section_10_6(note: str) -> str:
    return note[note.index("### 10.6 "):]


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
    edges = registry.get("conversion_edges", {})
    check("conversion-edges-closed", set(edges) == CONVERSIONS,
          f"registry edges {sorted(edges)} != frozen {sorted(CONVERSIONS)}")
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
    used: dict[str, set[str]] = {"w": set(), "m": set(), "c": set(), "x": set(), "e": set()}
    for name, entry in methods.items():
        cls = entry.get("class")
        conv = entry.get("conversion")
        if cls not in CLASSES:
            problems.append(f"{name}: class {cls!r}")
            continue
        if conv not in CONVERSIONS:
            problems.append(f"{name}: conversion {conv!r} not frozen")
            continue
        used["e"].add(conv)
        has_x = "exclusion" in entry
        if (cls == "indirect") != has_x:
            problems.append(f"{name}: indirect <=> exclusion violated")
        if has_x:
            if entry["exclusion"] not in exclusions:
                problems.append(f"{name}: unknown exclusion {entry['exclusion']!r}")
            used["x"].add(entry["exclusion"])
        if cls == "transparent":
            if entry.get("wrapper") not in wrappers:
                problems.append(f"{name}: wrapper {entry.get('wrapper')!r} not frozen")
            used["w"].add(entry.get("wrapper", ""))
        elif cls == "may_value":
            if entry.get("form") not in may_forms:
                problems.append(f"{name}: may-value form {entry.get('form')!r} not frozen")
            used["m"].add(entry.get("form", ""))
        elif cls == "call_like":
            if entry.get("form") not in call_forms:
                problems.append(f"{name}: call-like form {entry.get('form')!r} not frozen")
            used["c"].add(entry.get("form", ""))
        elif "wrapper" in entry or "form" in entry:
            problems.append(f"{name}: {cls} carries a wrapper/form")
        # ---- the conversion rules, mutually exclusive by construction ----
        if cls in {"direct", "transparent"} and conv not in VALUE_PRESERVING:
            problems.append(f"{name}: {cls} with conversion {conv} (must be value-preserving)")
        if (conv in USER_DEFINED) != (entry.get("exclusion") == "user_conversion"):
            problems.append(f"{name}: user-defined conversion <=> user_conversion violated")
        if (conv == "may_fail_null") != (entry.get("form") == "as_may_fail"):
            problems.append(f"{name}: may_fail_null <=> as_may_fail violated")
        if cls == "indirect" and entry.get("exclusion") != "user_conversion" \
                and conv != "not_applicable":
            problems.append(f"{name}: indirect non-conversion row carries conversion {conv}")
        if entry.get("a2_1_observed") not in observed_vocab:
            problems.append(f"{name}: a2_1_observed {entry.get('a2_1_observed')!r}")
    check("classification-valid", not problems, "; ".join(problems))
    check("registry-non-vacuous",
          used["w"] == wrappers and used["m"] == may_forms and used["c"] == call_forms
          and used["x"] == set(exclusions) and used["e"] == CONVERSIONS,
          f"unexercised wrappers {sorted(wrappers - used['w'])}, forms "
          f"{sorted(may_forms - used['m'])}, call forms {sorted(call_forms - used['c'])}, "
          f"exclusions {sorted(set(exclusions) - used['x'])}, "
          f"conversion edges {sorted(CONVERSIONS - used['e'])}")

    # The two pins the corrected freeze exists for: both user-defined kinds, and the
    # `as` split (a guaranteed upcast is transparent; a may-fail downcast is may-value).
    by_conv = {c: sorted(n for n, e in methods.items() if e.get("conversion") == c)
               for c in CONVERSIONS}
    check("user-defined-implicit-and-explicit-pinned",
          bool(by_conv["user_defined_implicit"]) and bool(by_conv["user_defined_explicit"]),
          f"implicit {by_conv['user_defined_implicit']}, "
          f"explicit {by_conv['user_defined_explicit']}")
    as_rows = {n: e for n, e in methods.items()
               if e.get("wrapper") == "as" or e.get("form") == "as_may_fail"}
    check("as-split-pinned",
          any(e.get("class") == "transparent" for e in as_rows.values())
          and any(e.get("class") == "may_value" for e in as_rows.values()),
          f"`as` rows: { {n: e.get('class') for n, e in as_rows.items()} }")
    check("no-row-transparent-and-user-conversion",
          not [n for n, e in methods.items()
               if e.get("class") == "transparent" and e.get("conversion") in USER_DEFINED],
          "a transparent row carries a user-defined conversion")
    check("observed-at-a-prime", expected.get("observed_at") == A_PRIME,
          f"observed_at is {expected.get('observed_at')!r}; re-observe deliberately, by step")

    missing = [x for x in exclusions if x not in section]
    missing += [c for c in CLASSES if c not in section and c.replace("_", "-") not in section]
    missing += [e for e in CONVERSIONS if e not in section]
    check("note-names-every-class-exclusion-and-edge", not missing,
          f"§10.6 never mentions {missing}")
    for sha, label in ((A_PRIME[:7], "A'"), ("cd7e020", "S'"), ("23e3203", "the merge"),
                       ("dce26ed", "superseded A"), ("ee4d065", "the superseded freeze")):
        check(f"note-provenance-names-{label.replace(' ', '-').replace(chr(39), '')}",
              sha in section, f"§10.6 does not name {label} ({sha})")
    rulings = " ".join(registry.get("production_representation_rulings", []))
    check("production-rulings-recorded",
          "mentions" in rulings and "pseudo-ordinal" in rulings and "losure" in rulings,
          "registry must record the no-mentions, no-pseudo-ordinal and closure rulings")
    rules = " ".join(registry.get("conversion_rules", []))
    check("walker-ruling-recorded", "IOperation" in rules and "InConversion" in rules,
          "registry must record the IOperation value-flow walker ruling")

    if _failures:
        print(f"RESULT: {len(_failures)} relevance-freeze check(s) failed")
        return 1
    print(f"RESULT: relevance taxonomy frozen consistently over {len(methods)} probe "
          f"method(s), {len(exclusions)} named exclusion(s), {len(CONVERSIONS)} conversion edge(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
