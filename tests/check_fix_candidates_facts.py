"""Assert the S0 `--fix-candidates` extractor contract at the fact level.

Not a ``test_*`` (it needs the C# extractor to produce the facts, so CI runs the
extractor first and passes the JSON paths). Exits non-zero on any violation.

Usage:
    python tests/check_fix_candidates_facts.py <fix_on.json> [<off.json>]
    python tests/check_fix_candidates_facts.py --additive-sections <on.json> <off.json>

  fix_on = FixCandidatesSample.cs scanned WITH --fix-candidates
  off    = the SAME sample WITHOUT the flag (optional; asserts NO fix metadata leaks)

The first form checks the metadata itself on FixCandidatesSample.cs. The second
checks the other half of the contract — the flag only ADDS — on
tests/fixtures/fix_candidates/AdditiveSections.cs scanned with `--flow-locals`,
flag on and flag off:

    flag-on  minus the S0 fields  ==  flag-off          (the whole document)

and refuses a pair that does not exercise every top-level section the extractor
can write (read off the extractor's own envelope), so that the equality cannot
be satisfied by a document with nothing in it. It was: the first form's sample
has subscriptions and no other section, and a flag-on envelope that dropped
`orphaned_awaitables` — every OWN053 site — passed it for as long as it existed.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ownlang.ownir import OWNIR_VERSION, OwnIRError, check_facts

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
# The ONLY top-level field S0 adds. Everything else under --fix-candidates lives inside
# `components[]` (see `_strip_additive`); a second top-level S0 field is a contract change
# and belongs here, in the open.
_ADDITIVE_TOP_LEVEL = ("fix_candidates_version",)
_EXTRACTOR = os.path.join(_ROOT, "frontend", "roslyn", "OwnSharp.Extractor", "Program.cs")

_ADDITIVE_COMPONENT_KEYS = (
    "qualified_name",
    "is_partial",
    "is_nested",
    "declaration_count",
    "is_generated",
)


def _strip_additive(facts: dict) -> dict:
    """The flag-ON facts with every S0-additive field removed — and nothing else.

    This is the whole list of what `--fix-candidates` is allowed to change. It is an
    ALLOWLIST of S0's own fields, so the comparison it feeds is over the complete
    document: a section the flag drops, reorders or rewrites is a difference, whether
    or not anyone thought to name that section in a test."""
    f = copy.deepcopy(facts)
    for k in _ADDITIVE_TOP_LEVEL:
        f.pop(k, None)
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


def _additivity_problem(on: dict, off: dict) -> str | None:
    """`flag-on minus the S0 fields == flag-off`, or what differs."""
    stripped = _strip_additive(on)
    detail = []
    for k in sorted(k for k in set(stripped) | set(off) if stripped.get(k) != off.get(k)):
        if k not in stripped:
            detail.append(f"`{k}` is in the flag-off facts and MISSING from the flag-on facts")
        elif k not in off:
            detail.append(f"`{k}` appears only in the flag-on facts and is not an S0 field")
        else:
            detail.append(f"`{k}` differs")
    if not detail and list(stripped) != list(off):
        detail.append(f"the top-level key ORDER differs: {list(stripped)} vs {list(off)}")
    if not detail:
        return None
    return ("flag-on minus the S0 fields must equal flag-off: " + "; ".join(detail)
            + " — --fix-candidates only adds, it never removes or changes another section")


def _extractor_sections() -> list[str]:
    """The top-level keys the extractor's envelope can write, read from its source.

    The envelope is built in one place as `facts["<key>"] = ...`. Reading the keys from
    there, instead of listing them here, is what makes a NEW section fail this check
    until the fixture exercises it."""
    with open(_EXTRACTOR, encoding="utf-8") as fh:
        keys = re.findall(r'\bfacts\["([a-z_]+)"\]\s*=', fh.read())
    return list(dict.fromkeys(keys))


def _findings(facts: dict) -> list[tuple[object, ...]] | str:
    try:
        return sorted((f.code, f.file, f.line, f.column or 0, f.severity, f.message)
                      for f in check_facts(facts))
    except OwnIRError as e:
        return f"refused: {e}"


def additive_sections(on_path: str, off_path: str) -> int:
    """`--additive-sections`: the flag only adds, over EVERY section the extractor writes."""
    on, off = _load(on_path), _load(off_path)
    fails: list[str] = []

    # 1. the pair really is flag-on / flag-off, at the current version
    if on.get("fix_candidates_version") != 1 or "fix_candidates_version" in off:
        fails.append("the pair is not (flag-on, flag-off): fix_candidates_version must be 1 "
                     "in the first document and absent from the second")
    components = on.get("components")
    if not any(s.get("fix") for c in (components if isinstance(components, list) else [])
               for s in c.get("subscriptions") or []):
        fails.append("the flag-on facts carry no `fix` block: the pair does not exercise S0")
    if on.get("ownir_version") != OWNIR_VERSION or off.get("ownir_version") != OWNIR_VERSION:
        fails.append(f"ownir_version must be the core's {OWNIR_VERSION} in both documents: "
                     f"{on.get('ownir_version')!r} with the flag, "
                     f"{off.get('ownir_version')!r} without")

    # 2. not vacuous: every section the extractor CAN write is there, and not empty
    sections = [k for k in _extractor_sections() if k not in _ADDITIVE_TOP_LEVEL]
    readable = {"ownir_version", "module", "components", "functions"} <= set(sections)
    if not readable:
        fails.append(f"could not read the extractor's envelope from {_EXTRACTOR} (found "
                     f"{sections}); the envelope moved — update `_extractor_sections`")
    for k in sections:
        v = off.get(k)
        if k not in off or (isinstance(v, (list, dict)) and not v):
            fails.append(f"the fixture does not exercise `{k}`: the extractor can write it, "
                         f"and the flag-off facts have it "
                         f"{'empty' if k in off else 'absent'}. "
                         f"Extend tests/fixtures/fix_candidates/AdditiveSections.cs so the "
                         f"additivity check covers it")
    unknown = sorted(set(off) - set(sections))
    if unknown and readable:
        fails.append(f"the flag-off facts carry top-level keys this check did not find in the "
                     f"extractor's envelope: {unknown} — update `_extractor_sections`")

    # 3. the invariant itself, over the whole document
    problem = _additivity_problem(on, off)
    if problem is not None:
        fails.append(problem)

    # 4. and its consequence: the flag changes no verdict and no advisory
    got_on, got_off = _findings(on), _findings(off)
    if got_on != got_off:
        said = [g if isinstance(g, str) else f"{len(g)} finding(s)" for g in (got_on, got_off)]
        fails.append(f"the reference gives different findings with the flag ({said[0]}) "
                     f"and without it ({said[1]})")
    elif isinstance(got_off, str):
        fails.append(f"the reference refuses the fixture's facts: {got_off}")
    else:
        orphans = off.get("orphaned_awaitables") or []
        own053 = [f for f in got_off if f[0] == "OWN053"]
        if not isinstance(orphans, list) or len(own053) != len(orphans):
            fails.append(f"{len(orphans) if isinstance(orphans, list) else '?'} "
                         f"orphaned_awaitables entr(ies) but {len(own053)} OWN053 advisor(ies)")

    if fails:
        for fmsg in fails:
            print("FAIL:", fmsg, file=sys.stderr)
        return 1
    print(f"fix-candidates additivity: flag-on minus the S0 fields equals flag-off over "
          f"all {len(sections)} sections the extractor writes ({', '.join(sections)}); "
          f"the reference gives the same {len(got_off)} finding(s) with and without the flag")
    return 0


def main(on_path: str, off_path: str | None) -> int:
    on = _load(on_path)
    fails: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    # Top-level: additive version present, ownir_version untouched. "Untouched" is a
    # claim about the FLAG, not about a number: `--fix-candidates` is additive metadata,
    # so it must stamp the vocabulary version the core currently understands — the same
    # one a flag-off run stamps (compared below, where the flag-off facts are in hand).
    # This used to read `== 0`, which held only until the vocabulary first moved.
    check(on.get("fix_candidates_version") == 1, "top-level fix_candidates_version must be 1")
    check(on.get("ownir_version") == OWNIR_VERSION,
          f"--fix-candidates must not move ownir_version: the facts are stamped "
          f"{on.get('ownir_version')!r}, the core understands {OWNIR_VERSION}")

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
        # #317: and now the RECORD itself tells them apart, not just the S0 fix block.
        # Until this change the two subscriptions were indistinguishable to anything
        # reading `path + line` — which is exactly what an OwnAudit occurrence anchor
        # reads.
        check(s0["start_column"] != s1["start_column"],
              "TwoOnOneLine: the two spans must differ in COLUMN, not only in the "
              "absolute offset — a byte offset is not a coordinate")

    # #317, the cross-check that needs no expected values: every subscription record's
    # `column` must equal its own fix block's `span.start_column`. The two are computed
    # in different places (the `subs.Add` anchor from PosOf(a.Left), the fix span from
    # FixSpanOf(a)), and an assignment expression starts exactly where its left side
    # does — so agreement is required and disagreement means the anchor took its column
    # from a node other than the one it names. This holds for every sample, on every
    # run, with nothing hardcoded.
    for comp in on.get("components", []):
        for sub in comp.get("subscriptions") or []:
            fix = sub.get("fix")
            if not fix:
                continue
            span = fix["span"]
            check(sub.get("line") == span["start_line"],
                  f"{comp.get('name')}/{sub.get('event')}: record line {sub.get('line')!r} "
                  f"!= fix span start_line {span['start_line']!r}")
            check("column" in sub,
                  f"{comp.get('name')}/{sub.get('event')}: subscription record carries no "
                  "'column' — the extractor is still line-only on the anchor path (#317)")
            if "column" in sub:
                check(sub["column"] == span["start_column"],
                      f"{comp.get('name')}/{sub.get('event')}: record column "
                      f"{sub['column']!r} != fix span start_column "
                      f"{span['start_column']!r} — two coordinates for one node")

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
        # handler half: method symbol != delegate identity, storage symbol != value
        ("HandlerDifferentTarget", "none", "stable_symbol", "computed"),
        ("HandlerReassignedField", "ambiguous", "stable_symbol", "computed"),
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
        check(on.get("ownir_version") == off.get("ownir_version"),
              f"the flag moved ownir_version: {off.get('ownir_version')!r} without it, "
              f"{on.get('ownir_version')!r} with it")
        for c in off.get("components", []):  # type: ignore[union-attr]
            check("qualified_name" not in c, f"flag-off: {c.get('name')} has qualified_name")
            for s in c.get("subscriptions") or []:
                check("fix" not in s, "flag-off: a subscription carries a fix block")
        # Additivity, positively: strip every additive field from the flag-ON facts and
        # the result must EQUAL the flag-off facts (same records, same order, same old
        # values) -- enabling the metadata changed nothing pre-existing.
        problem = _additivity_problem(on, off)
        check(problem is None, problem or "")

    if fails:
        for fmsg in fails:
            print("FAIL:", fmsg, file=sys.stderr)
        return 1
    print("fix-candidates facts: all checks pass")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--additive-sections":
        raise SystemExit(additive_sections(sys.argv[2], sys.argv[3]))
    if len(sys.argv) not in (2, 3) or sys.argv[1].startswith("--"):
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None))
