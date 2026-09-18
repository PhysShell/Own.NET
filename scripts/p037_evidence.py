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
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

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
        obj = _norm(path)
        if _git("cat-file", "-e", f"HEAD:{obj}").returncode != 0:
            problems.append(
                f"runtime path {path!r} is declared but does not exist in HEAD; "
                "a misspelled dependency would otherwise protect an empty path"
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


def input_paths(input_roots: tuple[str, ...], *, commit: str = "HEAD") -> list[Path]:
    """Exact committed C# denominator as working-tree paths.

    The path set comes from git, not filesystem rglob: after a .NET build the
    checkout contains generated obj/**/*.cs files, and measuring them while the
    evidence manifest names only committed blobs would be two denominators
    pretending to be one.
    """
    return [ROOT / entry["path"] for entry in _tree_cs_manifest(commit, input_roots)]


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


def _tool_text(argv: list[str], *, cwd: Path = ROOT) -> str:
    """Run one tool and return non-empty stdout, or refuse the evidence."""
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceRefused(f"{argv[0]} could not run: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip()[-800:]
        raise EvidenceRefused(
            f"{' '.join(argv)} exited {proc.returncode}"
            + (f": {detail}" if detail else "")
        )
    value = proc.stdout.strip()
    if not value:
        raise EvidenceRefused(f"{' '.join(argv)} returned no version/output")
    return value


def tool_versions(*, include_rust: bool) -> dict[str, str]:
    """Versions of the executables that can change an evidence run."""
    versions = {
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "dotnet": _tool_text(["dotnet", "--version"]),
    }
    if include_rust:
        versions["rustc"] = _tool_text(["rustc", "--version"])
        versions["cargo"] = _tool_text(["cargo", "--version"])
    return versions


def build_rust_binary(package: str, binary: str) -> dict[str, str | int]:
    """Build and name the exact Rust executable an evidence run will execute."""
    argv = ["cargo", "build", "--release", "--locked", "-p", package, "--bin", binary]
    try:
        proc = subprocess.run(
            argv,
            cwd=ROOT / "rust",
            capture_output=True,
            text=True,
            check=False,
            timeout=1200,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceRefused(f"cannot build {package}/{binary}: {exc}") from exc
    if proc.returncode != 0:
        raise EvidenceRefused(
            f"{' '.join(argv)} failed for {package}/{binary}: "
            f"{proc.stderr.strip()[-1200:]}"
        )
    name = binary + (".exe" if sys.platform == "win32" else "")
    path = ROOT / "rust" / "target" / "release" / name
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceRefused(
            f"built {package}/{binary} but cannot read {path}: {exc}"
        ) from exc
    return {
        "package": package,
        "binary": binary,
        "path": str(path),
        "repo_path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "build": " ".join(argv),
    }


def record_problems(record: dict[str, Any]) -> list[str]:
    """Self-consistency of one historical evidence record at its own source."""
    problems: list[str] = []
    source = record.get("source_commit")
    if not isinstance(source, str) or not source:
        return ["evidence records no source_commit"]
    if record.get("dirty") is not False:
        problems.append("evidence was taken on a dirty tree")
    if record.get("is_evidence") is not True:
        problems.append("record does not mark itself is_evidence=true")

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

    manifest_raw = record.get("input_manifest")
    recorded_manifest: list[dict[str, str]] = []
    if not isinstance(manifest_raw, list) or not manifest_raw:
        problems.append("record carries no non-empty input_manifest")
    else:
        for i, entry in enumerate(manifest_raw):
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

    if _git("cat-file", "-e", f"{source}^{{commit}}").returncode != 0:
        return [*problems, f"source commit {source[:12]} is not present in this checkout"]

    if roots and recorded_manifest:
        try:
            at_source = _tree_cs_manifest(source, roots)
        except EvidenceRefused as exc:
            problems.append(str(exc))
        else:
            if recorded_manifest != at_source:
                problems.append(
                    "recorded input_manifest does not match the source commit's exact C# input set"
                )
        if record.get("input_manifest_sha256") != _manifest_digest(recorded_manifest):
            problems.append(
                "input_manifest_sha256 does not name the manifest carried by the record"
            )
    return problems


def comparison_problems(
    before: dict[str, Any], after: dict[str, Any]
) -> list[str]:
    """Can two historical records be read as one before/after experiment?"""
    problems: list[str] = []
    for label, record in (("before", before), ("after", after)):
        for problem in record_problems(record):
            problems.append(f"{label}: {problem}")

    before_source = before.get("source_commit")
    after_source = after.get("source_commit")
    if isinstance(before_source, str) and isinstance(after_source, str):
        if _git("merge-base", "--is-ancestor", before_source, after_source).returncode != 0:
            problems.append(
                f"before source {before_source[:12]} is not an ancestor of "
                f"after source {after_source[:12]}"
            )

    if before.get("subject_paths") != after.get("subject_paths"):
        problems.append("before/after subject_paths differ")
    if before.get("input_roots") != after.get("input_roots"):
        problems.append("before/after input_roots differ")
    if before.get("input_manifest") != after.get("input_manifest"):
        problems.append("before/after source-input manifests differ")

    before_tools = before.get("toolchains")
    after_tools = after.get("toolchains")
    if not isinstance(before_tools, dict) or not before_tools:
        problems.append("before record carries no toolchain identity")
    if not isinstance(after_tools, dict) or not after_tools:
        problems.append("after record carries no toolchain identity")
    if isinstance(before_tools, dict) and isinstance(after_tools, dict):
        if before_tools != after_tools:
            problems.append("before/after toolchain identities differ")
    return problems


def provenance_problems(record: dict[str, Any], *, against: str = "HEAD") -> list[str]:
    """Whether record is still fresh evidence at against."""
    problems = [*closure_problems(), *record_problems(record)]
    source = record.get("source_commit")
    if not isinstance(source, str) or not source:
        return problems

    declared_subjects = record.get("subject_paths")
    if declared_subjects != list(SUBJECT_PATHS):
        problems.append(
            "recorded subject_paths differ from the current measurement closure; "
            "the older evidence does not cover the dependency set this tool now requires"
        )

    roots_raw = record.get("input_roots")
    roots = (
        tuple(str(x) for x in roots_raw)
        if isinstance(roots_raw, list) and all(isinstance(x, str) for x in roots_raw)
        else ()
    )

    if _git("cat-file", "-e", f"{against}^{{commit}}").returncode != 0:
        return [*problems, f"comparison commit {against!r} is not present in this checkout"]
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

    if roots:
        try:
            at_source = _tree_cs_manifest(source, roots)
            at_against = _tree_cs_manifest(against, roots)
        except EvidenceRefused as exc:
            problems.append(str(exc))
        else:
            if at_source != at_against:
                problems.append(
                    f"source inputs changed between {source[:12]} and {against}; "
                    "re-take the evidence"
                )
    return problems


# Measurement-contract constants are deliberately declared after every helper
# that launches subprocesses. The Stage-3 surface census sees the literal
# launcher path as data, with no nearby process launch to misclassify as a call.
OWN_CHECK_PATH = "scripts/own-check.sh"

SUBJECT_PATHS: tuple[str, ...] = (
    "frontend/roslyn/OwnSharp.Extractor/",
    "ownlang/",
    "rust/",
    OWN_CHECK_PATH,
    "scripts/p037_evidence.py",
    "scripts/p037_mos_snapshot.py",
    "scripts/p037_verdict_snapshot.py",
    "scripts/shadow_compare.py",
    "spec/",
)

RUNTIME_REPO_PATHS: tuple[str, ...] = (
    "frontend/roslyn/OwnSharp.Extractor/",
    "ownlang/",
    "rust/",
    OWN_CHECK_PATH,
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

REPO_TREE_DIRS: tuple[str, ...] = ("frontend", "audit")
