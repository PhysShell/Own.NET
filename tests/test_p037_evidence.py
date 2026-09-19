#!/usr/bin/env python3
"""Hostile controls for P-037's A2.0 evidence contract.

Fourteen negative controls and one positive control over the shared gate in
scripts/p037_evidence.py. Each negative control breaks exactly one clause of
the contract and requires the gate to refuse; the positive control proves the
gate still ADMITS the experiment it exists for (old before, current after, an
intentional treatment change in between, everything else identical).

The controls are not vacuous: every mutation is aimed at the predicate that
owns its clause, and where a clause is about history (ancestry, staleness,
population drift) a small synthetic git history is built in a temporary clone
so the real git-backed predicate runs over real commits.

Two fitness pins ride along: the extractor's explicit-file filesystem read
sites must all be classified against the four semantic mechanisms the support
closure covers, and the repository population's support closure must be
exactly the three files it is today.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import p037_evidence as ev  # noqa: E402

failures = 0

SHAPES = ("corpus/p037-shapes",)

SYNTHETIC_PROFILE: dict[str, Any] = {
    "python": {"implementation": "CPython", "version": "3.11.0 (synthetic)"},
    "platform": {"system": "Linux", "machine": "x86_64"},
    "dotnet": {"sdk": "8.0.0", "runtimes": ["Microsoft.NETCore.App 8.0.0"]},
    "rust": {"rustc": "rustc 1.0.0 (synthetic)", "cargo": "cargo 1.0.0",
             "host": "x86_64-unknown-linux-gnu"},
}

EXPECTED_REPO_SUPPORT = {
    "frontend/roslyn/samples/InjectedDcViewSample.xaml": "sibling-xaml",
    "frontend/roslyn/samples/ViewOwnsVmSample.xaml": "sibling-xaml",
    "frontend/roslyn/samples/weaved/FodyWeavers.xml": "ancestor-fody",
}
# Attached to SharedEnumerator.cs only through .csproj expansion
# (WeaverOwnedFiles), which explicit-file mode never performs.
NOT_REPO_SUPPORT = "frontend/roslyn/samples/weaved-linked/Proj/FodyWeavers.xml"

EXTRACTOR = ROOT / "frontend/roslyn/OwnSharp.Extractor/Program.cs"
FS_API = re.compile(
    r"\b(File\.(?:ReadAllText|ReadAllBytes|ReadAllLines|ReadLines|Exists|GetAttributes|"
    r"OpenRead|OpenText)|Directory\.(?:EnumerateFiles|Exists|GetFiles|EnumerateDirectories)|"
    r"XDocument\.Load|XmlReader\.Create)\(([^,)]*)"
)
DECL = re.compile(r"^static\s+[\w<>\[\]?,. ]+?\s+(\w+)\s*\(")

# Every filesystem read site in the extractor, classified. The explicit-file
# entries are the four semantic mechanisms the evidence closure covers; a new
# site (or a moved one) fails by NAME until someone classifies it here, and a
# classification into explicit-file analysis obliges a support-closure update
# in scripts/p037_evidence.py. Counting File.ReadAllText per file would guard
# spelling; this guards the contract.
EXTRACTOR_FS_SITES: dict[tuple[str, str, str], tuple[str, int]] = {
    ("ProjectCsFiles", "File.Exists", "full"): ("project-solution-mode", 1),
    ("ProjectCsFiles", "XDocument.Load", "full"): ("project-solution-mode", 1),
    ("ProjectCsFiles", "Directory.EnumerateFiles", "dir"): ("project-solution-mode", 1),
    ("ProjectCsFiles", "File.Exists", "path"): ("project-solution-mode", 1),
    ("SolutionProjects", "File.ReadAllLines", "sln"): ("project-solution-mode", 1),
    ("SolutionProjects", "File.Exists", "path"): ("project-solution-mode", 1),
    ("ProjectBinDirs", "File.Exists", "full"): ("project-solution-mode", 1),
    ("ProjectBinDirs", "Directory.Exists", "bin"): ("project-solution-mode", 1),
    ("Expand", "Directory.Exists", "p"): ("directory-input-mode", 1),
    ("Expand", "Directory.EnumerateFiles", "p"): ("directory-input-mode", 1),
    ("AncestorsHaveWeaverConfig", "File.GetAttributes", "candidate"):
        ("explicit-file:ancestor-fody", 1),
    ("<top-level>", "File.Exists", "path"): ("explicit-file:explicit-input-existence", 1),
    ("<top-level>", "File.ReadAllText", "path"): ("explicit-file:explicit-cs-contents", 1),
    ("<top-level>", "File.Exists", "xamlPath"): ("explicit-file:sibling-xaml", 1),
    ("<top-level>", "File.ReadAllText", "xamlPath"): ("explicit-file:sibling-xaml", 1),
    ("<top-level>", "Directory.Exists", "dir"): ("reference-environment", 2),
    ("<top-level>", "Directory.EnumerateFiles", "dir"): ("reference-environment", 2),
}


def ok(name: str) -> None:
    print(f"ok[{name}]")


def fail(name: str, detail: str) -> None:
    global failures
    failures += 1
    print(f"FAIL[{name}]: {detail}")


def check(name: str, condition: bool, detail: str) -> None:
    if condition:
        ok(name)
    else:
        fail(name, detail)


def expect_problem(name: str, problems: list[str], needle: str) -> None:
    if any(needle in p for p in problems):
        ok(name)
    else:
        fail(name, f"expected a refusal containing {needle!r}, got {problems!r}")


def complete(record: dict[str, Any]) -> dict[str, Any]:
    """A provenance record plus the run-time fields a take() writes."""
    full = copy.deepcopy(record)
    full["execution_profile"] = copy.deepcopy(SYNTHETIC_PROFILE)
    full["reference_profile"] = ev.clean_reference_profile()
    full["artifacts"] = {}
    full["post_run_population_intact"] = True
    return full


# --------------------------------------------------------------------------
# synthetic history in a temporary clone (real git, never the checkout's .git)
# --------------------------------------------------------------------------

class History:
    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="p037-hostile-"))
        self.repo = self.tmp / "repo"
        self.env = dict(os.environ)
        self.env.update({
            "GIT_AUTHOR_NAME": "p037-control", "GIT_AUTHOR_EMAIL": "p037@example.invalid",
            "GIT_COMMITTER_NAME": "p037-control", "GIT_COMMITTER_EMAIL": "p037@example.invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        })
        subprocess.run(
            ["git", "clone", "--quiet", "--depth=1", f"file://{ROOT.resolve()}", str(self.repo)],
            check=True, capture_output=True, env=self.env,
        )
        self.head_tree = self.git("rev-parse", "HEAD^{tree}")
        self.index_count = 0

    def git(self, *args: str, stdin: bytes | None = None) -> str:
        proc = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True,
                              check=False, env=self.env, input=stdin)
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.decode('utf-8', 'replace')}")
        return proc.stdout.decode("utf-8").strip()

    def show(self, path: str) -> bytes:
        proc = subprocess.run(["git", "-C", str(self.repo), "cat-file", "blob", f"HEAD:{path}"],
                              capture_output=True, check=True, env=self.env)
        return proc.stdout

    def tree_with(self, path: str, content: bytes) -> str:
        """HEAD's tree with one path replaced, built through a private index."""
        blob = self.git("hash-object", "-w", "--stdin", stdin=content)
        self.index_count += 1
        index = self.tmp / f"index-{self.index_count}"
        env = {**self.env, "GIT_INDEX_FILE": str(index)}
        for argv in (
            ["read-tree", self.head_tree],
            ["update-index", "--add", "--cacheinfo", f"100644,{blob},{path}"],
        ):
            subprocess.run(["git", "-C", str(self.repo), *argv], check=True,
                           capture_output=True, env=env)
        proc = subprocess.run(["git", "-C", str(self.repo), "write-tree"], check=True,
                              capture_output=True, env=env)
        return proc.stdout.decode("ascii").strip()

    def commit(self, tree: str, parents: list[str], message: str) -> str:
        args = ["commit-tree", tree, "-m", message]
        for parent in parents:
            args += ["-p", parent]
        return self.git(*args)

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# fitness pins
# --------------------------------------------------------------------------

