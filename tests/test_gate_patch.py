"""S2 step 9 — the gate's pure functions and the tampering cases that need forged bytes.

These call the validators / patch parser directly, so they run WITHOUT dotnet or git (the
`tests (pyX)` job). The filesystem-real cases — symlink entries, git-apply semantics,
publication — live in tests/gate_regressions.sh, which drives the whole chain.

Every forged fixture that must reach a SPECIFIC gate rebinds the upstream bindings it would
otherwise trip first (bundle_sha256, the canonical plan projection), so the refusal comes
from the branch under test — a test that refuses for the wrong reason is not a test.
"""

from __future__ import annotations

import hashlib
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ownlang.fix_gate import (
    AUTHORITY_BINDING,
    MANIFEST_SHAPE,
    PATCH_STRUCTURE,
    GateError,
    _bundle_sha256,
    _same_or_inside,
    parse_step8_patch,
    validate_gate_authority,
    validate_manifest_shape,
)

checks = 0
failures: list[str] = []


def check(cond: bool, label: str) -> None:
    global checks
    checks += 1
    if not cond:
        failures.append(label)


def refuses(fn: Any, category: str, label: str) -> None:
    global checks
    checks += 1
    try:
        fn()
    except GateError as exc:
        if exc.category != category:
            failures.append(f"{label}: category {exc.category} != {category} ({exc})")
        return
    except Exception as exc:
        failures.append(f"{label}: raised {type(exc).__name__}, not GateError ({exc})")
        return
    failures.append(f"{label}: expected a GateError[{category}]")


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def cp(o: Any) -> Any:
    import json
    return json.loads(json.dumps(o))


REL = "src/Sample.cs"
PRE = b"class A\n{\n    void M()\n    {\n        p.PropertyChanged += OnX;\n    }\n}\n"
POST = PRE.replace(b"p.PropertyChanged += OnX;", b"WeakEvents.AddPropertyChanged(p, OnX);")
FID_A = "OWN001:sha256:" + "a" * 64
FID_B = "OWN050:sha256:" + "b" * 64


def a_span(start: int) -> dict[str, int]:
    return {"start": start, "length": 10, "start_line": 5, "start_column": 9,
            "end_line": 5, "end_column": 19}


def a_candidate(fid: str, start: int, contract: str = "inotify_property_changed",
                actions: list[str] | None = None) -> dict[str, Any]:
    return {
        "finding_id": fid,
        "diagnostic_code": "OWN001",
        "containing_type": "N.A",
        "file": REL,
        "enclosing_member": "N.A..ctor(N.IPub)",
        "event": "PropertyChanged",
        "event_identity": "System.ComponentModel.INotifyPropertyChanged.PropertyChanged",
        "event_contract": contract,
        "source": "p",
        "source_identity": "p",
        "source_identity_kind": "computed",
        "handler": "OnX",
        "handler_identity": "N.A.OnX(object, System.ComponentModel.PropertyChangedEventArgs)",
        "handler_identity_kind": "stable_symbol",
        "occurrence_ordinal": 0,
        "acquire_span": a_span(start),
        "teardown": {"status": "none", "candidates": []},
        "allowed_actions": actions or ["convert_acquire", "manual_review"],
    }


def base_candidates() -> dict[str, Any]:
    return {
        "version": 1,
        "operation": "fix-subscriptions",
        "target_api": {"subscribe": "WeakEvents.AddPropertyChanged"},
        "selection": {
            "allowed_types": [{"full_name": "N.A", "file": REL}],
            "selected_findings": None,
            "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                            "allow_helper_changes": False, "allow_config_changes": False,
                            "allow_suppressions": False},
        },
        "source_files": [{"path": REL, "sha256": sha(PRE)}],
        "candidates": [a_candidate(FID_A, 40), a_candidate(FID_B, 80)],
    }


