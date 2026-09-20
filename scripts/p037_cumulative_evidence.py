#!/usr/bin/env python3
"""P-037 A2.2-S: one governed cumulative measurement of the whole A2 treatment.

A2 changed the extractor's FACT SURFACE (the guarded-fact sidecar, the orphan
carrier, the call-like forms) under one obligation: richer facts, zero MOS and
zero verdict movement, on both engines. Every A2.2 step rehearsed that
obligation locally; this program takes the one cumulative measurement that
closes the treatment, against the baseline evidence R recorded at T on the
measurement machine, and writes a single evidence artifact that says, per
document and per engine, what moved and what did not.

Three claims, proven together:

  FACTS     MOVED       the extractor's facts differ from T's on some documents,
                        and EVERY difference is inside the surfaces A2 was
                        allowed to touch: `functions[*].guarded_facts` and the
                        top-level `guarded_functions[]` carrier. A change to a
                        legacy body, a signature, `services`, `components`,
                        `stats` or the schema version is UNEXPECTED and refuses
                        the claim.
  MOS       UNCHANGED   the summaries surface of every document is identical
                        before and after on Python and on Rust (the four
                        governed takes compared against R by the snapshot tools,
                        plus a per-document layer differential recomputed here).
  VERDICTS  UNCHANGED   every verdict of every file is identical before and
                        after on Python and on Rust, and the two engines agree.

How the layer differential is anchored (no instrument change): the baseline
facts are re-derived by the extractor built from T's own sources, in the same
checkout root the takes ran in, and are accepted only when their digest equals
the one the R record carries for that document; the treatment facts are
re-derived by the tree under test and accepted only when their digest equals
the fresh take's. Each anchored pair then goes through both engines' capture
(the P-022 envelope: lowered, summaries, verdicts) and every layer document is
digested. A document that cannot be anchored refuses the differential.

Provenance is fail-closed: the checkout HEAD must be exactly the named
treatment commit; the tree must be clean before and after; T must be an
ancestor of R and R of the treatment; the instrument closure must be identical
at T, R and the treatment (object ids recorded as the instrument identity); the
baseline records must be the very files committed at R (digests pinned by R's
manifest and by R's tree); every take must be fresh at the treatment; every
comparison must be eligible by the snapshot tools' own rules. Any failure
stops the run with `REFUSED`, and nothing is written as evidence.

The measured checkout is never written: takes materialize the frozen
population under the ignored `.p037-population/`, T's extractor is built in a
temporary worktree under --out, and every output lands under --out, which must
lie outside the checkout.

In evidence mode the measurement is ONE command and one transaction: `--stage`
is refused (it exists for rehearsal and debugging only); `--out` must not
exist, everything runs in a sibling staging directory, a REFUSED run deletes
the staging directory so that no evidence-looking file (a take with
`is_evidence=true`, a takes.json, a layers.json) is left behind, while a valid
negative result (accepted=false, a real movement) is published in full and
exits 1, and an accepted result is published and exits 0. The driver itself is
pinned: it must run from a clean git checkout and be byte-identical to the blob
at that checkout's HEAD (commit, blob and sha256 recorded as the evidence
orchestrator's identity), and every measurement module it imports must resolve
to the measured checkout's own file, proven by path, not assumed from import
order.

Usage (the operator run, on the measurement machine):
  p037_cumulative_evidence.py run --repo <checkout at the treatment> \
      --treatment <sha> --population <T> --baseline-commit <R> --out <dir outside the checkout>
  p037_cumulative_evidence.py run ... --mode rehearsal --baseline-dir <dir> --baseline-prefix ""
  p037_cumulative_evidence.py --selftest
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "p037-cumulative-evidence/1"
TAKES: tuple[tuple[str, str, list[str]], ...] = (
    ("mos-repo", "p037_mos_snapshot.py", ["--source", "repo"]),
    ("mos-corpus", "p037_mos_snapshot.py", ["--source", "corpus"]),
    ("verdict-python", "p037_verdict_snapshot.py", ["--engine", "python"]),
    ("verdict-rust", "p037_verdict_snapshot.py", ["--engine", "rust"]),
)
ALLOWED_TOP_LEVEL_ADDED = frozenset({"guarded_functions"})
LAYERS = ("lowered", "summaries", "verdicts")
ENGINES = ("python", "rust")
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class Refused(RuntimeError):
    """The claim cannot be made honestly; nothing is written as evidence."""


@dataclass
class Config:
    repo: Path
    treatment: str
    population: str
    baseline_commit: str
    baseline_dir: Path
    baseline_prefix: str
    out: Path
    mode: str
    stage: str
    timeout: float
    manifest: Path | None
    tools: dict[str, Any] = field(default_factory=dict)
    driver: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(doc: Any) -> str:
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise Refused(f"git {' '.join(args)} failed: {proc.stderr.strip()[-300:]}")
    return proc.stdout.strip()


def git_ok(repo: Path, *args: str) -> bool:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    return proc.returncode == 0


def object_ids(repo: Path, commit: str, paths: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in paths:
        spec = f"{commit}:{p.rstrip('/')}"
        out[p] = git(repo, "rev-parse", spec)
    return out


def load_json(path: Path) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return doc


MEASUREMENT_MODULES: dict[str, str] = {
    "p037_evidence": "scripts/p037_evidence.py",
    "p037_mos_snapshot": "scripts/p037_mos_snapshot.py",
    "p037_verdict_snapshot": "scripts/p037_verdict_snapshot.py",
    "shadow_compare": "scripts/shadow_compare.py",
    "ownlang": "ownlang/__init__.py",
    "ownlang.repro": "ownlang/repro.py",
}


def verify_module_paths(modules: dict[str, Any], repo: Path) -> None:
    """Every measurement module must be the measured checkout's own file, by path."""
    problems: list[str] = []
    for name, rel in MEASUREMENT_MODULES.items():
        mod = modules.get(name)
        actual = getattr(mod, "__file__", None) if mod is not None else None
        expected = (repo / rel).resolve()
        if not isinstance(actual, str) or Path(actual).resolve() != expected:
            problems.append(f"{name} resolved to {actual!r}, not {expected}")
    if problems:
        raise Refused("a measurement module is not the measured checkout's: " + "; ".join(problems))