def _extractor_fs_sites() -> dict[tuple[str, str, str], int]:
    sites: dict[tuple[str, str, str], int] = {}
    enclosing: str | None = None
    for line in EXTRACTOR.read_text(encoding="utf-8").splitlines():
        m = DECL.match(line)
        if m:
            enclosing = m.group(1)
        code = line.split("//", 1)[0]
        if not code.strip():
            if line.startswith("}"):
                enclosing = None
            continue
        for api, arg in FS_API.findall(code):
            key = (enclosing or "<top-level>", api, arg.strip())
            sites[key] = sites.get(key, 0) + 1
        if line.startswith("}"):
            enclosing = None
    return sites


def fitness_pins() -> None:
    source = EXTRACTOR.read_text(encoding="utf-8")
    for dep in ev.EXPLICIT_FILE_SEMANTIC_FS_DEPENDENCIES:
        hits = len(re.findall(dep["anchor"], source))
        check(f"mechanism-anchored:{dep['mechanism']}", hits == 1,
              f"anchor matched {hits} time(s) in Program.cs; the mechanism moved or was removed")
    classified = {c for c, _ in EXTRACTOR_FS_SITES.values()}
    for dep in ev.EXPLICIT_FILE_SEMANTIC_FS_DEPENDENCIES:
        check(f"mechanism-has-classified-site:{dep['mechanism']}",
              f"explicit-file:{dep['mechanism']}" in classified,
              "no read site is classified under this mechanism")
    sites = _extractor_fs_sites()
    unclassified = sorted(k for k in sites if k not in EXTRACTOR_FS_SITES)
    check("extractor-fs-sites-all-classified", not unclassified,
          "unclassified filesystem read site(s) in Program.cs: "
          f"{unclassified}; classify each in tests/test_p037_evidence.py and, if it "
          "belongs to explicit-file analysis, extend the support closure")
    moved = sorted(
        f"{k}: expected {n}, found {sites.get(k, 0)}"
        for k, (_, n) in EXTRACTOR_FS_SITES.items() if sites.get(k, 0) != n
    )
    check("extractor-fs-sites-counts-pinned", not moved,
          f"read-site multiplicity moved: {moved}")

    fields = ev.population_fields("HEAD", ev.REPO_TREE_DIRS)
    support = {e["path"]: e["mechanism"] for e in fields["support_manifest"]}
    check("repo-support-closure-is-exactly-three", support == EXPECTED_REPO_SUPPORT,
          f"support closure {support!r} != {EXPECTED_REPO_SUPPORT!r}")
    check("linked-project-fody-is-not-explicit-file-support", NOT_REPO_SUPPORT not in support,
          f"{NOT_REPO_SUPPORT} is a project-mode dependency, not an explicit-file one")
    print(f"  repo population at HEAD: {len(fields['analysis_manifest'])} primary .cs, "
          f"{len(support)} support file(s)")


