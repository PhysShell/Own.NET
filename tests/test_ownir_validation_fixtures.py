#!/usr/bin/env python3
"""OwnIR strict-door validation ledger (P-022 step 6b, #259 checkpoint 1).

Freezes the **acceptance language** of `ownlang.ownir.load` — the BR-D1 strict
door — so the Rust `own_ir::OwnIr::from_json` can be shown to accept and reject
exactly the same documents, with zero Python at steady state.

## Why a ledger and not a port of 47 `if`s

Python's `load()` carries 47 `raise OwnIRError` sites; Rust carries three. That
gap is mostly illusory: Rust leans on serde's typing, which rejects a wrong
field type without an explicit check. So the checkpoint is not "transcribe 47
branches" — it is **prove the two loaders accept the same language**, and fix
wherever they do not. A differential probe over 17 hand-picked controls already
found four Rust-only accepts, which is why this file sweeps the contract
instead of spot-checking it.

## What is compared, and what deliberately is not

Compared: **accepted / rejected**, and on rejection the **category**. Not the
message text. #259 asks for a matching error *class/category*; Python funnels
everything into one `OwnIRError` whose strings are a human-facing presentation
aid, so byte-comparing them across two languages would freeze a debug surface
as a contract and fail on every rewording.

## Both failure directions are defects

* **Python reject / Rust accept** — the higher-severity direction: the strict
  door is the gate over untrusted extractor output, and a permissive Rust door
  would analyse facts the reference refuses.
* **Python accept / Rust reject** — not a security hole but a production
  outage after cutover: extractor output that works today would stop being
  analysable.

Both must be zero. So must category mismatches.

## Order is part of the contract

BR-D1 fixes the order of checks and notes it "is observable through which error
fires first". A document that violates two rules therefore has one *correct*
category, not two acceptable ones — the `order-*` controls below pin that
precedence rather than leaving it to whichever check an implementation happens
to run first.

Run:  python tests/test_ownir_validation_fixtures.py            (verify)
      python tests/test_ownir_validation_fixtures.py --write    (regenerate)
      python tests/run_tests.py                                 (in the suite)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.ownir import OWNIR_VERSION, OwnIRError, load

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ownir_validation.json")

SCHEMA_VERSION = 1

ROOT_KEYS = {"comment", "schema_version", "categories", "totals", "cases"}
CASE_KEYS = {"name", "why", "section", "document", "raw", "verdict",
             "category", "message"}

# The candidate taxonomy. Deliberately small: one entry per *mechanism* a
# loader can reject on, not one per message. A category is only worth having if
# two implementations could plausibly disagree about which one applies.
#
# `reference` is intentionally ABSENT until the sweep proves the strict door has
# a load-time referential constraint. Adding it now, on the strength of the
# issue text alone, would be inventing a category no control can exercise.
CATEGORIES = {
    "json": "the document is not JSON at all",
    "version": "the `ownir_version` gate — type or value",
    "shape": "right place, wrong JSON type or container shape",
    "vocabulary": "right JSON type, value outside a closed set",
    "identity": "an identity field that is empty or duplicated",
    "location": "a source coordinate violating the 1-based contract",
}


def _c(name: str, section: str, why: str, document: Any,
       category: str | None, raw: bool = False) -> dict[str, Any]:
    """One control. `category` is None for a document that must be ACCEPTED.

    `raw=True` means `document` is the file's literal TEXT, not a value to
    serialize — the only way to reach the JSON-parse branch. It is an explicit
    flag rather than "a `str` document is text", because that heuristic
    silently mis-encoded `root-string`: the intent was the JSON document
    `"hello"`, and it was written as the unparseable bytes `hello`, which then
    produced a category mismatch that looked like a port bug.
    """
    assert category is None or category in CATEGORIES, f"{name}: bad category"
    return {"name": name, "section": section, "why": why,
            "document": document, "category": category, "raw": raw}


def _svc(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"name": "S", "lifetime": "singleton"}
    base.update(kw)
    return base


def _controls() -> list[dict[str, Any]]:
    """Every BR-D1 rejection family, each with a neighbouring valid twin.

    A rejection control alone proves nothing about the boundary — it could pass
    against a loader that rejects everything. The valid twin is what makes each
    pair *discriminating*.
    """
    return [
        # ---- acceptance twins ------------------------------------------------
        _c("accept-empty-object", "root",
           "the minimal document: absent `ownir_version` means current, and "
           "every section is optional", {}, None),
        _c("accept-explicit-version", "version",
           "the current version stated explicitly", {"ownir_version": OWNIR_VERSION}, None),
        _c("accept-all-sections-empty", "root",
           "every known section present but empty — shape-valid, nothing to check",
           {"ownir_version": 0, "components": [], "services": [], "effects": [],
            "functions": [], "protocols": [], "protocol_functions": []}, None),
        _c("accept-unknown-top-level-key", "root",
           "an unrecognised TOP-LEVEL key is additive and accepted; the strict "
           "door gates known vocabulary, it is not a closed-world schema",
           {"ownir_version": 0, "future_section": [{"whatever": 1}]}, None),
        _c("accept-subscription-defaults", "components",
           "a subscription with no `resource` defaults to 'subscription', which "
           "is a known kind",
           {"ownir_version": 0, "components": [{"subscriptions": [{}]}]}, None),
        _c("accept-every-known-resource-kind", "components",
           "all eight known kinds in one document — the acceptance side of the "
           "closed vocabulary",
           {"ownir_version": 0, "components": [{"subscriptions": [
               {"resource": k} for k in
               ("capture", "disposable", "local-disposable", "pool",
                "subscribe", "subscription", "timer", "unresolved-subscription")
           ]}]}, None),
        _c("accept-column-one", "components",
           "column 1 is the smallest legal column — the boundary just inside the "
           "1-based contract",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"column": 1}]}]}, None),
        _c("accept-every-lifetime", "services",
           "all three DI lifetimes accepted",
           {"ownir_version": 0, "services": [
               _svc(name="A", lifetime="singleton"),
               _svc(name="B", lifetime="scoped"),
               _svc(name="C", lifetime="transient")]}, None),
        _c("accept-every-param-effect", "functions",
           "all four parameter effects accepted",
           {"ownir_version": 0, "functions": [{"params": [
               {"name": "a", "effect": "plain"}, {"name": "b", "effect": "borrow"},
               {"name": "c", "effect": "borrow_mut"},
               {"name": "d", "effect": "consume"}]}]}, None),
        _c("accept-param-effect-absent", "functions",
           "`effect` is optional — absent is not the same as an unknown value",
           {"ownir_version": 0, "functions": [{"params": [{"name": "a"}]}]}, None),

        # ---- json ------------------------------------------------------------
        _c("json-not-parseable", "json",
           "a truncated document is not JSON at all — rejected before any "
           "shape check can run", "{not json", "json", raw=True),

        # ---- root shape ------------------------------------------------------
        _c("root-array", "root", "the root must be an object, not an array",
           [1, 2, 3], "shape"),
        _c("root-string", "root", "nor a bare string", "hello", "shape"),
        _c("root-null", "root", "nor null", None, "shape"),

        # ---- version gate ----------------------------------------------------
        _c("version-mismatch", "version",
           "a different schema version makes every later check meaningless",
           {"ownir_version": 99}, "version"),
        _c("version-string", "version", "`ownir_version` must be an integer",
           {"ownir_version": "0"}, "version"),
        _c("version-bool", "version",
           "the bool-is-int trap: `True` would otherwise read as version 1",
           {"ownir_version": True}, "version"),
        _c("version-float", "version", "a float is not an integer",
           {"ownir_version": 0.0}, "version"),
        _c("version-null", "version",
           "explicit null is NOT the same as absent — absent defaults to "
           "current, null is a stated non-integer",
           {"ownir_version": None}, "version"),

        # ---- components / subscriptions -------------------------------------
        _c("components-object", "components",
           "`components` must be an array", {"ownir_version": 0,
                                             "components": {"a": 1}}, "shape"),
        _c("components-of-scalars", "components",
           "an array, but not of objects",
           {"ownir_version": 0, "components": [1, 2]}, "shape"),
        _c("subscriptions-not-array", "components",
           "each component's `subscriptions` must be an array of objects",
           {"ownir_version": 0, "components": [{"subscriptions": 7}]}, "shape"),
        _c("subscriptions-of-scalars", "components",
           "…of OBJECTS, not scalars",
           {"ownir_version": 0, "components": [{"subscriptions": ["x"]}]}, "shape"),
        _c("resource-not-string", "components",
           "`resource` must be a string before its value can be checked",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"resource": 7}]}]}, "shape"),
        _c("resource-unknown", "components",
           "IR4: a present-but-unknown kind changes routing, so it is rejected "
           "at the door rather than mis-routed. A new kind must bump "
           "OWNIR_VERSION",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"resource": "bogus"}]}]}, "vocabulary"),
        _c("resource-empty-string", "components",
           "the empty string is present-but-unknown, not absent",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"resource": ""}]}]}, "vocabulary"),
        _c("subscription-type-not-string", "components",
           "optional `type`, present ⇒ string",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"type": 7}]}]}, "shape"),
        _c("subscription-source-type-not-string", "components",
           "optional `source_type`, present ⇒ string",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"source_type": 7}]}]}, "shape"),
        _c("subscription-source-provenance-not-string", "components",
           "optional `source_provenance`, present ⇒ string",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"source_provenance": 7}]}]}, "shape"),
        _c("subscription-ignore-reason-not-string", "components",
           "optional `ignore_reason`, present ⇒ string",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"ignore_reason": 7}]}]}, "shape"),
        _c("column-zero", "components",
           "#317: a column is 1-based or absent. `0` is a producer bug, and "
           "reading it as 'unknown' would hide the bug while looking correct",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"column": 0}]}]}, "location"),
        _c("column-negative", "components", "…and so is a negative column",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"column": -1}]}]}, "location"),
        _c("column-bool", "components",
           "the bool-is-int trap again: `True` would otherwise be accepted as "
           "column 1 — a fabricated coordinate",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"column": True}]}]}, "location"),
        _c("column-string", "components", "a string column is not a coordinate",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"column": "3"}]}]}, "location"),

        # ---- services --------------------------------------------------------
        _c("services-not-array", "services", "`services` must be an array of objects",
           {"ownir_version": 0, "services": {"a": 1}}, "shape"),
        _c("service-lifetime-unknown", "services",
           "the DI lifetime is a closed set",
           {"ownir_version": 0, "services": [_svc(lifetime="eternal")]}, "vocabulary"),
        _c("service-name-empty", "services",
           "the service name is the identity the DI graph joins on",
           {"ownir_version": 0, "services": [_svc(name="")]}, "identity"),
        _c("service-name-not-string", "services", "…and it must be a string",
           {"ownir_version": 0, "services": [_svc(name=7)]}, "identity"),
        _c("service-deps-not-array", "services", "`deps` is an array of strings",
           {"ownir_version": 0, "services": [_svc(deps="a")]}, "shape"),
        _c("service-deps-of-ints", "services", "…of STRINGS",
           {"ownir_version": 0, "services": [_svc(deps=[1])]}, "shape"),
        _c("service-weak-deps-of-ints", "services", "same for `weak_deps`",
           {"ownir_version": 0, "services": [_svc(weak_deps=[1])]}, "shape"),
        _c("service-root-resolves-of-ints", "services", "same for `root_resolves`",
           {"ownir_version": 0, "services": [_svc(root_resolves=[1])]}, "shape"),
        _c("service-scope-cached-of-ints", "services", "same for `scope_cached`",
           {"ownir_version": 0, "services": [_svc(scope_cached=[1])]}, "shape"),
        _c("service-file-not-string", "services", "`file` is a string",
           {"ownir_version": 0, "services": [_svc(file=7)]}, "shape"),
        _c("service-line-not-int", "services", "`line` is an integer",
           {"ownir_version": 0, "services": [_svc(line="3")]}, "shape"),
        _c("service-line-bool", "services", "…and a bool is not an integer",
           {"ownir_version": 0, "services": [_svc(line=True)]}, "shape"),
        _c("service-ctor-file-not-string", "services", "`ctor_file` is a string",
           {"ownir_version": 0, "services": [_svc(ctor_file=7)]}, "shape"),
        _c("service-ctor-line-not-int", "services", "`ctor_line` is an integer",
           {"ownir_version": 0, "services": [_svc(ctor_line="3")]}, "shape"),
        _c("service-ctor-type-not-string", "services", "`ctor_type` is a string",
           {"ownir_version": 0, "services": [_svc(ctor_type=7)]}, "shape"),
        _c("service-root-resolve-sites-not-objects", "services",
           "`root_resolve_sites` is an array of {type,file,line} objects",
           {"ownir_version": 0, "services": [_svc(root_resolve_sites=["x"])]}, "shape"),
        _c("service-scope-cache-sites-not-objects", "services",
           "same for `scope_cache_sites`",
           {"ownir_version": 0, "services": [_svc(scope_cache_sites=["x"])]}, "shape"),

        # ---- effects ---------------------------------------------------------
        _c("effects-not-array", "effects", "`effects` must be an array of objects",
           {"ownir_version": 0, "effects": {"a": 1}}, "shape"),
        _c("effect-deps-of-ints", "effects", "`deps` is an array of strings",
           {"ownir_version": 0, "effects": [{"deps": [1]}]}, "shape"),
        _c("effect-io-not-bool", "effects", "`io` is a boolean",
           {"ownir_version": 0, "effects": [{"io": "yes"}]}, "shape"),
        _c("effect-line-not-int", "effects", "`line` is an integer",
           {"ownir_version": 0, "effects": [{"line": "3"}]}, "shape"),
        _c("effect-bindings-not-objects", "effects",
           "`bindings` is an array of objects",
           {"ownir_version": 0, "effects": [{"bindings": ["x"]}]}, "shape"),
        _c("binding-name-not-string", "effects", "binding `name` is a string",
           {"ownir_version": 0, "effects": [{"bindings": [{"name": 7}]}]}, "shape"),
        _c("binding-init-not-string", "effects", "binding `init` is a string",
           {"ownir_version": 0, "effects": [{"bindings": [{"init": 7}]}]}, "shape"),
        _c("binding-refs-of-ints", "effects", "binding `refs` is string array",
           {"ownir_version": 0, "effects": [{"bindings": [{"refs": [1]}]}]}, "shape"),
        _c("binding-line-not-int", "effects", "binding `line` is an integer",
           {"ownir_version": 0, "effects": [{"bindings": [{"line": "3"}]}]}, "shape"),

        # ---- functions / params ---------------------------------------------
        _c("functions-not-array", "functions", "`functions` must be an array of objects",
           {"ownir_version": 0, "functions": {"a": 1}}, "shape"),
        _c("function-sig-not-string", "functions",
           "`sig` present ⇒ string. It is the overload key MOS resolution joins "
           "on, so a non-string is not a cosmetic problem",
           {"ownir_version": 0, "functions": [{"sig": 7}]}, "shape"),
        _c("params-not-array", "functions", "`params` is an array of objects",
           {"ownir_version": 0, "functions": [{"params": "x"}]}, "shape"),
        _c("params-of-scalars", "functions", "…of OBJECTS",
           {"ownir_version": 0, "functions": [{"params": ["x"]}]}, "shape"),
        _c("param-name-empty", "functions",
           "the parameter name is the identity effects attach to",
           {"ownir_version": 0, "functions": [{"params": [{"name": ""}]}]}, "identity"),
        _c("param-name-not-string", "functions", "…and it must be a string",
           {"ownir_version": 0, "functions": [{"params": [{"name": 7}]}]}, "identity"),
        _c("param-line-not-int", "functions", "param `line` is an integer",
           {"ownir_version": 0,
            "functions": [{"params": [{"name": "p", "line": "3"}]}]}, "shape"),
        _c("param-effect-unknown", "functions",
           "the parameter effect is a closed set",
           {"ownir_version": 0,
            "functions": [{"params": [{"name": "p", "effect": "teleport"}]}]},
           "vocabulary"),

        # ---- protocols -------------------------------------------------------
        _c("protocols-not-array", "protocols", "`protocols` must be an array of objects",
           {"ownir_version": 0, "protocols": {"a": 1}}, "shape"),
        _c("protocol-duplicate-name", "protocols",
           "the protocol name is the identity verdicts map back by, so a "
           "duplicate is an identity collision, not a harmless repeat",
           {"ownir_version": 0, "protocols": [
               {"name": "P", "states": ["a"], "initial": "a", "transitions": []},
               {"name": "P", "states": ["a"], "initial": "a", "transitions": []}]},
           "identity"),
        _c("protocol-functions-not-array", "protocols",
           "`protocol_functions` must be an array of objects",
           {"ownir_version": 0, "protocol_functions": {"a": 1}}, "shape"),

        # ---- order discrimination -------------------------------------------
        # BR-D1 fixes the ORDER of checks and says it "is observable through
        # which error fires first". Each of these violates two rules at once, so
        # there is exactly one correct category — a loader that runs its checks
        # in a different order reports the other one and fails here.
        _c("order-version-before-components", "order",
           "both the version and `components` are wrong; the VERSION gate runs "
           "first, because a vocabulary mismatch makes every later shape check "
           "meaningless",
           {"ownir_version": 99, "components": {"a": 1}}, "version"),
        _c("order-version-before-resource", "order",
           "version wins over an unknown resource kind for the same reason",
           {"ownir_version": 99,
            "components": [{"subscriptions": [{"resource": "bogus"}]}]}, "version"),
        _c("order-root-before-version", "order",
           "root-is-object precedes the version gate — there is nowhere to read "
           "`ownir_version` from until the root is an object",
           [{"ownir_version": 99}], "shape"),
        _c("order-json-before-everything", "order",
           "an unparseable document cannot reach any structural check",
           "{\"ownir_version\": 99", "json", raw=True),
        _c("order-resource-shape-before-vocabulary", "order",
           "`resource` must be a STRING before its value can be tested against "
           "the closed set — a shape failure, not a vocabulary one",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"resource": 7, "column": 0}]}]},
           "shape"),
        _c("order-components-before-services", "order",
           "sections are validated in declaration order: `components` before "
           "`services`, so a document breaking both reports components",
           {"ownir_version": 0, "components": {"a": 1},
            "services": {"b": 2}}, "shape"),
    ]


def _oracle(document: Any, raw: bool) -> tuple[str, str]:
    """Run the reference strict door and record its verdict.

    A raw string document is written verbatim so the JSON-parse branch is
    reachable; anything else is serialized.

    `load()` takes a PATH and splices it into two of its messages ("cannot read
    {path}", "{path} is not valid JSON"), so the recorded message carries the
    temporary filename. That is genuinely volatile — the ledger was
    non-deterministic on the first regeneration until the path was normalized
    to a fixed token here. The message is not compared across languages, but a
    golden that changes on every run cannot detect anything at all.
    """
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "facts.ownir.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            if raw:
                f.write(document)
            else:
                json.dump(document, f)
        try:
            load(path)
            return "accept", ""
        except OwnIRError as e:
            return "reject", str(e).replace(path, "<facts>")
    finally:
        if os.path.exists(path):
            os.unlink(path)
        os.rmdir(directory)


def build() -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for ctl in _controls():
        verdict, message = _oracle(ctl["document"], ctl["raw"])
        cases.append({
            "name": ctl["name"],
            "why": ctl["why"],
            "section": ctl["section"],
            "document": ctl["document"],
            "raw": ctl["raw"],
            "verdict": verdict,
            "category": ctl["category"],
            # Kept for a human reading a failure, NOT compared across languages:
            # #259 asks for a matching error class/category, and Python's
            # strings are a presentation aid rather than a semantic surface.
            "message": message,
        })

    by_category: dict[str, int] = {}
    for case in cases:
        key = case["category"] or "accepted"
        by_category[key] = by_category.get(key, 0) + 1

    return {
        "comment": (
            "GENERATED by tests/test_ownir_validation_fixtures.py --write; do not "
            "edit. Python (ownlang.ownir.load) is authoritative. The BR-D1 "
            "strict-door acceptance language for P-022 step 6b, #259 checkpoint 1. "
            "Compared across languages: accepted/rejected and, on rejection, the "
            "CATEGORY -- never the message text, which is a human-facing "
            "presentation aid in the reference."
        ),
        "schema_version": SCHEMA_VERSION,
        "categories": CATEGORIES,
        "totals": {
            "cases": len(cases),
            "accepted": sum(1 for c in cases if c["verdict"] == "accept"),
            "rejected": sum(1 for c in cases if c["verdict"] == "reject"),
            "by_category": dict(sorted(by_category.items())),
        },
        "cases": cases,
    }


def _render_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def run() -> int:
    fresh = build()
    expected = _render_json(fresh)
    if not os.path.exists(FIXTURE):
        print(f"FAIL: {FIXTURE} missing; regenerate with "
              f"'python tests/test_ownir_validation_fixtures.py --write'")
        return 1
    with open(FIXTURE, encoding="utf-8") as f:
        actual = f.read()
    if actual != expected:
        print(f"FAIL: {FIXTURE} is stale (the strict door's acceptance changed); "
              f"regenerate with 'python tests/test_ownir_validation_fixtures.py "
              f"--write' and re-run the Rust side "
              f"(cd rust && cargo test -p own-ir)")
        return 1

    data = json.loads(actual)
    if set(data) != ROOT_KEYS:
        print(f"FAIL: fixture root keys {sorted(data)} != {sorted(ROOT_KEYS)}")
        return 1
    for case in data["cases"]:
        if set(case) != CASE_KEYS:
            print(f"FAIL: case {case.get('name')!r} keys {sorted(case)} "
                  f"!= {sorted(CASE_KEYS)}")
            return 1

    # A rejection control with no category, or an acceptance control carrying
    # one, would make the Rust comparison vacuous for that case.
    for case in data["cases"]:
        if case["verdict"] == "reject" and not case["category"]:
            print(f"FAIL: {case['name']}: rejected with no category")
            return 1
        if case["verdict"] == "accept" and case["category"]:
            print(f"FAIL: {case['name']}: accepted but carries a category")
            return 1

    # Every declared category must be exercised. An unused category is a claim
    # about the taxonomy that no control backs.
    used = {c["category"] for c in data["cases"] if c["category"]}
    unused = sorted(set(data["categories"]) - used)
    if unused:
        print(f"FAIL: declared categories with no control: {unused}. A category "
              f"is only worth having if a case exercises it")
        return 1

    # The acceptance twins are what make the rejections discriminating: without
    # them the ledger would pass against a loader that rejects everything.
    accepted = data["totals"]["accepted"]
    if accepted < 5:
        print(f"FAIL: only {accepted} acceptance control(s); the rejections are "
              f"not discriminating without valid twins")
        return 1

    # The oracle must be a pure function of the control. It was not, on the
    # first attempt: `load()` splices its input path into two messages and the
    # temporary filename changed every run. Asserted rather than assumed, so a
    # future volatile field cannot make the golden quietly self-defeating.
    if _render_json(build()) != expected:
        print("FAIL: the ledger is not deterministic — two builds of the same "
              "controls differ, so a stale golden could never be detected")
        return 1

    t = data["totals"]
    print(f"ownir validation ledger OK: {t['cases']} controls "
          f"({t['accepted']} accept / {t['rejected']} reject), "
          f"categories {t['by_category']}")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        os.makedirs(os.path.dirname(FIXTURE), exist_ok=True)
        with open(FIXTURE, "w", encoding="utf-8") as f:
            f.write(_render_json(build()))
        print(f"wrote {FIXTURE}")
        raise SystemExit(0)
    raise SystemExit(run())
