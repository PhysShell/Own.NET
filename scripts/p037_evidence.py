#!/usr/bin/env python3
"""Shared provenance contract for P-037 step evidence.

A recorded snapshot is fresh evidence for the current tree only when:

* it was taken on a clean tree and marked as evidence;
* its source commit exists and is an ancestor of the commit being checked;
* the declared measurement implementation did not move between those commits;
* the exact source-input set (paths and git blobs) did not move either.

The last two clauses are the reason this module exists. ``source_commit == HEAD``
is an impossible rule once the evidence file itself is committed, while ancestry
alone accepts a measurement after the extractor/core/input corpus has changed.
This is the middle rule: the evidence may be committed later, but none of the
bytes that could have changed what it measured may have changed meanwhile.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent

# Single source for the implementation closure used by both P-037 snapshots.
# Deliberately roots, not a hand-maintained transitive crate list: own-bridge and
# own-shadow depend on several sibling crates, and pretending that list will be
# remembered on every dependency edit is exactly the stale-allowlist failure this
# gate is meant to avoid.
SUBJECT_PATHS: tuple[str, ...] = (
    "frontend/roslyn/OwnSharp.Extractor/",
    "ownlang/",
    "rust/",
    "scripts/own-check.sh",
    "scripts/p037_evidence.py",
    "scripts/p037_mos_snapshot.py",
    "scripts/p037_verdict_snapshot.py",
    "scripts/shadow_compare.py",
    "spec/",
)

# Repo-local paths the snapshot programs execute/import directly. The self-check
# below proves every one is covered by SUBJECT_PATHS. Source inputs are separate:
# their roots and exact blob set are recorded per evidence file.
RUNTIME_REPO_PATHS: tuple[str, ...] = (
    "frontend/roslyn/OwnSharp.Extractor/",
    "ownlang/",
    "rust/",
    "scripts/own-check.sh",
    "scripts/p037_evidence.py",
    "scripts/p037_mos_snapshot.py",
    "scripts/p037_verdict_snapshot.py",
    "scripts/shadow_compare.py",
    "spec/",
)

CORPUS_DIRS: tuple[str, ...] = (
    "corpus/real-world",
    "corpus/wpf",
    "corpus/di",
    "corpus/fixtures",
    "corpus/p036-bakeoff",
)

# The independent syntax-shape source that caught A1's return-parameter defect.
REPO_TREE_DIRS: tuple[str, ...] = ("frontend", "audit")


class EvidenceRefused(RuntimeError):
    """The requested evidence claim cannot be checked honestly."""


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True,
            check=check,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceRefused(f"git {' '.join(args)} failed: {exc}") from exc


def _git_text(*args: str) -> str:
    proc = _git(*args)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise EvidenceRefused(
            f"git {' '.join(args)} exited {proc.returncode}"
            + (f": {detail}" if detail else "")
        )
    return proc.stdout.decode("utf-8").strip()


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _covered(path: str, roots: Iterable[str]) -> bool:
    p = _norm(path)
    for root in roots:
        r = _norm(root)
        if p == r or p.startswith(r + "/"):
            return True
    return False


def closure_problems() -> list[str]:
    """Static self-check: every repo-local runtime path is in the closure."""
    problems: list[str] = []
    for path in RUNTIME_REPO_PATHS:
        if not _covered(path, SUBJECT_PATHS):
            problems.append(
                f"runtime path {path!r} is outside SUBJECT_PATHS; a measurement "
                "could change without invalidating its evidence"
            )
    if len(set(SUBJECT_PATHS)) != len(SUBJECT_PATHS):
        problems.append("SUBJECT_PATHS contains duplicate entries")
    return problems


def _tree_cs_manifest(commit: str, roots: tuple[str, ...]) -> list[dict[str, str]]:
    """Exact committed C# input set at ``commit``, with git blob identity."""
    if not roots:
        raise EvidenceRefused("an evidence input set may not have zero roots")
    proc = _git("ls-tree", "-r", "-z", commit, "--", *roots)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise EvidenceRefused(
            f"cannot enumerate input roots at {commit[:12]}"
            + (f": {detail}" if detail else "")
        )
    out: list[dict[str, str]] = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            meta, path_raw = raw.split(b"\t", 1)
            _mode, kind, blob = meta.decode("ascii").split()
            path = path_raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise EvidenceRefused(f"cannot parse git ls-tree record {raw!r}: {exc}") from exc
        if kind != "blob" or not path.endswith(".cs"):
            continue
        out.append({"path": path.replace("\\", "/"), "blob": blob})
    out.sort(key=lambda e: e["path"].encode("utf-8"))
    if not out:
        raise EvidenceRefused(
            f"input roots {list(roots)!r} contain no committed .cs files at {commit[:12]}"
        )
    return out


