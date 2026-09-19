#!/usr/bin/env python3
"""Shared provenance contract for P-037 step evidence (A2.0 hardening).

The A2.1 claim is "richer facts, zero MOS/verdict movement". A differential can
only carry that claim when before and after measured ONE frozen population with
ONE measuring instrument in ONE qualified execution environment, and only the
treatment under test moved between them. This module is that contract, in
executable form, shared by both P-037 snapshot tools.

Instrument vs treatment
    INSTRUMENT_PATHS is what we measure WITH (engines, launcher, capture and
    compare plumbing, these tools). It may not move between before and after.
    TREATMENT_PATHS is what A2.1 intentionally changes (the extractor and the
    OwnIR schema). It may move between before and after; it may not move
    between a record's source commit and the HEAD that record is a claim about.

Frozen population
    A record names a ``population_commit``. Its primary inputs are the tracked
    ``.cs`` blobs under the input roots AT THAT COMMIT, materialized from git
    into a deterministic ignored directory under the checkout, never read from
    the working tree. Both sides of a comparison must name the same population.

Explicit-file semantic filesystem closure
    The extractor, fed explicit ``.cs`` paths, reads more than those paths:
    the sibling ``.xaml`` of a ``*.xaml.cs`` and any ``FodyWeavers.xml`` on a
    file's ancestor chain. Those committed side inputs are the SUPPORT manifest,
    materialized with the same adjacency. The ancestor walk continues above the
    materialization root to the filesystem root, so an external weaver config
    there is refused before extraction. Project/solution input modes are NOT
    certified here.

Execution environment
    Both Rust executables are built qualified (cargo --locked --release, path
    from cargo's compiler-artifact message, digest recorded) and only those are
    executed. Python/.NET/Rust identities are recorded and must be equal across
    a comparison. ``OWN_EXTRA_REF_DIRS`` is removed from every child environment
    and the extractor's own stderr attests that no extra reference was loaded.

Snapshot validity vs differential eligibility
    ``record_problems``       one record is self-consistent at its own commit
    ``provenance_problems``   ...and fresh at a given HEAD
    ``comparison_problems``   before is self-valid, after is fresh at HEAD, the
                              instrument, population, support closure and
                              execution profile are identical, and before is an
                              ancestor of after
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


class EvidenceRefused(RuntimeError):
    """The requested evidence claim cannot be checked honestly."""


# --------------------------------------------------------------------------
# Measurement contract
# --------------------------------------------------------------------------

# The launcher path is provenance DATA: it names a file inside the instrument
# closure and nothing in this module executes it. The Stage-3 launcher census
# exempts exactly this assignment shape, on this marker, in this file only.
OWN_CHECK_PATH = "scripts/own-check.sh"  # p037-stage3: launcher-literal-is-provenance-data

# What we measure WITH. Frozen across a before/after pair.
INSTRUMENT_PATHS: tuple[str, ...] = (
    "ownlang/",
    "rust/",
    OWN_CHECK_PATH,
    "scripts/p037_evidence.py",
    "scripts/p037_mos_snapshot.py",
    "scripts/p037_verdict_snapshot.py",
    "scripts/shadow_compare.py",
)

# What A2.1 is allowed to change between before and after.
TREATMENT_PATHS: tuple[str, ...] = (
    "frontend/roslyn/OwnSharp.Extractor/",
    "spec/",
)

# The full closure a record is fresh against: neither half may move between a
# record's source commit and the HEAD it is used at.
SUBJECT_PATHS: tuple[str, ...] = INSTRUMENT_PATHS + TREATMENT_PATHS

# Repo-local paths the snapshot programs execute or import directly. The
# self-check proves every one is inside SUBJECT_PATHS and exists in HEAD.
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

# The independent syntax-shape source that caught A1's return-parameter defect.
REPO_TREE_DIRS: tuple[str, ...] = ("frontend", "audit")

# Frozen populations are materialized here, one directory per population commit.
# Ignored by git, so materializing never dirties the tree; deterministic, so the
# extractor's cwd-relative file paths are identical on both sides of a pair.
POPULATION_DIR = ".p037-population"

# The extractor widens its Roslyn reference set from this variable. An evidence
# run removes it from the child environment AND reads the extractor's stderr for
# the line it prints whenever it did load extra references.
EXTRA_REF_ENV = "OWN_EXTRA_REF_DIRS"
EXTRA_REF_LINE = re.compile(r"^extractor: \+\d+ extra references from ")
REFERENCE_PROFILE_CLEAN = "removed-from-child-environment"

RUST_ARTIFACTS: dict[str, tuple[str, str]] = {
    "own-shadow-engine": ("own-shadow", "own-shadow-engine"),
    "own-cli": ("own-cli", "own-cli"),
}

# The semantic filesystem mechanisms of the extractor's EXPLICIT-FILE input
# mode, each anchored to the construct that implements it. tests/
# test_p037_evidence.py requires every anchor to match and every filesystem
# read site in the extractor to be classified, so a new side input cannot enter
# explicit-file analysis without this closure being updated on purpose.
EXPLICIT_FILE_SEMANTIC_FS_DEPENDENCIES: tuple[dict[str, str], ...] = (
    {
        "mechanism": "explicit-input-existence",
        "closure": "analysis_manifest",
        "anchor": r"if \(!File\.Exists\(path\)\)",
    },
    {
        "mechanism": "explicit-cs-contents",
        "closure": "analysis_manifest",
        "anchor": r"text = File\.ReadAllText\(path\);",
    },
    {
        "mechanism": "sibling-xaml",
        "closure": "support_manifest",
        "anchor": (
            r"File\.Exists\(xamlPath\) && "
            r"XamlDeclaresOwnedDataContext\(File\.ReadAllText\(xamlPath\)\)"
        ),
    },
    {
        "mechanism": "ancestor-fody",
        "closure": "support_manifest + external_ancestor_problems",
        "anchor": r"Path\.Combine\(dir, \"FodyWeavers\.xml\"\)",
    },
)


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def _git(
    *args: str, repo: Path = ROOT, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=False,
            input=stdin,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceRefused(f"git {' '.join(args)} failed: {exc}") from exc


def _git_text(*args: str, repo: Path = ROOT) -> str:
    proc = _git(*args, repo=repo)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise EvidenceRefused(
            f"git {' '.join(args)} exited {proc.returncode}"
            + (f": {detail}" if detail else "")
        )
    return proc.stdout.decode("utf-8").strip()


def commit_exists(rev: str, *, repo: Path = ROOT) -> bool:
    return _git("cat-file", "-e", f"{rev}^{{commit}}", repo=repo).returncode == 0


def resolve_commit(rev: str, *, repo: Path = ROOT) -> str:
    return _git_text("rev-parse", "--verify", f"{rev}^{{commit}}", repo=repo)


def is_ancestor(older: str, newer: str, *, repo: Path = ROOT) -> bool:
    return _git("merge-base", "--is-ancestor", older, newer, repo=repo).returncode == 0


def paths_differ(a: str, b: str, paths: Iterable[str], *, repo: Path = ROOT) -> bool:
    proc = _git("diff", "--quiet", a, b, "--", *paths, repo=repo)
    if proc.returncode == 0:
        return False
    if proc.returncode == 1:
        return True
    raise EvidenceRefused(
        f"git could not compare {a[:12]}..{b[:12]}: "
        f"{proc.stderr.decode('utf-8', 'replace').strip()}"
    )


def current_commit(*, repo: Path = ROOT) -> str:
    return _git_text("rev-parse", "HEAD", repo=repo)


def tree_is_dirty(*, repo: Path = ROOT) -> bool:
    return bool(_git_text("status", "--porcelain", repo=repo))


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _covered(path: str, roots: Iterable[str]) -> bool:
    p = _norm(path)
    for root in roots:
        r = _norm(root)
        if p == r or p.startswith(r + "/"):
            return True
    return False


def closure_problems(*, repo: Path = ROOT) -> list[str]:
    """Static self-check: every repo-local runtime path is in the closure."""
    problems: list[str] = []
    for path in RUNTIME_REPO_PATHS:
        if not _covered(path, SUBJECT_PATHS):
            problems.append(
                f"runtime path {path!r} is outside SUBJECT_PATHS; a measurement "
                "could change without invalidating its evidence"
            )
        if _git("cat-file", "-e", f"HEAD:{_norm(path)}", repo=repo).returncode != 0:
            problems.append(
                f"runtime path {path!r} is declared but does not exist in HEAD; "
                "a misspelled dependency would otherwise protect an empty path"
            )
    if len(set(SUBJECT_PATHS)) != len(SUBJECT_PATHS):
        problems.append("SUBJECT_PATHS contains duplicate entries")
    if set(INSTRUMENT_PATHS) & set(TREATMENT_PATHS):
        problems.append("a path is declared as both instrument and treatment")
    return problems


# --------------------------------------------------------------------------
# Frozen population: manifests, digests, materialization
# --------------------------------------------------------------------------

def _tree_blobs(commit: str, paths: tuple[str, ...], *, repo: Path = ROOT) -> dict[str, str]:
    """path -> blob for every blob at ``commit`` under ``paths`` (all, if empty)."""
    proc = _git("ls-tree", "-r", "-z", commit, "--", *paths, repo=repo)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise EvidenceRefused(
            f"cannot enumerate {list(paths) or 'the tree'} at {commit[:12]}"
            + (f": {detail}" if detail else "")
        )
    out: dict[str, str] = {}
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            meta, path_raw = raw.split(b"\t", 1)
            _mode, kind, blob = meta.decode("ascii").split()
            path = path_raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise EvidenceRefused(f"cannot parse git ls-tree record {raw!r}: {exc}") from exc
        if kind == "blob":
            out[path.replace("\\", "/")] = blob
    return out


def _sorted_entries(entries: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(entries, key=lambda e: e["path"].encode("utf-8"))


def analysis_manifest(
    commit: str, roots: tuple[str, ...], *, repo: Path = ROOT
) -> list[dict[str, str]]:
    """Exact committed C# primary input set at ``commit``: path and git blob."""
    if not roots:
        raise EvidenceRefused("an evidence input set may not have zero roots")
    blobs = _tree_blobs(commit, roots, repo=repo)
    out = _sorted_entries(
        {"path": p, "blob": b} for p, b in blobs.items() if p.endswith(".cs")
    )
    if not out:
        raise EvidenceRefused(
            f"input roots {list(roots)!r} contain no committed .cs files at {commit[:12]}"
        )
    return out


