"""S2 step 8 — the canonical patch bundle, at the pure-function level.

The tampering cases live here rather than in the shell suite on purpose: forging a
rewriter-report requires WRITING a bad transport artifact, and the production rewriter
must not grow a test-only hook that can emit one. These call the validator directly with
a hand-built workdir, which is both stricter and honest about what is being tested.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ownlang.fix_apply import ApplyError
from ownlang.fix_bundle import (
    _same_or_inside,
    build_manifest,
    canonical_patch,
    manifest_bytes,
    split_rewriter_command,
    validate_rewriter_output,
)

checks = 0
failures: list[str] = []


def check(cond: bool, label: str) -> None:
    global checks
    checks += 1
    if not cond:
        failures.append(label)


def refuses(fn: Any, label: str, needle: str = "") -> None:
    global checks
    checks += 1
    try:
        fn()
    except ApplyError as exc:
        if needle and needle not in str(exc):
            failures.append(f"{label}: wrong refusal: {exc}")
        return
    failures.append(f"{label}: expected an ApplyError")


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


REL = "src/Sample.cs"
PRE = b"class A\n{\n    void M()\n    {\n        p.PropertyChanged += OnX;\n    }\n}\n"
POST = PRE.replace(b"p.PropertyChanged += OnX;", b"Weak.Add(p, OnX);")
FID_A = "OWN001:sha256:" + "a" * 64
FID_B = "OWN001:sha256:" + "b" * 64


def a_plan(actions: tuple[str, ...] = ("convert_acquire", "manual_review")) -> dict[str, Any]:
    return {
        "version": 1,
        "operation": "fix-subscriptions",
        "input_bundle_sha256": "sha256:" + "c" * 64,
        "target_api": {"subscribe": "Weak.Add"},
        "selection": {"allowed_types": [{"full_name": "N.A", "file": REL}],
                      "selected_findings": None,
                      "constraints": {"max_types_changed": 1, "max_files_changed": 1,
                                      "allow_helper_changes": False,
                                      "allow_config_changes": False,
                                      "allow_suppressions": False}},
        "source_files": [{"path": REL, "sha256": sha(PRE)}],
        "decisions": [
            {"finding_id": FID_A, "action": actions[0], "file": REL,
             "acquire_span": {"start": 0, "length": 1}},
            {"finding_id": FID_B, "action": actions[1], "file": REL,
             "acquire_span": {"start": 2, "length": 1}},
        ],
    }


PLAN_SHA = "sha256:" + "d" * 64


def a_report(**over: Any) -> dict[str, Any]:
    report = {
        "version": 1,
        "operation": "apply-subscription-fixes",
        "input_bundle_sha256": "sha256:" + "c" * 64,
        "validated_plan_sha256": PLAN_SHA,
        "target_api": {"subscribe": "Weak.Add"},
        "source_files": [{"path": REL, "pre_sha256": sha(PRE), "post_sha256": sha(POST)}],
        "applied_findings": [FID_A],
        "manual_review_findings": [FID_B],
    }
    report.update(over)
    return report


def workdir(tmp: str, report: dict[str, Any] | None, post: bytes | None = POST,
            extra: str | None = None) -> str:
    wd = tempfile.mkdtemp(dir=tmp)
    if report is not None:
        with open(os.path.join(wd, "rewriter-report.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh)
    if post is not None:
        target = os.path.join(wd, "postimage", *REL.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(post)
    if extra is not None:
        with open(os.path.join(wd, extra), "wb") as fh:
            fh.write(b"surprise")
    return wd


def validate(wd: str) -> bytes:
    return validate_rewriter_output(wd, a_plan(), PLAN_SHA, REL, sha(PRE), {FID_A}, {FID_B})


# --- the canonical patch -----------------------------------------------------------

patch = canonical_patch(REL, PRE, POST)
check(patch.startswith(b"diff --git a/src/Sample.cs b/src/Sample.cs\n"), "patch: git header")
check(b"--- a/src/Sample.cs\n" in patch, "patch: --- header")
check(b"+++ b/src/Sample.cs\n" in patch, "patch: +++ header")
check(b"-        p.PropertyChanged += OnX;\n" in patch, "patch: the removed line")
check(b"+        Weak.Add(p, OnX);\n" in patch, "patch: the added line")
check(b"@@ -" in patch, "patch: a hunk header")
check(patch == canonical_patch(REL, PRE, POST), "patch: deterministic")
check(b"\t" not in patch, "patch: no timestamp column")
check(b"/tmp" not in patch and b"C:" not in patch, "patch: no absolute/temp paths")
check(b"rename" not in patch and b"old mode" not in patch, "patch: no rename/mode records")
check(canonical_patch(REL, PRE, PRE) == b"", "patch: an unchanged file is the empty patch")
check(sha(b"") == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "patch: the empty-patch sha is sha256 of no bytes")

# A lone \r is CONTENT, not a line break: bytes.splitlines() would disagree and reflow.
cr_pre = b"a = \"x\ry\";\nb;\n"
cr_post = b"a = \"x\ry\";\nc;\n"
cr_patch = canonical_patch(REL, cr_pre, cr_post)
check(b" a = \"x\ry\";\n" in cr_patch, "patch: a lone \\r stays inside its line")

# No trailing newline at EOF needs git's own marker on both sides.
nn = canonical_patch(REL, b"x;\ny;", b"x;\nz;")
check(nn.count(b"\\ No newline at end of file\n") == 2, "patch: the no-newline marker")

# CRLF survives as content.
crlf = canonical_patch(REL, b"a;\r\nb;\r\n", b"a;\r\nc;\r\n")
check(b"-b;\r\n" in crlf and b"+c;\r\n" in crlf, "patch: CRLF lines are preserved")

# A path the headers cannot carry literally must be refused, not emitted: a patch that
# does not parse back would break step 8's promise that every published patch applies.
# `src/Sample.cs` is the path civilization normally uses; these are the ones it doesn't.
for bad_path, why in (
    ("src/we\tird.cs", "a tab"),
    ("src/we\nird.cs", "a newline"),
    ("src/we\rird.cs", "a carriage return"),
    ("src/we\x00ird.cs", "a NUL"),
    ("src/we\x7fird.cs", "a DEL"),
    ("src/we\x01ird.cs", "a C0 control"),
    ("src/we\ud800ird.cs", "an unpaired surrogate"),
):
    refuses(lambda p=bad_path: canonical_patch(p, PRE, POST), f"patch path: {why} is refused")
    # ...and the refusal must not depend on there being a change to emit.
    refuses(lambda p=bad_path: canonical_patch(p, PRE, PRE),
            f"patch path: {why} is refused even for an empty patch")
check(canonical_patch("src/with space.cs", PRE, POST).startswith(
    b"diff --git a/src/with space.cs b/src/with space.cs\n"),
    "patch path: a space is supported (git reads the name literally)")

# --- the canonical manifest --------------------------------------------------------

m = build_manifest(a_plan(), PLAN_SHA, REL, sha(PRE), POST, patch)
check(set(m) == {"version", "operation", "input_bundle_sha256", "validated_plan_sha256",
                 "target_api", "source_files", "applied_findings", "manual_review_findings",
                 "patch_sha256"}, "manifest: exact key set, no extras")
check(m["patch_sha256"] == sha(patch), "manifest: patch_sha256 is over the patch bytes")
check(m["validated_plan_sha256"] == PLAN_SHA, "manifest: validated_plan_sha256 is the plan's")
check(m["source_files"] == [{"path": REL, "pre_sha256": sha(PRE), "post_sha256": sha(POST)}],
      "manifest: one source file, pre from the plan, post recomputed")
check(m["target_api"] == {"subscribe": "Weak.Add"}, "manifest: canonical target_api")
check(m["applied_findings"] == [FID_A] and m["manual_review_findings"] == [FID_B],
      "manifest: partitioned by action")

# Candidate order, not sorted order: a plan whose FIRST decision is the LATER id must
# keep that order in the manifest.
rev = a_plan()
rev["decisions"] = [dict(rev["decisions"][1], action="convert_acquire"),
                    dict(rev["decisions"][0], action="convert_acquire")]
check(build_manifest(rev, PLAN_SHA, REL, sha(PRE), POST, patch)["applied_findings"]
      == [FID_B, FID_A], "manifest: applied_findings follows candidate order")

blob = manifest_bytes(m)
check(blob.endswith(b"\n") and blob.count(b"\n") == 1, "manifest: one trailing newline")
check(b", " not in blob and b": " not in blob, "manifest: compact separators")
check(blob == manifest_bytes(build_manifest(a_plan(), PLAN_SHA, REL, sha(PRE), POST, patch)),
      "manifest: byte-identical on a re-run")
check(list(json.loads(blob)) == sorted(json.loads(blob)), "manifest: keys sorted")
for banned in (b"1970", b"202", b"/tmp", b"/home", b"runner"):
    check(banned not in blob, f"manifest: no {banned!r} (no timestamps/paths/run ids)")

# manual-only: the empty patch contract
mo = a_plan(("manual_review", "manual_review"))
empty = canonical_patch(REL, PRE, PRE)
mm = build_manifest(mo, PLAN_SHA, REL, sha(PRE), PRE, empty)
check(mm["applied_findings"] == [], "manual-only: applied_findings is empty")
check(mm["manual_review_findings"] == [FID_A, FID_B], "manual-only: all ids in candidate order")
check(mm["patch_sha256"] == sha(b""), "manual-only: patch_sha256 is the empty-bytes sha")
check(mm["source_files"][0]["post_sha256"] == mm["source_files"][0]["pre_sha256"],
      "manual-only: post == pre")

# --- the transport artifact: verified, never trusted -------------------------------

with tempfile.TemporaryDirectory() as tmp:
    check(validate(workdir(tmp, a_report())) == POST, "transport: a good report validates")

    refuses(lambda: validate(workdir(tmp, a_report(), post=POST + b"// tampered\n")),
            "transport: postimage bytes changed after the report", "is not the postimage's actual")
    refuses(lambda: validate(workdir(tmp, a_report(
        source_files=[{"path": REL, "pre_sha256": sha(PRE), "post_sha256": sha(b"lies")}]))),
        "transport: wrong post SHA", "post_sha256")
    refuses(lambda: validate(workdir(tmp, a_report(extra_field=True))),
            "transport: an extra report field", "key set")
    refuses(lambda: validate(workdir(tmp, a_report(), post=None)),
            "transport: a missing postimage", "missing")
    refuses(lambda: validate(workdir(tmp, a_report(), extra="unexpected.txt")),
            "transport: an unexpected extra file", "extra")
    refuses(lambda: validate(workdir(tmp, None)),
            "transport: no report at all", "missing")
    refuses(lambda: validate(workdir(tmp, a_report(applied_findings=[FID_A, FID_B],
                                                   manual_review_findings=[]))),
            "transport: a wrong applied/manual partition", "partition")
    refuses(lambda: validate(workdir(tmp, a_report(applied_findings=[FID_A, FID_A]))),
            "transport: duplicate findings", "duplicates")
    refuses(lambda: validate(workdir(tmp, a_report(version=2))),
            "transport: an unsupported version", "version")
    refuses(lambda: validate(workdir(tmp, a_report(operation="rm -rf"))),
            "transport: an unexpected operation", "operation")
    refuses(lambda: validate(workdir(tmp, a_report(input_bundle_sha256="sha256:" + "0" * 64))),
            "transport: a report bound to other candidates", "input_bundle_sha256")
    refuses(lambda: validate(workdir(tmp, a_report(validated_plan_sha256="sha256:" + "0" * 64))),
            "transport: a report bound to other plan bytes", "validated_plan_sha256")
    refuses(lambda: validate(workdir(tmp, a_report(target_api={"subscribe": "Evil.Add"}))),
            "transport: a swapped target api", "target_api")
    refuses(lambda: validate(workdir(tmp, a_report(
        source_files=[{"path": "other.cs", "pre_sha256": sha(PRE), "post_sha256": sha(POST)}]))),
        "transport: a different source path", "source path")
    refuses(lambda: validate(workdir(tmp, a_report(
        source_files=[{"path": REL, "pre_sha256": "sha256:" + "0" * 64,
                       "post_sha256": sha(POST)}]))),
        "transport: a wrong preimage sha", "pre_sha256")
    refuses(lambda: validate(workdir(tmp, a_report(source_files=[]))),
            "transport: no source file", "exactly one source file")

# --- path containment is a platform property ---------------------------------------

check(_same_or_inside("/repo", "/repo"), "containment: a root contains itself")
check(_same_or_inside("/repo", "/repo/sub/x"), "containment: a descendant is inside")
check(not _same_or_inside("/repo", "/repository"), "containment: a name PREFIX is not inside")
check(not _same_or_inside("/repo", "/other/x"), "containment: an unrelated path is outside")
check(_same_or_inside("/", "/anything"), "containment: everything is inside the fs root")
check(_same_or_inside("/repo", "/repo/") and _same_or_inside("/repo/", "/repo"),
      "containment: a trailing separator does not change the answer")
# The case rule must follow the PLATFORM, or `c:\repo\out` slips past a `C:\Repo` root.
if os.name == "nt":
    check(_same_or_inside("C:\\Repo", "c:\\repo\\artifact"),
          "containment: Windows is case-insensitive")
else:
    check(not _same_or_inside("/repo", "/REPO/artifact"),
          "containment: a case-sensitive filesystem is case-sensitive")

# --- the --rewriter command grammar (one grammar, every platform) -------------------

check(split_rewriter_command("owen-rewrite") == ["owen-rewrite"], "rewriter: a bare command")
check(split_rewriter_command("dotnet run --project x --no-build --")
      == ["dotnet", "run", "--project", "x", "--no-build", "--"], "rewriter: extra arguments")
check(split_rewriter_command("'/opt/my tools/owen-rewrite' --quiet")
      == ["/opt/my tools/owen-rewrite", "--quiet"],
      "rewriter: a quoted exe path with spaces keeps NO quotes in argv[0]")
check(split_rewriter_command("'C:\\Program Files\\owen\\owen-rewrite.exe'")
      == ["C:\\Program Files\\owen\\owen-rewrite.exe"],
      "rewriter: a single-quoted Windows path keeps its backslashes")
try:
    split_rewriter_command('"unterminated')
    failures.append("rewriter: an unterminated quote must not parse")
except ValueError:
    pass  # the CLI maps this to `own-fix: refuse:` + exit 2, never a traceback
checks += 1

def run() -> int:
    """The aggregate contract run_tests.py expects: report + an int rc, NEVER a
    process-ending sys.exit at import time (which would silence every later module)."""
    print(f"patch bundle (S2 step 8): {checks - len(failures)}/{checks} checks pass")
    for f in failures:
        print(f"  FAIL: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
