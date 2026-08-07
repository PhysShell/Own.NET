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

## The first census was not a sweep, and said it was

The first round of this ledger reached a 0/0/0 matrix over 77 controls and was
recorded as complete. Review then found seven divergences it could not see, and
the reason was structural rather than careless: **the same author wrote the
oracle and the port**, so one gap in reading BR-D1 produced a matching gap in
each, and the matrix agreed with itself.

The sharpest instance: `_svc()` below always supplied `lifetime`, so no control
could ever omit it — and the reference rejects an absent `lifetime` while the
port accepted it. The ledger could not fail, which is a different property from
the port being right.

Mutation testing proved the *implementation* against the *ledger*. Nothing
proved the ledger against the *contract*. So this round works the other way
round: every control below is derived by reading `load()` and the shared
obligation parser line by line, section by section, and each section's controls
are written before looking at what the port does with them. The helpers now
deliberately build *incomplete* records, because the missing-field case is the
one a convenience helper hides.

## What "category" means per field, and why it is not the mechanism

`identity` is every **name slot** — a value some other fact joins on: a service
name, a parameter name, a protocol name, a protocol function's name, a
matcher's `target`/`callee`, an event's `target`/`callee`, an entry of
`scope.methods`. Empty, mistyped, or duplicated, they are all the same defect:
the name cannot be used to join. `shape` is a wrong JSON type or container.

That line is drawn on **what the field is**, not on which helper raised. Two
consequences worth stating, because both look like inconsistencies otherwise:

* `scope.methods: 7` is `shape` and `scope.methods: [""]` is `identity`, even
  though the reference raises one message for both. The category is a semantic
  claim the ledger makes; the oracle only supplies accept/reject.
* A protocol that "can never fire" (no barriers with `exit_barriers: false`, or
  a barrier equal to `opens`) is `well_formedness`, the seventh category. Every
  value in such a record has the right type and a legal vocabulary; what is
  broken is that the record cannot *mean* anything.

  An earlier revision filed both under `shape`, reasoning that the taxonomy was
  already frozen at six. That was backwards. The taxonomy was frozen by the
  FIRST census; this mechanism was found by the SECOND. A category set settled
  by one census is a claim about that census, not about the contract — and
  filing a newly discovered mechanism under the nearest existing name is the
  exact substitution the taxonomy exists to prevent. Seven categories are not
  worse than six; a false one is worse than both.

## Integer width: measured, and deliberately not covered here

Python integers are unbounded. Every `line`-like and `column`-like field in
`load()` accepts values far beyond 64 bits — measured across `services[].line`,
`ctor_line`, `root_resolve_sites[].line`, `effects[].line`,
`bindings[].line`, `params[].line`, `protocol_functions[].events[].line`,
`subscriptions[].column`, `params[].column` and flow-op `column`. All accept
`i64::MAX + 1`, `u64::MAX`, `u64::MAX + 1` and below `i64::MIN`. The single
exception is `ownir_version`, rejected for its *value*, not its width.

Rust rejects all of them. That is a real Python-accept/Rust-reject divergence
across seven field families, not one stray column.

It is **not** closed by widening Rust: threading arbitrary-precision integers
through `own-ir` and then the bridge, so that a source coordinate of nine
quintillion can round-trip, would be an expensive way to honour a file no
extractor can produce. The controls here therefore pin the boundary at
`i64::MAX`, where both sides agree, and stop. Closing the range above it is a
Python-first change — a documented defensive limit on source-coordinate
integers, which is what #259 asks for on externally supplied input — and lands
separately. This ledger is regenerated against that once it exists.

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
    "identity": "a name slot — empty, mistyped, or duplicated",
    "location": "a source coordinate violating the 1-based contract",
    "well_formedness": ("right types, legal vocabulary, and the record still "
                        "cannot mean anything"),
}

# The largest integer both loaders accept. Above it Python keeps going and Rust
# stops; see "Integer width" in the module docstring for the measurement and why
# that boundary is closed elsewhere.
I64_MAX = 9223372036854775807


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
    """A service record with both REQUIRED fields supplied, so a control that
    overrides one field isolates that field.

    Its convenience is also its hazard, and this is where the first census went
    wrong: because `_svc()` always sets `lifetime` and `name`, no control built
    through it can express *absence*, and absence is exactly what the reference
    rejects and the port accepted. The `service-*-absent` controls below are
    therefore written as literal dicts, deliberately bypassing this helper.
    """
    base: dict[str, Any] = {"name": "S", "lifetime": "singleton"}
    base.update(kw)
    return base