def plan_for(cands: dict[str, Any], actions: list[str]) -> dict[str, Any]:
    return {
        "version": 1,
        "operation": "fix-subscriptions",
        "input_bundle_sha256": _bundle_sha256(cands),
        "target_api": {"subscribe": cands["target_api"]["subscribe"]},
        "selection": {
            "allowed_types": [dict(cands["selection"]["allowed_types"][0])],
            "selected_findings": cands["selection"]["selected_findings"],
            "constraints": dict(cands["selection"]["constraints"]),
        },
        "source_files": [dict(cands["source_files"][0])],
        "decisions": [
            {"finding_id": c["finding_id"], "action": actions[i], "file": c["file"],
             "acquire_span": c["acquire_span"]}
            for i, c in enumerate(cands["candidates"])
        ],
    }


# --- authority validator -----------------------------------------------------------

cands = base_candidates()
plan = plan_for(cands, ["convert_acquire", "manual_review"])
auth = validate_gate_authority(plan, cands)
check(auth.rel == REL, "authority: rel")
check(auth.applied == [FID_A] and auth.manual == [FID_B], "authority: partition in candidate order")
check(auth.pre_sha256 == sha(PRE), "authority: pre_sha256")
check(auth.input_bundle_sha256 == _bundle_sha256(cands), "authority: input_bundle_sha256")

# A forged permission tier: name_only claiming convert_acquire, freshly re-bound so only
# the tiering can refuse it.
forged = base_candidates()
forged["candidates"][0]["event_contract"] = "name_only"
refuses(lambda: validate_gate_authority(plan_for(forged, ["convert_acquire", "manual_review"]),
                                        forged), AUTHORITY_BINDING, "authority: forged tier")

# The hash must actually bind.
bad_hash = plan_for(cands, ["convert_acquire", "manual_review"])
bad_hash["input_bundle_sha256"] = "sha256:" + "0" * 64
refuses(lambda: validate_gate_authority(bad_hash, cands), AUTHORITY_BINDING,
        "authority: hash does not bind")

# Decision order must equal candidate order.
reordered = plan_for(cands, ["convert_acquire", "manual_review"])
reordered["decisions"].reverse()
refuses(lambda: validate_gate_authority(reordered, cands), AUTHORITY_BINDING,
        "authority: decisions out of candidate order")

# An unknown key anywhere in the envelope.
extra = plan_for(cands, ["convert_acquire", "manual_review"])
extra["autofix_everything"] = True
refuses(lambda: validate_gate_authority(extra, cands), AUTHORITY_BINDING,
        "authority: unknown plan key")
extra_c = base_candidates()
extra_c["candidates"][0]["surprise"] = 1
refuses(lambda: validate_gate_authority(plan_for(extra_c, ["convert_acquire", "manual_review"]),
                                        extra_c),
        AUTHORITY_BINDING, "authority: unknown candidate key")

# The type file and the source file must be the same file.
drift = base_candidates()
drift["selection"]["allowed_types"][0]["file"] = "src/Other.cs"
refuses(lambda: validate_gate_authority(plan_for(drift, ["convert_acquire", "manual_review"]),
                                        drift),
        AUTHORITY_BINDING, "authority: type/source file drift")

# An action outside the candidate's own allowed list (the candidate only permits
# manual_review, the plan tries to convert it).
def base_no_convert() -> dict[str, Any]:
    c = base_candidates()
    c["candidates"][1]["event_contract"] = "name_only"
    c["candidates"][1]["allowed_actions"] = ["manual_review"]
    return c


nc = base_no_convert()
refuses(lambda: validate_gate_authority(plan_for(nc, ["convert_acquire", "convert_acquire"]), nc),
        AUTHORITY_BINDING, "authority: action not in candidate's allowed list")

# A span that disagrees between decision and candidate.
span_drift = plan_for(cands, ["convert_acquire", "manual_review"])
span_drift["decisions"][0]["acquire_span"] = a_span(999)
refuses(lambda: validate_gate_authority(span_drift, cands), AUTHORITY_BINDING,
        "authority: decision span != candidate")

# selected_findings must name exactly the candidates.
sel = base_candidates()
sel["selection"]["selected_findings"] = [FID_A]
refuses(lambda: validate_gate_authority(plan_for(sel, ["convert_acquire", "manual_review"]), sel),
        AUTHORITY_BINDING, "authority: selected_findings incomplete")


