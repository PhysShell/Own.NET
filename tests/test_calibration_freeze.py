#!/usr/bin/env python3
"""#263-A calibration policy — the step 4 digest freeze, and its controls.

Step 4 freezes WHICH BYTES the policy mechanism consists of. It freezes no
constant value and reads no measurement. An artifact that carried `q`, a ladder
or a fitted `A_abs` would have quietly become step 5, and step 5 is not
authorised — so `freeze-artifact-shape` enumerates the whole permitted schema
and refuses anything else, rather than listing the field names it happens to
know are forbidden today.

The artifact lives outside `scripts/calibration/` deliberately: a freeze stored
inside the tree it freezes would change that tree by existing.

    freeze-artifact-shape     the artifact is identity and nothing else
    freeze-ancestry           the frozen source commit is an ancestor of HEAD
    freeze-source-set         the recorded files are git's, at that commit
    freeze-source-root-clean  nothing under the policy root escapes the selector
    freeze-digest             the frozen digest recomputes from the blobs at S
    freeze-source-unchanged   the policy source has not moved since S
    freeze-harness-untouched  the measurement harness digest still holds

All but the first need git history. Where it is absent they REFUSE rather than
skip, because a control that quietly verifies nothing is the defect this PR has
spent twelve rounds removing.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:   python tests/test_calibration_freeze.py
Emit:  python tests/test_calibration_freeze.py --emit
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import perf_baseline as pb  # noqa: E402

FREEZE_ARTIFACT = ROOT / "docs" / "evidence" / "calibration" / "p022-263a-policy-freeze.json"

ARTIFACT_NAME = "p022-263a-calibration-policy-freeze"
POLICY_SOURCE_ROOT = "scripts/calibration/"
POLICY_SOURCE_SELECTOR = (
    "all committed *.py recursively under policy_source_root at policy_source_commit"
)

# The framing is part of the freeze: a digest whose byte layout is described only
# in prose is a digest a second implementation cannot reproduce.
DIGEST_FRAMING = (
    "sha256 over the source set ordered by the UTF-8 bytes of each repo-relative "
    "POSIX path. Each file contributes, with no header and no separator: its path "
    "byte length as an 8-byte big-endian unsigned integer, its path's exact UTF-8 "
    "bytes, its blob byte length as an 8-byte big-endian unsigned integer, and its "
    "exact git blob bytes."
)

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


class FreezeRefused(Exception):
    """Raised rather than returning a value that would look like a result."""


# --------------------------------------------------------------------------
# The digest formula, written ONCE.
#
# `--emit` produced the committed artifact with this function and the controls
# recompute with the same one. That is deliberate: two implementations agreeing
# would only prove the two agree. What the control actually compares is a frozen
# literal in a committed JSON against a fresh read of immutable git objects, so
# a drift in either the bytes or the formula shows up as a mismatch.
# --------------------------------------------------------------------------

def _u64(value: int) -> bytes:
    if value < 0 or value >= 1 << 64:
        raise FreezeRefused(f"length {value} does not fit an 8-byte big-endian field")
    return value.to_bytes(8, "big")


def implementation_digest(entries: list[tuple[str, bytes]]) -> str:
    """The aggregate digest over a source set of (repo-relative path, blob bytes)."""
    if not entries:
        raise FreezeRefused(
            "the source set is empty; sha256 of nothing is a perfectly stable value "
            "that proves nothing about a policy implementation")
    seen = {path for path, _ in entries}
    if len(seen) != len(entries):
        raise FreezeRefused("the source set names the same path twice")
    digest = hashlib.sha256()
    for path, blob in sorted(entries, key=lambda entry: entry[0].encode("utf-8")):
        path_bytes = path.encode("utf-8")
        digest.update(_u64(len(path_bytes)))
        digest.update(path_bytes)
        digest.update(_u64(len(blob)))
        digest.update(blob)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# git, refusing rather than degrading
# --------------------------------------------------------------------------

def _git(*args: str) -> tuple[int, bytes]:
    proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    return proc.returncode, proc.stdout


def is_shallow() -> bool:
    rc, out = _git("rev-parse", "--is-shallow-repository")
    return rc == 0 and out.decode().strip() == "true"


def require_objects(commit: str) -> None:
    """Refuse unless this checkout really holds what the claim is about.

    The first draft of this refused on shallowness alone, which is a proxy: a
    shallow clone can still hold the commit in question, and this one does. What
    every check below actually needs is the objects, so that is what is read. The
    one claim shallowness genuinely blocks is ancestry, and that is handled where
    it arises rather than by refusing everything in advance.
    """
    for spec, what in ((f"{commit}^{{commit}}", "commit"), (f"{commit}^{{tree}}", "tree")):
        if _git("cat-file", "-e", spec)[0] != 0:
            raise FreezeRefused(
                f"the {what} object for {commit[:12]} is not in this checkout, so no "
                "claim about its contents can be tested here"
                + ("; the history is truncated, and the job needs fetch-depth: 0"
                   if is_shallow() else ""))


def source_set_at(commit: str, root: str) -> list[tuple[str, str, int]]:
    """(path, blob sha1, byte length) for every *.py under `root` at `commit`."""
    rc, out = _git("ls-tree", "-r", "--long", "-z", commit, "--", root)
    if rc != 0:
        raise FreezeRefused(f"git could not list {root} at {commit[:12]}")
    return [entry for entry in _parse_ls_tree(out) if entry[0].endswith(".py")]


def _parse_ls_tree(out: bytes) -> list[tuple[str, str, int]]:
    entries: list[tuple[str, str, int]] = []
    for record in out.decode("utf-8").split("\0"):
        if not record.strip():
            continue
        meta, path = record.split("\t", 1)
        _mode, kind, sha, size = meta.split()
        if kind != "blob":
            raise FreezeRefused(f"{path} is a {kind}, and a source set is files")
        entries.append((path, sha, int(size)))
    return entries


def blob_at(sha: str) -> bytes:
    rc, out = _git("cat-file", "blob", sha)
    if rc != 0:
        raise FreezeRefused(f"blob {sha[:12]} could not be read")
    return out


def build_freeze(commit: str) -> dict[str, object]:
    """The artifact, computed entirely from git objects at `commit`."""
    require_objects(commit)
    rc, out = _git("rev-parse", f"{commit}^{{tree}}")
    if rc != 0:
        raise FreezeRefused(f"{commit[:12]} has no tree")
    tree = out.decode().strip()
    entries = source_set_at(commit, POLICY_SOURCE_ROOT)
    digest = implementation_digest([(path, blob_at(sha)) for path, sha, _ in entries])
    return {
        "artifact": ARTIFACT_NAME,
        "measurement_harness_digest": pb.harness_digest_at(ROOT, commit) or "",
        "policy_implementation_digest": digest,
        "policy_implementation_digest_framing": DIGEST_FRAMING,
        "policy_source_commit": commit,
        "policy_source_files": [
            {"path": path, "blob_sha1": sha, "size_bytes": size}
            for path, sha, size in sorted(entries, key=lambda e: e[0].encode("utf-8"))
        ],
        "policy_source_root": POLICY_SOURCE_ROOT,
        "policy_source_selector": POLICY_SOURCE_SELECTOR,
        "policy_source_tree": tree,
    }


# --------------------------------------------------------------------------
# The controls
# --------------------------------------------------------------------------

HEX40 = "0123456789abcdef"
FILE_ENTRY_KEYS = {"path", "blob_sha1", "size_bytes"}


def _is_hex(value: object, width: int) -> bool:
    return (isinstance(value, str) and len(value) == width
            and all(char in HEX40 for char in value))


def _is_count(value: object) -> bool:
    """An exact non-negative count. `bool` is excluded on purpose: in Python a
    bool IS an int, and Round 9 of this PR was lost to exactly that."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _numbers(node: object) -> list[object]:
    """Every numeric leaf anywhere in the document, bools included."""
    if isinstance(node, dict):
        return [n for value in node.values() for n in _numbers(value)]
    if isinstance(node, list):
        return [n for item in node for n in _numbers(item)]
    if isinstance(node, (int, float, bool)):
        return [node]
    return []