# --------------------------------------------------------------------------
# controls
# --------------------------------------------------------------------------

def record_level_controls() -> None:
    base = complete(ev.evidence_fields(SHAPES))
    live = ev.provenance_problems(base)
    if live:
        fail("fresh-record-valid", "; ".join(live))
        return
    ok("fresh-record-valid")
    allowed = ev.comparison_problems(base, copy.deepcopy(base))
    check("same-commit-pair-allowed", not allowed, "; ".join(allowed))

    def pair() -> tuple[dict[str, Any], dict[str, Any]]:
        return copy.deepcopy(base), copy.deepcopy(base)

    before, after = pair()
    before["is_evidence"] = False
    expect_problem("control-01-before-not-evidence", ev.comparison_problems(before, after),
                   "before: record does not mark itself is_evidence=true")
    before, after = pair()
    before["dirty"] = True
    expect_problem("control-02-before-dirty", ev.comparison_problems(before, after),
                   "before: evidence was taken on a dirty tree")
    before, after = pair()
    after["is_evidence"] = False
    expect_problem("control-03-after-not-evidence", ev.comparison_problems(before, after),
                   "after: record does not mark itself is_evidence=true")
    before, after = pair()
    after["dirty"] = True
    expect_problem("control-04-after-dirty", ev.comparison_problems(before, after),
                   "after: evidence was taken on a dirty tree")
    before, after = pair()
    after["post_run_dirty"] = True
    expect_problem("control-04b-after-post-run-dirty", ev.comparison_problems(before, after),
                   "dirty after the measurement")
    before, after = pair()
    after["post_run_population_intact"] = False
    expect_problem("control-09c-population-tampered-during-run",
                   ev.comparison_problems(before, after),
                   "population stayed intact through the run")

    before, after = pair()
    before["analysis_manifest"][0]["blob"] = "0" * 40
    expect_problem("control-06-before-manifest-tampered", ev.comparison_problems(before, after),
                   "before: recorded analysis_manifest does not match")
    before, after = pair()
    after["analysis_manifest"][0]["blob"] = "0" * 40
    expect_problem("control-07-after-manifest-tampered", ev.comparison_problems(before, after),
                   "after: recorded analysis_manifest does not match")
    before, after = pair()
    after["analysis_manifest_sha256"] = "0" * 64
    expect_problem("control-07b-after-digest-tampered", ev.comparison_problems(before, after),
                   "analysis_manifest_sha256")

    before, after = pair()
    after["execution_profile"]["python"]["version"] = "3.13.0 (another interpreter)"
    expect_problem("control-11-execution-profile-mismatch",
                   ev.comparison_problems(before, after),
                   "execution profiles differ")
    before, after = pair()
    after["execution_profile"] = {}
    expect_problem("control-11b-execution-profile-missing",
                   ev.comparison_problems(before, after),
                   "carries no execution_profile")

    # 12: semantic support drift, on the population that HAS a support closure.
    repo_base = complete(ev.evidence_fields(ev.REPO_TREE_DIRS))
    before, after = copy.deepcopy(repo_base), copy.deepcopy(repo_base)
    after["support_manifest"][0]["blob"] = "0" * 40
    expect_problem("control-12-support-manifest-drift",
                   ev.comparison_problems(before, after),
                   "after: recorded support_manifest does not match")
    before, after = copy.deepcopy(repo_base), copy.deepcopy(repo_base)
    after["support_manifest"] = after["support_manifest"][1:]
    expect_problem("control-12b-support-file-dropped",
                   ev.comparison_problems(before, after),
                   "support_manifest")

    # 13: ambient reference profile, three layers.
    saved = os.environ.get(ev.EXTRA_REF_ENV)
    os.environ[ev.EXTRA_REF_ENV] = "/nonexistent/ref-pack"
    try:
        child = ev.sanitized_env(OWEN_RUST_CORE="/qualified/own-cli")
    finally:
        if saved is None:
            os.environ.pop(ev.EXTRA_REF_ENV, None)
        else:
            os.environ[ev.EXTRA_REF_ENV] = saved
    check("control-13a-extra-ref-dirs-removed-from-child-env",
          ev.EXTRA_REF_ENV not in child and child.get("OWEN_RUST_CORE") == "/qualified/own-cli",
          f"child env still carries {ev.EXTRA_REF_ENV} or lost the override")
    seen = ev.reference_contamination(
        "extractor: analysing 3 file(s)\nextractor: +12 extra references from /x/ref\n"
    )
    check("control-13b-extractor-attestation-read",
          seen == ["extractor: +12 extra references from /x/ref"],
          f"contamination lines {seen!r}")
    check("control-13b-clean-stderr-is-clean",
          ev.reference_contamination("extractor: analysing 3 file(s)\n") == [],
          "a clean stderr was reported as contaminated")
    before, after = pair()
    after["reference_profile"]["observed_extra_reference_lines"] = 1
    expect_problem("control-13c-observed-extra-references-refused",
                   ev.comparison_problems(before, after),
                   "loading extra references")
    before, after = pair()
    after["reference_profile"][ev.EXTRA_REF_ENV] = "inherited"
    expect_problem("control-13d-inherited-env-refused",
                   ev.comparison_problems(before, after),
                   "was not removed from the child environment")

    # 10: the file about to run must be the qualified build the record names.
    with tempfile.TemporaryDirectory(prefix="p037-artifact-") as td:
        exe = Path(td) / "own-cli"
        exe.write_bytes(b"qualified build bytes\n")
        artifact: dict[str, Any] = {
            "package": "own-cli", "binary": "own-cli", "executable": str(exe),
            "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(), "bytes": exe.stat().st_size,
            "source_commit": base["source_commit"], "dirty": False,
            "rustc": "rustc", "cargo": "cargo", "host": "x86_64", "cargo_lock_blob": "0" * 40,
        }
        check("control-10-qualified-artifact-accepted", not ev.artifact_problems(artifact),
              "; ".join(ev.artifact_problems(artifact)))
        attested = {**artifact, "executed": {"sealed_path": str(exe), "sha256": artifact["sha256"],
                                             "bytes": artifact["bytes"], "post_run_intact": True}}
        before, after = pair()
        after["artifacts"] = {"own-cli": copy.deepcopy(attested)}
        check("control-10-attested-artifact-record-accepted",
              not ev.comparison_problems(before, after),
              "; ".join(ev.comparison_problems(before, after)))
        exe.write_bytes(b"some other binary that happened to be lying around\n")
        expect_problem("control-10-artifact-digest-mismatch-refused",
                       ev.artifact_problems(artifact), "does not match the qualified build")
        before, after = pair()
        after["artifacts"] = {"own-cli": {**attested, "source_commit": "0" * 40}}
        expect_problem("control-10b-artifact-from-other-commit-refused",
                       ev.comparison_problems(before, after),
                       "was not built from the record's source commit")
        before, after = pair()
        after["artifacts"] = {"own-cli": {**attested, "dirty": True}}
        expect_problem("control-10c-artifact-from-dirty-tree-refused",
                       ev.comparison_problems(before, after), "built on a dirty tree")
        before, after = pair()
        after["artifacts"] = {"own-cli": {**attested, "executed": {**attested["executed"],
                                                                   "sha256": "f" * 64}}}
        expect_problem("control-10d-executed-other-than-qualified-refused",
                       ev.comparison_problems(before, after),
                       "executed a file other than the qualified build")
        before, after = pair()
        after["artifacts"] = {"own-cli": {**attested, "executed": {**attested["executed"],
                                                                   "post_run_intact": False}}}
        expect_problem("control-10d-not-intact-through-run-refused",
                       ev.comparison_problems(before, after),
                       "does not attest it stayed intact through the run")
        before, after = pair()
        after["artifacts"] = {"own-cli": {k: v for k, v in attested.items() if k != "executed"}}
        expect_problem("control-10d-unsealed-artifact-refused",
                       ev.comparison_problems(before, after), "no executed attestation")

    # 10d, through the real lifecycle: seal, mutate, finalize_run flips is_evidence.
    with tempfile.TemporaryDirectory(prefix="p037-seal-") as td:
        built = Path(td) / "target" / "own-cli"
        built.parent.mkdir()
        built.write_bytes(b"qualified build bytes\n")
        artifact = {
            "package": "own-cli", "binary": "own-cli", "executable": str(built),
            "sha256": hashlib.sha256(built.read_bytes()).hexdigest(),
            "bytes": built.stat().st_size, "source_commit": base["source_commit"],
            "dirty": False, "rustc": "rustc", "cargo": "cargo", "host": "x86_64",
            "cargo_lock_blob": "0" * 40,
        }
        take_dir = Path(td) / "take"
        ev.seal_artifact(artifact, take_dir)
        sealed = Path(artifact["executed"]["sealed_path"])
        check("control-10d-sealed-copy-is-private-and-identical",
              sealed.parent == take_dir and sealed != built
              and sealed.read_bytes() == b"qualified build bytes\n"
              and not ev.executed_artifact_problems(artifact),
              "the sealed copy is not a private, verified copy of the qualified build")
        # a rebuild of the shared target/ path after sealing must not reach the run
        built.write_bytes(b"a later cargo build of somebody else\n")
        check("control-10d-rebuild-after-sealing-does-not-reach-the-run",
              not ev.executed_artifact_problems(artifact),
              "; ".join(ev.executed_artifact_problems(artifact)))
        # the sealed copy itself rewritten under the run: the record cannot be evidence
        sealed.chmod(0o600)
        with sealed.open("ab") as handle:
            handle.write(b"tampered under the run\n")
        expect_problem("control-10d-post-run-artifact-integrity-fails",
                       ev.executed_artifact_problems(artifact),
                       "no longer matches the qualified build")
        snapshot: dict[str, Any] = {**copy.deepcopy(base), "artifacts": {"own-cli": artifact}}
        pop_root = ev.materialize_population(snapshot)
        try:
            ev.finalize_run(snapshot, snapshot, pop_root)
        finally:
            shutil.rmtree(pop_root, ignore_errors=True)
        check("control-10d-finalize-run-drops-evidence",
              snapshot["is_evidence"] is False
              and snapshot["artifacts"]["own-cli"]["executed"]["post_run_intact"] is False
              and "own-cli" in snapshot.get("artifact_tampered", {}),
              f"finalize_run kept is_evidence={snapshot.get('is_evidence')}")
        expect_problem("control-10d-tampered-run-refused-as-evidence",
                       ev.record_problems(snapshot),
                       "does not attest it stayed intact through the run")

    # 14: an external weaver config above the population, present or unprovable.
    with tempfile.TemporaryDirectory(prefix="p037-ancestors-") as td:
        pop = Path(td) / "a" / "b" / "population"
        pop.mkdir(parents=True)
        (pop / "FodyWeavers.xml").write_text("<Weavers/>")  # INSIDE: allowed
        clean = [p for p in ev.external_ancestor_problems(pop) if td in p]
        check("control-14-clean-ancestors-pass", not clean, "; ".join(clean))
        (Path(td) / "a" / "FodyWeavers.xml").write_text("<Weavers/>")
        expect_problem("control-14-external-ancestor-fody-refused",
                       ev.external_ancestor_problems(pop), "external FodyWeavers.xml")
        (Path(td) / "a" / "FodyWeavers.xml").unlink()
        real_probe = ev._fody_probe
        blocked = (Path(td) / "a" / "FodyWeavers.xml").resolve()

        def blocked_probe(candidate: Path) -> str:
            return "uninspectable" if candidate.resolve() == blocked else real_probe(candidate)

        ev._fody_probe = blocked_probe
        try:
            expect_problem("control-14-uninspectable-ancestor-refused",
                           ev.external_ancestor_problems(pop),
                           "cannot prove FodyWeavers.xml absent")
        finally:
            ev._fody_probe = real_probe

    # output location: evidence never lands in a tracked place.
    expect_problem("evidence-output-in-tracked-tree-refused",
                   ev.scratch_problems(ROOT / "docs" / "evidence" / "p037-a2-probe.json"),
                   "not git-ignored")
    check("evidence-output-outside-tree-allowed",
          not ev.scratch_problems(Path(tempfile.gettempdir()) / "p037-a2-probe.json"),
          "a path outside the checkout was refused")


