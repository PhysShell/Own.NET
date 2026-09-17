#!/usr/bin/env python3
"""P-022 / #263 — step 7: the execution binding, one per campaign.

Host qualification answers "is this one environment fit". This answers a
different question: **which** Linux and Windows environments, which candidates
and which instrument form THIS campaign. A utility that checks a CPU governor
must not become the root of campaign identity, so the two stay apart.

Nothing here is taken on the caller's word. Every bound component is **proved**
against git objects and file bytes at emit time, and re-proved by `--verify`:

  T0           the commit exists, `blob_sha` really is `commit:path`, the bytes
               hash to `sha256`, and the document says FROZEN.
  instrument   the harness digest is RECOMPUTED from the instrument sources at
               the named commit, using the frozen formula, without importing the
               harness. Because the workload manifest is one of those sources,
               proving the digest at a commit also proves the manifest at that
               commit — so there is no second anchor to write and none to get
               wrong.
  hosts        each qualification says qualified, and names the SAME T0 as this
               binding. A qualification earned against an older T0 cannot enter
               a newer campaign.
  candidates   sha256 and byte length of the exact files.

The binding carries references and identity, never copies: duplicating the
governor or the provisioning blob would make two copies of one fact, and two
copies drift.

    provisioning -> envcapture -> qualification -> execution binding
      -> training -> N -> D7 C1 -> D7 C2 -> decisive collection

D7 later binds `execution_binding_sha256`; it does not restate the machines.

Lifecycle: before the first clock a rebuild is legitimate but never silent —
`--emit` refuses to overwrite. After the first clock the binding is immutable,
and any drift `--verify` reports is not a patch: the campaign stops and a new
binding identity begins.

Usage:
    execbinding.py --emit <out.json> --t0-path <p> --t0-commit <sha> \\
        --instrument-commit <sha> --harness-digest <hex> \\
        --linux <q.json> --linux-candidate <bin> \\
        --windows <q.json> --windows-candidate <bin>
    execbinding.py --verify <binding.json> --linux <q.json> --windows <q.json> \\
        --linux-candidate <bin> --windows-candidate <bin>
    execbinding.py --selftest
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

BINDING_SCHEMA = "own.net/p022/execution-binding"
QUALIFICATION_SCHEMA = "own.net/p022/host-qualification"
SCHEMA_VERSION = 1
STRATA = ("linux", "windows")

MEMORY_METRIC_RESIDENT = "max_process_peak_resident"
MEMORY_METRIC_COMMIT = "max_process_peak_commit"
STRATUM_METRIC = {"linux": MEMORY_METRIC_RESIDENT, "windows": MEMORY_METRIC_COMMIT}

# The instrument's identity is the content of these files, in this order. The
# manifest is one of them on purpose — see the module docstring.
INSTRUMENT_SOURCES = ("scripts/perf_baseline.py", "docs/evidence/p022-263a-workloads.json")
WORKLOAD_MANIFEST = "docs/evidence/p022-263a-workloads.json"

REQUIRED_STRATUM_KEYS = ("qualification_sha256", "environment_id", "host_fingerprint",
                         "candidate_sha256", "candidate_bytes", "memory_metric")


class BindingRefused(Exception):
    """Raised by name, so a caller that reads through gets an exception."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def _git(repo: Path, *args: str) -> tuple[int, bytes]:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
    except (OSError, ValueError):
        return 127, b""
    return proc.returncode, proc.stdout


def normalized_text(data: bytes) -> bytes:
    """Line endings normalized, so identity is content and not checkout policy."""
    return data.replace(b"\r\n", b"\n")


def harness_digest_at(repo: Path, commit: str) -> str | None:
    """The frozen formula, recomputed from git blobs — not imported.

    Importing the harness to check the harness would prove only that a function
    agrees with itself.
    """
    lines = []
    for path in INSTRUMENT_SOURCES:
        rc, raw = _git(repo, "cat-file", "blob", f"{commit}:{path}")
        if rc != 0:
            return None
        lines.append(f"{Path(path).name}:{sha256_bytes(normalized_text(raw))}")
    return sha256_bytes("\n".join(lines).encode("utf-8"))


