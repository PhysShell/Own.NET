#!/usr/bin/env python3
"""P-022 / #263 — step 7: the execution binding, one per campaign.

Host qualification answers "is this one environment fit". This answers a
different question: **which** Linux and Windows environments, which candidates
and which instrument form THIS measurement campaign. The two are separate
artifacts on purpose — a utility that checks a CPU governor must not become the
root of campaign identity, and a campaign identity must not be re-derived from
whichever qualified host happens to be lying around.

The binding carries **references and identity**, never copies. Governors, power
plans, CPU samples and the provisioning declaration stay in the qualification
record, which owns them; duplicating them here would create two copies of one
fact, and two copies drift.

The chain is acyclic, and each link names only the one before it:

    provisioning declaration -> envcapture manifest -> host qualification
      -> execution binding -> training session(s) -> N -> D7 C1 -> D7 C2
      -> decisive collection

D7 later binds `execution_binding_sha256`. It does not restate the machines.

Lifecycle, enforced here as far as a tool can and stated where it cannot:

  BEFORE the first clock  the binding may be rebuilt whenever a host or a
                          candidate changes. `--emit` refuses to overwrite an
                          existing file, so a rebuild is a deliberate act.
  AFTER the first clock   the binding is immutable. A change to any bound
                          component does not patch the running campaign: the old
                          campaign stops and a new binding identity begins.
                          `--verify` detects the drift; it cannot un-run a clock.

Usage:
    python scripts/step7/execbinding.py --emit <out.json> --t0 <t0.md> \\
        --t0-commit <sha> --instrument-commit <sha> --harness-digest <hex> \\
        --workloads <workloads.json> \\
        --linux <qualification.linux.json> --linux-candidate <path> \\
        --windows <qualification.windows.json> --windows-candidate <path>
    python scripts/step7/execbinding.py --verify <binding.json> \\
        --linux <qualification.linux.json> --windows <qualification.windows.json>
    python scripts/step7/execbinding.py --selftest
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

BINDING_SCHEMA = "own.net/p022/execution-binding"
SCHEMA_VERSION = 1
STRATA = ("linux", "windows")

# Kept in step with hostqual's own declaration; a control proves they agree.
MEMORY_METRIC_RESIDENT = "max_process_peak_resident"
MEMORY_METRIC_COMMIT = "max_process_peak_commit"
STRATUM_METRIC = {"linux": MEMORY_METRIC_RESIDENT, "windows": MEMORY_METRIC_COMMIT}

REQUIRED_STRATUM_KEYS = ("qualification_sha256", "environment_id", "host_fingerprint",
                         "candidate_sha256", "candidate_bytes", "memory_metric")


class BindingRefused(Exception):
    """Raised by name, so a caller that reads through gets an exception."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _stratum_block(stratum: str, qualification_path: Path,
                   candidate_path: Path) -> dict[str, object]:
    doc = json.loads(qualification_path.read_text(encoding="utf-8"))
    if doc.get("kind") != "own.net/p022/host-qualification":
        raise BindingRefused(f"{qualification_path} is not a host-qualification artifact")
    if doc.get("stratum") != stratum:
        raise BindingRefused(
            f"{qualification_path} declares stratum {doc.get('stratum')!r}, bound as {stratum!r}")
    if not doc.get("qualified"):
        raise BindingRefused(f"{qualification_path} does not say qualified; an unqualified host "
                             "may not enter a campaign")
    metric = doc.get("memory_metric")
    if metric != STRATUM_METRIC[stratum]:
        raise BindingRefused(
            f"stratum {stratum} must carry {STRATUM_METRIC[stratum]!r}, not {metric!r}")
    raw = candidate_path.read_bytes()
    return {
        "qualification_sha256": sha256_file(qualification_path),
        "environment_id": doc.get("environment_id"),
        "host_fingerprint": doc.get("host_fingerprint"),
        "candidate_sha256": hashlib.sha256(raw).hexdigest(),
        "candidate_bytes": len(raw),
        "memory_metric": metric,
    }