def load_artifact() -> dict[str, object] | None:
    if not FREEZE_ARTIFACT.exists():
        fail("freeze-artifact-shape",
             f"{FREEZE_ARTIFACT.relative_to(ROOT).as_posix()} does not exist; step 4 "
             "is the artifact, so its absence is the whole failure")
        return None
    try:
        loaded = json.loads(FREEZE_ARTIFACT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail("freeze-artifact-shape", f"the artifact could not be read as JSON: {exc}")
        return None
    if not isinstance(loaded, dict):
        fail("freeze-artifact-shape", f"the artifact is a {type(loaded).__name__}, not an object")
        return None
    return loaded


def control_artifact_shape(art: dict[str, object]) -> None:
    """The whole permitted schema, enumerated.

    This is the control that keeps step 4 from becoming step 5. It does not list
    the constant names that are forbidden today — `q`, `M`, `R_runs`, the ladder,
    `G`, a fitted `A_abs`/`R_rel`, any measurement output — because such a list is
    only ever as complete as the day it was written. It states what the artifact
    MAY contain, and everything else is a failure by construction.
    """
    problems: list[str] = []

    expected = {
        "artifact": ARTIFACT_NAME,
        "policy_implementation_digest_framing": DIGEST_FRAMING,
        "policy_source_root": POLICY_SOURCE_ROOT,
        "policy_source_selector": POLICY_SOURCE_SELECTOR,
    }
    digests = ("measurement_harness_digest", "policy_implementation_digest")
    shas = ("policy_source_commit", "policy_source_tree")
    permitted = set(expected) | set(digests) | set(shas) | {"policy_source_files"}

    unexpected = sorted(set(art) - permitted)
    missing = sorted(permitted - set(art))
    if unexpected:
        problems.append(f"keys the freeze schema does not permit: {unexpected}; step 4 "
                        "freezes identity, and a field outside this set is step 5 "
                        "arriving early")
    if missing:
        problems.append(f"keys the freeze schema requires: {missing}")

    for key, literal in expected.items():
        if key in art and art[key] != literal:
            problems.append(f"{key} is not the frozen literal")
    for key in digests:
        if key in art and not _is_hex(art[key], 64):
            problems.append(f"{key} is not 64 lowercase hex characters")
    for key in shas:
        if key in art and not _is_hex(art[key], 40):
            problems.append(f"{key} is not 40 lowercase hex characters")

    files = art.get("policy_source_files")
    sizes: list[object] = []
    if not isinstance(files, list) or not files:
        problems.append("policy_source_files is not a non-empty list")
    else:
        for index, entry in enumerate(files):
            where = f"policy_source_files[{index}]"
            if not isinstance(entry, dict):
                problems.append(f"{where} is not an object")
                continue
            if set(entry) != FILE_ENTRY_KEYS:
                problems.append(f"{where} keys are {sorted(entry)}, not {sorted(FILE_ENTRY_KEYS)}")
                continue
            path = entry["path"]
            if not isinstance(path, str) or not path.startswith(POLICY_SOURCE_ROOT):
                problems.append(f"{where} path is not under {POLICY_SOURCE_ROOT}")
            elif not path.endswith(".py") or ".." in path:
                problems.append(f"{where} path is not a plain *.py path")
            if not _is_hex(entry["blob_sha1"], 40):
                problems.append(f"{where} blob_sha1 is not 40 lowercase hex characters")
            if not _is_count(entry["size_bytes"]):
                problems.append(f"{where} size_bytes is not a positive exact count")
            else:
                sizes.append(entry["size_bytes"])

    stray = [n for n in _numbers(art) if n not in sizes or isinstance(n, (bool, float))]
    if stray:
        problems.append(f"numbers that are not a recorded file size: {stray}; the only "
                        "quantity this artifact is allowed to carry is a byte length, "
                        "which is how a design constant is kept from moving in beside it")

    if problems:
        fail("freeze-artifact-shape", "; ".join(problems))
    else:
        ok("freeze-artifact-shape",
           f"{len(permitted)} permitted keys and no others, every digest well-formed, "
           f"and the only numbers present are the {len(sizes)} recorded byte lengths")


def control_ancestry(art: dict[str, object]) -> None:
    commit = str(art.get("policy_source_commit", ""))
    require_objects(commit)
    head = _git("rev-parse", "HEAD")[1].decode().strip()
    if _git("merge-base", "--is-ancestor", commit, "HEAD")[0] != 0:
        # A truncated history answers "no" for a link it simply cannot see, which
        # is indistinguishable from a real negative. Both fail; only the remedy
        # differs, so the message has to say which one this is rather than let a
        # shallow checkout read as a provenance break.
        truncated = ("; the history here is truncated, so this answer is not "
                     "trustworthy either way and the job needs fetch-depth: 0"
                     if is_shallow() else "")
        fail("freeze-ancestry",
             f"the frozen source commit {commit[:12]} does not read as an ancestor of "
             f"HEAD {head[:12]}{truncated}")
        return
    if commit == head:
        fail("freeze-ancestry",
             "the freeze commit is the source commit; the artifact has to live in a "
             "descendant, or it would be part of the tree it freezes")
        return
    tree = _git("rev-parse", f"{commit}^{{tree}}")[1].decode().strip()
    if tree != str(art.get("policy_source_tree", "")):
        fail("freeze-ancestry",
             f"policy_source_tree is {str(art.get('policy_source_tree'))[:12]} but "
             f"{commit[:12]} has tree {tree[:12]}")
        return
    ok("freeze-ancestry",
       f"{commit[:12]} is a strict ancestor of HEAD {head[:12]} and really carries "
       f"tree {tree[:12]}")


def control_source_set(art: dict[str, object]) -> None:
    commit = str(art.get("policy_source_commit", ""))
    require_objects(commit)
    actual = sorted(source_set_at(commit, POLICY_SOURCE_ROOT),
                    key=lambda e: e[0].encode("utf-8"))
    files = art.get("policy_source_files")
    recorded = [(str(e["path"]), str(e["blob_sha1"]), int(str(e["size_bytes"])))
                for e in files] if isinstance(files, list) else []
    if recorded != actual:
        fail("freeze-source-set",
             f"the artifact records {recorded} but git at {commit[:12]} has {actual}")
        return
    ok("freeze-source-set",
       f"{len(actual)} file(s) recorded, each path, blob sha1 and byte length equal to "
       f"git's own at {commit[:12]}")


def control_source_root_clean(art: dict[str, object]) -> None:
    """Nothing under the policy root may sit outside the `*.py` selector.

    The selector the owner specified covers `*.py`. That leaves a gap it does not
    mention: a `constants.json` dropped beside the module would be under the frozen
    root, invisible to the digest, and a perfectly comfortable home for `q`. The
    digest still covers exactly `*.py`; this refuses the gap instead of widening it.
    """
    commit = str(art.get("policy_source_commit", ""))
    require_objects(commit)
    problems: list[str] = []
    for where in (commit, "HEAD"):
        rc, out = _git("ls-tree", "-r", "--long", "-z", where, "--", POLICY_SOURCE_ROOT)
        if rc != 0:
            problems.append(f"git could not list {POLICY_SOURCE_ROOT} at {where[:12]}")
            continue
        outside = sorted(p for p, _, _ in _parse_ls_tree(out) if not p.endswith(".py"))
        if outside:
            problems.append(f"at {where[:12]}, {outside} sit under the frozen root but "
                            "outside the *.py selector, so the digest does not cover them")
    if problems:
        fail("freeze-source-root-clean", "; ".join(problems))
    else:
        ok("freeze-source-root-clean",
           f"every committed path under {POLICY_SOURCE_ROOT} is a *.py the digest covers, "
           "at the frozen commit and at HEAD")


def control_digest(art: dict[str, object]) -> None:
    commit = str(art.get("policy_source_commit", ""))
    require_objects(commit)
    entries = source_set_at(commit, POLICY_SOURCE_ROOT)
    recomputed = implementation_digest([(p, blob_at(sha)) for p, sha, _ in entries])
    frozen = str(art.get("policy_implementation_digest", ""))
    if recomputed != frozen:
        fail("freeze-digest",
             f"the frozen digest is {frozen[:12]} but the blobs at {commit[:12]} hash "
             f"to {recomputed[:12]}")
        return
    ok("freeze-digest",
       f"{frozen[:12]}… recomputed from {len(entries)} git blob(s) at {commit[:12]}, "
       "under the framing the artifact states")


def control_source_unchanged(art: dict[str, object]) -> None:
    """The freeze commit must not have touched the tree it freezes.

    Blob sha1s are compared rather than working-tree bytes: a CRLF checkout makes
    an identical file look different on disk, which is the Round 3 defect, and the
    digest is over git blob bytes anyway.
    """
    commit = str(art.get("policy_source_commit", ""))
    require_objects(commit)
    at_source = sorted(source_set_at(commit, POLICY_SOURCE_ROOT))
    at_head = sorted(source_set_at("HEAD", POLICY_SOURCE_ROOT))
    if at_source != at_head:
        fail("freeze-source-unchanged",
             f"the policy source at HEAD is {at_head}, but the freeze was taken over "
             f"{at_source}; the freeze commit changed the tree it froze")
        return
    ok("freeze-source-unchanged",
       f"all {len(at_head)} policy source blob(s) are byte-identical at HEAD and at "
       f"{commit[:12]}")


def control_harness_untouched(art: dict[str, object]) -> None:
    recorded = str(art.get("measurement_harness_digest", ""))
    working = pb.harness_digest()
    at_head = pb.harness_digest_at(ROOT, "HEAD")
    problems: list[str] = []
    if working != recorded:
        problems.append(f"the working tree harness digest is {working[:12]}, not {recorded[:12]}")
    if at_head != recorded:
        problems.append(f"the harness digest at HEAD is {str(at_head)[:12]}, not {recorded[:12]}")
    if problems:
        fail("freeze-harness-untouched", "; ".join(problems)
             + "; the freeze commit moved the measurement instrument, which would "
               "invalidate every recording taken against it")
    else:
        ok("freeze-harness-untouched",
           f"{recorded[:12]}… unchanged, in the working tree and at HEAD")


def run() -> int:
    art = load_artifact()
    if art is not None:
        control_artifact_shape(art)
        for control in (control_ancestry, control_source_set, control_source_root_clean,
                        control_digest, control_source_unchanged, control_harness_untouched):
            try:
                control(art)
            except FreezeRefused as exc:
                fail(control.__name__.replace("control_", "freeze-").replace("_", "-"),
                     f"refused rather than reporting a pass it cannot support: {exc}")
    print()
    print(f"calibration freeze controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


def emit() -> int:
    """Step 4, run once: compute the freeze from git and write the artifact."""
    head = _git("rev-parse", "HEAD")[1].decode().strip()
    freeze = build_freeze(head)
    FREEZE_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    FREEZE_ARTIFACT.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    print(f"wrote {FREEZE_ARTIFACT.relative_to(ROOT).as_posix()}")
    print(json.dumps(freeze, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(emit() if "--emit" in sys.argv[1:] else run())