def _proto(**kw: Any) -> dict[str, Any]:
    """A minimally VALID protocol: a name plus an opens/closes matcher pair.

    Both matchers state their written boolean, because an `opens`/`closes`
    assign matcher that does not is refused ("any write cannot open or close an
    obligation"). `exit_barriers` defaults true, so the record also clears the
    never-fires rule.

    The valid baseline is the point. `protocol-duplicate-name` previously used
    records with no `opens`/`closes` at all, so the reference rejected them for
    record shape and never reached the duplicate-name branch — the control
    passed while testing something else entirely.
    """
    base: dict[str, Any] = {
        "name": "P",
        "opens": {"kind": "assign", "target": "flag", "value": True},
        "closes": {"kind": "assign", "target": "flag", "value": False},
    }
    base.update(kw)
    return base


def _open(**kw: Any) -> dict[str, Any]:
    """A protocol whose `opens` matcher is replaced wholesale — the shortest way
    to reach one matcher rule without disturbing the rest of the record."""
    return _proto(opens=dict(kw))


def _pfn(**kw: Any) -> dict[str, Any]:
    """A minimally valid `protocol_functions[]` record: `events` defaults to
    empty, so a name alone is accepted."""
    base: dict[str, Any] = {"name": "M"}
    base.update(kw)
    return base


