"""S2 step 8 — the canonical patch bundle: turn the accepted rewriter's postimage into a
deterministic, reviewable, hash-addressed artifact.

    <out>/
      change.patch            # canonical unified diff, a/<rel> -> b/<rel>
      apply-manifest.json     # the AUTHORITY artifact: exact shape, byte-deterministic
      postimage/<rel>         # the exact post-apply bytes

No model and no o7 here: this step is pure orchestration over two hash-bound inputs and
one trusted-but-verified transport artifact. `rewriter-report.json` is transport only —
it never reaches the published bundle, and it is re-checked rather than believed: the
validated plan stays the sole authority for `action`, the hash-bound candidates stay the
sole authority for identity, and the report merely confirms the rewriter did the work
that was asked of it.

Everything published is a pure function of the pristine inputs, so a re-run over the same
inputs is byte-identical: no timestamps, no absolute or temp paths, no hostname, no run
id, no command line — nothing that would make one machine's bundle differ from another's.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import subprocess
from typing import Any

from ownlang.fix_apply import ApplyError, validate_apply_inputs

_REPORT_KEYS = {
    "version", "operation", "input_bundle_sha256", "validated_plan_sha256",
    "target_api", "source_files", "applied_findings", "manual_review_findings",
}
_REPORT_SOURCE_KEYS = {"path", "pre_sha256", "post_sha256"}


def _sha_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


# --- the canonical patch -----------------------------------------------------------


def _split_lines(data: bytes) -> list[bytes]:
    """Split on b"\\n" ONLY — git's own notion of a line — keeping the terminator.
    `bytes.splitlines()` also breaks on a lone \\r (and \\v, \\f, \\x1c...), which would
    silently reflow a file whose content legitimately carries one."""
    lines: list[bytes] = []
    start = 0
    while start < len(data):
        cut = data.find(b"\n", start)
        if cut < 0:
            lines.append(data[start:])
            break
        lines.append(data[start:cut + 1])
        start = cut + 1
    return lines


def _emit(prefix: bytes, line: bytes) -> list[bytes]:
    """A patch line. A final line with no newline needs git's own marker, or the patch
    would claim a terminator the file does not have."""
    if line.endswith(b"\n"):
        return [prefix + line]
    return [prefix + line + b"\n", b"\\ No newline at end of file\n"]


def _hunk_range(start: int, count: int) -> bytes:
    if count == 1:
        return b"%d" % (start + 1)
    if count == 0:  # an empty range names the line BEFORE it, per the unified format
        return b"%d,0" % start
    return b"%d,%d" % (start + 1, count)


def canonical_patch(rel: str, pre: bytes, post: bytes, context: int = 3) -> bytes:
    """A deterministic `git apply`-able unified diff for the ONE allowed file. Depends on
    nothing but (rel, pre, post) — no timestamps, no temp or absolute paths, no username,
    no cwd — so the same inputs always yield the same bytes. An unchanged file is the
    EMPTY patch (a manual_review-only plan is valid, not a refusal)."""
    if pre == post:
        return b""
    before = _split_lines(pre)
    after = _split_lines(post)
    path = rel.encode("utf-8")
    out: list[bytes] = [
        b"diff --git a/" + path + b" b/" + path + b"\n",
        b"--- a/" + path + b"\n",
        b"+++ b/" + path + b"\n",
    ]
    # autojunk would make the diff depend on the file's size heuristically; off for a
    # result that depends only on the content.
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for group in matcher.get_grouped_opcodes(context):
        a_start, a_end = group[0][1], group[-1][2]
        b_start, b_end = group[0][3], group[-1][4]
        out.append(b"@@ -" + _hunk_range(a_start, a_end - a_start)
                   + b" +" + _hunk_range(b_start, b_end - b_start) + b" @@\n")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in before[i1:i2]:
                    out.extend(_emit(b" ", line))
                continue
            if tag in ("replace", "delete"):
                for line in before[i1:i2]:
                    out.extend(_emit(b"-", line))
            if tag in ("replace", "insert"):
                for line in after[j1:j2]:
                    out.extend(_emit(b"+", line))
    return b"".join(out)


# --- the canonical manifest --------------------------------------------------------


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """The one serialization. sort_keys makes key order independent of construction
    order; the compact separators and the trailing newline make the file itself the
    hashable artifact."""
    return json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8") + b"\n"


def build_manifest(
    validated_plan: dict[str, Any],
    plan_sha256: str,
    rel: str,
    pre_sha256: str,
    post_bytes: bytes,
    patch: bytes,
) -> dict[str, Any]:
    """The authority artifact, built ONLY from the validated plan (for actions and their
    order), the plan's own bytes, and the real postimage/patch bytes. The rewriter's
    report contributes nothing here — it was verification, not a source."""
    applied: list[str] = []
    manual: list[str] = []
    for decision in validated_plan["decisions"]:  # already pinned to candidate order
        (applied if decision["action"] == "convert_acquire" else manual).append(
            decision["finding_id"]
        )
    return {
        "version": 1,
        "operation": "apply-subscription-fixes",
        "input_bundle_sha256": validated_plan["input_bundle_sha256"],
        "validated_plan_sha256": plan_sha256,
        "target_api": {"subscribe": validated_plan["target_api"]["subscribe"]},
        "source_files": [{
            "path": rel,
            "pre_sha256": pre_sha256,
            "post_sha256": _sha_bytes(post_bytes),
        }],
        "applied_findings": applied,
        "manual_review_findings": manual,
        "patch_sha256": _sha_bytes(patch),
    }


# --- the transport artifact (verified, never trusted) ------------------------------


def _walk_rel(root: str) -> set[str]:
    found: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            found.add(os.path.relpath(full, root).replace("\\", "/"))
    return found


def validate_rewriter_output(
    workdir: str,
    validated_plan: dict[str, Any],
    plan_sha256: str,
    rel: str,
    pre_sha256: str,
    expected_applied: set[str],
    expected_manual: set[str],
) -> bytes:
    """Re-derive every claim `rewriter-report.json` makes and return the postimage bytes.
    A neighbouring executable produced it, which is not the same as it being true."""
    files = _walk_rel(workdir)
    expected_files = {"rewriter-report.json", f"postimage/{rel}"}
    if files != expected_files:
        extra = sorted(files - expected_files)
        missing = sorted(expected_files - files)
        raise ApplyError(
            f"rewriter output is not the expected file set (extra={extra}, missing={missing})"
        )

    report_path = os.path.join(workdir, "rewriter-report.json")
    try:
        with open(report_path, "rb") as fh:
            report = json.loads(fh.read())
    except (OSError, ValueError) as exc:
        raise ApplyError(f"cannot read rewriter-report.json: {exc}") from exc
    if not isinstance(report, dict):
        raise ApplyError("rewriter-report.json must be an object")
    if set(report) != _REPORT_KEYS:
        raise ApplyError(
            f"rewriter-report.json key set is {sorted(report)}, expected {sorted(_REPORT_KEYS)}"
        )
    if report["version"] != 1:
        raise ApplyError("rewriter-report.json: unsupported version")
    if report["operation"] != "apply-subscription-fixes":
        raise ApplyError("rewriter-report.json: unexpected operation")
    if report["input_bundle_sha256"] != validated_plan["input_bundle_sha256"]:
        raise ApplyError("rewriter-report.json: input_bundle_sha256 does not match the plan")
    if report["validated_plan_sha256"] != plan_sha256:
        raise ApplyError("rewriter-report.json: validated_plan_sha256 is not the plan's bytes")
    expected_api = {"subscribe": validated_plan["target_api"]["subscribe"]}
    if report["target_api"] != expected_api:
        raise ApplyError("rewriter-report.json: target_api does not match the plan")

    sources = report["source_files"]
    if not isinstance(sources, list) or len(sources) != 1:
        raise ApplyError("rewriter-report.json: expected exactly one source file")
    source = sources[0]
    if not isinstance(source, dict) or set(source) != _REPORT_SOURCE_KEYS:
        raise ApplyError("rewriter-report.json: source_files[0] has an unexpected key set")
    if source["path"] != rel:
        raise ApplyError(f"rewriter-report.json: source path {source['path']!r} is not {rel!r}")
    if source["pre_sha256"] != pre_sha256:
        raise ApplyError("rewriter-report.json: pre_sha256 is not the plan's preimage")

    post_path = os.path.join(workdir, "postimage", *rel.split("/"))
    try:
        with open(post_path, "rb") as fh:
            post_bytes = fh.read()
    except OSError as exc:
        raise ApplyError(f"cannot read the postimage: {exc}") from exc
    # RECOMPUTED, never taken on the report's word: the bytes are what get published.
    actual_post = _sha_bytes(post_bytes)
    if source["post_sha256"] != actual_post:
        raise ApplyError(
            f"rewriter-report.json: post_sha256 {source['post_sha256']} is not the postimage's "
            f"actual {actual_post}"
        )

    for key, expected in (("applied_findings", expected_applied),
                          ("manual_review_findings", expected_manual)):
        got = report[key]
        if not isinstance(got, list) or not all(isinstance(x, str) for x in got):
            raise ApplyError(f"rewriter-report.json: {key} must be a list of strings")
        if len(set(got)) != len(got):
            raise ApplyError(f"rewriter-report.json: {key} has duplicates")
        if set(got) != expected:
            raise ApplyError(
                f"rewriter-report.json: {key} is not the plan's partition for that action"
            )
    return post_bytes


# --- orchestration -----------------------------------------------------------------


def _realpath(path: str) -> str:
    return os.path.realpath(path)


def _inside(parent: str, path: str) -> bool:
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def _prepare_out(out: str, root: str) -> tuple[str, str, str]:
    """(out, workdir, staging) — all physical. The out-dir must be fresh and physically
    off the source tree; a symlinked parent must not land the bundle in the tree while
    the string still looks external."""
    out_abs = os.path.abspath(out)
    name = os.path.basename(out_abs.rstrip(os.sep))
    if not name:
        raise ApplyError(f"--out {out!r}: not a directory name")
    parent = os.path.dirname(out_abs.rstrip(os.sep))
    if not os.path.isdir(parent):
        raise ApplyError(f"--out {out!r}: the parent directory does not exist")
    parent_phys = _realpath(parent)
    root_phys = _realpath(root)
    if _inside(root_phys, parent_phys):
        raise ApplyError(
            f"--out {out!r} resolves inside the source root ({parent_phys}) — refusing to "
            "write into the tree"
        )
    out_phys = os.path.join(parent_phys, name)
    if os.path.exists(out_phys) or os.path.islink(out_phys):
        raise ApplyError(f"--out {out!r} already exists — refusing to mix runs")
    workdir = os.path.join(parent_phys, f".{name}.owen-apply")
    if os.path.exists(workdir) or os.path.islink(workdir):
        raise ApplyError(f"the work directory {workdir!r} already exists — refusing")
    return out_phys, workdir, os.path.join(workdir, "staging")


def apply_bundle(
    plan_path: str, candidates_path: str, root: str, out: str, rewriter: list[str]
) -> str:
    """Build and atomically publish the canonical patch bundle. Returns the published
    path; raises ApplyError (leaving no output and an untouched source tree) otherwise."""
    try:
        with open(plan_path, "rb") as fh:
            plan_raw = fh.read()
        with open(candidates_path, "rb") as fh:
            cand_raw = fh.read()
    except OSError as exc:
        raise ApplyError(f"cannot read inputs: {exc}") from exc
    try:
        validated_plan = json.loads(plan_raw)
        candidates = json.loads(cand_raw)
    except ValueError as exc:
        raise ApplyError(f"input is not valid JSON: {exc}") from exc
    if not isinstance(validated_plan, dict) or not isinstance(candidates, dict):
        raise ApplyError("both inputs must be JSON objects")

    # The accepted step-1 gate, run again here: nothing downstream may assume it ran.
    validate_apply_inputs(validated_plan, candidates, root)
    plan_sha256 = _sha_bytes(plan_raw)          # the EXACT bytes read here
    rel = candidates["source_files"][0]["path"]
    pre_sha256 = candidates["source_files"][0]["sha256"]
    expected_applied = {d["finding_id"] for d in validated_plan["decisions"]
                        if d["action"] == "convert_acquire"}
    expected_manual = {d["finding_id"] for d in validated_plan["decisions"]
                       if d["action"] == "manual_review"}

    out_phys, workdir, staging = _prepare_out(out, root)
    try:
        os.makedirs(workdir)
    except OSError as exc:
        raise ApplyError(f"cannot create the work directory: {exc}") from exc

    try:
        rewriter_out = os.path.join(workdir, "rewriter")
        cmd = [*rewriter, "--plan", plan_path, "--candidates", candidates_path,
               "--root", root, "--out", rewriter_out]
        try:
            # No shell: the rewriter is invoked as an argv vector, so nothing in a path
            # can be read as syntax.
            proc = subprocess.run(cmd, capture_output=True, check=False)
        except OSError as exc:
            raise ApplyError(f"cannot run the rewriter {cmd[0]!r}: {exc}") from exc
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip() or f"exit {proc.returncode}"
            raise ApplyError(f"the rewriter refused: {detail}")

        post_bytes = validate_rewriter_output(
            rewriter_out, validated_plan, plan_sha256, rel, pre_sha256,
            expected_applied, expected_manual,
        )
        pre_bytes = _read_pristine(root, rel, pre_sha256)
        patch = canonical_patch(rel, pre_bytes, post_bytes)
        manifest = build_manifest(validated_plan, plan_sha256, rel, pre_sha256, post_bytes, patch)

        # Stage the WHOLE bundle, then publish it with one rename: <out> must not exist
        # until every check has passed.
        os.makedirs(os.path.join(staging, "postimage", *rel.split("/")[:-1]) or staging,
                    exist_ok=True)
        _write(os.path.join(staging, "change.patch"), patch)
        _write(os.path.join(staging, "apply-manifest.json"), manifest_bytes(manifest))
        _write(os.path.join(staging, "postimage", *rel.split("/")), post_bytes)
        try:
            os.rename(staging, out_phys)      # atomic: same parent, same volume
        except OSError as exc:
            raise ApplyError(f"cannot publish the bundle: {exc}") from exc
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    shutil.rmtree(workdir, ignore_errors=True)
    return out_phys


def _read_pristine(root: str, rel: str, pre_sha256: str) -> bytes:
    """The preimage the patch is against — re-read and re-hashed here, so the diff can
    never be built against a source that moved under us since the gate."""
    path = os.path.join(_realpath(root), *rel.split("/"))
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise ApplyError(f"cannot read the pristine source: {exc}") from exc
    if _sha_bytes(data) != pre_sha256:
        raise ApplyError(f"STALE SOURCE / PREIMAGE MISMATCH for {rel}")
    return data


def _write(path: str, data: bytes) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        raise ApplyError(f"cannot write {os.path.basename(path)}: {exc}") from exc
