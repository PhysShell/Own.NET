"""Assert the S0 `--fix-candidates` extractor metadata on FixCandidatesSample.cs.

Not a ``test_*`` (it needs the C# extractor to produce the facts, so CI runs the
extractor first and passes the JSON path). Encodes the Part-A extractor contract
at the fact level; exits non-zero on any violation.

Usage:
    python tests/check_fix_candidates_facts.py <fix_on.json> [<off.json>]

  fix_on = FixCandidatesSample.cs scanned WITH --fix-candidates
  off    = the SAME sample WITHOUT the flag (optional; asserts NO fix metadata leaks)
"""

from __future__ import annotations

import copy
import json
import sys

_ADDITIVE_COMPONENT_KEYS = (
    "qualified_name",
    "is_partial",
    "is_nested",
    "declaration_count",
    "is_generated",
)


def _strip_additive(facts: dict) -> dict:
    """The flag-ON facts with every S0-additive field removed."""
    f = copy.deepcopy(facts)
    f.pop("fix_candidates_version", None)
    for c in f.get("components", []):
        for k in _ADDITIVE_COMPONENT_KEYS:
            c.pop(k, None)
        for s in c.get("subscriptions") or []:
            s.pop("fix", None)
    return f


def _load(path: str) -> dict[str, object]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _component(facts: dict, name: str) -> dict | None:
    for c in facts.get("components", []):  # type: ignore[union-attr]
        if c.get("name") == name:
            return c
    return None


def _fixes(facts: dict, name: str) -> list[dict]:
    comp = _component(facts, name)
    if comp is None:
        return []
    return [s["fix"] for s in (comp.get("subscriptions") or []) if s.get("fix")]