def history_controls() -> None:
    hist = History()
    try:
        treatment = "frontend/roslyn/OwnSharp.Extractor/Program.cs"
        instrument = "scripts/p037_evidence.py"
        first_shape = ev.analysis_manifest("HEAD", SHAPES, repo=hist.repo)[0]["path"]

        a = hist.commit(hist.tree_with(treatment, hist.show(treatment) + b"\n// old treatment\n"),
                        [], "A: old treatment (root)")
        c = hist.commit(hist.head_tree, [a], "C: new treatment")
        x = hist.commit(hist.head_tree, [], "X: unrelated root")
        d = hist.commit(hist.tree_with(instrument, hist.show(instrument) + b"\n# drift\n"),
                        [c], "D: instrument moved")
        e = hist.commit(hist.tree_with(treatment, hist.show(treatment) + b"\n// newer\n"),
                        [c], "E: treatment moved again")
        p = hist.commit(hist.tree_with(first_shape, hist.show(first_shape) + b"\n// drift\n"),
                        [], "P: population drift (root)")
        m = hist.commit(hist.head_tree, [a, p], "M: merges the drifted population")

        check("synthetic-history-non-vacuous",
              ev.paths_differ(a, c, ev.TREATMENT_PATHS, repo=hist.repo)
              and not ev.paths_differ(a, c, ev.INSTRUMENT_PATHS, repo=hist.repo)
              and ev.paths_differ(c, d, ev.INSTRUMENT_PATHS, repo=hist.repo)
              and ev.paths_differ(c, e, ev.TREATMENT_PATHS, repo=hist.repo),
              "the synthetic commits do not move what they are meant to move")

        before = complete(ev.evidence_fields(SHAPES, population_commit=a, source_commit=a,
                                             repo=hist.repo))
        after = complete(ev.evidence_fields(SHAPES, population_commit=a, source_commit=c,
                                            repo=hist.repo))
        positive = ev.comparison_problems(before, after, against=c, repo=hist.repo)
        check("positive-control-allowed-treatment-change-admitted", not positive,
              "; ".join(positive))

        before_x = complete(ev.evidence_fields(SHAPES, population_commit=x, source_commit=x,
                                               repo=hist.repo))
        expect_problem("control-05-before-not-ancestor-of-after",
                       ev.comparison_problems(before_x, after, against=c, repo=hist.repo),
                       "is not an ancestor of after source")

        expect_problem("control-08-after-stale-instrument-moved-since",
                       ev.comparison_problems(before, after, against=d, repo=hist.repo),
                       "the measurement instrument changed between")
        expect_problem("control-08-after-stale-treatment-moved-since",
                       ev.comparison_problems(before, after, against=e, repo=hist.repo),
                       "the treatment changed between")
        expect_problem("control-08-verify-alone-refuses-stale",
                       ev.provenance_problems(after, against=d, repo=hist.repo),
                       "the measurement instrument changed between")

        after_m = complete(ev.evidence_fields(SHAPES, population_commit=p, source_commit=m,
                                              repo=hist.repo))
        drift = ev.comparison_problems(before, after_m, against=m, repo=hist.repo)
        expect_problem("control-09-frozen-population-drift", drift,
                       "name different frozen populations")
        expect_problem("control-09-primary-manifests-differ", drift,
                       "primary population manifests differ")
        check("control-09-drift-is-the-only-refusal",
              all("population" in p_ for p_ in drift),
              f"unexpected extra refusals: {drift!r}")

        # instrument drift BETWEEN before and after, ancestry intact
        after_d = complete(ev.evidence_fields(SHAPES, population_commit=a, source_commit=d,
                                              repo=hist.repo))
        expect_problem("control-08b-instrument-differs-across-pair",
                       ev.comparison_problems(before, after_d, against=d, repo=hist.repo),
                       "instrument differs between before and after")

        # materialization of a frozen population, verified byte for byte
        root = ev.materialize_population(before, repo=hist.repo)
        try:
            paths = ev.analysis_paths(before, root)
            check("frozen-population-materialized",
                  root.is_dir() and all(p_.is_file() for p_ in paths)
                  and root.parent.parent.name == ev.POPULATION_DIR,
                  "materialization did not produce the population's files")
            drifted = hist.show(first_shape) + b"\n// drift\n"
            check("frozen-population-is-the-named-commit-not-the-tree",
                  paths[0].read_bytes() != drifted
                  and paths[0].read_bytes() == hist.show(first_shape),
                  "materialized bytes are not the population commit's blob")
            check("materialization-is-ignored-by-git",
                  not ev.tree_is_dirty(repo=hist.repo),
                  "materializing the population dirtied the tree")
            check("population-intact-after-materialization",
                  not ev.population_intact(before, root, repo=hist.repo),
                  "; ".join(ev.population_intact(before, root, repo=hist.repo)))
            with paths[0].open("ab") as handle:
                handle.write(b"// a concurrent writer\n")
            expect_problem("control-09c-population-rewritten-under-the-run",
                           ev.population_intact(before, root, repo=hist.repo),
                           "do not re-hash to their blobs")
            paths[1].unlink()
            expect_problem("control-09c-population-file-vanished-under-the-run",
                           ev.population_intact(before, root, repo=hist.repo),
                           "are missing")
            lease = ev.acquire_population(root)
            try:
                try:
                    ev.acquire_population(root)
                    fail("population-lease-is-exclusive", "a second lease was granted")
                except ev.EvidenceRefused as exc:
                    expect_problem("population-lease-is-exclusive", [str(exc)],
                                   "another take holds this population")
            finally:
                ev.release_population(lease)
        finally:
            shutil.rmtree(root, ignore_errors=True)
    finally:
        hist.cleanup()


def main() -> int:
    problems = ev.closure_problems()
    check("runtime-closure-covered", not problems, "; ".join(problems))
    if problems:
        return 1
    fitness_pins()
    record_level_controls()
    history_controls()
    if failures:
        print(f"RESULT: {failures} P-037 evidence control(s) failed")
        return 1
    print("RESULT: all P-037 evidence controls passed (14 negative, 1 positive, fitness pins)")
    return 0


def run() -> int:
    """Entry point required by tests/run_tests.py's test_*.py census."""
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