def support_manifest(
    commit: str, analysis: list[dict[str, str]], *, repo: Path = ROOT
) -> list[dict[str, str]]:
    """Committed side inputs the extractor reads BECAUSE of the primary inputs.

    Explicit-file mode only: the sibling ``.xaml`` of every ``*.xaml.cs``, and
    every ``FodyWeavers.xml`` on a primary file's ancestor chain up to the repo
    root. Project/solution expansion (``WeaverOwnedFiles`` via a ``.csproj``) is
    not part of this closure and is not certified by it.
    """
    tree = _tree_blobs(commit, (), repo=repo)
    out: dict[str, dict[str, str]] = {}
    for entry in analysis:
        path = entry["path"]
        if path.endswith(".xaml.cs"):
            sibling = path[:-3]
            if sibling in tree:
                out[sibling] = {"path": sibling, "blob": tree[sibling],
                                "mechanism": "sibling-xaml"}
        parts = path.split("/")[:-1]
        for depth in range(len(parts), -1, -1):
            candidate = "/".join([*parts[:depth], "FodyWeavers.xml"])
            if candidate in tree:
                out[candidate] = {"path": candidate, "blob": tree[candidate],
                                  "mechanism": "ancestor-fody"}
    return _sorted_entries(out.values())


def _manifest_digest(entries: list[dict[str, str]]) -> str:
    """Stable identity of a manifest, independent of JSON layout."""
    h = hashlib.sha256()
    for entry in entries:
        for field in ("path", "blob", "mechanism"):
            value = entry.get(field, "").encode("utf-8")
            h.update(len(value).to_bytes(8, "big"))
            h.update(value)
    return h.hexdigest()


