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

A `--manifest` run is the exception, and deliberately so: it *is* the record,
so every document's result is written, plus one run summary. An artifact is
still written only on mismatch.

## Which adapter ran, said in a way a stale build cannot fake

Every recorded comparison and every failure report names the adapter by
`sha256` and byte length as well as by path, computed from the file this run
actually executed. A path is not an identity: `rust/target/release/own-shadow-
engine` is a different program on Tuesday, and a run that reported agreement
against yesterday's build reported agreement about yesterday. The digest is
taken here rather than by the caller for the same reason `consumed` is taken by
each engine — an identity somebody else supplies is a claim, not a measurement.

## The empty set is not agreement

A run that compared **zero** documents FAILS, and so does a target whose
compare-attempted count is zero. #250's fifth failure mode is that a green gate
over an empty set is worse than a red one, because a red one at least says it
is awake; a repository is not covered because its extraction succeeded, and a
solution is not covered because some project inside it emitted OwnIR. The
denominators are therefore part of what a run reports, per target and in total.

Run:  python scripts/shadow_compare.py --engine compare <file>
      python scripts/shadow_compare.py --engine python <file>
      python scripts/shadow_compare.py --engine rust   <file>
      python scripts/shadow_compare.py --engine compare --corpus   (every committed document)
      python scripts/shadow_compare.py --engine compare --manifest <manifest.json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ownlang.repro import (
    ACCEPTANCE_DECLARED,
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

# The shape of the documents this driver writes. 1 → 2 adds the adapter's
# identity (`engine_binary_sha256` / `engine_binary_bytes`) to every result and
# every failure report, and the manifest run's summary. The ARTIFACT format
# (`REPRO_VERSION`) is a different number and is not touched.
SHADOW_COMPARE_VERSION = 2

# The manifest schema this driver speaks. A manifest is provenance as well as a
# work list: each entry says which target and which commit the document came
# from, by which extraction mode and command, and what its bytes hash to.
MANIFEST_SCHEMA = 1
MANIFEST_FIELDS = ("source", "target", "target_commit", "extraction_mode",
                   "extraction_command", "facts_sha256")

# Where the port's adapter is looked for, in order, when `--engine-binary` is
# not given. A fixed, short list that is REPORTED in the result rather than
# guessed at: "which binary did this run actually use" is part of what a
# recorded comparison means — and since v2 it is reported by DIGEST, so a
# candidate that resolves to a stale build can no longer stand in unnoticed.
# The `.exe` spellings are here because without them the whole list names files
# that cannot exist on Windows, which is not a safer default, only a quieter
# one.
ENGINE_BINARY_ENV = "OWN_SHADOW_ENGINE"
ENGINE_BINARY_CANDIDATES = (
    os.path.join(ROOT, "rust", "target", "release", "own-shadow-engine"),
    os.path.join(ROOT, "rust", "target", "release", "own-shadow-engine.exe"),
    os.path.join(ROOT, "rust", "target", "debug", "own-shadow-engine"),
    os.path.join(ROOT, "rust", "target", "debug", "own-shadow-engine.exe"),
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


def engine_identity(binary: str) -> dict[str, Any]:
    """The adapter, named by digest and length as well as by path.

    Taken from the file this run is about to execute, in this program, rather
    than accepted from whoever invoked it: an identity somebody else supplies
    is a claim. A path that cannot be read is a usage error and not a run — a
    driver that could not say WHICH engine it ran should not be reporting what
    that engine said."""
    try:
        with open(binary, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise SystemExit(
            f"shadow_compare: cannot read the adapter at {binary!r} to name it "
            f"({e}). A recorded comparison names the engine by sha256, not only "
            f"by path, so an adapter this driver cannot hash is one it must not "
            f"run.") from e
    return {"path": binary, "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw)}


def read_once(path: str) -> bytes:
    """The **only** read of the input in this program.

    Binary, because #260's invariant is byte-level and a text-mode read
    translates CRLF to LF on the way in — it would normalize away the exact
    difference `input.raw` exists to attest, before anything could see it."""
    with open(path, "rb") as f:
        return f.read()


def _source_label(path: str) -> str:
    """The name a result records for an input.

    Repository-relative when the input is inside the repository, and the
    absolute path otherwise. It used to be `os.path.relpath` unconditionally,
    which RAISES on Windows for a path on another drive — the sweep's facts
    documents live outside the checkout, so the driver crashed on the first one
    before either engine ran. A label is not worth an exception."""
    try:
        rel = os.path.relpath(path, ROOT)
    except ValueError:
        return os.path.abspath(path).replace(os.sep, "/")
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return os.path.abspath(path).replace(os.sep, "/")
    return rel.replace(os.sep, "/")


def _spawn(binary: str, raw: bytes, timeout: float
           ) -> tuple[bytes, bytes, int, bool]:
    """Run the adapter over `raw` and come back within `timeout`, always.

    `subprocess.run(timeout=…)` is not enough, and the timeout control is what
    said so: it kills the CHILD and then waits for the pipes to close, so any
    grandchild still holding them keeps the driver blocked — a timeout that
    never returns is not a timeout, and owner decision R-2 makes a timeout a
    run-level hard failure the driver has to *report*. So the child gets its own
    process group (POSIX) or is killed as a tree (Windows).

    The real adapter starts nothing, which is exactly why this had never been
    hit: the property is about what the driver guarantees, not about what
    today's adapter happens to do."""
    process = subprocess.Popen(
        [binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name != "nt"))
    try:
        stdout, stderr = process.communicate(input=raw, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - the pipes are gone
            stdout, stderr = b"", b""
        return stdout, stderr, process.returncode or 0, True
    return stdout, stderr, process.returncode, False


def _kill_tree(process: subprocess.Popen[bytes]) -> None:
    """The adapter and everything it started, on both platforms."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       capture_output=True, check=False)
    else:
        import signal as _signal
        try:
            os.killpg(os.getpgid(process.pid), _signal.SIGKILL)
        except OSError:
            pass
    process.kill()


def run_port(raw: bytes, adapter: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Pipe the captured bytes to the port's adapter and read back its capture.

    Every way this can go wrong is a **run-level hard failure** and raises
    (owner decision R-2): a crash, a signal, a timeout, a non-zero exit, output
    that is not JSON, or an envelope this driver does not speak. None of them
    is a layer refusal, and none of them may be replaced by the reference's
    result."""
    binary = str(adapter["path"])

    def failure(detail: str, **extra: Any) -> ExecutionFailure:
        return ExecutionFailure({
            "engine": ENGINE_RUST, "binary": binary,
            "engine_binary_sha256": adapter["sha256"],
            "engine_binary_bytes": adapter["bytes"],
            "detail": detail,
            "exit_code": None, "signal": None, "timed_out": False,
            "timeout_seconds": timeout, "stderr": "", **extra})

    try:
        stdout, stderr_raw, code, timed_out = _spawn(binary, raw, timeout)
    except OSError as e:
        raise failure(f"the port's adapter could not be run: {e}") from e
    if timed_out:
        raise failure(
            f"the port's adapter did not finish within {timeout}s",
            timed_out=True,
            stderr=_text(stderr_raw))
    stderr = _text(stderr_raw)
    if code != 0:
        # A negative return code is a signal on POSIX. Recorded as a signal
        # rather than folded into the exit code, because "killed by SIGSEGV"
        # and "exited 11" are different events and only one of them is a crash.
        signal = -code if code < 0 else None
        raise failure(
            f"the port's adapter exited {code}",
            exit_code=code, signal=signal, stderr=stderr)
    try:
        envelope = json.loads(stdout.decode("utf-8"))
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


def compare(raw: bytes, source: str, adapter: dict[str, Any],
            timeout: float) -> tuple[str, dict[str, Any]]:
    """One byte sequence through both engines, and the verdict about them.

    Returns `(outcome, result)`; `result` is what `--out` writes and what the
    caller prints. Raises nothing for a divergence — a divergence is a result.
    """
    identity = hash_bytes(raw)
    result: dict[str, Any] = {
        "shadow_compare_version": SHADOW_COMPARE_VERSION,
        "source": source,
        "input": {"raw": identity},
        "engine_binary": adapter["path"],
        "engine_binary_sha256": adapter["sha256"],
        "engine_binary_bytes": adapter["bytes"],
        "timeout_seconds": timeout,
    }
    # The PORT first, then the reference. Adversarial on purpose: if anything
    # in this driver re-read the file, an input that changed between the two
    # runs would show up as a `consumed` mismatch instead of passing unnoticed.
    port = run_port(raw, adapter, timeout)
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

    # Both engines derived this identity from the same bytes, independently,
    # and the check above is what proved they agree about it. Recording it here
    # rather than only inside the artifact matters because the artifact is
    # written on MISMATCH only: without this line a green run would name the
    # bytes it compared and not the document they are.
    result["input"]["canonical"] = artifact["input"]["canonical"]

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


# --- the manifest run -----------------------------------------------------


@dataclass(frozen=True)
class Document:
    """One document of a manifest run: what to compare, and where it came from.

    `source` is both the file to read and the label the result records. One
    field rather than two on purpose — a record whose label can drift from the
    file it names is a record that can attribute a result to the wrong
    document. `id` is the document's name in the sweep's definition and in the
    aggregation; it defaults to the file's basename, which is enough for a
    hand run and not enough for CI, where every leg writes `facts.json`."""

    id: str
    source: str
    path: str
    target: str
    target_commit: str
    extraction_mode: str
    extraction_command: str
    facts_sha256: str
    timeout_seconds: float


def load_manifest(path: str, default_timeout: float
                  ) -> tuple[list[Document], list[str]]:
    """The work list, with its provenance, and the targets it claims to cover.

    Every document field is required. A relative `source` resolves against the
    MANIFEST's directory, not the process's, so a manifest and the documents it
    names travel together.

    The optional top-level `targets` is what makes "a target this run did not
    reach" *representable*: without it every target in the summary is one some
    document already named, so a skipped target would silently not appear
    rather than appear at zero. When it is given it is the authority — a
    document naming a target it does not list is a manifest error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"shadow_compare: cannot read the manifest {path!r}: {e}") from e
    if not isinstance(data, dict):
        raise SystemExit(f"shadow_compare: {path}: a manifest is a JSON object")
    if data.get("schema") != MANIFEST_SCHEMA:
        raise SystemExit(
            f"shadow_compare: {path}: manifest schema {data.get('schema')!r}, this "
            f"driver speaks {MANIFEST_SCHEMA} — regenerate it rather than reading "
            f"around the difference")
    entries = data.get("documents")
    if not isinstance(entries, list):
        raise SystemExit(f"shadow_compare: {path}: 'documents' must be a list")
    declared = data.get("targets", [])
    if not isinstance(declared, list) or not all(
            isinstance(t, str) and t for t in declared):
        raise SystemExit(
            f"shadow_compare: {path}: 'targets' must be a list of non-empty "
            f"strings when it is given")
    base = os.path.dirname(os.path.abspath(path))
    out: list[Document] = []
    for i, entry in enumerate(entries):
        where = f"{path}: documents[{i}]"
        if not isinstance(entry, dict):
            raise SystemExit(f"shadow_compare: {where}: must be an object")
        missing = [name for name in MANIFEST_FIELDS
                   if not isinstance(entry.get(name), str) or not entry[name]]
        if missing:
            raise SystemExit(
                f"shadow_compare: {where}: missing or empty {', '.join(missing)}. "
                f"A manifest entry is the document's provenance; a run that cannot "
                f"say which target and commit a document came from is not a record.")
        timeout = entry.get("timeout_seconds", default_timeout)
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise SystemExit(
                f"shadow_compare: {where}: 'timeout_seconds' must be a positive "
                f"number (it is recorded per document, never inherited silently)")
        source = str(entry["source"])
        doc_id = entry.get("id") or os.path.basename(source)
        if not isinstance(doc_id, str) or not doc_id:
            raise SystemExit(
                f"shadow_compare: {where}: 'id' must be a non-empty string")
        out.append(Document(
            id=doc_id,
            source=source,
            path=source if os.path.isabs(source) else os.path.join(base, source),
            target=str(entry["target"]),
            target_commit=str(entry["target_commit"]),
            extraction_mode=str(entry["extraction_mode"]),
            extraction_command=str(entry["extraction_command"]),
            facts_sha256=str(entry["facts_sha256"]),
            timeout_seconds=float(timeout)))
    seen: set[str] = set()
    for doc in out:
        if doc.id in seen:
            raise SystemExit(
                f"shadow_compare: {path}: two documents share the id {doc.id!r}. "
                f"The id is how a document is joined to the sweep definition and "
                f"to its own result, so two of them is one document lost.")
        seen.add(doc.id)
    if declared:
        stray = sorted({d.target for d in out} - set(declared))
        if stray:
            raise SystemExit(
                f"shadow_compare: {path}: documents name target(s) "
                f"{', '.join(stray)} that 'targets' does not declare — the "
                f"declared list is the denominator, so it may not be a subset "
                f"of what happened to be measured")
    return out, [str(t) for t in declared]


def read_and_verify(documents: list[Document]) -> tuple[list[bytes], list[str]]:
    """Every document read ONCE, hashed, and checked — before any engine runs.

    Reading first and hashing the buffer is deliberate, and it is stronger than
    hashing the file and then reading it: there is no window between the check
    and the use in which the file could change, and the bytes the engines
    receive are the very bytes that were verified. It also keeps the one-read
    invariant intact, which a separate hashing pass would not.

    Every problem is collected rather than raised at the first: a manifest with
    two stale digests should say so once."""
    buffers: list[bytes] = []
    problems: list[str] = []
    for doc in documents:
        try:
            raw = read_once(doc.path)
        except OSError as e:
            buffers.append(b"")
            problems.append(f"{doc.source}: cannot be read ({e})")
            continue
        buffers.append(raw)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != doc.facts_sha256:
            problems.append(
                f"{doc.source}: the manifest says the extracted document hashes to "
                f"{doc.facts_sha256}, the file hashes to {digest} — this is not "
                f"the document that was extracted, and no engine may see it")
    return buffers, problems


def _zeroed_target(target: str, extracted: int) -> dict[str, Any]:
    return {"target": target, "documents_extracted": extracted,
            "compare_attempted": 0, "agreed": 0, "diverged": 0,
            "execution_failures": 0, "input_refusals": 0,
            "input_disagreements": 0,
            "declared_boundary_observations": 0,
            "acceptance_unexplained_observations": 0}


_TALLY_FIELD = {
    OUTCOME_AGREED: "agreed",
    OUTCOME_DIVERGED: "diverged",
    OUTCOME_EXECUTION_FAILURE: "execution_failures",
    OUTCOME_INPUT_REFUSED: "input_refusals",
    OUTCOME_INPUT_DISAGREEMENT: "input_disagreements",
}
_SUMMED = ("documents_extracted", "compare_attempted", "agreed", "diverged",
           "execution_failures", "input_refusals", "input_disagreements",
           "declared_boundary_observations",
           "acceptance_unexplained_observations")


def _own_net_commit() -> str | None:
    """The commit this driver ran from, for the record. `None` outside a
    checkout — a missing provenance line is better than an invented one."""
    try:
        out = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="shadow_compare",
        description="Run one OwnIR byte sequence through both engines (dev only).")
    parser.add_argument("path", nargs="?", help="the facts document to compare")
    parser.add_argument("--engine", choices=("python", "rust", "compare"),
                        default="compare")
    parser.add_argument("--corpus", action="store_true",
                        help="compare over every committed facts document")
    parser.add_argument("--manifest", default=None,
                        help="a JSON manifest of documents with their provenance "
                             "(target, commit, extraction mode and command, "
                             "facts_sha256, and the targets the run claims to "
                             "cover); writes one result per document plus a run "
                             "summary")
    parser.add_argument("--engine-binary", default=None,
                        help="the own-shadow-engine adapter to run")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        help="hard timeout per adapter run, in seconds; a "
                             "manifest entry may name its own")
    parser.add_argument("--out", default=None,
                        help="directory for artifacts, reductions and failure "
                             "reports (written on divergence or failure only; a "
                             "--manifest run also writes every result and the "
                             "run summary)")
    parser.add_argument("--quiet", action="store_true",
                        help="print one line per case instead of the full result")
    args = parser.parse_args(argv)

    chosen = [name for name, given in (("<path>", bool(args.path)),
                                       ("--corpus", args.corpus),
                                       ("--manifest", args.manifest is not None))
              if given]
    if len(chosen) != 1:
        print("shadow_compare: give exactly one of <path>, --corpus or "
              "--manifest" + (f" (got {', '.join(chosen)})" if chosen else ""),
              file=sys.stderr)
        return EXIT_USAGE
    if args.manifest is not None and args.engine != "compare":
        print("shadow_compare: --manifest is a compare-mode run; --engine "
              "python and --engine rust take one path", file=sys.stderr)
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

    adapter = engine_identity(resolve_engine_binary(args.engine_binary))

    if args.engine == "rust":
        if args.path is None:
            print("shadow_compare: --engine rust takes a path", file=sys.stderr)
            return EXIT_USAGE
        try:
            port = run_port(read_once(args.path), adapter, args.timeout)
        except ExecutionFailure as e:
            print(f"shadow_compare: {e.report['detail']}", file=sys.stderr)
            if e.report.get("stderr"):
                print(e.report["stderr"], file=sys.stderr, end="")
            return EXIT[OUTCOME_EXECUTION_FAILURE]
        sys.stdout.write(_render(port["envelope"]["engine"]))
        return 0

    if args.manifest is not None:
        return _run_manifest(args, adapter)
    return _run_paths(args, adapter)


def _one(raw: bytes, source: str, adapter: dict[str, Any], timeout: float,
         refusals: set[str], out_dir: str | None,
         ) -> tuple[str, dict[str, Any], float]:
    """One document, end to end: compare, classify, report, time it.

    Shared by both run shapes so that the corpus gate and the sweep cannot
    develop two readings of one outcome."""
    stem = os.path.basename(source)
    stem = stem[: -len(".facts.json")] if stem.endswith(".facts.json") else stem
    started = time.monotonic()
    try:
        outcome, result = compare(raw, source, adapter, timeout)
    except ExecutionFailure as e:
        elapsed = time.monotonic() - started
        report = dict(e.report)
        report["shadow_compare_version"] = SHADOW_COMPARE_VERSION
        report["outcome"] = OUTCOME_EXECUTION_FAILURE
        report["source"] = source
        report["wall_clock_seconds"] = round(elapsed, 3)
        # The raw input rides in the FAILURE REPORT, never in a reproduction
        # artifact (owner decision R-2): there is no reproduction, because
        # no capture was produced.
        report["input"] = {"raw": encode_raw(raw)}
        written = _write(out_dir, f"{_safe_name(source)}.failure.json", report)
        print(f"FAIL[execution] {source}: {report['detail']}"
              + (f" (report: {written})" if written else ""), file=sys.stderr)
        if report.get("stderr"):
            print(report["stderr"], file=sys.stderr, end="")
        return OUTCOME_EXECUTION_FAILURE, report, elapsed
    elapsed = time.monotonic() - started

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
    result["wall_clock_seconds"] = round(elapsed, 3)
    if outcome != OUTCOME_AGREED:
        written = _write(out_dir, f"{_safe_name(source)}.compare.json", result)
        print(f"FAIL[{outcome}] {source}: {result.get('detail')}"
              + (f" (report: {written})" if written else ""), file=sys.stderr)
    return outcome, result, elapsed


def _run_paths(args: argparse.Namespace, adapter: dict[str, Any]) -> int:
    """`--corpus`, or one positional path."""
    refusals = _domain_refusal_names()
    paths = _corpus() if args.corpus else [args.path]
    worst = 0
    tally: dict[str, int] = {}
    for path in paths:
        source = _source_label(path)
        outcome, result, _ = _one(read_once(path), source, adapter, args.timeout,
                                  refusals, args.out)
        tally[outcome] = tally.get(outcome, 0) + 1
        worst = max(worst, EXIT[outcome])
        if outcome == OUTCOME_AGREED and not args.quiet and not args.corpus:
            sys.stdout.write(_render(result))
        elif outcome == OUTCOME_AGREED and args.corpus and not args.quiet:
            reduction = result.get("reduction")
            if reduction is None:
                print(f"ok {source}: {result['detail']}")
            else:
                print(f"ok {source}: {reduction['outcome']} / "
                      f"{result['derived']['outcome']}")
    if args.corpus or args.quiet:
        print(f"shadow compare over {len(paths)} document(s): "
              + ", ".join(f"{n} {name}" for name, n in sorted(tally.items())))
    if not paths:
        print("shadow_compare: this run compared ZERO documents, which is a "
              "failure and not agreement — a gate over an empty set is worse "
              "than a red one", file=sys.stderr)
        return EXIT_USAGE
    return worst


def _run_manifest(args: argparse.Namespace, adapter: dict[str, Any]) -> int:
    """A multi-document run with provenance, and the denominators to prove it.

    Every document is read and verified before any engine runs; then each is
    compared, each result is written, and one summary carries the per-target
    and total counts, the adapter's identity, this driver's version and the
    Own.NET commit."""
    documents, declared = load_manifest(args.manifest, args.timeout)
    buffers, problems = read_and_verify(documents)
    if not documents:
        problems.append("the manifest lists no documents, so this run compared "
                        "ZERO of them — a failure, never agreement")
    if problems:
        for p in problems:
            print(f"FAIL[manifest] {p}", file=sys.stderr)
        print("shadow_compare: no engine was run — the manifest is the record, "
              "and a record that does not describe the bytes on disk cannot be "
              "repaired by comparing them anyway", file=sys.stderr)
        return EXIT_USAGE

    refusals = _domain_refusal_names()
    per_target: dict[str, dict[str, Any]] = {
        target: _zeroed_target(target, 0) for target in declared}
    for doc in documents:
        row = per_target.setdefault(doc.target, _zeroed_target(doc.target, 0))
        row["documents_extracted"] += 1

    worst = 0
    records: list[dict[str, Any]] = []
    for doc, raw in zip(documents, buffers, strict=True):
        outcome, result, elapsed = _one(raw, doc.source, adapter,
                                        doc.timeout_seconds, refusals, args.out)
        row = per_target[doc.target]
        row["compare_attempted"] += 1
        row[_TALLY_FIELD[outcome]] += 1
        acceptance = (result.get("reduction") or {}).get(
            "classification", {}).get("by_acceptance", {})
        row["declared_boundary_observations"] += int(
            acceptance.get(ACCEPTANCE_DECLARED, 0))
        row["acceptance_unexplained_observations"] += int(
            acceptance.get(ACCEPTANCE_UNEXPLAINED, 0))
        worst = max(worst, EXIT[outcome])
        result["document_id"] = doc.id
        _write(args.out, f"{_safe_name(doc.id)}.result.json", result)
        records.append({
            "id": doc.id,
            "source": doc.source,
            "target": doc.target,
            "target_commit": doc.target_commit,
            "extraction_mode": doc.extraction_mode,
            "extraction_command": doc.extraction_command,
            "facts_sha256": doc.facts_sha256,
            "timeout_seconds": doc.timeout_seconds,
            "outcome": outcome,
            "wall_clock_seconds": round(elapsed, 3),
        })
        if not args.quiet:
            print(f"{'ok' if outcome == OUTCOME_AGREED else outcome} "
                  f"{doc.source} [{doc.target}/{doc.extraction_mode}]")

    # A target the run never reached is a FAILED target, not a passed
    # repository: extraction succeeding says nothing about a comparison.
    empty = [t for t, row in sorted(per_target.items())
             if row["compare_attempted"] == 0]
    totals = {name: sum(int(row[name]) for row in per_target.values())
              for name in _SUMMED}
    summary: dict[str, Any] = {
        "shadow_compare_version": SHADOW_COMPARE_VERSION,
        "manifest": args.manifest,
        "declared_targets": declared,
        "engine_binary": adapter["path"],
        "engine_binary_sha256": adapter["sha256"],
        "engine_binary_bytes": adapter["bytes"],
        "own_net_commit": _own_net_commit(),
        "documents": records,
        "targets": [per_target[t] for t in sorted(per_target)],
        "totals": totals,
        "targets_with_no_comparison": empty,
    }
    if empty:
        worst = max(worst, EXIT_USAGE)
        for t in empty:
            print(f"FAIL[manifest] target {t!r} had ZERO documents compared — a "
                  f"target is not covered because its extraction ran",
                  file=sys.stderr)
    # The backstop for the same rule, and it is UNREACHABLE while the check
    # above stands: an empty manifest returns before this, and a manifest with
    # documents cannot reach zero attempts. It is kept because it states the
    # rule at the place the number actually exists, and it is reachable exactly
    # when the first check is removed — which is what a mutation does. That is
    # why the control pins the FIRST check's own wording rather than the exit
    # code: two enforcement points of one rule and a control that cannot tell
    # them apart is a control that proves nothing (the shape §5.1 of the
    # acceptance note records).
    if totals["compare_attempted"] == 0:
        worst = max(worst, EXIT_USAGE)
        print("shadow_compare: the totals say ZERO documents were compared, "
              "which is a failure and not agreement", file=sys.stderr)
    summary["outcome"] = (OUTCOME_AGREED if worst == 0 else "not-agreed")
    _write(args.out, "summary.json", summary)
    print(f"shadow compare over {totals['compare_attempted']} document(s) in "
          f"{len(per_target)} target(s): {totals['agreed']} agreed, "
          f"{totals['diverged']} diverged, {totals['execution_failures']} "
          f"execution-failure, {totals['input_refusals']} input-refused, "
          f"{totals['input_disagreements']} input-disagreement; "
          f"{totals['declared_boundary_observations']} declared-boundary and "
          f"{totals['acceptance_unexplained_observations']} "
          f"acceptance-unexplained observation(s); adapter "
          f"{adapter['sha256'][:12]}")
    return worst


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