def _ev(*events: Any) -> dict[str, Any]:
    """A document carrying one protocol function with the given event list."""
    return {"ownir_version": 0, "protocol_functions": [_pfn(events=list(events))]}


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
           "duplicate is an identity collision, not a harmless repeat. Both "
           "records are individually VALID — the older version of this control "
           "used records with no `opens`/`closes`, which the reference refused "
           "for record shape long before it compared any names",
           {"ownir_version": 0,
            "protocols": [_proto(name="P"), _proto(name="P")]}, "identity"),
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

        # ==== second census ===================================================
        # Everything below was added after review found seven divergences the
        # controls above structurally could not express. Grouped by the blind
        # spot rather than by section, so the gap each one closes stays legible.

        # ---- required fields, absent (the `_svc()` blind spot) ---------------
        # A helper that always supplies a required field makes the absent case
        # unreachable. These bypass the helper on purpose.
        _c("service-lifetime-absent", "services",
           "there is no default lifetime: an absent one is `None`, which is "
           "outside the closed set exactly like a misspelt one. This is the "
           "case `_svc()` could not express, and the port accepted it",
           {"ownir_version": 0, "services": [{"name": "S"}]}, "vocabulary"),
        _c("service-empty-record", "services",
           "a service record with nothing in it: the lifetime gate fires first, "
           "so this is a vocabulary failure and not a missing-name one",
           {"ownir_version": 0, "services": [{}]}, "vocabulary"),
        _c("service-lifetime-null", "services",
           "an explicit null is the same as absent here — both are `None`, and "
           "neither is in the closed set",
           {"ownir_version": 0,
            "services": [{"name": "S", "lifetime": None}]}, "vocabulary"),
        _c("service-name-absent", "services",
           "with a valid lifetime, an absent name reaches the identity check",
           {"ownir_version": 0, "services": [{"lifetime": "singleton"}]},
           "identity"),

        # ---- ordering WITHIN a section --------------------------------------
        # BR-D1's order is per-field, not merely per-section. Each of these
        # breaks two rules inside one record.
        _c("order-lifetime-before-name", "order",
           "the reference checks `lifetime` BEFORE `name`, so a record that "
           "breaks both is a vocabulary failure. A port that validates identity "
           "first reports `identity` and is wrong about which rule fired",
           {"ownir_version": 0,
            "services": [{"name": "", "lifetime": "eternal"}]}, "vocabulary"),
        _c("order-name-before-deps", "order",
           "…and `name` before the remaining service fields",
           {"ownir_version": 0,
            "services": [{"lifetime": "singleton", "name": "", "deps": 7}]},
           "identity"),
        _c("order-resource-vocabulary-before-column", "order",
           "within one subscription, the resource vocabulary precedes the "
           "column contract",
           {"ownir_version": 0, "components": [{"subscriptions": [
               {"resource": "bogus", "column": 0}]}]}, "vocabulary"),
        _c("order-column-before-subscription-type", "order",
           "…and the column precedes the optional `type`",
           {"ownir_version": 0, "components": [{"subscriptions": [
               {"column": 0, "type": 7}]}]}, "location"),
        _c("order-sig-before-body-column", "order",
           "inside a function, `sig` is checked before the body's columns",
           {"ownir_version": 0, "functions": [
               {"sig": 7, "body": [{"op": "x", "column": 0}]}]}, "shape"),
        _c("order-body-column-before-param-name", "order",
           "and the BODY's columns are checked before `params` — the least "
           "obvious edge in the whole door, because params read like the more "
           "primitive thing",
           {"ownir_version": 0, "functions": [
               {"body": [{"op": "x", "column": 0}],
                "params": [{"name": ""}]}]}, "location"),
        _c("order-param-name-before-param-line", "order",
           "within a param, identity precedes the line",
           {"ownir_version": 0, "functions": [
               {"params": [{"name": "", "line": "3"}]}]}, "identity"),
        _c("order-param-line-before-param-column", "order",
           "…the line precedes the column",
           {"ownir_version": 0, "functions": [
               {"params": [{"name": "p", "line": "3", "column": 0}]}]}, "shape"),
        _c("order-param-column-before-effect", "order",
           "…and the column precedes the effect vocabulary",
           {"ownir_version": 0, "functions": [
               {"params": [{"name": "p", "column": 0, "effect": "teleport"}]}]},
           "location"),

        # ---- ordering ACROSS sections ---------------------------------------
        # A "run every semantic check, then every shape check" architecture
        # passes section-local controls and fails all of these: BR-D1 interleaves
        # shape and semantics per section, in declaration order.
        _c("order-components-shape-before-services-vocabulary", "order",
           "a components SHAPE failure outranks a services VOCABULARY failure, "
           "because components is validated first — completely. A door that "
           "runs all semantic gates before any shape check reports the "
           "vocabulary error and inverts the contract",
           {"ownir_version": 0, "components": {"a": 1},
            "services": [{"lifetime": "bad"}]}, "shape"),
        _c("order-components-location-before-services-vocabulary", "order",
           "same precedence with a column failure standing in for the shape one",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"column": 0}]}],
            "services": [{"lifetime": "bad"}]}, "location"),
        _c("order-services-vocabulary-before-effects-shape", "order",
           "and the same one section later: services before effects",
           {"ownir_version": 0, "services": [{"lifetime": "bad"}],
            "effects": {"a": 1}}, "vocabulary"),
        _c("order-effects-shape-before-functions-identity", "order",
           "effects before functions",
           {"ownir_version": 0, "effects": {"a": 1},
            "functions": [{"params": [{"name": ""}]}]}, "shape"),
        _c("order-functions-identity-before-protocols-shape", "order",
           "functions before protocols",
           {"ownir_version": 0, "functions": [{"params": [{"name": ""}]}],
            "protocols": 7}, "identity"),
        _c("order-protocols-identity-before-protocol-functions-shape", "order",
           "protocols before protocol_functions — the last edge in the chain",
           {"ownir_version": 0, "protocols": [{"name": ""}],
            "protocol_functions": 7}, "identity"),

        # ---- flow columns, including nested bodies ---------------------------
        # `_check_flow_columns` recurses through `then`/`else`/`body`. A hoisted
        # branch acquire is the path most likely to be forgotten, and it is
        # never at the top level.
        _c("accept-flow-column-one", "functions",
           "column 1 on a flow op, nested and not — the acceptance twin the "
           "rejections below need",
           {"ownir_version": 0, "functions": [{"body": [
               {"op": "acquire", "column": 1},
               {"op": "if", "then": [{"op": "release", "column": 1}],
                "else": [{"op": "call", "column": 1}]},
               {"op": "while", "body": [{"op": "acquire", "column": 1}]}]}]},
           None),
        _c("accept-flow-body-not-array", "functions",
           "a non-array `body` is SKIPPED, not rejected: the reference returns "
           "early rather than raising. Pinned because it is the kind of "
           "tolerance a port silently tightens",
           {"ownir_version": 0, "functions": [{"body": 7}]}, None),
        _c("accept-flow-body-of-scalars", "functions",
           "…and a non-object op inside the body is skipped the same way",
           {"ownir_version": 0, "functions": [{"body": [1, "x", None]}]}, None),
        _c("flow-column-zero", "functions",
           "the 1-based contract reaches flow ops, not just subscriptions",
           {"ownir_version": 0,
            "functions": [{"body": [{"op": "acquire", "column": 0}]}]},
           "location"),
        _c("flow-column-negative", "functions", "…negative likewise",
           {"ownir_version": 0,
            "functions": [{"body": [{"op": "acquire", "column": -2}]}]},
           "location"),
        _c("flow-column-bool", "functions", "…and the bool-is-int trap",
           {"ownir_version": 0,
            "functions": [{"body": [{"op": "acquire", "column": True}]}]},
           "location"),
        _c("flow-column-in-if-then", "functions",
           "recursion into `then` — a hoisted branch acquire",
           {"ownir_version": 0, "functions": [{"body": [
               {"op": "if", "then": [{"op": "acquire", "column": 0}]}]}]},
           "location"),
        _c("flow-column-in-if-else", "functions", "…into `else`",
           {"ownir_version": 0, "functions": [{"body": [
               {"op": "if", "else": [{"op": "acquire", "column": 0}]}]}]},
           "location"),
        _c("flow-column-in-while-body", "functions", "…into a loop `body`",
           {"ownir_version": 0, "functions": [{"body": [
               {"op": "while", "body": [{"op": "acquire", "column": 0}]}]}]},
           "location"),
        _c("flow-column-deeply-nested", "functions",
           "…and through three levels, so a one-level-deep port fails here",
           {"ownir_version": 0, "functions": [{"body": [
               {"op": "if", "then": [{"op": "while", "body": [
                   {"op": "if", "else": [{"op": "acquire", "column": 0}]}]}]}]}]},
           "location"),

        # ---- params[].column -------------------------------------------------
        _c("accept-param-column-one", "functions",
           "the 1-based boundary on a parameter coordinate",
           {"ownir_version": 0,
            "functions": [{"params": [{"name": "p", "column": 1}]}]}, None),
        _c("param-column-zero", "functions",
           "the same contract on `params[].column` — a separate call site in "
           "the reference, and one the port did not have at all",
           {"ownir_version": 0,
            "functions": [{"params": [{"name": "p", "column": 0}]}]},
           "location"),
        _c("param-column-negative", "functions", "…negative likewise",
           {"ownir_version": 0,
            "functions": [{"params": [{"name": "p", "column": -1}]}]},
           "location"),
        _c("param-column-bool", "functions", "…and the bool-is-int trap",
           {"ownir_version": 0,
            "functions": [{"params": [{"name": "p", "column": True}]}]},
           "location"),
        _c("param-column-string", "functions", "…and a string is no coordinate",
           {"ownir_version": 0,
            "functions": [{"params": [{"name": "p", "column": "3"}]}]},
           "location"),

        # ---- protocols: the acceptance grammar ------------------------------
        # `load()` delegates each record to the shared obligation parser
        # (ownlang/obligations.py), which is part of the strict-door contract
        # even though it lives in another module. cp1 ports its ACCEPTANCE
        # grammar only — parse_protocol / parse_matcher / parse_events /
        # parse_method. Protocol ANALYSIS (the lattice, matching, verdicts) is
        # not in this checkpoint and no control below reaches it.
        _c("accept-protocol-minimal", "protocols",
           "a name plus an opens/closes pair is a complete protocol",
           {"ownir_version": 0, "protocols": [_proto()]}, None),
        _c("accept-protocol-full", "protocols",
           "every optional key at once: barriers, allow with narrowed args, an "
           "explicit scope, a description, and `exit_barriers` false — legal "
           "only BECAUSE a barrier is present",
           {"ownir_version": 0, "protocols": [_proto(
               barriers=[{"kind": "call", "callee": "Barrier"}],
               allow=[{"kind": "call", "callee": "Allowed", "args": ["x"]}],
               exit_barriers=False,
               scope={"methods": ["Type.Method"]},
               description="d")]}, None),
        _c("accept-protocol-call-matchers", "protocols",
           "the other matcher kind: `call`, with and without narrowed args",
           {"ownir_version": 0, "protocols": [_proto(
               opens={"kind": "call", "callee": "Begin"},
               closes={"kind": "call", "callee": "End", "args": ["a", "b"]})]},
           None),
        _c("accept-two-distinct-protocols", "protocols",
           "two protocols with DIFFERENT names — the twin that makes the "
           "duplicate-name rejection discriminating rather than a test of "
           "'more than one protocol is refused'",
           {"ownir_version": 0,
            "protocols": [_proto(name="A"), _proto(name="B")]}, None),
        _c("protocol-not-object", "protocols",
           "`protocols` is checked only for LIST-ness at the top; a scalar "
           "entry is refused by the record parser",
           {"ownir_version": 0, "protocols": [7]}, "shape"),
        _c("protocol-null-entry", "protocols", "…and null is not a record",
           {"ownir_version": 0, "protocols": [None]}, "shape"),
        _c("protocol-name-absent", "protocols",
           "the protocol name is required, not defaulted",
           {"ownir_version": 0, "protocols": [{"opens": {}, "closes": {}}]},
           "identity"),
        _c("protocol-name-empty", "protocols", "…and must be non-empty",
           {"ownir_version": 0, "protocols": [_proto(name="")]}, "identity"),
        _c("protocol-name-not-string", "protocols", "…and a string",
           {"ownir_version": 0, "protocols": [_proto(name=7)]}, "identity"),
        _c("protocol-missing-opens", "protocols",
           "a protocol without `opens` cannot state what it is tracking",
           {"ownir_version": 0, "protocols": [
               {"name": "P", "closes": {"kind": "call", "callee": "E"}}]},
           "shape"),
        _c("protocol-missing-closes", "protocols", "…and likewise `closes`",
           {"ownir_version": 0, "protocols": [
               {"name": "P", "opens": {"kind": "call", "callee": "B"}}]},
           "shape"),
        _c("protocol-opens-not-object", "protocols", "a matcher is an object",
           {"ownir_version": 0, "protocols": [_proto(opens=7)]}, "shape"),
        _c("protocol-matcher-unknown-kind", "protocols",
           "the matcher kind is a closed vocabulary (assign | call), fail-loud "
           "like a flow op",
           {"ownir_version": 0,
            "protocols": [_open(kind="teleport", target="f")]}, "vocabulary"),
        _c("protocol-matcher-kind-absent", "protocols",
           "…and absent is outside that set too",
           {"ownir_version": 0, "protocols": [_open(target="f")]}, "vocabulary"),
        _c("protocol-assign-matcher-target-empty", "protocols",
           "the assign target is the member name the rule joins events by",
           {"ownir_version": 0,
            "protocols": [_open(kind="assign", target="", value=True)]},
           "identity"),
        _c("protocol-assign-matcher-without-value", "protocols",
           "an opens/closes assign matcher must state the written boolean — "
           "'any write opens' is not a checkable protocol",
           {"ownir_version": 0,
            "protocols": [_open(kind="assign", target="f")]}, "shape"),
        _c("protocol-assign-matcher-value-not-bool", "protocols",
           "…and that value is a boolean",
           {"ownir_version": 0,
            "protocols": [_open(kind="assign", target="f", value="yes")]},
           "shape"),
        _c("protocol-call-matcher-callee-empty", "protocols",
           "the callee is the name a call event joins by",
           {"ownir_version": 0, "protocols": [_open(kind="call", callee="")]},
           "identity"),
        _c("protocol-call-matcher-args-not-strings", "protocols",
           "narrowed args are strings",
           {"ownir_version": 0,
            "protocols": [_open(kind="call", callee="C", args=[1])]}, "shape"),
        _c("protocol-barriers-not-array", "protocols", "`barriers` is an array",
           {"ownir_version": 0, "protocols": [_proto(barriers=7)]}, "shape"),
        _c("protocol-allow-not-array", "protocols", "`allow` is an array",
           {"ownir_version": 0, "protocols": [_proto(allow=7)]}, "shape"),
        _c("protocol-exit-barriers-not-bool", "protocols",
           "`exit_barriers` is a boolean",
           {"ownir_version": 0, "protocols": [_proto(exit_barriers="no")]},
           "shape"),
        _c("protocol-never-fires", "protocols",
           "no barriers AND no exit barriers: the rule can structurally never "
           "fire, which the reference refuses as decoration. Every value here "
           "is correctly typed and in vocabulary — what fails is meaning, so "
           "the category is `well_formedness`",
           {"ownir_version": 0, "protocols": [_proto(exit_barriers=False)]},
           "well_formedness"),
        _c("protocol-barrier-equals-opens", "protocols",
           "a barrier identical to `opens` is dead — the walk checks opens "
           "first, so the barrier can never fire. Same category, different "
           "mechanism: the record is well-typed and means nothing",
           {"ownir_version": 0, "protocols": [_proto(
               barriers=[{"kind": "assign", "target": "flag", "value": True}])]},
           "well_formedness"),
        _c("accept-protocol-fires-via-barrier", "protocols",
           "`exit_barriers: false` is legal WITH a barrier — the twin that "
           "makes `protocol-never-fires` a rejection about meaning rather than "
           "a rejection of the field",
           {"ownir_version": 0, "protocols": [_proto(
               exit_barriers=False,
               barriers=[{"kind": "call", "callee": "Barrier"}])]}, None),
        _c("accept-protocol-barrier-differs-from-opens", "protocols",
           "…and a barrier that is not `opens` is legal, which is what makes "
           "the equality the defect rather than the presence",
           {"ownir_version": 0, "protocols": [_proto(
               barriers=[{"kind": "assign", "target": "flag", "value": False}])]},
           None),
        _c("protocol-scope-not-object", "protocols", "`scope` is an object",
           {"ownir_version": 0, "protocols": [_proto(scope=7)]}, "shape"),
        _c("protocol-scope-methods-not-array", "protocols",
           "`scope.methods` is an array — a CONTAINER failure",
           {"ownir_version": 0, "protocols": [_proto(scope={"methods": 7})]},
           "shape"),
        _c("protocol-scope-methods-empty-entry", "protocols",
           "…of non-empty method names. The reference raises one message for "
           "this and the case above; the ledger separates them because a "
           "missing container and an unusable name are different defects",
           {"ownir_version": 0,
            "protocols": [_proto(scope={"methods": [""]})]}, "identity"),
        _c("protocol-description-not-string", "protocols",
           "`description` is a string",
           {"ownir_version": 0, "protocols": [_proto(description=7)]}, "shape"),
        _c("order-protocol-name-before-opens", "order",
           "the name is read before `opens`/`closes` are required, so a record "
           "missing everything reports identity",
           {"ownir_version": 0, "protocols": [{"name": ""}]}, "identity"),
        _c("order-protocol-opens-before-closes", "order",
           "`opens` is parsed before `closes`",
           {"ownir_version": 0, "protocols": [
               _proto(opens=7, closes={"kind": "teleport"})]}, "shape"),

        # ---- protocol_functions: the event tree ------------------------------
        _c("accept-protocol-function-minimal", "protocol_functions",
           "`events` defaults to empty, so a name alone is a valid record",
           {"ownir_version": 0, "protocol_functions": [_pfn()]}, None),
        _c("accept-protocol-function-every-event-kind", "protocol_functions",
           "all six event kinds including the two recursive ones — the "
           "acceptance side of the closed `ev` vocabulary",
           _ev({"ev": "assign", "target": "f", "value": True, "line": 1},
               {"ev": "assign", "target": "f", "line": 2},
               {"ev": "call", "callee": "C", "arg": "x", "line": 3},
               {"ev": "call", "callee": "D", "line": 4},
               {"ev": "return", "line": 5},
               {"ev": "throw", "line": 6},
               {"ev": "if", "line": 7, "then": [{"ev": "return", "line": 8}],
                "else": [{"ev": "throw", "line": 9}]},
               {"ev": "while", "line": 10,
                "body": [{"ev": "call", "callee": "E", "line": 11}]}), None),
        _c("protocol-function-not-object", "protocol_functions",
           "like `protocols`, only list-ness is checked at the top",
           {"ownir_version": 0, "protocol_functions": [7]}, "shape"),
        _c("protocol-function-null-entry", "protocol_functions",
           "…and null is not a record",
           {"ownir_version": 0, "protocol_functions": [None]}, "shape"),
        _c("protocol-function-name-empty", "protocol_functions",
           "the method name is what a protocol's scope matches against",
           {"ownir_version": 0, "protocol_functions": [_pfn(name="")]},
           "identity"),
        _c("protocol-function-name-absent", "protocol_functions",
           "…and it is required",
           {"ownir_version": 0, "protocol_functions": [{"file": "a.cs"}]},
           "identity"),
        _c("protocol-function-file-not-string", "protocol_functions",
           "`file` is optional but, present, a string",
           {"ownir_version": 0, "protocol_functions": [_pfn(file=7)]}, "shape"),
        _c("protocol-function-events-not-array", "protocol_functions",
           "`events` is an ordered array",
           {"ownir_version": 0, "protocol_functions": [_pfn(events=7)]},
           "shape"),
        _c("protocol-function-event-not-object", "protocol_functions",
           "…of objects",
           _ev(7), "shape"),
        _c("protocol-function-event-unknown-kind", "protocol_functions",
           "the `ev` discriminator is closed (IR4): a present-but-unknown value "
           "is rejected, never skipped",
           _ev({"ev": "teleport"}), "vocabulary"),
        _c("protocol-function-event-kind-absent", "protocol_functions",
           "…and an absent one is outside the set too",
           _ev({"line": 1}), "vocabulary"),
        _c("protocol-function-event-line-not-int", "protocol_functions",
           "an event line is an integer",
           _ev({"ev": "return", "line": "3"}), "shape"),
        _c("protocol-function-event-line-bool", "protocol_functions",
           "…and the bool-is-int trap reaches here as well",
           _ev({"ev": "return", "line": True}), "shape"),
        _c("protocol-function-assign-target-empty", "protocol_functions",
           "an assign event's target is a name slot",
           _ev({"ev": "assign", "target": ""}), "identity"),
        _c("protocol-function-assign-value-not-bool", "protocol_functions",
           "…its value is a boolean or absent (absent = an opaque write)",
           _ev({"ev": "assign", "target": "f", "value": "yes"}), "shape"),
        _c("protocol-function-call-callee-empty", "protocol_functions",
           "a call event's callee is a name slot",
           _ev({"ev": "call", "callee": ""}), "identity"),
        _c("protocol-function-call-arg-not-string", "protocol_functions",
           "…its distinguished arg is a string or absent",
           _ev({"ev": "call", "callee": "C", "arg": 7}), "shape"),
        _c("protocol-function-event-in-if-then", "protocol_functions",
           "the event vocabulary is enforced recursively — inside `then`",
           _ev({"ev": "if", "then": [{"ev": "teleport"}]}), "vocabulary"),
        _c("protocol-function-event-in-if-else", "protocol_functions",
           "…inside `else`",
           _ev({"ev": "if", "else": [{"ev": "teleport"}]}), "vocabulary"),
        _c("protocol-function-event-in-while-body", "protocol_functions",
           "…and inside a loop body",
           _ev({"ev": "while", "body": [{"ev": "teleport"}]}), "vocabulary"),
        _c("protocol-function-event-deeply-nested", "protocol_functions",
           "…through three levels, so a one-level-deep port fails here",
           _ev({"ev": "if", "then": [{"ev": "while", "body": [
               {"ev": "assign", "target": ""}]}]}), "identity"),
        _c("order-event-kind-before-line", "order",
           "the `ev` vocabulary is tested before the line",
           _ev({"ev": "teleport", "line": "x"}), "vocabulary"),
        _c("order-event-line-before-assign-target", "order",
           "…and the line before the per-kind fields",
           _ev({"ev": "assign", "line": "x", "target": ""}), "shape"),

        # ---- explicit null on every section ---------------------------------
        # `d.get(k, [])` returns None for a PRESENT null, so every one of these
        # is a rejection — absent and null are not the same document.
        _c("components-null", "root", "a present null is not an absent section",
           {"ownir_version": 0, "components": None}, "shape"),
        _c("services-null", "root", "…same for services",
           {"ownir_version": 0, "services": None}, "shape"),
        _c("effects-null", "root", "…effects",
           {"ownir_version": 0, "effects": None}, "shape"),
        _c("functions-null", "root", "…functions",
           {"ownir_version": 0, "functions": None}, "shape"),
        _c("protocols-null", "root", "…protocols",
           {"ownir_version": 0, "protocols": None}, "shape"),
        _c("protocol-functions-null", "root", "…and protocol_functions",
           {"ownir_version": 0, "protocol_functions": None}, "shape"),
        _c("subscriptions-null", "components", "…and one level down",
           {"ownir_version": 0, "components": [{"subscriptions": None}]},
           "shape"),
        _c("params-null", "functions", "…likewise params",
           {"ownir_version": 0, "functions": [{"params": None}]}, "shape"),
        _c("service-deps-null", "services", "…and a null string array",
           {"ownir_version": 0, "services": [_svc(deps=None)]}, "shape"),
        _c("effect-bindings-null", "effects", "…and null bindings",
           {"ownir_version": 0, "effects": [{"bindings": None}]}, "shape"),
        _c("service-line-null", "services",
           "a null scalar is not an absent scalar either",
           {"ownir_version": 0, "services": [_svc(line=None)]}, "shape"),
        _c("service-file-null", "services", "…same for a string scalar",
           {"ownir_version": 0, "services": [_svc(file=None)]}, "shape"),
        _c("subscription-resource-null", "components",
           "…and `resource` null fails the string check before the vocabulary",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"resource": None}]}]}, "shape"),
        _c("accept-column-null", "components",
           "the column is the exception: the reference returns early on None, "
           "so an explicit null IS accepted where a null line is not",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"column": None}]}]}, None),
        _c("accept-param-effect-null", "functions",
           "…and a null effect is read as absent, not as an unknown value",
           {"ownir_version": 0,
            "functions": [{"params": [{"name": "p", "effect": None}]}]}, None),
        _c("accept-function-sig-null", "functions",
           "…and a null `sig` is accepted, because the check is `is not None`",
           {"ownir_version": 0, "functions": [{"sig": None}]}, None),

        # ---- site records ----------------------------------------------------
        _c("accept-service-sites-full", "services",
           "well-formed DI004/DI005 call-site metadata",
           {"ownir_version": 0, "services": [_svc(
               root_resolve_sites=[{"type": "T", "file": "a.cs", "line": 3}],
               scope_cache_sites=[{"type": "U", "file": "b.cs", "line": 4}])]},
           None),
        _c("accept-service-site-empty-object", "services",
           "every site field is defaulted, so `{}` is a legal site",
           {"ownir_version": 0,
            "services": [_svc(root_resolve_sites=[{}])]}, None),
        _c("service-site-line-bool", "services",
           "the bool-is-int trap inside a site record",
           {"ownir_version": 0,
            "services": [_svc(root_resolve_sites=[{"line": True}])]}, "shape"),
        _c("service-site-type-not-string", "services",
           "…and a site `type` is a string",
           {"ownir_version": 0,
            "services": [_svc(root_resolve_sites=[{"type": 7}])]}, "shape"),
        _c("service-scope-cache-site-line-bool", "services",
           "…both site arrays carry the same contract",
           {"ownir_version": 0,
            "services": [_svc(scope_cache_sites=[{"line": True}])]}, "shape"),

        # ---- integer boundaries both loaders agree on ------------------------
        # Pinned at i64::MAX, where they still agree. Above it Python keeps
        # accepting and Rust stops; see "Integer width" in the module docstring.
        _c("accept-line-at-i64-max", "services",
           "the largest line both loaders accept",
           {"ownir_version": 0, "services": [_svc(line=I64_MAX)]}, None),
        _c("accept-column-at-i64-max", "components",
           "…and the largest column",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"column": I64_MAX}]}]}, None),
        _c("accept-negative-line", "services",
           "a NEGATIVE line is accepted: only columns carry the 1-based rule, "
           "and conflating the two would tighten the door",
           {"ownir_version": 0, "services": [_svc(line=-5)]}, None),
        _c("accept-zero-line", "services", "…and zero is the line default",
           {"ownir_version": 0, "services": [_svc(line=0)]}, None),
        _c("column-float", "components",
           "a float is not an integer coordinate even when it is whole",
           {"ownir_version": 0,
            "components": [{"subscriptions": [{"column": 1.0}]}]}, "location"),
        _c("service-line-float", "services",
           "…and the same for a line, where it is a shape failure instead",
           {"ownir_version": 0, "services": [_svc(line=1.0)]}, "shape"),
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