def bootstrap(repo: Path) -> dict[str, Any]:
    """Import the measured checkout's own instrument modules (never this file's), proven."""
    for p in (str(repo / "scripts"), str(repo)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    for name in list(sys.modules):
        if name in MEASUREMENT_MODULES or name == "ownlang" or name.startswith("ownlang."):
            sys.modules.pop(name, None)
    modules: dict[str, Any] = {name: importlib.import_module(name) for name in MEASUREMENT_MODULES}
    verify_module_paths(modules, repo)
    return {
        "ev": modules["p037_evidence"],
        "mos": modules["p037_mos_snapshot"],
        "verdict": modules["p037_verdict_snapshot"],
        "shadow": modules["shadow_compare"],
        "repro": modules["ownlang.repro"],
    }


def validate_stage(mode: str, stage: str) -> None:
    """Evidence is one command: a staged run is a different protocol and is refused."""
    if mode == "evidence" and stage != "all":
        raise Refused(f"evidence is one command; --stage {stage} is for rehearsal and "
                      "debugging only")


def driver_identity(script: Path) -> dict[str, Any]:
    """This program's own provenance: the checkout it runs from, HEAD, blob, cleanliness."""
    script = script.resolve()
    identity: dict[str, Any] = {"path": str(script), "sha256": sha256_file(script),
                                "commit": None, "blob": None, "clean": False,
                                "byte_identical_to_head": False}
    proc = subprocess.run(["git", "-C", str(script.parent), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        identity["problem"] = "the driver is not inside a git checkout"
        return identity
    top = Path(proc.stdout.strip()).resolve()
    try:
        identity["commit"] = git(top, "rev-parse", "HEAD")
        identity["clean"] = git(top, "status", "--porcelain") == ""
        rel = script.relative_to(top).as_posix()
        identity["blob"] = git(top, "rev-parse", f"HEAD:{rel}")
        now = git(top, "hash-object", str(script))
        identity["byte_identical_to_head"] = identity["blob"] == now
    except (Refused, ValueError) as exc:
        identity["problem"] = str(exc)
    return identity


def require_reviewed_driver(identity: dict[str, Any]) -> None:
    """Evidence may only be decided by a driver that IS a reviewed commit's blob."""
    problems: list[str] = []
    if not identity.get("commit"):
        problems.append(identity.get("problem") or "no commit resolved")
    if not identity.get("clean"):
        problems.append("the driver's checkout is dirty")
    if not identity.get("byte_identical_to_head"):
        problems.append("the driver differs from the blob at its checkout's HEAD")
    if problems:
        raise Refused("the evidence orchestrator is not pinned to a reviewed commit: "
                      + "; ".join(problems))


def publish_transactionally(final: Path, body: Callable[[Path], int]) -> int:
    """Run ``body`` in a fresh sibling staging directory and publish it whole, or nothing.

    ``final`` must not exist. A Refused raised by ``body`` deletes the staging
    directory and propagates: no evidence-looking file survives. Any other
    outcome (accepted, or a valid negative result) is published by rename."""
    final = final.resolve()
    if final.exists():
        raise Refused(f"--out {final} exists; evidence is written once, into a fresh directory")
    final.parent.mkdir(parents=True, exist_ok=True)
    staging = final.parent / f".{final.name}.staging-{secrets.token_hex(4)}"
    staging.mkdir(parents=False, exist_ok=False)
    try:
        rc = body(staging)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    staging.rename(final)
    return rc


# --------------------------------------------------------------------------
# the fact-diff classifier
# --------------------------------------------------------------------------

def classify_fact_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Every difference between two facts documents, by allowed surface.

    Allowed: `functions[i].guarded_facts` (added or changed) and the top-level
    `guarded_functions` carrier. Everything else is unexpected, by path.
    """
    allowed: list[str] = []
    unexpected: list[str] = []
    bkeys, akeys = set(before), set(after)
    for k in sorted(akeys - bkeys):
        (allowed if k in ALLOWED_TOP_LEVEL_ADDED else unexpected).append(f"+{k}")
    for k in sorted(bkeys - akeys):
        unexpected.append(f"-{k}")
    for k in sorted(bkeys & akeys):
        if k == "functions":
            continue
        if k in ALLOWED_TOP_LEVEL_ADDED:
            if before[k] != after[k]:
                allowed.append(f"~{k}")
            continue
        if before[k] != after[k]:
            unexpected.append(f"~{k}")
    bf: list[Any] = list(before["functions"]) if isinstance(before.get("functions"), list) else []
    af: list[Any] = list(after["functions"]) if isinstance(after.get("functions"), list) else []
    gained = 0
    if len(bf) != len(af):
        unexpected.append(f"~functions[] count {len(bf)} -> {len(af)}")
    else:
        for i, (x, y) in enumerate(zip(bf, af, strict=True)):
            xs, ys = dict(x), dict(y)
            gx, gy = xs.pop("guarded_facts", None), ys.pop("guarded_facts", None)
            ident = f"functions[{i}]:{ys.get('name')}"
            if xs != ys:
                unexpected.append(f"~{ident} outside guarded_facts")
            if gx != gy:
                allowed.append(f"~{ident}.guarded_facts")
                if gx is None and gy is not None:
                    gained += 1
    orphans = after.get("guarded_functions")
    status = "unchanged"
    if unexpected:
        status = "moved_unexpected"
    elif allowed:
        status = "moved_allowed"
    return {
        "status": status,
        "allowed": allowed,
        "unexpected": unexpected,
        "functions_gaining_guarded_facts": gained,
        "guarded_functions": len(orphans) if isinstance(orphans, list) else 0,
    }


# --------------------------------------------------------------------------
# provenance preflight
# --------------------------------------------------------------------------

def parse_manifest_digests(text: str) -> dict[str, str]:
    """`| <file> | `<sha256>` |` rows of a baseline manifest."""
    out: dict[str, str] = {}
    for m in re.finditer(r"^\|\s*([\w.\-]+\.json)\s*\|\s*`([0-9a-f]{64})`\s*\|", text, re.M):
        out[m.group(1)] = m.group(2)
    return out


def baseline_file(cfg: Config, key: str) -> Path:
    return cfg.baseline_dir / f"{cfg.baseline_prefix}{key}.json"


def preflight(cfg: Config) -> dict[str, Any]:
    ev = cfg.tools["ev"]
    repo = cfg.repo
    problems: list[str] = []
    for name, sha in (("treatment", cfg.treatment), ("population", cfg.population),
                      ("baseline-commit", cfg.baseline_commit)):
        if not SHA40.match(sha):
            problems.append(f"--{name} must be a full 40-hex commit, got {sha!r}")
    if problems:
        raise Refused("; ".join(problems))
    head = git(repo, "rev-parse", "HEAD")
    if head != cfg.treatment:
        raise Refused(f"the measured checkout is at {head[:12]}, not the treatment "
                      f"{cfg.treatment[:12]}: the measurement head must be exactly the treatment")
    if ev.tree_is_dirty(repo=repo):
        raise Refused("the measured checkout is dirty; evidence starts clean")
    for older, newer, what in ((cfg.population, cfg.baseline_commit, "T is not an ancestor of R"),
                               (cfg.baseline_commit, cfg.treatment,
                                "R is not an ancestor of the treatment")):
        if not git_ok(repo, "merge-base", "--is-ancestor", older, newer):
            raise Refused(f"{what}: the evidence describes a history this tree does not contain")
    instrument = list(ev.INSTRUMENT_PATHS)
    treatment_paths = list(ev.TREATMENT_PATHS)
    ids = {c: object_ids(repo, sha, instrument)
           for c, sha in (("population", cfg.population), ("baseline", cfg.baseline_commit),
                          ("treatment", cfg.treatment))}
    if not (ids["population"] == ids["baseline"] == ids["treatment"]):
        moved = [p for p in instrument
                 if not (ids["population"][p] == ids["baseline"][p] == ids["treatment"][p])]
        raise Refused(f"the measurement instrument moved between T, R and the treatment: {moved}")
    treated = {c: object_ids(repo, sha, treatment_paths)
               for c, sha in (("population", cfg.population), ("treatment", cfg.treatment))}
    out_problems: list[str] = []
    try:
        cfg.out.mkdir(parents=True, exist_ok=True)
        out_problems = list(ev.scratch_problems(cfg.out / "probe.json", repo=repo))
    except Exception as exc:  # the reason is reported verbatim
        out_problems = [str(exc)]
    if out_problems:
        raise Refused("; ".join(out_problems))
    # The baseline records: the four files, pinned to R.
    baseline: dict[str, Any] = {"dir": str(cfg.baseline_dir), "files": {}}
    manifest_digests: dict[str, str] = {}
    if cfg.manifest is not None:
        if not cfg.manifest.exists():
            raise Refused(f"baseline manifest {cfg.manifest} is missing")
        manifest_digests = parse_manifest_digests(cfg.manifest.read_text(encoding="utf-8"))
        if len(manifest_digests) < 4:
            raise Refused(f"baseline manifest names {len(manifest_digests)} artifact digest(s), "
                          "expected the four takes")
        baseline["manifest"] = {"path": str(cfg.manifest), "sha256": sha256_file(cfg.manifest)}
    for key, _, _ in TAKES:
        path = baseline_file(cfg, key)
        if not path.exists():
            raise Refused(f"baseline record {path} is missing")
        digest = sha256_file(path)
        rec = load_json(path)
        entry: dict[str, Any] = {"path": str(path), "sha256": digest,
                                 "source_commit": rec.get("source_commit"),
                                 "population_commit": rec.get("population_commit"),
                                 "is_evidence": rec.get("is_evidence")}
        if rec.get("source_commit") != cfg.population:
            problems.append(f"{path.name}: source_commit is not T")
        if rec.get("population_commit") != cfg.population:
            problems.append(f"{path.name}: population_commit is not T")
        if rec.get("is_evidence") is not True:
            problems.append(f"{path.name}: not marked is_evidence")
        if manifest_digests:
            pinned = manifest_digests.get(path.name)
            entry["manifest_pin"] = pinned
            if pinned != digest:
                problems.append(f"{path.name}: sha256 {digest[:12]} is not the manifest's "
                                f"{(pinned or 'absent')[:12]}")
        if cfg.mode == "evidence":
            rel = path.resolve().relative_to(repo.resolve()).as_posix() \
                if path.resolve().is_relative_to(repo.resolve()) else None
            committed = git(repo, "rev-parse", f"{cfg.baseline_commit}:{rel}") if rel else ""
            here = git(repo, "hash-object", str(path))
            entry["blob_at_R"] = committed
            if not rel or committed != here:
                problems.append(f"{path.name}: not the file committed at R "
                                f"{cfg.baseline_commit[:12]}")
        baseline["files"][key] = entry
    if problems:
        raise Refused("; ".join(problems))
    return {
        "measurement_head": head,
        "instrument": {"paths": instrument, "object_ids": ids["treatment"],
                       "identical_at": ["population", "baseline", "treatment"]},
        "treatment_identity": {"paths": treatment_paths, "object_ids_at_T": treated["population"],
                               "object_ids_at_treatment": treated["treatment"]},
        "baseline": baseline,
        "driver": dict(cfg.driver),
    }


# --------------------------------------------------------------------------
# the four governed takes, verified and compared by the instrument's own tools
# --------------------------------------------------------------------------

def run_tool(cfg: Config, script: str, args: list[str], log: Path) -> tuple[int, str]:
    cmd = [sys.executable, str(cfg.repo / "scripts" / script), *args]
    proc = subprocess.run(cmd, cwd=cfg.repo, capture_output=True, text=True, check=False)
    text = proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else "")
    log.write_text(text, encoding="utf-8")
    return proc.returncode, text


def result_line(text: str) -> str:
    lines = [ln for ln in text.splitlines() if ln.startswith("RESULT:")]
    return lines[-1] if lines else ""


def counts_of(line: str) -> dict[str, int]:
    return {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", line)}


def after_file(cfg: Config, key: str) -> Path:
    return cfg.out / f"p037-a2.2-s-after-{key}.json"


def run_takes(cfg: Config) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, script, args in TAKES:
        target = after_file(cfg, key)
        rc, text = run_tool(cfg, script, ["take", *args, "--population-commit", cfg.population,
                                         "--out", str(target)], cfg.out / f"take-{key}.log")
        print(f"  take {key}: rc={rc}", flush=True)
        if rc != 0 or not target.exists():
            raise Refused(f"take {key} failed (rc {rc}): {text.strip()[-400:]}")
        rc, text = run_tool(cfg, script, ["verify", str(target), "--against", cfg.treatment],
                            cfg.out / f"verify-{key}.log")
        if rc != 0:
            raise Refused(f"take {key} is not fresh evidence at the treatment: "
                          f"{text.strip()[-400:]}")
        rec = load_json(target)
        if rec.get("source_commit") != cfg.treatment:
            raise Refused(f"take {key} names source {str(rec.get('source_commit'))[:12]}, "
                          "not the treatment")
        compares: dict[str, Any] = {}
        levels = [("verdict", [])] if script == "p037_mos_snapshot.py" \
            else [("verdict", ["--level", "verdict"]), ("all", ["--level", "all"])]
        for level, extra in levels:
            rc, text = run_tool(cfg, script, ["compare", "--before", str(baseline_file(cfg, key)),
                                              "--after", str(target), "--against", cfg.treatment,
                                              *extra], cfg.out / f"compare-{key}-{level}.log")
            line = result_line(text)
            if rc == 2 or not line:
                raise Refused(f"compare {key} ({level}) refused: {text.strip()[-500:]}")
            compares[level] = {"rc": rc, "result": line, "counts": counts_of(line),
                               "unchanged": rc == 0}
            print(f"  compare {key} [{level}]: {line[:110]}", flush=True)
        artifacts = {name: a.get("sha256") for name, a in (rec.get("artifacts") or {}).items()}
        out[key] = {"path": target.name, "sha256": sha256_file(target),
                    "source_commit": rec.get("source_commit"),
                    "population_commit": rec.get("population_commit"),
                    "is_evidence": rec.get("is_evidence"), "artifacts": artifacts,
                    "execution_profile": rec.get("execution_profile"),
                    "compare": compares}
    return out


def cross_engine_verdicts(cfg: Config, python_take: Path, rust_take: Path) -> dict[str, Any]:
    vs = cfg.tools["verdict"]
    a, b = load_json(python_take), load_json(rust_take)
    files = sorted(set(a.get("files", {})) | set(b.get("files", {})))
    dis: dict[str, list[str]] = {"verdict": [], "all": [], "exit": []}
    for rel in files:
        ra, rb = a.get("files", {}).get(rel), b.get("files", {}).get(rel)
        if ra is None or rb is None:
            for k in dis:
                dis[k].append(rel)
            continue
        for level in ("verdict", "all"):
            if vs.key_set(ra, level) != vs.key_set(rb, level):
                dis[level].append(rel)
        if ra.get("exit") != rb.get("exit"):
            dis["exit"].append(rel)
    return {"files": len(files), "disagreements": {k: len(v) for k, v in dis.items()},
            "disagreeing_files": dis}


# --------------------------------------------------------------------------
# the anchored layer differential
# --------------------------------------------------------------------------

def extract_with(cfg: Config, project: Path, inputs: list[Path], document: str) -> bytes:
    """One extractor execution, spelled exactly as the launcher spells it."""
    ev = cfg.tools["ev"]
    with tempfile.TemporaryDirectory(prefix="p037-s-") as td:
        facts = Path(td) / "facts.json"
        cmd = ["dotnet", "run", "--project", str(project), "--",
               *(str(p) for p in inputs), "-o", str(facts), "--flow-locals"]
        proc = subprocess.run(cmd, cwd=cfg.repo, capture_output=True, text=True, check=False,
                              env=ev.sanitized_env())
        contamination = ev.reference_contamination(proc.stderr)
        if contamination:
            raise Refused(f"{document}: the extractor loaded extra references: {contamination}")
        if proc.returncode != 0 or not facts.exists():
            raise Refused(f"{document}: extractor failed ({proc.returncode}): "
                          f"{proc.stderr.strip()[-400:]}")
        return facts.read_bytes()


def layer_digests(entry: dict[str, Any]) -> dict[str, str]:
    layers = entry.get("layers")
    if not isinstance(layers, list):
        raise Refused("a capture carries no layers array")
    out: dict[str, str] = {}
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        name = str(layer.get("layer"))
        if layer.get("status") == "produced":
            out[name] = canonical_digest(layer.get("document"))
        else:
            out[name] = f"{layer.get('status')}:{canonical_digest(layer.get('error'))}"
    missing = [x for x in LAYERS if x not in out]
    if missing:
        raise Refused(f"a capture lacks the layer(s) {missing}")
    return {k: out[k] for k in LAYERS}


def capture_layers(cfg: Config, raw: bytes, adapter: dict[str, Any]) -> dict[str, dict[str, str]]:
    shadow, repro = cfg.tools["shadow"], cfg.tools["repro"]
    identity = repro.hash_bytes(raw)
    reference = shadow.run_reference(raw)
    py = reference.get("entry")
    if not isinstance(py, dict):
        raise Refused(f"Python capture refused the facts: {reference.get('canonical_error')}")
    envelope = shadow.run_port(raw, adapter, cfg.timeout).get("envelope")
    if not isinstance(envelope, dict) or not isinstance(envelope.get("engine"), dict):
        raise Refused("the Rust adapter returned no engine capture")
    rs = envelope["engine"]
    for name, entry in (("python", py), ("rust", rs)):
        if entry.get("consumed") != identity:
            raise Refused(f"the {name} capture does not attest the exact facts bytes")
    return {"python": layer_digests(py), "rust": layer_digests(rs)}


def instrument_worktree(cfg: Config) -> Path:
    path = cfg.out / "instrument-T"
    if path.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=cfg.repo,
                       capture_output=True, check=False)
        shutil.rmtree(path, ignore_errors=True)
    git(cfg.repo, "worktree", "add", "--detach", str(path), cfg.population)
    return path


def remove_worktree(cfg: Config, path: Path) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(path)], cwd=cfg.repo,
                   capture_output=True, check=False)
    subprocess.run(["git", "worktree", "prune"], cwd=cfg.repo, capture_output=True, check=False)


def layer_differential(cfg: Config, takes: dict[str, Any]) -> dict[str, Any]:
    ev, mos, shadow, repro = (cfg.tools["ev"], cfg.tools["mos"], cfg.tools["shadow"],
                              cfg.tools["repro"])
    t_root = instrument_worktree(cfg)
    take_dir = Path(tempfile.mkdtemp(prefix="p037-s-take-"))
    try:
        artifact = ev.build_rust_artifact("own-shadow", "own-shadow-engine", repo=cfg.repo)
        problems = list(ev.artifact_problems(artifact))
        if problems:
            raise Refused("; ".join(problems))
        expected_engine = {takes[k]["artifacts"].get("own-shadow-engine")
                           for k in ("mos-repo", "mos-corpus")}
        if expected_engine != {artifact["sha256"]}:
            raise Refused("the own-shadow-engine built for the differential is not the one the "
                          f"MOS takes ran ({artifact['sha256'][:12]} vs {expected_engine})")
        ev.seal_artifact(artifact, take_dir)
        adapter = shadow.engine_identity(str(artifact["executed"]["sealed_path"]))
        t_project = t_root / "frontend" / "roslyn" / "OwnSharp.Extractor"
        b_project = cfg.repo / "frontend" / "roslyn" / "OwnSharp.Extractor"
        documents: dict[str, Any] = {}
        anchors_failed: list[str] = []
        for source, key in (("corpus", "mos-corpus"), ("repo", "mos-repo")):
            baseline_rec = load_json(baseline_file(cfg, key))
            after_rec = load_json(after_file(cfg, key))
            provenance = ev.population_fields(cfg.population, mos.SOURCES[source], repo=cfg.repo)
            if provenance["analysis_manifest"] != after_rec.get("analysis_manifest"):
                raise Refused(f"{source}: the population re-derived here is not the take's")
            root = ev.materialize_population(provenance, repo=cfg.repo)
            files = ev.analysis_paths(provenance, root)
            docs = mos.source_documents(source, files, root)
            for i, (doc_id, paths) in enumerate(docs, 1):
                raw_t = extract_with(cfg, t_project, paths, f"{doc_id}@T")
                raw_b = extract_with(cfg, b_project, paths, f"{doc_id}@treatment")
                dt, db = repro.hash_bytes(raw_t), repro.hash_bytes(raw_b)
                want_t = (baseline_rec.get("documents", {}).get(doc_id) or {}).get("facts")
                want_b = (after_rec.get("documents", {}).get(doc_id) or {}).get("facts")
                anchored = {"baseline": dt == want_t, "treatment": db == want_b}
                record: dict[str, Any] = {
                    "source": source, "inputs": len(paths),
                    "facts": {"baseline": dt, "treatment": db, "anchored": anchored},
                }
                if not all(anchored.values()):
                    anchors_failed.append(doc_id)
                    documents[doc_id] = record
                    print(f"  [{i:3}/{len(docs)}] {doc_id}: NOT ANCHORED {anchored}", flush=True)
                    continue
                diff = classify_fact_diff(json.loads(raw_t), json.loads(raw_b))
                record["fact_diff"] = diff
                record["layers"] = {"baseline": capture_layers(cfg, raw_t, adapter),
                                    "treatment": capture_layers(cfg, raw_b, adapter)}
                documents[doc_id] = record
                print(f"  [{i:3}/{len(docs)}] {doc_id}: facts {diff['status']}", flush=True)
            tampered = ev.population_intact(provenance, root, repo=cfg.repo)
            if tampered:
                raise Refused(f"{source}: {'; '.join(tampered)}")
        post = list(ev.executed_artifact_problems(artifact))
        if post:
            raise Refused("; ".join(post))
    finally:
        remove_worktree(cfg, t_root)
        shutil.rmtree(take_dir, ignore_errors=True)
    result = {"adapter": {"sha256": artifact["sha256"], "bytes": artifact["bytes"]},
              "documents": documents, "anchors_failed": anchors_failed}
    (cfg.out / "layers.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n",
                                         encoding="utf-8")
    return result


def profiles_consistent(takes: dict[str, Any]) -> bool:
    """One execution environment across the four takes, on the identities each records.

    A Python-only verdict take records no Rust identity by design (the instrument's
    own rule), so the profiles are compared on their common keys; every identity a
    take does carry must equal the others'."""
    profiles = [t.get("execution_profile") or {} for t in takes.values()]
    if not profiles or any(not p for p in profiles):
        return False
    common = set.intersection(*(set(p) for p in profiles))
    if not {"python", "dotnet", "platform"} <= common:
        return False
    keys = set.union(*(set(p) for p in profiles))
    for key in keys:
        values = {json.dumps(p[key], sort_keys=True) for p in profiles if key in p}
        if len(values) != 1:
            return False
    return True


def summarize_layers(documents: dict[str, Any]) -> dict[str, Any]:
    mismatches: dict[str, dict[str, list[str]]] = {e: {ly: [] for ly in LAYERS} for e in ENGINES}
    disagreements: dict[str, dict[str, list[str]]] = {
        side: {ly: [] for ly in LAYERS} for side in ("baseline", "treatment")}
    facts: dict[str, list[str]] = {"unchanged": [], "moved_allowed": [], "moved_unexpected": []}
    for doc_id, rec in sorted(documents.items()):
        diff = rec.get("fact_diff")
        if diff:
            facts[str(diff["status"])].append(doc_id)
        layers = rec.get("layers")
        if not layers:
            continue
        for e in ENGINES:
            for ly in LAYERS:
                if layers["baseline"][e][ly] != layers["treatment"][e][ly]:
                    mismatches[e][ly].append(doc_id)
        for side in ("baseline", "treatment"):
            for ly in LAYERS:
                if layers[side]["python"][ly] != layers[side]["rust"][ly]:
                    disagreements[side][ly].append(doc_id)
    return {
        "facts": {k: {"count": len(v), "documents": v} for k, v in facts.items()},
        "mismatches": {e: {ly: {"count": len(v), "documents": v} for ly, v in m.items()}
                       for e, m in mismatches.items()},
        "disagreements": {s: {ly: {"count": len(v), "documents": v} for ly, v in d.items()}
                          for s, d in disagreements.items()},
    }


# --------------------------------------------------------------------------
# the artifact
# --------------------------------------------------------------------------

def assemble(cfg: Config, prov: dict[str, Any], takes: dict[str, Any], cross: dict[str, Any],
             layers: dict[str, Any], post_clean: bool) -> dict[str, Any]:
    summary = summarize_layers(layers["documents"])
    compares_unchanged = all(c["unchanged"] for t in takes.values()
                             for c in t["compare"].values())
    mos_unchanged = all(takes[k]["compare"]["verdict"]["unchanged"]
                        for k in ("mos-repo", "mos-corpus"))
    verdicts_unchanged = all(takes[k]["compare"][lv]["unchanged"]
                             for k in ("verdict-python", "verdict-rust")
                             for lv in ("verdict", "all"))
    layer_ok = all(summary["mismatches"][e][ly]["count"] == 0 for e in ENGINES for ly in LAYERS)
    agree = all(summary["disagreements"][s][ly]["count"] == 0
                for s in ("baseline", "treatment") for ly in LAYERS)
    cross_ok = all(n == 0 for n in cross["disagreements"].values())
    facts_moved = summary["facts"]["moved_allowed"]["count"]
    unexpected = summary["facts"]["moved_unexpected"]["count"]
    takes_evidence = all(t["is_evidence"] is True for t in takes.values())
    conditions = {
        "head_is_treatment": prov["measurement_head"] == cfg.treatment,
        "instrument_identical_at_T_R_treatment": True,
        "four_takes_fresh_and_evidence": takes_evidence,
        "four_compares_eligible_and_unchanged": compares_unchanged,
        "mos_unchanged_both_engines": mos_unchanged,
        "verdicts_unchanged_both_engines": verdicts_unchanged,
        "verdict_engines_agree": cross_ok,
        "every_document_anchored": not layers["anchors_failed"],
        "facts_moved": facts_moved > 0,
        "unexpected_fact_changes_zero": unexpected == 0,
        "lowered_summaries_verdicts_unchanged_both_engines": layer_ok,
        "layer_engines_agree": agree,
        "execution_profile_single": profiles_consistent(takes),
        "tree_clean_after": post_clean,
    }
    accepted = all(conditions.values())
    n_docs = len(layers["documents"])
    return {
        "schema": SCHEMA,
        "mode": cfg.mode,
        "is_evidence": cfg.mode == "evidence" and accepted,
        "population_sha": cfg.population,
        "baseline_evidence_sha": cfg.baseline_commit,
        "treatment_sha": cfg.treatment,
        "measurement_head": prov["measurement_head"],
        "instrument_identity": prov["instrument"],
        "treatment_identity": prov["treatment_identity"],
        "cumulative_driver": prov["driver"],
        "baseline_records": prov["baseline"],
        "takes": takes,
        "verdict_cross_engine": cross,
        "layer_differential": {"adapter": layers["adapter"], "documents_measured": n_docs,
                               "anchors_failed": layers["anchors_failed"], **summary,
                               "documents": layers["documents"]},
        "fact_documents": {"changed": facts_moved,
                           "unchanged": summary["facts"]["unchanged"]["count"],
                           "unexpected": unexpected,
                           "classified_changed": summary["facts"]["moved_allowed"]["documents"]},
        "matrix": {
            "python": {ly: summary["mismatches"]["python"][ly]["count"] for ly in LAYERS},
            "rust": {ly: summary["mismatches"]["rust"][ly]["count"] for ly in LAYERS},
            "python_rust_disagreements": {
                ly: summary["disagreements"]["treatment"][ly]["count"] for ly in LAYERS},
            "verdict_snapshot_disagreements": cross["disagreements"],
        },
        "result": {"facts": "MOVED" if facts_moved else "UNCHANGED",
                   "mos": "UNCHANGED" if mos_unchanged and layer_ok else "MOVED",
                   "verdicts": "UNCHANGED" if verdicts_unchanged and cross_ok else "MOVED",
                   "conditions": conditions, "accepted": accepted},
    }


def manifest_md(cfg: Config, art: dict[str, Any], art_sha: str) -> str:
    rows = "\n".join(
        f"| {t['path']} | `{t['sha256']}` | "
        + "; ".join(f"{lv}: {c['result'][len('RESULT: '):]}" for lv, c in t["compare"].items())
        + " |"
        for t in art["takes"].values())
    m = art["matrix"]
    r = art["result"]
    fd = art["fact_documents"]
    py, rs, dg = m["python"], m["rust"], m["python_rust_disagreements"]
    drv = art["cumulative_driver"]
    return f"""# P-037 A2.2-S cumulative evidence ({art['mode']})

T = `{art['population_sha']}` (population)
R = `{art['baseline_evidence_sha']}` (baseline evidence)
treatment = `{art['treatment_sha']}` (measurement head `{art['measurement_head']}`)

Result: FACTS {r['facts']} · MOS {r['mos']} · VERDICTS {r['verdicts']} · accepted={r['accepted']}
· is_evidence={art['is_evidence']}

## Four governed takes at the treatment, population held at T

| artifact | sha256 | compare against R |
|---|---|---|
{rows}

## Fact documents

changed={fd['changed']} unchanged={fd['unchanged']} unexpected={fd['unexpected']}
(every changed document classified: guarded_facts / guarded_functions only)

## Layer differential (per-document digests, both engines)

| engine | lowered | summaries | verdicts |
|---|---|---|---|
| python mismatches | {py['lowered']} | {py['summaries']} | {py['verdicts']} |
| rust mismatches | {rs['lowered']} | {rs['summaries']} | {rs['verdicts']} |
| python/rust disagreements (treatment) | {dg['lowered']} | {dg['summaries']} | {dg['verdicts']} |

Verdict-snapshot cross-engine disagreements: {json.dumps(m['verdict_snapshot_disagreements'])}

Cumulative artifact: p037-a2.2-s-cumulative.json sha256 `{art_sha}`
Evidence orchestrator: commit `{drv.get('commit')}`, blob `{drv.get('blob')}`,
sha256 `{drv.get('sha256')}`
Instrument identity: {json.dumps(art['instrument_identity']['object_ids'], sort_keys=True)}
"""


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def run(cfg: Config) -> int:
    """The measurement in cfg.out; raises Refused, returns 0 (accepted) or 1 (a valid no)."""
    ev = cfg.tools["ev"]
    prov = preflight(cfg)
    print(f"preflight ok: head {prov['measurement_head'][:12]} == treatment; instrument "
          "identical at T, R and the treatment; baseline records pinned", flush=True)
    takes_path = cfg.out / "takes.json"
    if cfg.stage in ("takes", "all"):
        takes = run_takes(cfg)
        takes_path.write_text(json.dumps(takes, indent=1, sort_keys=True) + "\n",
                              encoding="utf-8")
    else:
        if not takes_path.exists():
            raise Refused("stage layers needs the takes of an earlier `--stage takes` run")
        takes = load_json(takes_path)
    if cfg.stage == "takes":
        print("takes done; run --stage layers for the differential", flush=True)
        return 0
    cross = cross_engine_verdicts(cfg, after_file(cfg, "verdict-python"),
                                  after_file(cfg, "verdict-rust"))
    layers_path = cfg.out / "layers.json"
    if cfg.stage == "report":
        # Re-render the artifact from the persisted measurement; nothing is re-measured.
        if not layers_path.exists():
            raise Refused("stage report needs the layers.json of an earlier run")
        layers = load_json(layers_path)
    else:
        layers = layer_differential(cfg, takes)
    post_clean = not ev.tree_is_dirty(repo=cfg.repo)
    art = assemble(cfg, prov, takes, cross, layers, post_clean)
    target = cfg.out / "p037-a2.2-s-cumulative.json"
    target.write_text(json.dumps(art, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    art_sha = sha256_file(target)
    (cfg.out / "p037-a2.2-s-manifest.md").write_text(manifest_md(cfg, art, art_sha),
                                                     encoding="utf-8")
    r = art["result"]
    failed = [k for k, v in r["conditions"].items() if not v]
    print(f"RESULT: FACTS {r['facts']} · MOS {r['mos']} · VERDICTS {r['verdicts']} · "
          f"accepted={r['accepted']} · is_evidence={art['is_evidence']} · "
          f"documents={art['layer_differential']['documents_measured']} · "
          f"changed={art['fact_documents']['changed']} "
          f"unexpected={art['fact_documents']['unexpected']}"
          + (f" · failed conditions: {failed}" if failed else ""))
    print(f"wrote {target.name} ({art_sha[:12]})")
    return 0 if r["accepted"] else 1


def selftest() -> int:
    failures: list[str] = []

    def check(name: str, ok: bool) -> None:
        print(f"{'ok' if ok else 'FAIL'}[{name}]")
        if not ok:
            failures.append(name)

    base = {"module": "Extracted", "ownir_version": 0, "stats": {"a": 1}, "services": [],
            "components": [],
            "functions": [{"file": "f.cs", "name": "M", "sig": "", "body": [{"op": "x"}]},
                          {"file": "f.cs", "name": "N", "sig": "", "body": []}]}
    twin = json.loads(json.dumps(base))
    check("unchanged-is-unchanged", classify_fact_diff(base, twin)["status"] == "unchanged")
    guarded = json.loads(json.dumps(base))
    guarded["functions"][0]["guarded_facts"] = {"version": 1, "calls": [], "guards": []}
    guarded["guarded_functions"] = [{"name": "O", "file": "f.cs", "sig": "", "guarded_facts": {}}]
    d = classify_fact_diff(base, guarded)
    check("guarded-only-is-allowed", d["status"] == "moved_allowed" and not d["unexpected"]
          and d["functions_gaining_guarded_facts"] == 1 and d["guarded_functions"] == 1)
    body = json.loads(json.dumps(guarded))
    body["functions"][1]["body"] = [{"op": "release"}]
    d = classify_fact_diff(base, body)
    check("legacy-body-change-is-unexpected", d["status"] == "moved_unexpected"
          and any("functions[1]:N outside guarded_facts" in u for u in d["unexpected"]))
    added = json.loads(json.dumps(guarded))
    added["functions"].append({"file": "f.cs", "name": "P", "sig": "", "body": []})
    check("added-function-is-unexpected",
          classify_fact_diff(base, added)["status"] == "moved_unexpected")
    stats = json.loads(json.dumps(guarded))
    stats["stats"] = {"a": 2}
    d = classify_fact_diff(base, stats)
    check("stats-change-is-unexpected", "~stats" in d["unexpected"])
    services = json.loads(json.dumps(guarded))
    services["services"] = [{"x": 1}]
    check("services-change-is-unexpected",
          "~services" in classify_fact_diff(base, services)["unexpected"])
    other = json.loads(json.dumps(guarded))
    other["mentions"] = []
    check("other-new-top-level-key-is-unexpected",
          "+mentions" in classify_fact_diff(base, other)["unexpected"])
    version = json.loads(json.dumps(guarded))
    version["ownir_version"] = 1
    check("schema-version-change-is-unexpected",
          "~ownir_version" in classify_fact_diff(base, version)["unexpected"])
    manifest = ("| artifact | sha256 |\n|---|---|\n| p037-a2-baseline-mos-repo.json | `"
                + "a" * 64 + "` |\n| other.json | `" + "b" * 64 + "` |\n")
    parsed = parse_manifest_digests(manifest)
    check("manifest-digests-parsed", parsed == {"p037-a2-baseline-mos-repo.json": "a" * 64,
                                                 "other.json": "b" * 64})
    line = "RESULT: UNCHANGED — x, facts_moved=36, python_mos_moved=0"
    check("result-line-counts", counts_of(line) == {"facts_moved": 36, "python_mos_moved": 0})
    capture = {"layers": [{"layer": "lowered", "status": "produced", "document": {"a": 1}},
                          {"layer": "summaries", "status": "produced", "document": {"b": [1]}},
                          {"layer": "verdicts", "status": "refused", "error": "nope"}]}
    dig = layer_digests(capture)
    check("layer-digests-cover-three-layers", set(dig) == set(LAYERS)
          and dig["verdicts"].startswith("refused:"))
    moved = json.loads(json.dumps(capture))
    moved["layers"][1]["document"]["b"] = [2]
    check("layer-digest-moves-with-document", layer_digests(moved)["summaries"] != dig["summaries"]
          and layer_digests(moved)["lowered"] == dig["lowered"])
    full = {"python": {"version": "3.11"}, "dotnet": {"sdk": "8"}, "platform": {"system": "L"},
            "rust": {"rustc": "1.94"}}
    py_only = {k: v for k, v in full.items() if k != "rust"}
    takes_ok = {"a": {"execution_profile": full}, "b": {"execution_profile": py_only},
                "c": {"execution_profile": full}}
    check("profiles-consistent-with-python-only-take", profiles_consistent(takes_ok))
    other_python = json.loads(json.dumps(takes_ok))
    other_python["b"]["execution_profile"]["python"] = {"version": "3.13"}
    check("profiles-differing-interpreter-refused", not profiles_consistent(other_python))
    other_rust = json.loads(json.dumps(takes_ok))
    other_rust["c"]["execution_profile"]["rust"] = {"rustc": "1.90"}
    check("profiles-differing-rust-refused", not profiles_consistent(other_rust))
    check("profiles-missing-refused", not profiles_consistent({"a": {"execution_profile": {}}}))
    # H1: evidence is one command.
    try:
        validate_stage("evidence", "layers")
        check("evidence-with-stage-refused", False)
    except Refused:
        check("evidence-with-stage-refused", True)
    for stage in ("takes", "layers", "report", "all"):
        validate_stage("rehearsal", stage)
    validate_stage("evidence", "all")
    check("rehearsal-stages-allowed", True)
    # H2: transactional output.
    with tempfile.TemporaryDirectory(prefix="p037-s-selftest-") as td:
        final = Path(td) / "out"
        final.mkdir()
        try:
            publish_transactionally(final, lambda out: 0)
            check("pre-existing-out-refused", False)
        except Refused:
            check("pre-existing-out-refused", True)
        final2 = Path(td) / "out2"

        def late_refused(out: Path) -> int:
            (out / "p037-a2.2-s-after-mos-repo.json").write_text('{"is_evidence": true}')
            raise Refused("simulated late refusal after a take was written")
        try:
            publish_transactionally(final2, late_refused)
            check("late-refused-propagates", False)
        except Refused:
            check("late-refused-propagates", True)
        leftovers = sorted(x.name for x in Path(td).iterdir())
        check("late-refused-leaves-no-final-out-and-no-staging",
              not final2.exists() and leftovers == ["out"])
        final3 = Path(td) / "out3"

        def valid_negative(out: Path) -> int:
            (out / "p037-a2.2-s-cumulative.json").write_text('{"result": {"accepted": false}}')
            return 1
        rc = publish_transactionally(final3, valid_negative)
        check("valid-negative-result-published-with-exit-1",
              rc == 1 and (final3 / "p037-a2.2-s-cumulative.json").exists()
              and not any(x.name.startswith(".out3.staging") for x in Path(td).iterdir()))
    # H3: the driver pinned to a clean reviewed commit and blob.
    with tempfile.TemporaryDirectory(prefix="p037-s-driver-") as td:
        repo = Path(td)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "s@x"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "s"], check=True)
        script = repo / "scripts" / "p037_cumulative_evidence.py"
        script.parent.mkdir()
        script.write_text("print('driver')\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "driver"], check=True)
        ident = driver_identity(script)
        require_reviewed_driver(ident)
        check("clean-driver-checkout-accepted", bool(ident["commit"]) and ident["clean"]
              and ident["byte_identical_to_head"] and ident["blob"])
        script.write_text("print('driver, modified')\n")
        try:
            require_reviewed_driver(driver_identity(script))
            check("modified-driver-refused", False)
        except Refused:
            check("modified-driver-refused", True)
        script.write_text("print('driver')\n")
        (repo / "stray.txt").write_text("x")
        try:
            require_reviewed_driver(driver_identity(script))
            check("dirty-driver-checkout-refused", False)
        except Refused:
            check("dirty-driver-checkout-refused", True)
        loose = Path(tempfile.mkdtemp(prefix="p037-s-loose-")) / "p037_cumulative_evidence.py"
        loose.write_text("print('loose copy')\n")
        try:
            require_reviewed_driver(driver_identity(loose))
            check("loose-driver-copy-refused", False)
        except Refused:
            check("loose-driver-copy-refused", True)
        shutil.rmtree(loose.parent, ignore_errors=True)
    # H4: every measurement module proven to come from the measured checkout.
    class Mod:
        def __init__(self, file: str) -> None:
            self.__file__ = file
    with tempfile.TemporaryDirectory(prefix="p037-s-mods-") as td:
        repo = Path(td)
        good = {name: Mod(str(repo / rel)) for name, rel in MEASUREMENT_MODULES.items()}
        verify_module_paths(good, repo)
        check("measured-checkout-modules-accepted", True)
        bad = dict(good)
        bad["ownlang.repro"] = Mod("/somewhere/else/ownlang/repro.py")
        try:
            verify_module_paths(bad, repo)
            check("foreign-module-path-refused", False)
        except Refused:
            check("foreign-module-path-refused", True)
        missing = dict(good)
        del missing["shadow_compare"]
        try:
            verify_module_paths(missing, repo)
            check("missing-module-refused", False)
        except Refused:
            check("missing-module-refused", True)
    if failures:
        print(f"RESULT: {len(failures)} cumulative-evidence selftest(s) failed")
        return 1
    print("RESULT: cumulative-evidence classifier and readers hold their controls")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    r.add_argument("--treatment", required=True)
    r.add_argument("--population", required=True)
    r.add_argument("--baseline-commit", required=True)
    r.add_argument("--baseline-dir", type=Path, default=None,
                   help="default: <repo>/docs/evidence")
    r.add_argument("--baseline-prefix", default="p037-a2-baseline-")
    r.add_argument("--baseline-manifest", type=Path, default=None,
                   help="default in evidence mode: <baseline-dir>/p037-a2-baseline-manifest.md")
    r.add_argument("--out", type=Path, required=True,
                   help="evidence: a directory that does not exist yet, outside the checkout; "
                        "rehearsal: a directory outside the checkout")
    r.add_argument("--mode", choices=("evidence", "rehearsal"), default="evidence")
    r.add_argument("--stage", choices=("takes", "layers", "report", "all"), default="all",
                   help="rehearsal only. takes: the four takes; layers: the differential over "
                        "saved takes; report: re-render the artifact from the saved measurement")
    r.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.cmd != "run":
        ap.error("one command is required (or --selftest)")
    repo = Path(args.repo).resolve()
    baseline_dir = Path(args.baseline_dir).resolve() if args.baseline_dir \
        else repo / "docs" / "evidence"
    manifest: Path | None = Path(args.baseline_manifest).resolve() if args.baseline_manifest \
        else (baseline_dir / "p037-a2-baseline-manifest.md" if args.mode == "evidence" else None)
    cfg = Config(repo=repo, treatment=args.treatment, population=args.population,
                 baseline_commit=args.baseline_commit, baseline_dir=baseline_dir,
                 baseline_prefix=args.baseline_prefix, out=Path(args.out).resolve(),
                 mode=args.mode, stage=args.stage, timeout=args.timeout, manifest=manifest)
    try:
        validate_stage(cfg.mode, cfg.stage)
        cfg.driver = driver_identity(Path(__file__))
        if cfg.mode == "evidence":
            require_reviewed_driver(cfg.driver)
        cfg.tools = bootstrap(repo)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"orchestrator: commit {str(cfg.driver.get('commit'))[:12]} blob "
          f"{str(cfg.driver.get('blob'))[:12]} clean={cfg.driver.get('clean')} "
          f"byte_identical_to_head={cfg.driver.get('byte_identical_to_head')}", flush=True)

    def body(out: Path) -> int:
        cfg.out = out
        with contextlib.chdir(repo):
            return run(cfg)

    try:
        if cfg.mode == "evidence":
            final = cfg.out
            rc = publish_transactionally(final, body)
            print(f"published {final}", flush=True)
            return rc
        cfg.out.mkdir(parents=True, exist_ok=True)
        return body(cfg.out)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        if cfg.mode == "evidence":
            print(f"nothing published: {args.out} does not exist", file=sys.stderr)
        return 2


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main(sys.argv[1:]))