def t0_at(repo: Path, path: str, commit: str) -> dict[str, object]:
    rc, _ = _git(repo, "cat-file", "-e", f"{commit}^{{commit}}")
    if rc != 0:
        raise BindingRefused(f"T0 commit {commit} does not exist")
    rc, blob = _git(repo, "rev-parse", f"{commit}:{path}")
    if rc != 0:
        raise BindingRefused(f"T0 path {path} does not exist at {commit}")
    rc, raw = _git(repo, "cat-file", "blob", f"{commit}:{path}")
    if rc != 0:
        raise BindingRefused(f"the T0 blob at {commit}:{path} could not be read")
    text = raw.decode("utf-8", "replace")
    status = re.search(r"^\s*(NOT_FROZEN|FROZEN)\.?\s*$", text, re.MULTILINE)
    flag = re.search(r"^\s*collection_authorized:\s*(true|false)\s*$", text, re.MULTILINE)
    declared = status.group(1) if status else "<no status line>"
    authorized = (flag.group(1) == "true") if flag else None
    # One authority state read from two fields (R15); three of the four
    # combinations refuse, and the same three refuse on the qualification path.
    if declared != "FROZEN" and authorized is True:
        raise BindingRefused(
            f"T0 at {commit}:{path} declares {declared} while claiming collection_authorized: "
            "true; an authorisation without a fixed protocol is a contradiction")
    if declared != "FROZEN":
        raise BindingRefused(
            f"T0 at {commit}:{path} declares {declared}; a campaign cannot be bound to a "
            "protocol whose rules may still change")
    if authorized is not True:
        raise BindingRefused(
            f"T0 at {commit}:{path} is FROZEN but collection_authorized is {authorized!r}; the "
            "freeze is the owner's authorising act and carries both, so a campaign bound "
            "without it would be bound to a protocol nobody has released")
    return {"commit": commit, "path": path, "blob_sha": blob.decode().strip(),
            "sha256": sha256_bytes(raw), "status": declared,
            "collection_authorized": authorized}


def validate_qualification(doc: object) -> list[str]:
    """The one qualification validator. `hostqual` reuses this rather than keeping
    a second opinion: the module that binds campaigns is the lower one, so there
    is no import cycle and no drift between two copies of the same rules."""
    if not isinstance(doc, dict):
        return ["the qualification is not a JSON object"]
    problems = []
    if doc.get("kind") != QUALIFICATION_SCHEMA:
        problems.append(f"kind is {doc.get('kind')!r}, not {QUALIFICATION_SCHEMA!r}")
    if doc.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema is {doc.get('schema')!r}, not {SCHEMA_VERSION}")
    stratum = doc.get("stratum")
    if stratum not in STRATUM_METRIC:
        problems.append(f"stratum is {stratum!r}")
    elif doc.get("memory_metric") != STRATUM_METRIC[stratum]:
        problems.append(f"memory_metric {doc.get('memory_metric')!r} does not belong to "
                        f"stratum {stratum!r}")
    t0 = doc.get("t0")
    if not isinstance(t0, dict) or not t0.get("sha256") or not t0.get("commit"):
        problems.append("t0 does not name a commit and a sha256")
    for key in ("environment_id", "host_fingerprint", "environment_identity_sha256"):
        if not doc.get(key):
            problems.append(f"{key} is missing")
    if not isinstance(doc.get("power_snapshot"), dict):
        problems.append("power_snapshot is missing")
    if not isinstance(doc.get("qualified"), bool):
        problems.append("qualified is not a boolean")
    return problems


def _stratum_block(stratum: str, qualification_path: Path, candidate_path: Path,
                   t0_block: dict) -> dict[str, object]:
    doc = json.loads(qualification_path.read_text(encoding="utf-8"))
    problems = validate_qualification(doc)
    if problems:
        raise BindingRefused(
            f"{qualification_path} does not validate as a host qualification: "
            + "; ".join(problems))
    if doc.get("stratum") != stratum:
        raise BindingRefused(
            f"{qualification_path} declares stratum {doc.get('stratum')!r}, bound as {stratum!r}")
    if not doc.get("qualified"):
        raise BindingRefused(f"{qualification_path} does not say qualified")
    qualified_t0 = doc.get("t0") if isinstance(doc.get("t0"), dict) else {}
    if (qualified_t0.get("sha256") != t0_block["sha256"]
            or qualified_t0.get("commit") != t0_block["commit"]):
        raise BindingRefused(
            f"{stratum}: the host was qualified against T0 "
            f"{str(qualified_t0.get('sha256'))[:12]} at {qualified_t0.get('commit')}, and this "
            f"campaign binds {t0_block['sha256'][:12]} at {t0_block['commit']}. A qualification "
            "earned under one protocol is not evidence under another")
    if doc.get("memory_metric") != STRATUM_METRIC[stratum]:
        raise BindingRefused(f"stratum {stratum} must carry {STRATUM_METRIC[stratum]!r}, "
                             f"not {doc.get('memory_metric')!r}")
    raw = candidate_path.read_bytes()
    return {
        "qualification_sha256": sha256_file(qualification_path),
        "environment_id": doc.get("environment_id"),
        "host_fingerprint": doc.get("host_fingerprint"),
        "environment_identity_sha256": doc.get("environment_identity_sha256"),
        "candidate_sha256": sha256_bytes(raw),
        "candidate_bytes": len(raw),
        "memory_metric": doc.get("memory_metric"),
    }