# Full value / nested-shape validation of the frozen candidate (amendment 2): the exact key
# set alone is not enough — a wrong-typed value or a malformed teardown on a re-hashed bundle
# must still be refused, so each fixture is bound through plan_for.
def tamper(mut: Any, label: str) -> None:
    c = base_candidates()
    mut(c["candidates"][0])
    refuses(lambda: validate_gate_authority(plan_for(c, ["convert_acquire", "manual_review"]), c),
            AUTHORITY_BINDING, label)


def _set(key: str, value: Any) -> Any:
    return lambda cand: cand.__setitem__(key, value)


tamper(_set("event_identity", 123), "authority: event_identity wrong type")
tamper(_set("occurrence_ordinal", "banana"), "authority: occurrence_ordinal wrong type")
tamper(_set("occurrence_ordinal", -1), "authority: occurrence_ordinal negative")
tamper(_set("diagnostic_code", 7), "authority: diagnostic_code wrong type")
tamper(_set("enclosing_member", None), "authority: enclosing_member wrong type")
tamper(lambda c: c["teardown"].__setitem__("whatever", True), "authority: teardown extra key")
tamper(lambda c: c["teardown"].__setitem__("status", "maybe"), "authority: teardown unknown status")
tamper(_set("teardown", {"status": "exact", "candidates": [{"source": "a"}]}),
       "authority: teardown candidate malformed")
tamper(_set("teardown", {"status": "exact", "candidates": [
    {"source": "a", "handler": "b", "match": "text", "span": {"start": 1, "length": 2}}]}),
    "authority: teardown candidate span shape")


# --- manifest shape ----------------------------------------------------------------


def a_manifest(**over: Any) -> dict[str, Any]:
    m = {
        "version": 1,
        "operation": "apply-subscription-fixes",
        "input_bundle_sha256": _bundle_sha256(cands),
        "validated_plan_sha256": "sha256:" + "d" * 64,
        "target_api": {"subscribe": "WeakEvents.AddPropertyChanged"},
        "source_files": [{"path": REL, "pre_sha256": sha(PRE), "post_sha256": sha(POST)}],
        "applied_findings": [FID_A],
        "manual_review_findings": [FID_B],
        "patch_sha256": sha(b"x"),
    }
    m.update(over)
    return m


rel_m, pre_m, post_m, patch_m = validate_manifest_shape(a_manifest())
check((rel_m, pre_m, post_m) == (REL, sha(PRE), sha(POST)), "manifest: returns rel + shas")
refuses(lambda: validate_manifest_shape(a_manifest(surprise=1)), MANIFEST_SHAPE,
        "manifest: extra key")
refuses(lambda: validate_manifest_shape(a_manifest(version=2)), MANIFEST_SHAPE,
        "manifest: bad version")
refuses(lambda: validate_manifest_shape(a_manifest(operation="rm -rf")), MANIFEST_SHAPE,
        "manifest: bad operation")
refuses(lambda: validate_manifest_shape(a_manifest(patch_sha256="nope")), MANIFEST_SHAPE,
        "manifest: bad sha format")
refuses(lambda: validate_manifest_shape(a_manifest(applied_findings=[FID_A, FID_A])),
        MANIFEST_SHAPE, "manifest: duplicate findings")
refuses(lambda: validate_manifest_shape(a_manifest(applied_findings=[FID_A],
                                                   manual_review_findings=[FID_A])),
        MANIFEST_SHAPE, "manifest: overlapping partitions")
refuses(lambda: validate_manifest_shape(a_manifest(
    source_files=[{"path": "/abs/x.cs", "pre_sha256": sha(PRE), "post_sha256": sha(POST)}])),
    MANIFEST_SHAPE, "manifest: non-canonical path")
refuses(lambda: validate_manifest_shape(a_manifest(source_files=[])), MANIFEST_SHAPE,
        "manifest: not exactly one source file")


# --- the strict step 8 patch language ----------------------------------------------

