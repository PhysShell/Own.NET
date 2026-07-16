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

import json
import sys


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

    # INPC + exact teardown.
    f = only_fix("InpcExactTeardown")
    if f:
        check(f["event_contract"] == "inotify_property_changed", "InpcExactTeardown: contract")
        check(f["teardown"]["status"] == "exact", "InpcExactTeardown: teardown exact")
        check(len(f["teardown"]["candidates"]) == 1, "InpcExactTeardown: one teardown candidate")

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

    # Off-run must carry NO fix metadata at all.
    if off_path is not None:
        off = _load(off_path)
        check("fix_candidates_version" not in off, "flag-off: no fix_candidates_version")
        for c in off.get("components", []):  # type: ignore[union-attr]
            check("qualified_name" not in c, f"flag-off: {c.get('name')} has qualified_name")
            for s in c.get("subscriptions") or []:
                check("fix" not in s, "flag-off: a subscription carries a fix block")

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