def build(repo: Path, t0_path: str, t0_commit: str, instrument_commit: str,
          harness_digest: str, strata: dict[str, tuple[Path, Path]]) -> dict[str, object]:
    missing = [s for s in STRATA if s not in strata]
    if missing:
        raise BindingRefused(f"both strata are required; missing {missing}. `U_linux` and "
                             "`U_windows` are never pooled, and never optional either")
    t0_block = t0_at(repo, t0_path, t0_commit)

    live = harness_digest_at(repo, instrument_commit)
    if live is None:
        raise BindingRefused(f"the instrument sources could not be read at {instrument_commit}")
    if live != harness_digest:
        raise BindingRefused(
            f"the instrument at {instrument_commit} hashes to {live[:12]}, not the accepted "
            f"{harness_digest[:12]}; a binding may not name a digest the sources do not produce")
    rc, manifest_raw = _git(repo, "cat-file", "blob", f"{instrument_commit}:{WORKLOAD_MANIFEST}")
    if rc != 0:
        raise BindingRefused(f"the workload manifest is absent at {instrument_commit}")

    binding: dict[str, object] = {
        "kind": BINDING_SCHEMA,
        "schema": SCHEMA_VERSION,
        "t0": t0_block,
        "instrument": {"accepted_commit": instrument_commit, "harness_digest": harness_digest},
        # Taken from the git object at the instrument commit, never from a
        # working-tree file that happened to be passed under the same flag.
        "workloads": {"path": WORKLOAD_MANIFEST, "manifest_sha256": sha256_bytes(manifest_raw)},
        "bound_at": _now(),
    }
    for stratum in STRATA:
        binding[stratum] = _stratum_block(stratum, *strata[stratum], t0_block)
    return binding


def validate(binding: dict) -> list[str]:
    problems: list[str] = []
    if binding.get("kind") != BINDING_SCHEMA:
        problems.append(f"kind is {binding.get('kind')!r}, not {BINDING_SCHEMA!r}")
    if binding.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema is {binding.get('schema')!r}, not {SCHEMA_VERSION}")
    for section, keys in (("t0", ("commit", "path", "blob_sha", "sha256")),
                          ("instrument", ("accepted_commit", "harness_digest")),
                          ("workloads", ("path", "manifest_sha256"))):
        block = binding.get(section)
        if not isinstance(block, dict):
            problems.append(f"{section} is missing")
            continue
        problems.extend(f"{section}.{k} is missing or empty" for k in keys if not block.get(k))
    for stratum in STRATA:
        block = binding.get(stratum)
        if not isinstance(block, dict):
            problems.append(f"{stratum} is missing")
            continue
        problems.extend(f"{stratum}.{k} is missing"
                        for k in REQUIRED_STRATUM_KEYS if block.get(k) in (None, ""))
        if block.get("memory_metric") != STRATUM_METRIC[stratum]:
            problems.append(f"{stratum}.memory_metric is {block.get('memory_metric')!r}, "
                            f"not {STRATUM_METRIC[stratum]!r}")
        if not isinstance(block.get("candidate_bytes"), int):
            problems.append(f"{stratum}.candidate_bytes is not an integer")
    linux, windows = binding.get("linux"), binding.get("windows")
    if isinstance(linux, dict) and isinstance(windows, dict):
        if linux.get("memory_metric") == windows.get("memory_metric"):
            problems.append("both strata carry the same memory metric; they measure different "
                            "physical quantities and may not be pooled")
    return problems


