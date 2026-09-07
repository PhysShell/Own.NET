#!/usr/bin/env python3
"""The one interpretation of #260's sweep: its definition, one recorded run.

The counterpart to `tests/shadow_census.py` for the measurement the acceptance
surfaces over the committed corpus deliberately did not take — the five pinned
OSS repositories of #243, the large-solution controls and the `examples/` tree.
The status renderer and the test gate both read this module, because two
readings of one run is how two documents come to disagree about it.

## What a definition is, and what a result is

The **definition** (`docs/evidence/p022-shadow-sweep.json`) is what SHOULD be
measured: the targets with their pins, the documents with their extraction mode
and verbatim command, the timeout each carries, the driver version it expects
and how the port's adapter is built. It is the DENOMINATOR, and that is the
whole reason it exists as a separate file: a run that reports only what it
happened to measure cannot be short.

The **result** (`….result.json`) is one actual run. A re-run replaces it whole;
it is never patched, because a document patched into a run that did not produce
it is a claim wearing a measurement's clothes.

## What this refuses

Nothing here decides whether two engines agree — the driver does that, and this
reads what it wrote. What this decides is whether the RUN is evidence:

* an empty run, or a target whose compare-attempted count is zero — #250's
  fifth failure mode, and the reason the denominators are recorded per target;
* a document the definition declares and the result does not carry;
* a document the result carries that the definition does not declare;
* a document measured at a commit, in a mode, or by a command other than the
  one the definition names — the run then measured something, but not this;
* a driver version, or an adapter identity, the result cannot name;
* a `source_commit` that is not an ancestor of HEAD;
* any document outcome other than `agreed`, and any acceptance-unexplained
  observation, including one hiding inside a document recorded as agreed.

## `--collect`

CI runs one leg per document and each leg writes its own run summary. Collect
merges them into the single result document above, so that the record a
workflow produces and the record a local run produces are the same shape,
assembled by the same code.

Run:  python tests/shadow_sweep.py                      (the committed pair)
      python tests/shadow_sweep.py --result <path>      (the definition vs another run)
      python tests/shadow_sweep.py --collect <dir> --write <path>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE = os.path.join(ROOT, "docs", "evidence")
DEFINITION = os.path.join(EVIDENCE, "p022-shadow-sweep.json")
RESULT = os.path.join(EVIDENCE, "p022-shadow-sweep.result.json")

SCHEMA = 1
# The only document outcome this sweep may report. `declared-boundary` is an
# ACCEPTANCE of an observation inside a document (owner decision D-5), never a
# document outcome — a document whose observations are all agreed-or-declared
# is reported by the driver as `agreed`, which is the value checked here.
OUTCOME_AGREED = "agreed"
SHA256 = re.compile(r"^[0-9a-f]{64}$")

# The counters a target row carries. Named here rather than derived from
# whatever a result happens to contain: a denominator that only exists when
# somebody wrote it is not a denominator.
TARGET_FIELDS = ("documents_extracted", "compare_attempted", "agreed",
                 "diverged", "execution_failures", "input_refusals",
                 "input_disagreements", "declared_boundary_observations",
                 "acceptance_unexplained_observations")


class SweepError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class DocumentRow:
    id: str
    target: str
    target_commit: str
    extraction_mode: str
    outcome: str
    raw_digest: str
    raw_bytes: int
    canonical_digest: str
    reduction_outcome: str
    derived_outcome: str
    declared_boundary: int
    unexplained: int
    timeout_seconds: float
    wall_clock_seconds: float


@dataclass
class SweepSummary:
    """Every figure the sweep's status surfaces may show, and nothing else."""

    sweep: str = ""
    source_commit: str = ""
    recorded_at: str = ""
    host: str = ""
    workflow_run_url: str | None = None
    driver_version: int = 0
    adapters: tuple[tuple[str, int], ...] = ()
    documents: tuple[DocumentRow, ...] = ()
    targets: tuple[tuple[str, ...], ...] = ()
    totals: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _git_ok(*args: str) -> bool:
    try:
        done = subprocess.run(["git", "-C", ROOT, *args], capture_output=True,
                              text=True, check=False, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def provenance_problems(source_commit: str) -> list[str]:
    """The gate's view of a run's provenance, and deliberately the same shape a
    mutation campaign's has: the recorded commit must exist in this tree and be
    an ancestor of HEAD. It refuses a run that describes a history this tree
    does not contain, without making the record depend on HEAD's content."""
    if not source_commit:
        return ["the run records no source commit, so nothing says which tree "
                "it measured"]
    if not _git_ok("rev-parse", "--git-dir"):
        return [f"cannot verify the provenance of {source_commit[:12]}: not a "
                f"git checkout"]
    if not _git_ok("cat-file", "-e", f"{source_commit}^{{commit}}"):
        return [f"source commit {source_commit[:12]} does not exist in this "
                f"repository — a rebased or deleted branch? re-run the sweep"]
    if not _git_ok("merge-base", "--is-ancestor", source_commit, "HEAD"):
        return [f"source commit {source_commit[:12]} is not an ancestor of HEAD "
                f"— the run describes a history this tree does not contain; "
                f"re-run the sweep"]
    return []


def compute_sweep_summary(definition: dict[str, Any],
                          result: dict[str, Any]) -> SweepSummary:
    """Definition + one run → the summary, with every problem it has."""
    problems: list[str] = []
    for name, doc, expected in (("definition", definition, SCHEMA),
                                ("result", result, SCHEMA)):
        if doc.get("schema") != expected:
            problems.append(f"the {name} declares schema "
                            f"{doc.get('schema')!r}, this interpreter reads "
                            f"{expected}")
    declared = {str(d["id"]): d for d in definition.get("documents", [])}
    measured = {str(d["id"]): d for d in result.get("documents", [])}

    if not measured:
        problems.append(
            "the run carries NO documents: it compared zero of them, which is a "
            "failure and never agreement (a green gate over an empty set is "
            "worse than a red one)")
    for doc_id in sorted(set(declared) - set(measured)):
        problems.append(
            f"{doc_id}: declared by the definition and absent from the run — a "
            f"document nobody measured is not a document that agreed")
    for doc_id in sorted(set(measured) - set(declared)):
        problems.append(
            f"{doc_id}: measured by the run and not declared by the definition; "
            f"the definition is the denominator and may not be a subset of what "
            f"happened to be measured")

    want_driver = definition.get("driver_version")
    if result.get("driver_version") != want_driver:
        problems.append(
            f"the run names driver version {result.get('driver_version')!r}, the "
            f"definition expects {want_driver!r}")

    adapters: list[tuple[str, int]] = []
    for entry in result.get("adapters", []):
        digest = str(entry.get("sha256", ""))
        size = entry.get("bytes")
        if not SHA256.match(digest) or not isinstance(size, int) or size <= 0:
            problems.append(
                f"an adapter is recorded as {entry!r}: a recorded comparison "
                f"names the engine by a sha256 and a byte length, because a "
                f"path is not an identity")
            continue
        adapters.append((digest, size))
    if not adapters:
        problems.append(
            "the run names no adapter at all — nothing says which engine it "
            "compared the reference against")

    rows: list[DocumentRow] = []
    for doc_id in sorted(measured):
        m = measured[doc_id]
        d = declared.get(doc_id)
        if d is not None:
            for field_name in ("target", "extraction_mode", "extraction_command"):
                if m.get(field_name) != d.get(field_name):
                    problems.append(
                        f"{doc_id}: the run recorded {field_name}="
                        f"{m.get(field_name)!r}, the definition declares "
                        f"{d.get(field_name)!r} — the run measured something, "
                        f"but not this")
            # A null pin in the definition means "this repository, at the commit
            # the run was taken on" — the `examples/` document, whose target IS
            # the tree being measured. It is a check rather than an exemption:
            # the recorded pin must then be the run's own source commit.
            want_pin = d.get("target_commit")
            if want_pin is None:
                want_pin = result.get("source_commit")
            if m.get("target_commit") != want_pin:
                problems.append(
                    f"{doc_id}: the run recorded target_commit="
                    f"{m.get('target_commit')!r}, expected {want_pin!r} — the "
                    f"run measured something, but not this")
        outcome = str(m.get("outcome", ""))
        unexplained = int(m.get("acceptance_unexplained_observations", 0) or 0)
        if outcome != OUTCOME_AGREED:
            problems.append(
                f"{doc_id}: outcome {outcome!r}. Only 'agreed' is an outcome "
                f"this sweep may report; a divergence is a finding and stays on "
                f"the record until it is resolved")
        if unexplained:
            problems.append(
                f"{doc_id}: {unexplained} acceptance-unexplained observation(s) "
                f"in a document recorded as {outcome!r}")
        raw = m.get("raw") or {}
        canonical = m.get("canonical") or {}
        if not SHA256.match(str(raw.get("digest", ""))):
            problems.append(f"{doc_id}: no raw byte identity is recorded, so "
                            f"nothing says which bytes were compared")
        rows.append(DocumentRow(
            id=doc_id,
            target=str(m.get("target", "")),
            target_commit=str(m.get("target_commit", "")),
            extraction_mode=str(m.get("extraction_mode", "")),
            outcome=outcome,
            raw_digest=str(raw.get("digest", "")),
            raw_bytes=int(raw.get("bytes", 0) or 0),
            canonical_digest=str(canonical.get("digest", "")),
            reduction_outcome=str(m.get("reduction_outcome", "")),
            derived_outcome=str(m.get("derived_outcome", "")),
            declared_boundary=int(
                m.get("declared_boundary_observations", 0) or 0),
            unexplained=unexplained,
            timeout_seconds=float(m.get("timeout_seconds", 0) or 0),
            wall_clock_seconds=float(m.get("wall_clock_seconds", 0) or 0)))

    target_rows = {str(t["target"]): t for t in result.get("targets", [])}
    for target in sorted({str(t["target"]) for t in definition.get("targets", [])}):
        row = target_rows.get(target)
        if row is None:
            problems.append(
                f"target {target!r} is declared by the definition and missing "
                f"from the run — a skipped target is not a passed repository")
            continue
        if int(row.get("compare_attempted", 0) or 0) == 0:
            problems.append(
                f"target {target!r} had ZERO documents compared: a target is "
                f"not covered because its extraction ran")
        extracted = int(row.get("documents_extracted", 0) or 0)
        attempted = int(row.get("compare_attempted", 0) or 0)
        if extracted != attempted:
            problems.append(
                f"target {target!r}: {extracted} document(s) extracted and "
                f"{attempted} compared — the gap is a document that was skipped")
    for target in sorted(set(target_rows) - {
            str(t["target"]) for t in definition.get("targets", [])}):
        problems.append(f"target {target!r} appears in the run and not in the "
                        f"definition")

    totals = {name: int((result.get("totals") or {}).get(name, 0) or 0)
              for name in TARGET_FIELDS}
    recomputed = {name: sum(int(r.get(name, 0) or 0) for r in target_rows.values())
                  for name in TARGET_FIELDS}
    for name in TARGET_FIELDS:
        if totals[name] != recomputed[name]:
            problems.append(
                f"totals[{name!r}] is {totals[name]}, the per-target rows sum to "
                f"{recomputed[name]} — a total that is not the sum of its parts "
                f"is a number somebody typed")
    problems.extend(provenance_problems(str(result.get("source_commit", ""))))

    return SweepSummary(
        sweep=str(definition.get("sweep", "")),
        source_commit=str(result.get("source_commit", "")),
        recorded_at=str(result.get("recorded_at", "")),
        host=str(result.get("host", "")),
        workflow_run_url=(str(result["workflow_run_url"])
                          if result.get("workflow_run_url") else None),
        driver_version=int(result.get("driver_version", 0) or 0),
        adapters=tuple(adapters),
        documents=tuple(rows),
        targets=tuple(
            tuple([target] + [str(target_rows[target].get(name, 0))
                              for name in TARGET_FIELDS])
            for target in sorted(target_rows)),
        totals=totals,
        problems=problems)


def load_pair(definition_path: str = DEFINITION,
              result_path: str = RESULT) -> tuple[dict[str, Any], dict[str, Any]]:
    for path in (definition_path, result_path):
        if not os.path.exists(path):
            raise SweepError([f"{os.path.relpath(path, ROOT)}: missing — the "
                              f"sweep is definition AND one recorded run"])
    return _load(definition_path), _load(result_path)


# --- assembling one record out of the legs of a run ------------------------


def collect(directory: str, workflow_run_url: str | None,
            definition_path: str = DEFINITION) -> dict[str, Any]:
    """Merge every leg's run summary and per-document result into one record.

    CI runs one leg per document; a local run does all of them at once. Both
    write the same files, so both are collected by this one function — the
    record a workflow produces and the record a hand run produces cannot drift
    into different shapes."""
    import hashlib
    import platform
    import time

    summaries: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    for dirpath, _dirnames, filenames in os.walk(directory):
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if name == "summary.json":
                summaries.append(_load(path))
            elif name.endswith(".result.json"):
                doc = _load(path)
                key = str(doc.get("document_id") or "")
                if key:
                    details[key] = doc
    if not summaries:
        raise SweepError([f"{directory}: no run summary found. A sweep record is "
                          f"assembled from what the driver wrote, never typed."])

    documents: list[dict[str, Any]] = []
    targets: dict[str, dict[str, Any]] = {}
    adapters: dict[str, int] = {}
    versions: set[int] = set()
    commits: set[str] = set()
    for summary in summaries:
        digest = str(summary.get("engine_binary_sha256", ""))
        if digest:
            adapters[digest] = int(summary.get("engine_binary_bytes", 0) or 0)
        versions.add(int(summary.get("shadow_compare_version", 0) or 0))
        if summary.get("own_net_commit"):
            commits.add(str(summary["own_net_commit"]))
        for row in summary.get("targets", []):
            into = targets.setdefault(
                str(row["target"]),
                {"target": str(row["target"]), **dict.fromkeys(TARGET_FIELDS, 0)})
            for name in TARGET_FIELDS:
                into[name] = int(into[name]) + int(row.get(name, 0) or 0)
        for record in summary.get("documents", []):
            doc_id = str(record.get("id", ""))
            detail = details.get(doc_id, {})
            reduction = detail.get("reduction") or {}
            acceptance = (reduction.get("classification") or {}).get(
                "by_acceptance", {})
            documents.append({
                "id": doc_id,
                "source": record.get("source"),
                "target": record.get("target"),
                "target_commit": record.get("target_commit"),
                "extraction_mode": record.get("extraction_mode"),
                "extraction_command": record.get("extraction_command"),
                "facts_sha256": record.get("facts_sha256"),
                "raw": (detail.get("input") or {}).get("raw"),
                "canonical": (detail.get("input") or {}).get("canonical"),
                "outcome": record.get("outcome"),
                "timeout_seconds": record.get("timeout_seconds"),
                "reduction_outcome": reduction.get("outcome"),
                "by_kind": (reduction.get("classification") or {}).get("by_kind"),
                "declared_boundary_observations": int(
                    acceptance.get("declared-boundary", 0) or 0),
                "acceptance_unexplained_observations": int(
                    acceptance.get("unexplained", 0) or 0),
                "derived_outcome": (detail.get("derived") or {}).get("outcome"),
                "wall_clock_seconds": record.get("wall_clock_seconds"),
            })
    with open(definition_path, "rb") as f:
        definition_sha = hashlib.sha256(f.read()).hexdigest()
    return {
        "schema": SCHEMA,
        "comment": ("One recorded run of the #260 sweep, assembled by "
                    "tests/shadow_sweep.py --collect from what "
                    "scripts/shadow_compare.py wrote. Raw facts only: "
                    "identities, outcomes, denominators, provenance. Counts are "
                    "derived by scripts/render_checkpoint_status.py; regenerate "
                    "this file by re-running the sweep, never by hand."),
        "sweep": "p022-shadow-sweep",
        "definition": os.path.relpath(definition_path, ROOT).replace(os.sep, "/"),
        "definition_sha256": definition_sha,
        "source_commit": sorted(commits)[0] if len(commits) == 1 else "",
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": f"{platform.system()} {platform.machine()}",
        "workflow_run_url": workflow_run_url,
        "driver_version": sorted(versions)[0] if len(versions) == 1 else 0,
        "adapters": [{"sha256": d, "bytes": n} for d, n in sorted(adapters.items())],
        "documents": sorted(documents, key=lambda d: str(d["id"])),
        "targets": [targets[t] for t in sorted(targets)],
        "totals": {name: sum(int(t[name]) for t in targets.values())
                   for name in TARGET_FIELDS},
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="shadow_sweep",
        description="Interpret #260's sweep definition and one recorded run.")
    parser.add_argument("--result", default=RESULT,
                        help="the recorded run to read (default: the committed one)")
    parser.add_argument("--definition", default=DEFINITION)
    parser.add_argument("--collect", default=None,
                        help="assemble one record from a run directory instead")
    parser.add_argument("--write", default=None,
                        help="where --collect writes the assembled record")
    parser.add_argument("--workflow-run-url", default=None)
    args = parser.parse_args(argv)

    if args.collect is not None:
        record = collect(args.collect, args.workflow_run_url, args.definition)
        text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
        if args.write:
            with open(args.write, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(f"wrote {args.write}: {len(record['documents'])} document(s), "
                  f"{len(record['targets'])} target(s)")
        else:
            sys.stdout.write(text)
        return 0

    try:
        definition, result = load_pair(args.definition, args.result)
    except SweepError as e:
        for p in e.problems:
            print(f"FAIL[shadow-sweep]: {p}")
        return 1
    summary = compute_sweep_summary(definition, result)
    for p in summary.problems:
        print(f"FAIL[shadow-sweep]: {p}")
    if summary.problems:
        return 1
    print(f"shadow sweep OK: {len(summary.documents)} document(s) over "
          f"{len(summary.targets)} target(s), all agreed; "
          f"{summary.totals['acceptance_unexplained_observations']} "
          f"acceptance-unexplained observation(s); recorded at "
          f"{summary.source_commit[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