GOOD = (b"diff --git a/" + REL.encode() + b" b/" + REL.encode() + b"\n"
        b"--- a/" + REL.encode() + b"\n"
        b"+++ b/" + REL.encode() + b"\n"
        b"@@ -5,1 +5,1 @@\n"
        b"-        p.PropertyChanged += OnX;\n"
        b"+        WeakEvents.AddPropertyChanged(p, OnX);\n")

parse_step8_patch(GOOD, REL, PRE)  # must not raise
check(True, "patch: a canonical step 8 patch parses")
parse_step8_patch(b"", REL, PRE)  # the empty patch is structurally fine here
check(True, "patch: the empty patch parses")

# A space in the path is legal and must be accepted (git reads names literally).
SP = "src/with space.cs"
sp_patch = (b"diff --git a/" + SP.encode() + b" b/" + SP.encode() + b"\n"
            b"--- a/" + SP.encode() + b"\n+++ b/" + SP.encode() + b"\n"
            b"@@ -1,1 +1,1 @@\n-a\n+b\n")
parse_step8_patch(sp_patch, SP, b"a\n")
check(True, "patch: a space in the path is accepted")


def variant(replace_pairs: list[tuple[bytes, bytes]], insert_after: bytes = b"",
            extra: bytes = b"") -> bytes:
    p = GOOD
    for a, b in replace_pairs:
        p = p.replace(a, b)
    if insert_after:
        p = p.replace(insert_after, insert_after + extra)
    return p


REB = REL.encode()
# A second file.
_SECOND = (b"diff --git a/other.cs b/other.cs\n--- a/other.cs\n"
           b"+++ b/other.cs\n@@ -1 +1 @@\n-a\n+b\n")
refuses(lambda: parse_step8_patch(GOOD + _SECOND, REL, PRE),
        PATCH_STRUCTURE, "patch: a second file")
# Wrong header path.
refuses(lambda: parse_step8_patch(GOOD.replace(b"a/" + REB, b"a/evil.cs", 1), REL, PRE),
        PATCH_STRUCTURE, "patch: wrong '---' path")
# A rename / copy / mode / index / binary record grafted in.
for rec, name in ((b"rename from x\n", "rename"), (b"copy from x\n", "copy"),
                  (b"old mode 100644\n", "mode"), (b"index abc..def 100644\n", "index"),
                  (b"GIT binary patch\n", "binary"),
                  (b"new file mode 100644\n", "new-file"),
                  (b"deleted file mode 100644\n", "deleted-file")):
    refuses(lambda r=rec: parse_step8_patch(
        GOOD.replace(b"@@ -5,1", r + b"@@ -5,1", 1), REL, PRE),
        PATCH_STRUCTURE, f"patch: a {name} record")
# An absolute or traversal path in the header.
refuses(lambda: parse_step8_patch(
    (b"diff --git a//etc/passwd b//etc/passwd\n--- a//etc/passwd\n"
     b"+++ b//etc/passwd\n@@ -1 +1 @@\n-a\n+b\n"), REL, PRE),
    PATCH_STRUCTURE, "patch: an absolute path")
refuses(lambda: parse_step8_patch(GOOD.replace(REB, b"../../etc/passwd"), REL, PRE),
        PATCH_STRUCTURE, "patch: a traversal path")
# A quoted (C-escaped) alternate filename never matches the exact expected header.
refuses(lambda: parse_step8_patch(GOOD.replace(b"a/" + REB, b"\"a/" + REB + b"\"", 1),
                                  REL, PRE), PATCH_STRUCTURE, "patch: a quoted path")
# Hunk arithmetic that does not add up.
refuses(lambda: parse_step8_patch(GOOD.replace(b"@@ -5,1 +5,1 @@", b"@@ -5,2 +5,1 @@"),
                                  REL, PRE), PATCH_STRUCTURE, "patch: wrong old count")
# A malformed hunk header.
refuses(lambda: parse_step8_patch(GOOD.replace(b"@@ -5,1 +5,1 @@", b"@@ nonsense @@"),
                                  REL, PRE), PATCH_STRUCTURE, "patch: malformed hunk header")