def population_fields(
    population_commit: str, roots: tuple[str, ...], *, repo: Path = ROOT
) -> dict[str, Any]:
    commit = resolve_commit(population_commit, repo=repo)
    analysis = analysis_manifest(commit, roots, repo=repo)
    support = support_manifest(commit, analysis, repo=repo)
    return {
        "population_commit": commit,
        "input_roots": list(roots),
        "analysis_manifest": analysis,
        "analysis_manifest_sha256": _manifest_digest(analysis),
        "support_manifest": support,
        "support_manifest_sha256": _manifest_digest(support),
    }


def materialization_root(
    population_commit: str, analysis_digest: str, *, repo: Path = ROOT
) -> Path:
    """One directory per (population commit, primary manifest): the corpus and
    the repo populations of the same commit never share a tree, so a take of
    one cannot rewrite the files a take of the other is reading."""
    return repo / POPULATION_DIR / population_commit / analysis_digest[:16]


def acquire_population(root: Path) -> Path:
    """One take per population at a time. The extractor reads side inputs
    lazily (the weaver walk runs after parsing), so a concurrent rewrite of the
    same directory changes facts without failing anything visible; the lease
    refuses that up front and population_intact() refuses it after the fact."""
    lock = root.with_name(root.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise EvidenceRefused(
            f"another take holds this population ({lock}); takes run one at a time. "
            "Remove the lease only if no take is running"
        ) from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\n")
    return lock


def release_population(lock: Path) -> None:
    lock.unlink(missing_ok=True)


def _manifest_entries(record: dict[str, Any], key: str) -> list[dict[str, str]]:
    raw = record.get(key)
    if not isinstance(raw, list):
        raise EvidenceRefused(f"record carries no {key} list")
    out: list[dict[str, str]] = []
    for i, entry in enumerate(raw):
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("path"), str)
            and isinstance(entry.get("blob"), str)
        ):
            raise EvidenceRefused(f"{key}[{i}] is not a path/blob record")
        clean = {"path": str(entry["path"]), "blob": str(entry["blob"])}
        if isinstance(entry.get("mechanism"), str):
            clean["mechanism"] = str(entry["mechanism"])
        out.append(clean)
    return out