def verify(repo: Path, binding_path: Path, qualifications: dict[str, Path],
           candidates: dict[str, Path]) -> list[str]:
    """Re-prove every bound component that can drift or be substituted.

    There is no partial mode. A verifier that silently narrows to whatever it was
    handed will eventually be called with two arguments missing, and the string
    `binding verified` will be filed as evidence that nobody checked the hosts.
    Incomplete inputs are refused here, not only in argparse, because the next
    caller may be a script.
    """
    incomplete = ([f"qualification for {s}" for s in STRATA if s not in qualifications]
                  + [f"candidate for {s}" for s in STRATA if s not in candidates])
    if incomplete:
        return [f"full verification requires both qualification and candidate inputs for "
                f"linux and windows; missing {incomplete}. There is no partial verification "
                f"under this name"]
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    problems = validate(binding)

    t0 = binding.get("t0") if isinstance(binding.get("t0"), dict) else {}
    try:
        live_t0 = t0_at(repo, str(t0.get("path")), str(t0.get("commit")))
        if live_t0["sha256"] != t0.get("sha256") or live_t0["blob_sha"] != t0.get("blob_sha"):
            problems.append("T0: the bytes at the bound commit are not the bytes bound")
    except BindingRefused as exc:
        problems.append(f"T0: {exc}")

    instrument = binding.get("instrument") if isinstance(binding.get("instrument"), dict) else {}
    live_digest = harness_digest_at(repo, str(instrument.get("accepted_commit")))
    if live_digest is None:
        problems.append("instrument: the sources could not be read at the bound commit")
    elif live_digest != instrument.get("harness_digest"):
        problems.append(f"instrument: the sources at the bound commit now hash to "
                        f"{live_digest[:12]}, bound as "
                        f"{str(instrument.get('harness_digest'))[:12]}")
    rc, manifest_raw = _git(repo, "cat-file", "blob",
                            f"{instrument.get('accepted_commit')}:{WORKLOAD_MANIFEST}")
    workloads = binding.get("workloads") if isinstance(binding.get("workloads"), dict) else {}
    if rc != 0:
        problems.append("workloads: the manifest is absent at the bound instrument commit")
    elif sha256_bytes(manifest_raw) != workloads.get("manifest_sha256"):
        problems.append("workloads: the manifest at the bound commit is not the one bound")

    for stratum, path in qualifications.items():
        block = binding.get(stratum) if isinstance(binding.get(stratum), dict) else {}
        live = sha256_file(path)
        if block.get("qualification_sha256") != live:
            problems.append(
                f"{stratum}: the qualification now hashes to {live[:12]}, bound as "
                f"{str(block.get('qualification_sha256'))[:12]}")
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        qualified_t0 = doc.get("t0") if isinstance(doc.get("t0"), dict) else {}
        if qualified_t0.get("sha256") != t0.get("sha256"):
            problems.append(f"{stratum}: the qualification names a different T0 than the binding")

    for stratum, path in candidates.items():
        block = binding.get(stratum) if isinstance(binding.get(stratum), dict) else {}
        raw = path.read_bytes()
        if sha256_bytes(raw) != block.get("candidate_sha256") or len(raw) != block.get(
                "candidate_bytes"):
            problems.append(
                f"{stratum}: the candidate present is {sha256_bytes(raw)[:12]} / {len(raw)} B, "
                f"bound as {str(block.get('candidate_sha256'))[:12]} / "
                f"{block.get('candidate_bytes')} B")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--t0-path")
    parser.add_argument("--t0-commit")
    parser.add_argument("--instrument-commit")
    parser.add_argument("--harness-digest")
    parser.add_argument("--linux", type=Path)
    parser.add_argument("--linux-candidate", type=Path)
    parser.add_argument("--windows", type=Path)
    parser.add_argument("--windows-candidate", type=Path)
    args = parser.parse_args(argv)

    if args.selftest:
        print(json.dumps({"kind": BINDING_SCHEMA, "schema": SCHEMA_VERSION,
                          "strata": STRATUM_METRIC, "instrument_sources": INSTRUMENT_SOURCES,
                          "required_stratum_keys": list(REQUIRED_STRATUM_KEYS)}, indent=2))
        return 0

    if args.verify:
        needed = {"linux": args.linux, "windows": args.windows,
                  "linux-candidate": args.linux_candidate,
                  "windows-candidate": args.windows_candidate}
        absent = sorted(k for k, v in needed.items() if v is None)
        if absent:
            # Refusing to run beats running half of it and printing the word
            # "verified" over the half that was skipped.
            parser.error(f"--verify performs the FULL campaign verification and requires "
                         f"{['--' + k for k in absent]}")
        qualifications = {"linux": args.linux, "windows": args.windows}
        candidates = {"linux": args.linux_candidate, "windows": args.windows_candidate}
        problems = verify(args.repo, args.verify, qualifications, candidates)
        for problem in problems:
            print(f"BINDING-DRIFT: {problem}")
        print("binding verified" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0

    if args.emit:
        if args.emit.exists():
            print(f"refused: {args.emit} exists. A rebuild is a deliberate act — remove it "
                  "first, and only before the first clock.", file=sys.stderr)
            return 2
        needed = {"t0-path": args.t0_path, "t0-commit": args.t0_commit,
                  "instrument-commit": args.instrument_commit,
                  "harness-digest": args.harness_digest, "linux": args.linux,
                  "linux-candidate": args.linux_candidate, "windows": args.windows,
                  "windows-candidate": args.windows_candidate}
        absent = sorted(k for k, v in needed.items() if v is None)
        if absent:
            parser.error(f"--emit requires {absent}")
        binding = build(args.repo, args.t0_path, args.t0_commit, args.instrument_commit,
                        args.harness_digest,
                        {"linux": (args.linux, args.linux_candidate),
                         "windows": (args.windows, args.windows_candidate)})
        problems = validate(binding)
        if problems:
            raise BindingRefused("; ".join(problems))
        args.emit.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        print(f"bound: {sha256_file(args.emit)}")
        return 0

    parser.error("choose --emit, --verify or --selftest")
    return 2


if __name__ == "__main__":
    sys.exit(main())