# An unterminated final line.
refuses(lambda: parse_step8_patch(GOOD[:-1], REL, PRE), PATCH_STRUCTURE,
        "patch: unterminated final line")
# A hunk range past the end of the preimage.
refuses(lambda: parse_step8_patch(GOOD.replace(b"@@ -5,1 +5,1 @@", b"@@ -99,1 +99,1 @@"),
                                  REL, PRE), PATCH_STRUCTURE, "patch: range past the preimage")

# --- the no-newline marker + range invariants (amendment / blocker 5) --------------

PRE3 = b"a\nb\nc\n"
X = "x.cs"


def small(hunk: bytes) -> bytes:
    xb = X.encode()
    return (b"diff --git a/" + xb + b" b/" + xb + b"\n--- a/" + xb + b"\n+++ b/" + xb + b"\n"
            + hunk)


parse_step8_patch(small(b"@@ -1,1 +1,1 @@\n-a\n+z\n"), X, PRE3)
check(True, "patch: a minimal single-line change parses")
# A legitimate no-newline marker on the last line of each side.
parse_step8_patch(small(b"@@ -3,1 +3,1 @@\n-c\n\\ No newline at end of file\n+z\n"
                         b"\\ No newline at end of file\n"), X, b"a\nb\nc")
check(True, "patch: a well-placed no-newline marker parses")
# A marker before any eligible line.
refuses(lambda: parse_step8_patch(
    small(b"@@ -1,1 +1,1 @@\n\\ No newline at end of file\n-a\n+z\n"), X, PRE3),
    PATCH_STRUCTURE, "patch: marker before any line")
# Two markers in a row (a duplicate / stray marker).
refuses(lambda: parse_step8_patch(
    small(b"@@ -1,1 +1,1 @@\n-a\n\\ No newline at end of file\n"
          b"\\ No newline at end of file\n+z\n"), X, PRE3),
    PATCH_STRUCTURE, "patch: a duplicate no-newline marker")
# A marker on a line that is NOT the last of its side.
refuses(lambda: parse_step8_patch(
    small(b"@@ -1,2 +1,1 @@\n-a\n\\ No newline at end of file\n-b\n+z\n"), X, PRE3),
    PATCH_STRUCTURE, "patch: marker with more of the same side after it")
# A zero-length (insertion) range whose start is past the preimage.
refuses(lambda: parse_step8_patch(small(b"@@ -99,0 +4,1 @@\n+z\n"), X, PRE3),
        PATCH_STRUCTURE, "patch: an insertion range past the preimage")
# A non-zero range starting at line 0.
refuses(lambda: parse_step8_patch(small(b"@@ -0,1 +1,1 @@\n-a\n+z\n"), X, PRE3),
        PATCH_STRUCTURE, "patch: a non-zero range starting at 0")
# A valid pure insertion at the top (old range -0,0).
parse_step8_patch(small(b"@@ -0,0 +1,1 @@\n+z\n"), X, PRE3)
check(True, "patch: a pure insertion at the top parses")


# --- containment platform rule -----------------------------------------------------

check(_same_or_inside("/repo", "/repo"), "containment: root contains itself")
check(_same_or_inside("/repo", "/repo/sub/x"), "containment: a descendant")
check(not _same_or_inside("/repo", "/repository"), "containment: a name prefix is not inside")
check(not _same_or_inside("/repo", "/other"), "containment: unrelated is outside")
if os.name == "nt":
    check(_same_or_inside("C:\\Repo", "c:\\repo\\x"), "containment: Windows case-insensitive")
else:
    check(not _same_or_inside("/repo", "/REPO/x"), "containment: POSIX case-sensitive")


def run() -> int:
    """The aggregate contract run_tests.py expects: report + an int rc, NEVER a
    process-ending sys.exit at import time (which would silence every later module)."""
    print(f"gate (S2 step 9): {checks - len(failures)}/{checks} checks pass")
    for f in failures:
        print(f"  FAIL: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