def build(t0_path: Path, t0_commit: str, t0_blob_sha: str, instrument_commit: str,
          harness_digest: str, workloads_path: Path,
          strata: dict[str, tuple[Path, Path]]) -> dict[str, object]:
    missing = [s for s in STRATA if s not in strata]
    if missing:
        raise BindingRefused(f"both strata are required; missing {missing}. `U_linux` and "
                             "`U_windows` are never pooled, and never optional either")
    binding: dict[str, object] = {
        "kind": BINDING_SCHEMA,
        "schema": SCHEMA_VERSION,
        "t0": {"commit": t0_commit, "blob_sha": t0_blob_sha, "sha256": sha256_file(t0_path)},
        "instrument": {"accepted_commit": instrument_commit, "harness_digest": harness_digest},
        "workloads": {"manifest_sha256": sha256_file(workloads_path)},
        "bound_at": _now(),
    }
    for stratum in STRATA:
        binding[stratum] = _stratum_block(stratum, *strata[stratum])
    return binding


def validate(binding: dict) -> list[str]:
    problems: list[str] = []
    if binding.get("kind") != BINDING_SCHEMA:
        problems.append(f"kind is {binding.get('kind')!r}, not {BINDING_SCHEMA!r}")
    if binding.get("schema") != SCHEMA_VERSION:
        problems.append(f"schema is {binding.get('schema')!r}, not {SCHEMA_VERSION}")
    for section, keys in (("t0", ("commit", "blob_sha", "sha256")),
                          ("instrument", ("accepted_commit", "harness_digest")),
                          ("workloads", ("manifest_sha256",))):
        block = binding.get(section)
        if not isinstance(block, dict):
            problems.append(f"{section} is missing")
            continue
        problems.extend(f"{section}.{k} is missing or empty"
                        for k in keys if not block.get(k))
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
    if isinstance(binding.get("linux"), dict) and isinstance(binding.get("windows"), dict):
        if binding["linux"].get("memory_metric") == binding["windows"].get("memory_metric"):
            problems.append("both strata carry the same memory metric; they measure different "
                            "physical quantities and may not be pooled")
    return problems


def verify(binding_path: Path, qualifications: dict[str, Path]) -> list[str]:
    """Does the campaign still describe the hosts it was bound to?"""
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    problems = validate(binding)
    for stratum, path in qualifications.items():
        block = binding.get(stratum)
        if not isinstance(block, dict):
            continue
        live = sha256_file(path)
        if block.get("qualification_sha256") != live:
            problems.append(
                f"{stratum}: the qualification now hashes to {live[:12]}, bound as "
                f"{str(block.get('qualification_sha256'))[:12]}. After the first clock this is "
                "not a patch: the campaign stops and a new binding identity begins")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--emit", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--t0", type=Path)
    parser.add_argument("--t0-commit", default="")
    parser.add_argument("--t0-blob-sha", default="")
    parser.add_argument("--instrument-commit", default="")
    parser.add_argument("--harness-digest", default="")
    parser.add_argument("--workloads", type=Path)
    parser.add_argument("--linux", type=Path)
    parser.add_argument("--linux-candidate", type=Path)
    parser.add_argument("--windows", type=Path)
    parser.add_argument("--windows-candidate", type=Path)
    args = parser.parse_args(argv)

    if args.selftest:
        print(json.dumps({"kind": BINDING_SCHEMA, "schema": SCHEMA_VERSION,
                          "strata": STRATUM_METRIC,
                          "required_stratum_keys": list(REQUIRED_STRATUM_KEYS)}, indent=2))
        return 0

    if args.verify:
        qualifications = {s: p for s, p in (("linux", args.linux), ("windows", args.windows))
                          if p is not None}
        problems = verify(args.verify, qualifications)
        for problem in problems:
            print(f"BINDING-DRIFT: {problem}")
        print("binding verified" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0

    if args.emit:
        if args.emit.exists():
            # Before the first clock a rebuild is legitimate; it is never silent.
            print(f"refused: {args.emit} exists. A rebuild is a deliberate act — remove it "
                  "first, and only before the first clock.", file=sys.stderr)
            return 2
        required = {"t0": args.t0, "workloads": args.workloads, "linux": args.linux,
                    "linux-candidate": args.linux_candidate, "windows": args.windows,
                    "windows-candidate": args.windows_candidate}
        absent = sorted(k for k, v in required.items() if v is None)
        if absent:
            parser.error(f"--emit requires {absent}")
        binding = build(args.t0, args.t0_commit, args.t0_blob_sha, args.instrument_commit,
                        args.harness_digest, args.workloads,
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