def main(on_path: str, off_path: str | None) -> int:
    on = _load(on_path)
    fails: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    # Top-level: additive version present, ownir_version untouched.
    check(on.get("fix_candidates_version") == 1, "top-level fix_candidates_version must be 1")
    check(on.get("ownir_version") == 0, "ownir_version must stay 0")

    def only_fix(name: str) -> dict | None:
        fx = _fixes(on, name)
        check(len(fx) == 1, f"{name}: expected exactly one fix block, got {len(fx)}")
        return fx[0] if fx else None

    # INPC + exact teardown (stable source + stable handler, stable candidate match).
    f = only_fix("InpcExactTeardown")
    if f:
        check(f["event_contract"] == "inotify_property_changed", "InpcExactTeardown: contract")
        check(f["teardown"]["status"] == "exact", "InpcExactTeardown: teardown exact")
        cands = f["teardown"]["candidates"]
        check(len(cands) == 1, "InpcExactTeardown: one teardown candidate")
        check(f["source_identity_kind"] == "stable_symbol", "InpcExactTeardown: source stable")
        check(f["handler_identity_kind"] == "stable_symbol", "InpcExactTeardown: handler stable")
        check(bool(cands) and cands[0]["match"] == "stable", "InpcExactTeardown: candidate stable")

    # INPC + no teardown.
    f = only_fix("InpcNoTeardown")
    if f:
        check(f["event_contract"] == "inotify_property_changed", "InpcNoTeardown: contract")
        check(f["teardown"]["status"] == "none", "InpcNoTeardown: teardown none")

    # INPC + two -= -> ambiguous.
    f = only_fix("InpcAmbiguousTeardown")
    if f:
        check(f["teardown"]["status"] == "ambiguous", "InpcAmbiguousTeardown: teardown ambiguous")
        check(len(f["teardown"]["candidates"]) == 2, "InpcAmbiguousTeardown: 2 candidates")

    # Event NAMED PropertyChanged but not INotifyPropertyChanged.
    f = only_fix("NameOnlySubscriber")
    if f:
        check(f["event_contract"] == "name_only", "NameOnlySubscriber: must be name_only")

    # Unrelated event.
    f = only_fix("OtherEventSubscriber")
    if f:
        check(f["event_contract"] == "other", "OtherEventSubscriber: must be other")

    # Two subscriptions on one line: same start_line, DIFFERENT span.start.
    two = _fixes(on, "TwoOnOneLine")
    check(len(two) == 2, f"TwoOnOneLine: expected two fix blocks, got {len(two)}")
    if len(two) == 2:
        s0, s1 = two[0]["span"], two[1]["span"]
        check(s0["start_line"] == s1["start_line"], "TwoOnOneLine: same line")
        check(s0["start"] != s1["start"], "TwoOnOneLine: spans must differ (full span)")

    # Wrapped delegate: handler NORMALIZED to the method, teardown still exact.
    f = only_fix("WrappedDelegate")
    if f:
        hid = f["handler_identity"]
        check(
            "OnChanged(" in hid and "PropertyChangedEventHandler" not in hid,
            f"WrappedDelegate: handler must normalize to the method, got {hid!r}",
        )
        check(f["teardown"]["status"] == "exact", "WrappedDelegate: teardown must be exact")

    # Nested-type isolation: the outer component carries ONLY its own subscription
    # as a fix candidate; the nested class's subscription is fixed under Nested.
    outer = _fixes(on, "OuterWithNested")
    check(len(outer) == 1, f"OuterWithNested: outer must have exactly one fix, got {len(outer)}")
    if outer:
        check("OnOuter(" in outer[0]["handler_identity"], "OuterWithNested: fix must be OnOuter")
    nested_comp = _component(on, "Nested")
    is_nested = nested_comp is not None and nested_comp.get("is_nested") is True
    check(is_nested, "Nested: is_nested must be true")
    nested = _fixes(on, "Nested")
    check(len(nested) == 1, "Nested: must carry its own OnNested fix")

    # Component qualified_name is a real FQN.
    comp = _component(on, "InpcExactTeardown")
    fqn = comp.get("qualified_name") if comp else None
    check(
        fqn == "Own.Samples.FixCandidates.InpcExactTeardown",
        "InpcExactTeardown: qualified_name must be the FQN",
    )

    # Blocker-1: a computed/unresolved receiver or handler must NEVER be exact.
    b1 = [
        ("ComputedReceiverInvocation", "ambiguous", "computed", "stable_symbol"),
        ("ComputedReceiverProperty", "ambiguous", "computed", "stable_symbol"),
        ("DifferentRoots", "none", "computed", "stable_symbol"),
        ("ComputedHandler", "ambiguous", "stable_symbol", "computed"),
    ]
    for name, status, srck, hk in b1:
        f = only_fix(name)
        if f:
            check(f["teardown"]["status"] == status, f"{name}: teardown must be {status}")
            check(f["teardown"]["status"] != "exact", f"{name}: must NOT be exact")
            check(f["source_identity_kind"] == srck, f"{name}: source_identity_kind {srck}")
            check(f["handler_identity_kind"] == hk, f"{name}: handler_identity_kind {hk}")

    # Blocker-2: occurrence_ordinal is scoped by enclosing member.
    across = _fixes(on, "OrdinalAcrossMembers")
    check(len(across) == 2, f"OrdinalAcrossMembers: expected 2 fixes, got {len(across)}")
    if len(across) == 2:
        check(all(x["occurrence_ordinal"] == 0 for x in across), "OrdinalAcrossMembers: each ord 0")
        check(
            across[0]["enclosing_member"] != across[1]["enclosing_member"],
            "OrdinalAcrossMembers: distinct enclosing members",
        )
    within = _fixes(on, "OrdinalWithinMember")
    check(len(within) == 2, f"OrdinalWithinMember: expected 2 fixes, got {len(within)}")
    if len(within) == 2:
        check(
            {x["occurrence_ordinal"] for x in within} == {0, 1},
            "OrdinalWithinMember: ordinals must be 0 and 1",
        )
        check(
            within[0]["enclosing_member"] == within[1]["enclosing_member"],
            "OrdinalWithinMember: same enclosing member",
        )
    refov = _fixes(on, "RefOverloadEnclosing")
    check(len(refov) == 2, f"RefOverloadEnclosing: expected 2 fixes, got {len(refov)}")
    if len(refov) == 2:
        encls = {x["enclosing_member"] for x in refov}
        check(len(encls) == 2, "RefOverloadEnclosing: ref/value overloads need distinct signatures")
        check(any("ref " in e for e in encls), "RefOverloadEnclosing: a signature must show `ref`")

    # Off-run must carry NO fix metadata at all.
    if off_path is not None:
        off = _load(off_path)
        check("fix_candidates_version" not in off, "flag-off: no fix_candidates_version")
        for c in off.get("components", []):  # type: ignore[union-attr]
            check("qualified_name" not in c, f"flag-off: {c.get('name')} has qualified_name")
            for s in c.get("subscriptions") or []:
                check("fix" not in s, "flag-off: a subscription carries a fix block")
        # Additivity, positively: strip every additive field from the flag-ON facts and
        # the result must EQUAL the flag-off facts (same records, same order, same old
        # values) -- enabling the metadata changed nothing pre-existing.
        check(_strip_additive(on) == off, "flag-on minus additive fields must equal flag-off")

    if fails:
        for fmsg in fails:
            print("FAIL:", fmsg, file=sys.stderr)
        return 1
    print("fix-candidates facts: all checks pass")
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None))
