#!/usr/bin/env python3
"""The compare driver: one input, two engines, one verdict about their agreement
(P-022 step 7a, #260 acceptance — owner decisions R-1, R-2, B-2, D-5, D-6).

**A dev surface.** Nothing in `owen` / `own-check` invokes this, and nothing
here is a user-facing CLI: it is the harness that runs the two engines against
one byte sequence and reports what it found. Python remains the public default
engine; this compares, it does not choose.

## The one invariant everything else hangs off

> The input is read **once**, as bytes, and no engine ever sees a path.

`raw = open(path, "rb").read()` happens exactly once. From then on the driver
holds a value, not a name: the reference capture runs in-process from that
buffer, and the port's runs by piping the same buffer to `own-shadow-engine` on
stdin. There is no code path that re-reads the file, and no engine that could —
the adapter takes no arguments (owner decision R-1). #260 forbids running the
extractor twice because frontend nondeterminism would contaminate the
comparison; the same reasoning forbids a second *read*, which is why the
artifact then attests it: `input.raw` carries the bytes, every engine entry
carries `consumed`, and a `consumed` that is not `input.raw`'s identity fails
verification (owner decision B-2).

The order below is adversarial on purpose. The port runs FIRST, then the
reference: if anything in this driver re-read the file, a change to it between
the two would show up as a `consumed` mismatch rather than passing unnoticed.
A control drives exactly that, with a stand-in engine that rewrites the input
while it runs.

## The outcomes, and why "not comparable" is not "fine"

| exit | outcome | what it means |
|---|---|---|
| 0 | `agreed` | every layer agrees or is a declared boundary, and the |
|   |   | derived surface is `equal` or `not-comparable` |
| 1 | `diverged` | an acceptance-`unexplained` observation, or a |
|   |   | `renderer-only divergence` |
| 2 | `execution-failure` | an engine crashed, timed out, or exited non-zero. |
|   |   | Never a refusal, never a fallback (owner decision R-2) |
| 3 | `input-refused` | the bytes are not a nameable document, and BOTH |
|   |   | engines say so |
| 4 | `input-disagreement` | one engine names the input and the other does |
|   |   | not — a **domain decision for the owner**, not a result |
| 5 | `usage` | the driver was invoked wrongly, or its own invariants broke |

`input-disagreement` is the one that must never be quietly filed under
something else. Two readers disagreeing about whether a byte sequence is a
document is the shape owner decision D-2 records for `-0`, and this driver
stops and reports rather than picking a side.

## What is written, and where

Nothing, on agreement — a driver that wrote an artifact per green run would
bury the one that matters. On divergence, the artifact and the reduction go to
`--out`. On an execution failure, a **failure report** goes there instead: raw
input, engine id, exit code, signal, timeout flag and stderr (owner decision
R-2 — that information belongs in a failure report, not in a reproduction
artifact, because there is no reproduction).

Run:  python scripts/shadow_compare.py --engine compare <file>
      python scripts/shadow_compare.py --engine python <file>
      python scripts/shadow_compare.py --engine rust   <file>
      python scripts/shadow_compare.py --engine compare --corpus   (every committed document)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ownlang.repro import (
    ACCEPTANCE_UNEXPLAINED,
    DERIVED_RENDERER_ONLY,
    ENGINE_PYTHON,
    ENGINE_RUST,
    ReproError,
    capture,
    derived_outcome,
    encode_raw,
    hash_bytes,
    project_repro,
    project_traces,
    reduce_traces,
    verify_repro,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The adapter protocol version this driver speaks (owner decision R-1). A
# mismatch is refused rather than read around: an envelope whose shape has
# changed is not a capture this driver knows how to place in an artifact.
ADAPTER_PROTOCOL = 1

# Where the port's adapter is looked for, in order, when `--engine-binary` is
# not given. A fixed, short list that is REPORTED in the result rather than
# guessed at: "which binary did this run actually use" is part of what a
# recorded comparison means.
ENGINE_BINARY_ENV = "OWN_SHADOW_ENGINE"
ENGINE_BINARY_CANDIDATES = (
    os.path.join(ROOT, "rust", "target", "release", "own-shadow-engine"),
    os.path.join(ROOT, "rust", "target", "debug", "own-shadow-engine"),
)

OUTCOME_AGREED = "agreed"
OUTCOME_DIVERGED = "diverged"
OUTCOME_EXECUTION_FAILURE = "execution-failure"
OUTCOME_INPUT_REFUSED = "input-refused"
OUTCOME_INPUT_DISAGREEMENT = "input-disagreement"

EXIT = {
    OUTCOME_AGREED: 0,
    OUTCOME_DIVERGED: 1,
    OUTCOME_EXECUTION_FAILURE: 2,
    OUTCOME_INPUT_REFUSED: 3,
    OUTCOME_INPUT_DISAGREEMENT: 4,
}
EXIT_USAGE = 5

DEFAULT_TIMEOUT_SECONDS = 120.0


class ExecutionFailure(Exception):
    """An engine crashed, timed out or exited non-zero (owner decision R-2).

    Deliberately its own exception rather than a status value: a run-level hard
    failure must not be able to travel through the same channel a layer refusal
    does, or the two eventually get handled by one `if`."""

    def __init__(self, report: dict[str, Any]) -> None:
        super().__init__(report.get("detail", "execution failure"))
        self.report = report


def resolve_engine_binary(explicit: str | None) -> str:
    """The adapter to run, and it is an error not to find one.

    No fallback to anything (owner decision R-2): a driver that quietly ran
    without the port, or that substituted the reference's answer, would report
    agreement it never measured."""
    if explicit:
        return explicit
    from_env = os.environ.get(ENGINE_BINARY_ENV)
    if from_env:
        return from_env
    for candidate in ENGINE_BINARY_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise SystemExit(
        f"no own-shadow-engine binary found. Build it "
        f"(cd rust && cargo build -p own-shadow --bin own-shadow-engine), pass "
        f"--engine-binary, or set {ENGINE_BINARY_ENV}. This driver does not "
        f"fall back to the reference's answer: a comparison with one engine is "
        f"not a comparison.")


def read_once(path: str) -> bytes:
    """The **only** read of the input in this program.

    Binary, because #260's invariant is byte-level and a text-mode read
    translates CRLF to LF on the way in — it would normalize away the exact
    difference `input.raw` exists to attest, before anything could see it."""
    with open(path, "rb") as f:
        return f.read()


def run_port(raw: bytes, binary: str, timeout: float) -> dict[str, Any]:
    """Pipe the captured bytes to the port's adapter and read back its capture.

    Every way this can go wrong is a **run-level hard failure** and raises
    (owner decision R-2): a crash, a signal, a timeout, a non-zero exit, output
    that is not JSON, or an envelope this driver does not speak. None of them
    is a layer refusal, and none of them may be replaced by the reference's
    result."""
    def failure(detail: str, **extra: Any) -> ExecutionFailure:
        return ExecutionFailure({
            "engine": ENGINE_RUST, "binary": binary, "detail": detail,
            "exit_code": None, "signal": None, "timed_out": False,
            "timeout_seconds": timeout, "stderr": "", **extra})

    try:
        completed = subprocess.run(
            [binary], input=raw, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as e:
        raise failure(
            f"the port's adapter did not finish within {timeout}s",
            timed_out=True,
            stderr=_text(e.stderr)) from e
    except OSError as e:
        raise failure(f"the port's adapter could not be run: {e}") from e
    stderr = _text(completed.stderr)
    if completed.returncode != 0:
        # A negative return code is a signal on POSIX. Recorded as a signal
        # rather than folded into the exit code, because "killed by SIGSEGV"
        # and "exited 11" are different events and only one of them is a crash.
        signal = -completed.returncode if completed.returncode < 0 else None
        raise failure(
            f"the port's adapter exited {completed.returncode}",
            exit_code=completed.returncode, signal=signal, stderr=stderr)
    try:
        envelope = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise failure(
            f"the port's adapter wrote something that is not a JSON capture: {e}",
            stderr=stderr) from e
    if envelope.get("own_shadow_engine") != ADAPTER_PROTOCOL:
        raise failure(
            f"the port's adapter speaks protocol "
            f"{envelope.get('own_shadow_engine')!r}, this driver speaks "
            f"{ADAPTER_PROTOCOL} — rebuild it rather than reading around the "
            f"difference",
            stderr=stderr)
    return {"envelope": envelope, "stderr": stderr}


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_reference(raw: bytes) -> dict[str, Any]:
    """The reference capture, in-process, from the SAME buffer.

    In-process rather than through a subprocess because there is no second
    implementation to isolate: this driver and the reference engine are the
    same program. It gets the bytes, not the path, for the same reason the
    adapter does."""
    try:
        entry = capture(raw)
    except ReproError as e:
        return {"entry": None, "canonical_error": str(e)}
    except json.JSONDecodeError as e:
        return {"entry": None, "canonical_error": str(e)}
    return {"entry": entry, "canonical_error": None}


def compare(raw: bytes, source: str, binary: str,
            timeout: float) -> tuple[str, dict[str, Any]]:
    """One byte sequence through both engines, and the verdict about them.

    Returns `(outcome, result)`; `result` is what `--out` writes and what the
    caller prints. Raises nothing for a divergence — a divergence is a result.
    """
    identity = hash_bytes(raw)
    result: dict[str, Any] = {
        "shadow_compare_version": 1,
        "source": source,
        "input": {"raw": identity},
        "engine_binary": binary,
    }
    # The PORT first, then the reference. Adversarial on purpose: if anything
    # in this driver re-read the file, an input that changed between the two
    # runs would show up as a `consumed` mismatch instead of passing unnoticed.
    port = run_port(raw, binary, timeout)
    envelope = port["envelope"]
    reference = run_reference(raw)

    port_names_it = envelope.get("canonical_error") is None
    reference_names_it = reference["canonical_error"] is None
    if port_names_it != reference_names_it:
        result["outcome"] = OUTCOME_INPUT_DISAGREEMENT
        result["detail"] = (
            "the two engines DISAGREE about whether these bytes are a document "
            "at all. That is a domain decision for the repository owner (the "
            "shape owner decision D-2 records for '-0'), not a comparison "
            "result — stop and report it.")
        result["engines"] = {
            ENGINE_PYTHON: {"names_the_input": reference_names_it,
                            "error": reference["canonical_error"]},
            ENGINE_RUST: {"names_the_input": port_names_it,
                          "error": envelope.get("canonical_error")},
        }
        return OUTCOME_INPUT_DISAGREEMENT, result
    if not port_names_it:
        result["outcome"] = OUTCOME_INPUT_REFUSED
        result["detail"] = ("neither engine can name these bytes as a document, "
                            "so there is nothing to compare. A negative control, "
                            "not a divergence.")
        result["input"]["raw"] = encode_raw(raw)
        result["engines"] = {
            ENGINE_PYTHON: {"error": reference["canonical_error"]},
            ENGINE_RUST: {"error": envelope.get("canonical_error")},
        }
        return OUTCOME_INPUT_REFUSED, result

    # Both engines name the input, and they must name it the SAME. This is the
    # port's independent derivation, taken with zero Python — without it the
    # driver would be taking the reference's word for what the document is.
    artifact = project_repro(raw, [envelope["engine"]])
    problems = verify_repro(artifact)
    port_canonical = envelope.get("canonical")
    if port_canonical != artifact["input"]["canonical"]:
        problems.append(
            f"the port names this input {port_canonical}, the reference names it "
            f"{artifact['input']['canonical']} — the two engines derived "
            f"different canonical identities from one byte sequence")
    if problems:
        result["outcome"] = OUTCOME_DIVERGED
        # The first problem rides in `detail` rather than only in the written
        # report: a gate whose console line says "does not verify" makes a
        # reader open a file to learn which of eight links broke, and the link
        # is the finding.
        result["detail"] = (f"the assembled artifact does not verify: "
                            f"{problems[0]}"
                            + (f" (+{len(problems) - 1} more)"
                               if len(problems) > 1 else ""))
        result["problems"] = problems
        result["artifact"] = artifact
        return OUTCOME_DIVERGED, result

    traces = project_traces(artifact, source)
    reduction = reduce_traces(traces)
    derived = derived_outcome(artifact, reduction)
    unexplained = [o for o in reduction["observations"]
                   if o["acceptance"] == ACCEPTANCE_UNEXPLAINED]
    result["reduction"] = {
        "outcome": reduction["outcome"],
        "classification": reduction["classification"],
        "first": reduction["first"],
    }
    result["derived"] = derived
    if unexplained or derived["outcome"] == DERIVED_RENDERER_ONLY:
        result["outcome"] = OUTCOME_DIVERGED
        result["detail"] = (
            f"{len(unexplained)} acceptance-unexplained observation(s); derived "
            f"surface: {derived['outcome']}")
        # The full reproduction, and — only here — the full derived documents.
        result["artifact"] = _with_derived_documents(artifact, envelope, raw)
        result["reduction_full"] = reduction
        return OUTCOME_DIVERGED, result
    result["outcome"] = OUTCOME_AGREED
    result["detail"] = None
    return OUTCOME_AGREED, result


def _with_derived_documents(artifact: dict[str, Any], envelope: dict[str, Any],
                            raw: bytes) -> dict[str, Any]:
    """The artifact with both engines' full derived surfaces attached.

    Written on MISMATCH only (owner decision D-6). The port's comes back from
    the adapter's envelope — asking for it by re-invoking the adapter would be
    a second execution of the thing whose single execution is the point — and
    the reference's is re-rendered here from the verdict layer the artifact
    already carries."""
    from ownlang.repro import derived_sarif_document

    documents: dict[str, Any] = {}
    port_documents = envelope.get("derived_documents")
    if isinstance(port_documents, dict):
        documents[ENGINE_RUST] = port_documents
    reference = next((e for e in artifact["engines"]
                      if e["id"] == ENGINE_PYTHON), None)
    if reference is not None:
        verdicts = next((lyr for lyr in reference["layers"]
                         if lyr["layer"] == "verdicts"), None)
        if verdicts is not None:
            surface = ({"error": verdicts.get("error")}
                       if verdicts["status"] == "refused"
                       else verdicts.get("document", {}))
            document = derived_sarif_document(surface)
            if document is not None:
                documents[ENGINE_PYTHON] = {"sarif": document}
    del raw
    if not documents:
        return artifact
    out = dict(artifact)
    out["derived_documents"] = documents
    return out


def _render(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _write(out_dir: str | None, name: str, value: Any) -> str | None:
    if out_dir is None:
        return None
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_render(value))
    return path


def _safe_name(source: str) -> str:
    """A filename derived from the source path — flattened, not basenamed, so
    two corpus documents with the same basename cannot overwrite each other's
    report."""
    cleaned = source.replace(os.sep, "_").replace("/", "_").replace(":", "_")
    return cleaned.lstrip("._") or "input"


def _corpus() -> list[str]:
    """Every committed facts document, in a fixed order — the same sweep
    `tests/test_repro_fixtures.py` uses, read from the same directories, so the
    gate and the fixture family cannot disagree about what "the corpus" is."""
    out: list[str] = []
    for corpus in ("ownir", "lowered", "summaries", "verdicts", "repro"):
        directory = os.path.join(ROOT, "tests", "fixtures", corpus)
        if not os.path.isdir(directory):
            continue
        out += [os.path.join(directory, name) for name in sorted(os.listdir(directory))
                if name.endswith(".facts.json")]
    return out


def _domain_refusal_names() -> set[str]:
    """The documents the repro ledger declares unnameable by BOTH engines.

    They are swept out of the positive corpus and run as negative controls
    instead: a gate that counted them as failures would be red for the one
    thing it is supposed to prove."""
    path = os.path.join(ROOT, "tests", "fixtures", "repro", "manifest.json")
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    return {e["name"] for e in manifest.get("domain_refusals", [])
            if isinstance(e.get("name"), str)}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="shadow_compare",
        description="Run one OwnIR byte sequence through both engines (dev only).")
    parser.add_argument("path", nargs="?", help="the facts document to compare")
    parser.add_argument("--engine", choices=("python", "rust", "compare"),
                        default="compare")
    parser.add_argument("--corpus", action="store_true",
                        help="compare over every committed facts document")
    parser.add_argument("--engine-binary", default=None,
                        help="the own-shadow-engine adapter to run")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        help="hard timeout per adapter run, in seconds")
    parser.add_argument("--out", default=None,
                        help="directory for artifacts, reductions and failure "
                             "reports (written on divergence or failure only)")
    parser.add_argument("--quiet", action="store_true",
                        help="print one line per case instead of the full result")
    args = parser.parse_args(argv)

    if args.corpus == bool(args.path):
        print("shadow_compare: give exactly one of <path> or --corpus",
              file=sys.stderr)
        return EXIT_USAGE

    if args.engine == "python":
        if args.path is None:
            print("shadow_compare: --engine python takes a path", file=sys.stderr)
            return EXIT_USAGE
        reference = run_reference(read_once(args.path))
        if reference["entry"] is None:
            print(f"shadow_compare: the reference cannot name this input: "
                  f"{reference['canonical_error']}", file=sys.stderr)
            return EXIT[OUTCOME_INPUT_REFUSED]
        sys.stdout.write(_render(reference["entry"]))
        return 0

    binary = resolve_engine_binary(args.engine_binary)

    if args.engine == "rust":
        if args.path is None:
            print("shadow_compare: --engine rust takes a path", file=sys.stderr)
            return EXIT_USAGE
        try:
            port = run_port(read_once(args.path), binary, args.timeout)
        except ExecutionFailure as e:
            print(f"shadow_compare: {e.report['detail']}", file=sys.stderr)
            if e.report.get("stderr"):
                print(e.report["stderr"], file=sys.stderr, end="")
            return EXIT[OUTCOME_EXECUTION_FAILURE]
        sys.stdout.write(_render(port["envelope"]["engine"]))
        return 0

    refusals = _domain_refusal_names()
    paths = _corpus() if args.corpus else [args.path]
    worst = 0
    tally: dict[str, int] = {}
    for path in paths:
        source = os.path.relpath(path, ROOT).replace(os.sep, "/")
        stem = os.path.basename(path)[: -len(".facts.json")]
        raw = read_once(path)
        try:
            outcome, result = compare(raw, source, binary, args.timeout)
        except ExecutionFailure as e:
            report = dict(e.report)
            report["shadow_compare_version"] = 1
            report["outcome"] = OUTCOME_EXECUTION_FAILURE
            report["source"] = source
            # The raw input rides in the FAILURE REPORT, never in a reproduction
            # artifact (owner decision R-2): there is no reproduction, because
            # no capture was produced.
            report["input"] = {"raw": encode_raw(raw)}
            written = _write(args.out, f"{_safe_name(source)}.failure.json", report)
            print(f"FAIL[execution] {source}: {report['detail']}"
                  + (f" (report: {written})" if written else ""), file=sys.stderr)
            if report.get("stderr"):
                print(report["stderr"], file=sys.stderr, end="")
            tally[OUTCOME_EXECUTION_FAILURE] = tally.get(
                OUTCOME_EXECUTION_FAILURE, 0) + 1
            worst = max(worst, EXIT[OUTCOME_EXECUTION_FAILURE])
            continue

        # A document the ledger declares unnameable by both engines is expected
        # to be refused; anything else there is the finding.
        if stem in refusals:
            if outcome == OUTCOME_INPUT_REFUSED:
                outcome = OUTCOME_AGREED
                result["outcome"] = OUTCOME_AGREED
                result["detail"] = ("a declared domain refusal: both engines "
                                    "refuse to name it, which is the control")
            else:
                result["detail"] = (
                    f"{result.get('detail')} — and this document is a DECLARED "
                    f"domain refusal, so anything but a refusal is the finding")
                outcome = OUTCOME_DIVERGED
                result["outcome"] = OUTCOME_DIVERGED

        tally[outcome] = tally.get(outcome, 0) + 1
        worst = max(worst, EXIT[outcome])
        if outcome != OUTCOME_AGREED:
            written = _write(args.out, f"{_safe_name(source)}.compare.json", result)
            print(f"FAIL[{outcome}] {source}: {result.get('detail')}"
                  + (f" (report: {written})" if written else ""), file=sys.stderr)
        elif not args.quiet and not args.corpus:
            sys.stdout.write(_render(result))
        elif args.corpus and not args.quiet:
            print(f"ok {source}: {result['reduction']['outcome']} / "
                  f"{result['derived']['outcome']}"
                  if "reduction" in result else f"ok {source}: {result['detail']}")
    if args.corpus or args.quiet:
        print(f"shadow compare over {len(paths)} document(s): "
              + ", ".join(f"{n} {name}" for name, n in sorted(tally.items())))
    return worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