def materialize_population(record: dict[str, Any], *, repo: Path = ROOT) -> Path:
    """Write the frozen population's exact blobs under the deterministic root.

    Fresh every time (the directory is removed first), verified afterwards by
    re-hashing every written file through git so the bytes on disk ARE the
    committed blobs, and checked to contain nothing else.
    """
    commit = record.get("population_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise EvidenceRefused("record carries no full population_commit")
    entries = _manifest_entries(record, "analysis_manifest") + _manifest_entries(
        record, "support_manifest"
    )
    digest = record.get("analysis_manifest_sha256")
    if not isinstance(digest, str) or not digest:
        raise EvidenceRefused("record carries no analysis_manifest_sha256")
    root = materialization_root(commit, digest, repo=repo)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for entry in entries:
        rel = _norm(entry["path"])
        if rel.startswith("../") or "/../" in rel or Path(rel).is_absolute():
            raise EvidenceRefused(f"refusing to materialize a non-relative path {rel!r}")
        proc = _git("cat-file", "blob", entry["blob"], repo=repo)
        if proc.returncode != 0:
            raise EvidenceRefused(
                f"blob {entry['blob'][:12]} for {rel} is not in this repository"
            )
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(proc.stdout)
    problems = population_intact(record, root, repo=repo)
    if problems:
        raise EvidenceRefused("; ".join(problems))
    return root


def population_intact(record: dict[str, Any], root: Path, *, repo: Path = ROOT) -> list[str]:
    """Every materialized file still re-hashes to its blob and nothing else is
    there. Run after materializing AND after measuring: the extractor reads
    side inputs lazily, so a population that changed under a run produced facts
    about a population nobody named."""
    entries = _manifest_entries(record, "analysis_manifest") + _manifest_entries(
        record, "support_manifest"
    )
    missing = [e["path"] for e in entries if not (root / _norm(e["path"])).is_file()]
    if missing:
        return [f"{len(missing)} population file(s) are missing; first: {missing[0]}"]
    listing = "\n".join(str(root / _norm(e["path"])) for e in entries) + "\n"
    proc = _git("hash-object", "--stdin-paths", repo=repo, stdin=listing.encode("utf-8"))
    if proc.returncode != 0:
        return ["git could not re-hash the materialized population"]
    hashes = proc.stdout.decode("ascii").split()
    problems: list[str] = []
    changed = [e["path"] for e, h in zip(entries, hashes, strict=True) if h != e["blob"]]
    if changed:
        problems.append(
            f"{len(changed)} population file(s) do not re-hash to their blobs; "
            f"first: {changed[0]}"
        )
    on_disk = sum(1 for p in root.rglob("*") if p.is_file())
    if on_disk != len(entries):
        problems.append(
            f"materialization root holds {on_disk} file(s), manifest names {len(entries)}"
        )
    return problems


def analysis_paths(record: dict[str, Any], root: Path) -> list[Path]:
    return [root / _norm(e["path"]) for e in _manifest_entries(record, "analysis_manifest")]


def _fody_probe(candidate: Path) -> str:
    """Mirror of the extractor's ancestor walk: File.GetAttributes semantics.

    FileNotFound / DirectoryNotFound keep the extractor walking; any other
    failure makes it grant the weaver exemption. So: absent, present, or
    uninspectable, and only absent is acceptable outside the population.
    """
    try:
        os.lstat(candidate)
    except (FileNotFoundError, NotADirectoryError):
        return "absent"
    except OSError:
        return "uninspectable"
    return "present"


def external_ancestor_problems(root: Path) -> list[str]:
    """No FodyWeavers.xml may exist, or be uninspectable, above the population.

    The extractor walks from each file's directory to the filesystem root;
    inside the materialized population that walk is deterministic (only
    committed blobs exist there), above it the environment decides. The
    exemption a stray external config would grant changes facts with no change
    to any commit, so it is refused before extraction, not discovered after.
    """
    problems: list[str] = []
    for ancestor in root.resolve().parents:
        state = _fody_probe(ancestor / "FodyWeavers.xml")
        if state == "present":
            problems.append(
                f"external FodyWeavers.xml at {ancestor} would grant the extractor's weaver "
                "exemption to every materialized file; remove it or move the checkout"
            )
        elif state == "uninspectable":
            problems.append(
                f"cannot prove FodyWeavers.xml absent at {ancestor}; the extractor fails "
                "closed toward an exemption there"
            )
    return problems


# --------------------------------------------------------------------------
# Execution environment: profile, qualified artifacts, reference sanitation
# --------------------------------------------------------------------------

def _tool_text(argv: list[str], *, cwd: Path = ROOT, timeout: float = 120) -> str:
    """Run one tool and return non-empty stdout, or refuse the evidence."""
    try:
        proc = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceRefused(f"{argv[0]} could not run: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip()[-800:]
        raise EvidenceRefused(
            f"{' '.join(argv)} exited {proc.returncode}" + (f": {detail}" if detail else "")
        )
    value = proc.stdout.strip()
    if not value:
        raise EvidenceRefused(f"{' '.join(argv)} returned no output")
    return value


def _dotnet_runtimes() -> list[str]:
    runtimes: list[str] = []
    for line in _tool_text(["dotnet", "--list-runtimes"]).splitlines():
        parts = line.split()
        if len(parts) >= 2:
            runtimes.append(f"{parts[0]} {parts[1]}")
    if not runtimes:
        raise EvidenceRefused("dotnet --list-runtimes named no runtime")
    return sorted(runtimes)


def rust_identity() -> dict[str, str]:
    rustc = _tool_text(["rustc", "-vV"])
    host = ""
    for line in rustc.splitlines():
        if line.startswith("host:"):
            host = line.split(":", 1)[1].strip()
    if not host:
        raise EvidenceRefused("rustc -vV did not report a host triple")
    return {"rustc": rustc, "cargo": _tool_text(["cargo", "-V"]), "host": host}


def execution_profile(*, include_rust: bool) -> dict[str, Any]:
    """Identities that change what a run measures; an eligibility field, not
    decoration. The reference engine is Python, the extractor's reference set
    is the .NET runtime's trusted platform assemblies, the port is Rust."""
    profile: dict[str, Any] = {
        "python": {
            "implementation": platform.python_implementation(),
            "version": sys.version,
        },
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "dotnet": {"sdk": _tool_text(["dotnet", "--version"]), "runtimes": _dotnet_runtimes()},
    }
    if include_rust:
        profile["rust"] = rust_identity()
    return profile


def build_rust_artifact(package: str, binary: str, *, repo: Path = ROOT) -> dict[str, Any]:
    """Build the exact Rust executable an evidence run will execute, qualified.

    The path comes from cargo's own compiler-artifact message, never from a
    guessed target/ layout; the digest is taken from that file; the lock file,
    toolchain and source commit are recorded next to it.
    """
    # The package's own artifacts are removed first so that the executable this
    # call qualifies is the one THIS build produced from HEAD's sources: cargo
    # judges freshness by source fingerprints, never by the output's bytes, so
    # a target/ file rewritten by anyone would otherwise be "fresh" and qualified
    # as is. Dependencies stay cached; only the package is recompiled and linked.
    clean = ["cargo", "clean", "--release", "-p", package]
    argv = [
        "cargo", "build", "--locked", "--release", "--message-format=json",
        "-p", package, "--bin", binary,
    ]
    try:
        cleaned = subprocess.run(
            clean, cwd=repo / "rust", capture_output=True, text=True, check=False, timeout=600,
        )
        if cleaned.returncode != 0:
            raise EvidenceRefused(
                f"{' '.join(clean)} failed: {cleaned.stderr.strip()[-800:]}"
            )
        proc = subprocess.run(
            argv, cwd=repo / "rust", capture_output=True, text=True, check=False,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise EvidenceRefused(f"cannot build {package}/{binary}: {exc}") from exc
    if proc.returncode != 0:
        raise EvidenceRefused(
            f"{' '.join(argv)} failed: {proc.stderr.strip()[-1200:]}"
        )
    executable: str | None = None
    fresh: bool | None = None
    for line in proc.stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict) or message.get("reason") != "compiler-artifact":
            continue
        target = message.get("target")
        if not isinstance(target, dict):
            continue
        kinds = target.get("kind")
        if (
            target.get("name") == binary
            and isinstance(kinds, list)
            and "bin" in kinds
            and isinstance(message.get("executable"), str)
        ):
            executable = str(message["executable"])
            fresh = bool(message.get("fresh"))
    if executable is None:
        raise EvidenceRefused(
            f"cargo reported no compiler-artifact executable for {package}/{binary}"
        )
    if fresh:
        raise EvidenceRefused(
            f"cargo did not rebuild {package}/{binary} after cleaning it; refusing to "
            "qualify an executable this build did not produce"
        )
    path = Path(executable)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceRefused(f"built {package}/{binary} but cannot read {path}: {exc}") from exc
    rust = rust_identity()
    lock = repo / "rust" / "Cargo.lock"
    try:
        lock_sha = hashlib.sha256(lock.read_bytes()).hexdigest()
    except OSError as exc:
        raise EvidenceRefused(f"cannot read {lock}: {exc}") from exc
    try:
        repo_path: str | None = path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        repo_path = None
    return {
        "package": package,
        "binary": binary,
        "profile": "release",
        "executable": str(path),
        "repo_path": repo_path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "source_commit": current_commit(repo=repo),
        "dirty": tree_is_dirty(repo=repo),
        "cargo_argv": argv,
        "cargo_clean_argv": clean,
        "rebuilt_by_this_call": True,
        "rustc": rust["rustc"],
        "cargo": rust["cargo"],
        "host": rust["host"],
        "cargo_lock_blob": _git_text("rev-parse", "HEAD:rust/Cargo.lock", repo=repo),
        "cargo_lock_sha256": lock_sha,
    }


def artifact_problems(artifact: dict[str, Any]) -> list[str]:
    """The file about to be executed IS the qualified build the record names."""
    problems: list[str] = []
    for key in ("package", "binary", "executable", "sha256", "bytes", "source_commit",
                "rustc", "cargo", "host", "cargo_lock_blob"):
        if key not in artifact:
            problems.append(f"artifact record lacks {key}")
    if problems:
        return problems
    if artifact.get("dirty") is not False:
        problems.append("artifact was built on a dirty tree")
    try:
        raw = Path(str(artifact["executable"])).read_bytes()
    except OSError as exc:
        return [*problems, f"qualified executable cannot be read: {exc}"]
    if hashlib.sha256(raw).hexdigest() != artifact["sha256"] or len(raw) != artifact["bytes"]:
        problems.append(
            f"executable {artifact['executable']} does not match the qualified build's digest"
        )
    return problems


def new_take_dir() -> Path:
    """A private, unique directory for one take's sealed executables. Outside
    the checkout on purpose: nothing that runs against the tree can reach it."""
    return Path(tempfile.mkdtemp(prefix="p037-take-"))


def seal_artifact(artifact: dict[str, Any], take_dir: Path) -> dict[str, Any]:
    """Copy the qualified executable into the take's private directory; the run
    executes ONLY that copy.

    target/release/<bin> is shared mutable state: any cargo build, anyone's,
    can replace it while a take is running, and the launcher would open the new
    file under the old digest on record. Sealing prevents that; finalize_run's
    re-hash of the sealed copy afterwards attests that prevention held.
    """
    source = Path(str(artifact["executable"]))
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise EvidenceRefused(f"qualified executable cannot be read for sealing: {exc}") from exc
    if hashlib.sha256(raw).hexdigest() != artifact["sha256"] or len(raw) != artifact["bytes"]:
        raise EvidenceRefused(
            f"{source} no longer matches the qualified build at sealing time"
        )
    take_dir.mkdir(parents=True, exist_ok=True)
    sealed = take_dir / source.name
    sealed.write_bytes(raw)
    sealed.chmod(0o700)
    check = sealed.read_bytes()
    if hashlib.sha256(check).hexdigest() != artifact["sha256"] or len(check) != artifact["bytes"]:
        raise EvidenceRefused("the sealed copy does not match the qualified build")
    artifact["executed"] = {
        "sealed_path": str(sealed),
        "sha256": artifact["sha256"],
        "bytes": len(check),
    }
    return artifact


def executed_artifact_problems(artifact: dict[str, Any]) -> list[str]:
    """Post-run attestation: the file that ran still IS the qualified build."""
    executed = artifact.get("executed")
    if not isinstance(executed, dict) or not isinstance(executed.get("sealed_path"), str):
        return ["artifact was never sealed for execution"]
    try:
        raw = Path(str(executed["sealed_path"])).read_bytes()
    except OSError as exc:
        return [f"the sealed executable cannot be read after the run: {exc}"]
    digest = hashlib.sha256(raw).hexdigest()
    if digest != artifact.get("sha256") or len(raw) != artifact.get("bytes"):
        return ["the executable that ran no longer matches the qualified build's digest"]
    return []


def finalize_run(
    snapshot: dict[str, Any], provenance: dict[str, Any], root: Path, *, repo: Path = ROOT
) -> None:
    """The post-run attestations every take makes before writing its record.

    The population must still re-hash to its blobs, every sealed executable
    must still re-hash to its qualified build, and the tree must still be
    clean. Any failure makes the snapshot not evidence; the reasons are kept.
    """
    tampered = population_intact(provenance, root, repo=repo)
    snapshot["post_run_population_intact"] = not tampered
    if tampered:
        snapshot["is_evidence"] = False
        snapshot["population_tampered"] = tampered
    artifacts = snapshot.get("artifacts")
    if isinstance(artifacts, dict):
        for name, artifact in artifacts.items():
            if not isinstance(artifact, dict):
                continue
            problems = executed_artifact_problems(artifact)
            executed = artifact.get("executed")
            if not isinstance(executed, dict):
                executed = {}
                artifact["executed"] = executed
            executed["post_run_intact"] = not problems
            if problems:
                snapshot["is_evidence"] = False
                tampered_artifacts = snapshot.setdefault("artifact_tampered", {})
                tampered_artifacts[name] = problems
    if tree_is_dirty(repo=repo):
        snapshot["is_evidence"] = False
        snapshot["post_run_dirty"] = True


def sanitized_env(**overrides: str) -> dict[str, str]:
    """The child environment for every launcher/extractor process."""
    env = {k: v for k, v in os.environ.items() if k != EXTRA_REF_ENV}
    env.update(overrides)
    return env


def reference_contamination(stderr_text: str) -> list[str]:
    """The extractor's own attestation that extra references were loaded."""
    return [line.strip() for line in stderr_text.splitlines() if EXTRA_REF_LINE.match(line.strip())]


def clean_reference_profile() -> dict[str, Any]:
    return {EXTRA_REF_ENV: REFERENCE_PROFILE_CLEAN, "observed_extra_reference_lines": 0}


def reference_profile_problems(record: dict[str, Any]) -> list[str]:
    profile = record.get("reference_profile")
    if not isinstance(profile, dict):
        return ["record carries no reference_profile"]
    problems: list[str] = []
    if profile.get(EXTRA_REF_ENV) != REFERENCE_PROFILE_CLEAN:
        problems.append(f"{EXTRA_REF_ENV} was not removed from the child environment")
    if profile.get("observed_extra_reference_lines") != 0:
        problems.append("the extractor reported loading extra references during the run")
    return problems


def scratch_problems(out: Path, *, repo: Path = ROOT) -> list[str]:
    """Evidence is written outside the checkout or into an ignored path only."""
    try:
        rel = out.resolve().relative_to(repo.resolve())
    except ValueError:
        return []
    if _git("check-ignore", "-q", "--", rel.as_posix(), repo=repo).returncode == 0:
        return []
    return [
        f"--out {out} is inside the checkout and not git-ignored; write evidence outside "
        "the tree (or to an ignored scratch path) and copy it into docs/evidence in a "
        "separate record commit"
    ]


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

def evidence_fields(
    input_roots: tuple[str, ...],
    *,
    population_commit: str = "HEAD",
    source_commit: str | None = None,
    repo: Path = ROOT,
) -> dict[str, Any]:
    """Provenance fields of a snapshot taken at ``source_commit`` (HEAD)."""
    problems = closure_problems(repo=repo)
    if problems:
        raise EvidenceRefused("; ".join(problems))
    source = resolve_commit(source_commit or "HEAD", repo=repo)
    dirty = tree_is_dirty(repo=repo)
    population = population_fields(population_commit, input_roots, repo=repo)
    if not is_ancestor(population["population_commit"], source, repo=repo):
        raise EvidenceRefused(
            f"population commit {population['population_commit'][:12]} is not an ancestor "
            f"of (or equal to) source commit {source[:12]}"
        )
    return {
        "source_commit": source,
        "dirty": dirty,
        "is_evidence": not dirty,
        "instrument_paths": list(INSTRUMENT_PATHS),
        "treatment_paths": list(TREATMENT_PATHS),
        "subject_paths": list(SUBJECT_PATHS),
        **population,
    }


def record_problems(record: dict[str, Any], *, repo: Path = ROOT) -> list[str]:
    """Self-consistency of one evidence record at its OWN source commit.

    This is what a historical ``before`` has to prove: honest bits, the
    closure this tool defines, a population that re-derives from its commit
    byte for byte, a clean reference profile, a recorded execution profile,
    artifacts built from the same commit.
    """
    problems: list[str] = []
    source = record.get("source_commit")
    if not isinstance(source, str) or not source:
        return ["evidence records no source_commit"]
    if record.get("dirty") is not False:
        problems.append("evidence was taken on a dirty tree")
    if record.get("is_evidence") is not True:
        problems.append("record does not mark itself is_evidence=true")
    if record.get("post_run_dirty"):
        problems.append("the tree was dirty after the measurement")
    if record.get("post_run_population_intact") is not True:
        problems.append("record does not attest that the population stayed intact through the run")
    if record.get("instrument_paths") != list(INSTRUMENT_PATHS):
        problems.append("recorded instrument_paths differ from this tool's instrument closure")
    if record.get("treatment_paths") != list(TREATMENT_PATHS):
        problems.append("recorded treatment_paths differ from this tool's treatment closure")
    if record.get("subject_paths") != list(SUBJECT_PATHS):
        problems.append("recorded subject_paths differ from this tool's measurement closure")

    roots_raw = record.get("input_roots")
    roots: tuple[str, ...] = ()
    if (
        isinstance(roots_raw, list)
        and roots_raw
        and all(isinstance(x, str) and x for x in roots_raw)
    ):
        roots = tuple(str(x) for x in roots_raw)
    else:
        problems.append("record carries no valid input_roots")

    if not commit_exists(source, repo=repo):
        return [*problems, f"source commit {source[:12]} is not present in this checkout"]

    population = record.get("population_commit")
    if not isinstance(population, str) or not commit_exists(population, repo=repo):
        problems.append("record names no population_commit present in this checkout")
    else:
        if not is_ancestor(population, source, repo=repo):
            problems.append(
                f"population commit {population[:12]} is not an ancestor of (or equal to) "
                f"source commit {source[:12]}"
            )
        try:
            recorded_analysis = _manifest_entries(record, "analysis_manifest")
            recorded_support = _manifest_entries(record, "support_manifest")
        except EvidenceRefused as exc:
            problems.append(str(exc))
        else:
            if roots:
                try:
                    analysis = analysis_manifest(population, roots, repo=repo)
                    support = support_manifest(population, analysis, repo=repo)
                except EvidenceRefused as exc:
                    problems.append(str(exc))
                else:
                    if recorded_analysis != analysis:
                        problems.append(
                            "recorded analysis_manifest does not match the population "
                            "commit's exact C# input set"
                        )
                    if recorded_support != support:
                        problems.append(
                            "recorded support_manifest does not match the population "
                            "commit's semantic support closure"
                        )
            if record.get("analysis_manifest_sha256") != _manifest_digest(recorded_analysis):
                problems.append("analysis_manifest_sha256 does not name the carried manifest")
            if record.get("support_manifest_sha256") != _manifest_digest(recorded_support):
                problems.append("support_manifest_sha256 does not name the carried manifest")

    problems.extend(reference_profile_problems(record))

    profile = record.get("execution_profile")
    if not isinstance(profile, dict) or not profile:
        problems.append("record carries no execution_profile")

    artifacts = record.get("artifacts", {})
    if not isinstance(artifacts, dict):
        problems.append("artifacts is not an object")
    else:
        for name, artifact in artifacts.items():
            if not isinstance(artifact, dict):
                problems.append(f"artifact {name!r} is not an object")
                continue
            if artifact.get("source_commit") != source:
                problems.append(f"artifact {name!r} was not built from the record's source commit")
            if artifact.get("dirty") is not False:
                problems.append(f"artifact {name!r} was built on a dirty tree")
            if not isinstance(artifact.get("sha256"), str):
                problems.append(f"artifact {name!r} carries no sha256")
            executed = artifact.get("executed")
            if not isinstance(executed, dict):
                problems.append(f"artifact {name!r} carries no executed attestation")
            else:
                if executed.get("sha256") != artifact.get("sha256"):
                    problems.append(
                        f"artifact {name!r} executed a file other than the qualified build"
                    )
                if executed.get("post_run_intact") is not True:
                    problems.append(
                        f"artifact {name!r} does not attest it stayed intact through the run"
                    )
    return problems


def provenance_problems(
    record: dict[str, Any], *, against: str = "HEAD", repo: Path = ROOT
) -> list[str]:
    """Whether ``record`` is fresh evidence at ``against``: self-valid, an
    ancestor, and neither instrument nor treatment moved in between."""
    problems = [*closure_problems(repo=repo), *record_problems(record, repo=repo)]
    source = record.get("source_commit")
    if not isinstance(source, str) or not source or not commit_exists(source, repo=repo):
        return problems
    if not commit_exists(against, repo=repo):
        return [*problems, f"comparison commit {against!r} is not present in this checkout"]
    if not is_ancestor(source, against, repo=repo):
        problems.append(
            f"source commit {source[:12]} is not an ancestor of {against}; "
            "the evidence describes a history this tree does not contain"
        )
        return problems
    try:
        if paths_differ(source, against, INSTRUMENT_PATHS, repo=repo):
            problems.append(
                f"the measurement instrument changed between {source[:12]} and {against}; "
                "re-take the evidence"
            )
        if paths_differ(source, against, TREATMENT_PATHS, repo=repo):
            problems.append(
                f"the treatment changed between {source[:12]} and {against}; this record "
                "does not describe the analyzer at that commit"
            )
    except EvidenceRefused as exc:
        problems.append(str(exc))
    return problems


def comparison_problems(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    against: str = "HEAD",
    repo: Path = ROOT,
) -> list[str]:
    """Differential eligibility: may these two records be read as one
    before/after experiment whose result is a claim about ``against``?

    before: self-valid at its own commit (it predates the treatment change on
            purpose, so it is NOT required to be fresh at HEAD).
    after:  self-valid AND fresh at ``against``.
    pair:   ancestry, identical instrument, identical frozen population and
            support closure, identical execution profile.
    """
    problems = [f"before: {p}" for p in record_problems(before, repo=repo)]
    problems += [f"after: {p}" for p in provenance_problems(after, against=against, repo=repo)]

    before_source = before.get("source_commit")
    after_source = after.get("source_commit")
    if (
        isinstance(before_source, str)
        and isinstance(after_source, str)
        and commit_exists(before_source, repo=repo)
        and commit_exists(after_source, repo=repo)
    ):
        if not is_ancestor(before_source, after_source, repo=repo):
            problems.append(
                f"before source {before_source[:12]} is not an ancestor of "
                f"after source {after_source[:12]}"
            )
        else:
            try:
                if paths_differ(before_source, after_source, INSTRUMENT_PATHS, repo=repo):
                    problems.append(
                        "the measurement instrument differs between before and after; "
                        "only the treatment may move across a comparison"
                    )
            except EvidenceRefused as exc:
                problems.append(str(exc))

    if before.get("population_commit") != after.get("population_commit"):
        problems.append("before/after name different frozen populations")
    if before.get("input_roots") != after.get("input_roots"):
        problems.append("before/after input_roots differ")
    if before.get("analysis_manifest") != after.get("analysis_manifest"):
        problems.append("before/after primary population manifests differ")
    if before.get("support_manifest") != after.get("support_manifest"):
        problems.append("before/after semantic support manifests differ")

    before_profile = before.get("execution_profile")
    after_profile = after.get("execution_profile")
    if (
        isinstance(before_profile, dict)
        and isinstance(after_profile, dict)
        and before_profile
        and after_profile
        and before_profile != after_profile
    ):
        problems.append("before/after execution profiles differ")
    return problems


# --------------------------------------------------------------------------
# CLI: exercise the environment-facing machinery where cargo, git and dotnet
# are real (the Linux dogfood job), without taking any baseline.
# --------------------------------------------------------------------------

def _cli_profile() -> int:
    include_rust = shutil.which("cargo") is not None
    print(json.dumps(execution_profile(include_rust=include_rust), indent=1, sort_keys=True))
    return 0


def _cli_artifacts() -> int:
    rc = 0
    take_dir = new_take_dir()
    try:
        for name, (package, binary) in RUST_ARTIFACTS.items():
            artifact = build_rust_artifact(package, binary)
            problems = artifact_problems(artifact)
            if not problems:
                seal_artifact(artifact, take_dir)
                problems = executed_artifact_problems(artifact)
            for problem in problems:
                print(f"FAIL[{name}]: {problem}")
                rc = 1
            print(
                f"{'ok' if not problems else 'FAIL'}[{name}] {artifact['executable']} "
                f"sha256={artifact['sha256']} bytes={artifact['bytes']} "
                f"source={artifact['source_commit'][:12]} host={artifact['host']}"
                + (f" sealed={artifact['executed']['sealed_path']}" if "executed" in artifact
                   else "")
            )
    finally:
        shutil.rmtree(take_dir, ignore_errors=True)
    return rc


def _cli_population(source: str, commit: str, materialize: bool, cleanup: bool) -> int:
    roots = {"corpus": CORPUS_DIRS, "repo": REPO_TREE_DIRS}[source]
    fields = population_fields(commit, roots)
    analysis = fields["analysis_manifest"]
    support = fields["support_manifest"]
    print(
        f"population {fields['population_commit'][:12]} source={source}: "
        f"{len(analysis)} primary .cs, {len(support)} support file(s)"
    )
    for entry in support:
        print(f"  support {entry['mechanism']:14s} {entry['path']}")
    if not materialize:
        return 0
    lock = acquire_population(
        materialization_root(fields["population_commit"], fields["analysis_manifest_sha256"])
    )
    try:
        root = materialize_population(fields)
        problems = external_ancestor_problems(root) + population_intact(fields, root)
        for problem in problems:
            print(f"FAIL[population]: {problem}")
        print(f"materialized {len(analysis) + len(support)} file(s) under {root}")
        if cleanup:
            shutil.rmtree(root)
            print("removed the materialization again (cleanup requested)")
    finally:
        release_population(lock)
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("profile", help="print the execution profile of this machine")
    sub.add_parser("artifacts", help="build both qualified Rust executables and verify them")
    p = sub.add_parser("population", help="derive (and optionally materialize) a frozen population")
    p.add_argument("--source", required=True, choices=("corpus", "repo"))
    p.add_argument("--commit", default="HEAD")
    p.add_argument("--materialize", action="store_true")
    p.add_argument("--cleanup", action="store_true",
                   help="remove the materialization after verifying it")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "profile":
            return _cli_profile()
        if args.cmd == "artifacts":
            return _cli_artifacts()
        return _cli_population(args.source, args.commit, args.materialize, args.cleanup)
    except EvidenceRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