def _manifest_digest(entries: list[dict[str, str]]) -> str:
    """Stable identity of the path/blob manifest, independent of JSON layout."""
    h = hashlib.sha256()
    for entry in entries:
        p = entry["path"].encode("utf-8")
        b = entry["blob"].encode("ascii")
        h.update(len(p).to_bytes(8, "big"))
        h.update(p)
        h.update(len(b).to_bytes(8, "big"))
        h.update(b)
    return h.hexdigest()


def current_commit() -> str:
    return _git_text("rev-parse", "HEAD")


def tree_is_dirty() -> bool:
    return bool(_git_text("status", "--porcelain"))


def evidence_fields(input_roots: tuple[str, ...]) -> dict[str, Any]:
    """Provenance fields written into a snapshot taken at the current HEAD."""
    problems = closure_problems()
    if problems:
        raise EvidenceRefused("; ".join(problems))
    commit = current_commit()
    dirty = tree_is_dirty()
    manifest = _tree_cs_manifest(commit, input_roots)
    return {
        "source_commit": commit,
        "dirty": dirty,
        "is_evidence": not dirty,
        "subject_paths": list(SUBJECT_PATHS),
        "input_roots": list(input_roots),
        "input_manifest": manifest,
        "input_manifest_sha256": _manifest_digest(manifest),
    }


def provenance_problems(record: dict[str, Any], *, against: str = "HEAD") -> list[str]:
    """Whether ``record`` is still fresh evidence at ``against``.

    This predicate is intentionally for *freshness*, e.g. "may A2 start from
    this baseline?" A before/after differential may later compare two historical
    evidence records across an intentional source change; that comparison is a
    different claim and does not pretend the before record is fresh at the after
    commit.
    """
    problems: list[str] = []
    problems.extend(closure_problems())

    source = record.get("source_commit")
    if not isinstance(source, str) or not source:
        return problems + ["evidence records no source_commit"]
    if record.get("dirty") is not False:
        problems.append("evidence was taken on a dirty tree")
    if record.get("is_evidence") is not True:
        problems.append("record does not mark itself is_evidence=true")

    declared_subjects = record.get("subject_paths")
    if declared_subjects != list(SUBJECT_PATHS):
        problems.append(
            "recorded subject_paths differ from the current measurement closure; "
            "the older evidence does not cover the dependency set this tool now requires"
        )

    roots_raw = record.get("input_roots")
    if not (
        isinstance(roots_raw, list)
        and roots_raw
        and all(isinstance(x, str) and x for x in roots_raw)
    ):
        problems.append("record carries no valid input_roots")
        roots: tuple[str, ...] = ()
    else:
        roots = tuple(str(x) for x in roots_raw)

    manifest = record.get("input_manifest")
    if not isinstance(manifest, list) or not manifest:
        problems.append("record carries no non-empty input_manifest")
        recorded_manifest: list[dict[str, str]] = []
    else:
        recorded_manifest = []
        for i, entry in enumerate(manifest):
            if not (
                isinstance(entry, dict)
                and isinstance(entry.get("path"), str)
                and isinstance(entry.get("blob"), str)
            ):
                problems.append(f"input_manifest[{i}] is not a path/blob record")
                continue
            recorded_manifest.append(
                {"path": str(entry["path"]), "blob": str(entry["blob"])}
            )

    proc = _git("cat-file", "-e", f"{source}^{{commit}}")
    if proc.returncode != 0:
        return problems + [f"source commit {source[:12]} is not present in this checkout"]
    proc = _git("cat-file", "-e", f"{against}^{{commit}}")
    if proc.returncode != 0:
        return problems + [f"comparison commit {against!r} is not present in this checkout"]
    if _git("merge-base", "--is-ancestor", source, against).returncode != 0:
        problems.append(
            f"source commit {source[:12]} is not an ancestor of {against}; "
            "the evidence describes a history this tree does not contain"
        )
        return problems

    if declared_subjects == list(SUBJECT_PATHS):
        diff = _git("diff", "--quiet", source, against, "--", *SUBJECT_PATHS)
        if diff.returncode == 1:
            problems.append(
                f"measurement implementation changed between {source[:12]} and {against}; "
                "re-take the evidence"
            )
        elif diff.returncode != 0:
            problems.append("git could not compare the declared subject_paths")

    if roots and recorded_manifest:
        try:
            at_source = _tree_cs_manifest(source, roots)
            at_against = _tree_cs_manifest(against, roots)
        except EvidenceRefused as exc:
            problems.append(str(exc))
        else:
            if recorded_manifest != at_source:
                problems.append(
                    "recorded input_manifest does not match the source commit's exact C# input set"
                )
            if at_source != at_against:
                problems.append(
                    f"source inputs changed between {source[:12]} and {against}; "
                    "re-take the evidence"
                )
            want_digest = record.get("input_manifest_sha256")
            got_digest = _manifest_digest(recorded_manifest)
            if want_digest != got_digest:
                problems.append(
                    "input_manifest_sha256 does not name the manifest carried by the record"
                )
    return problems
