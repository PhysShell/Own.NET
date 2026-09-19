#!/usr/bin/env python3
"""P-037 A2.1 inertness control: the guarded-fact sidecar changes NOTHING an engine says.

The A2 staging invariant (docs/notes/p037-formal-kernel.md §10.3) is that the
sidecar is validated but semantically inert through A2: the legacy `body` stays
authoritative, and neither the MOS documents nor the verdicts may move because
the sidecar is present, absent, or WRONG. This control runs that sentence.

For every shape in corpus/p037-shapes, for the relevance probe
(corpus/p037-relevance/probe) and for the repository's own samples (one Roslyn
compilation, the dogfood input), the extractor runs once and four documents are
derived from its bytes:

  emitted          the facts exactly as the extractor wrote them, sidecar and
                   the A2.2-3P orphan carrier `guarded_functions[]` included
  stripped         the same document with every `guarded_facts` and the whole
                   `guarded_functions[]` carrier removed
  orphans_stripped the same document with only the carrier removed, so the
                   carrier's own inertness is isolated from the sidecar's
  contradictory    the same document with sidecars that LIE, in `functions[]`
                   and in the carrier alike: booleans flipped, forwarded
                   parameters negated, guard predicates swapped, and one
                   fabricated guard added to every function that had none

Two more things the A2.2-3P ruling asks this control to witness: no method
identity appears both as a `functions[]` record and as an orphan (a producer
refusal, exercised here through the producer's own control knob), and the
carrier is non-vacuous over the documents it runs.

Each document goes through BOTH engines by the P-022 capture protocol
(ownlang.repro.capture for Python, the own-shadow-engine adapter for Rust); the
lowered, summaries and verdicts layers must be identical across the three
documents on each engine, and Python must equal Rust on each. A difference is a
semantic cut that began early, and the answer to that is to isolate it, never to
note that the verdicts happened to agree.

Run:  python scripts/p037_sidecar_inertness.py [--only NAME,...]
      (needs dotnet for the extractor and a built own-shadow-engine; the CI
      dogfood step builds the latter via `p037_evidence.py artifacts` first)
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import p037_evidence as ev  # noqa: E402
from shadow_compare import (  # noqa: E402
    DEFAULT_TIMEOUT_SECONDS,
    engine_identity,
    resolve_engine_binary,
    run_port,
    run_reference,
)

SHAPES = ROOT / "corpus" / "p037-shapes"
SAMPLES = ROOT / "frontend" / "roslyn" / "samples"
PROBE = ROOT / "corpus" / "p037-relevance" / "probe" / "case.cs"
# The producer refuses a run whose orphan carrier repeats a `functions[]` identity; this
# knob makes it add such an orphan on purpose (Program.cs, the P-037 A2.2-3P self-check).
REFUSAL_KNOB = ("OWN_P037_SELFCHECK_PROBE", "duplicate_identity")
LAYERS = ("lowered", "summaries", "verdicts")


def extract(inputs: list[Path], knob: tuple[str, str] | None = None) -> bytes:
    with tempfile.TemporaryDirectory(prefix="p037-inert-") as td:
        out = Path(td) / "facts.json"
        project = ROOT / "frontend" / "roslyn" / "OwnSharp.Extractor"
        cmd = ["dotnet", "run", "--project", str(project), "--",
               *(str(p) for p in inputs), "--flow-locals", "-o", str(out)]
        env = ev.sanitized_env(**dict([knob])) if knob else ev.sanitized_env()
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=ROOT,
                              env=env)
        if proc.returncode != 0 or not out.exists():
            tail = proc.stderr.strip()[-600:]
            raise RuntimeError(f"extractor failed ({proc.returncode}): {tail}")
        return out.read_bytes()


def stripped(doc: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    for fn in out.get("functions", []):
        fn.pop("guarded_facts", None)
    out.pop("guarded_functions", None)
    return out


def orphans_stripped(doc: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    out.pop("guarded_functions", None)
    return out


def contradictory(doc: dict[str, Any]) -> dict[str, Any]:
    """A sidecar that is valid vocabulary and wrong about everything it can be wrong about."""
    out = copy.deepcopy(doc)
    swap = {"truth": "not_null", "not_null": "is_null", "is_null": "truth"}
    carriers = list(out.get("functions", [])) + list(out.get("guarded_functions", []))
    for fn in carriers:
        gf = fn.get("guarded_facts")
        if not isinstance(gf, dict):
            gf = {"version": 1, "calls": [], "guards": []}
            fn["guarded_facts"] = gf
        for call in gf.get("calls", []):
            for arg in call.get("args", []):
                if arg.get("kind") == "bool_const":
                    arg["value"] = not arg["value"]
                elif arg.get("kind") == "param":
                    if arg.pop("negated", None) is None:
                        arg["negated"] = True
                elif arg.get("kind") == "var":
                    arg["kind"] = "object_creation"
                    arg.pop("name", None)
                elif arg.get("kind") == "opaque":
                    arg["kind"] = "null_literal"
        for guard in gf.get("guards", []):
            guard["predicate"] = swap[guard["predicate"]]
            guard["negated"] = not guard["negated"]
        gf["guards"].append({"site": {"line": 1, "column": 1}, "param": 0,
                             "predicate": "truth", "negated": False})
    return out


def layers_of(entry: dict[str, Any]) -> dict[str, Any]:
    layers = entry.get("layers")
    if not isinstance(layers, list):
        raise RuntimeError("capture has no layers")
    return {str(layer.get("layer")): layer for layer in layers if isinstance(layer, dict)}


def capture_both(raw: bytes, adapter: dict[str, Any], timeout: float
                 ) -> tuple[dict[str, Any], dict[str, Any]]:
    reference = run_reference(raw)
    py = reference.get("entry")
    if not isinstance(py, dict):
        raise RuntimeError(
            f"Python capture refused the document: {reference.get('canonical_error')}")
    envelope = run_port(raw, adapter, timeout).get("envelope")
    if not isinstance(envelope, dict) or not isinstance(envelope.get("engine"), dict):
        raise RuntimeError("Rust adapter returned no engine capture")
    return layers_of(py), layers_of(envelope["engine"])


def identity_problems(doc: dict[str, Any]) -> list[str]:
    """No (file, name, sig) may be both a `functions[]` record and an orphan."""
    def ident(d: dict[str, Any]) -> str:
        return f"{d.get('file')}|{d.get('name')}|{d.get('sig') or ''}"
    recorded = {ident(fn) for fn in doc.get("functions", []) if isinstance(fn, dict)}
    orphans = [o for o in doc.get("guarded_functions", []) if isinstance(o, dict)]
    problems = [f"orphan {o.get('name')} is also a functions[] record"
                for o in orphans if ident(o) in recorded]
    problems += [f"orphan {o.get('name')} without guarded_facts"
                 for o in orphans if not isinstance(o.get("guarded_facts"), dict)]
    return problems


def refusal_witness(inputs: list[Path]) -> str | None:
    """The producer must refuse a carrier that repeats a functions[] identity (exit 2, no
    facts written) and must write facts normally without the knob; returns a problem or None."""
    try:
        extract(inputs, knob=REFUSAL_KNOB)
    except RuntimeError as exc:
        text = str(exc)
        expected = "present in both functions[] and guarded_functions[]"
        # extract() reports the exit code as "extractor failed (N)"; the refusal tier is 2.
        if "extractor failed (2)" not in text or expected not in text:
            return f"refusal fired with the wrong tier or message: {text[-300:]}"
        return None
    return "the producer accepted an orphan repeating a functions[] identity (no refusal)"


def documents(only: set[str]) -> list[tuple[str, list[Path]]]:
    docs = [(p.name, [p / "case.cs"]) for p in sorted(SHAPES.iterdir())
            if p.is_dir() and (p / "case.cs").exists() and (not only or p.name in only)]
    if not only or "relevance-probe" in only:
        docs.append(("relevance-probe", [PROBE]))
    if not only or "samples" in only:
        docs.append(("samples", sorted(SAMPLES.glob("*.cs"))))
    return docs


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default="", help="comma-separated shape names (and/or `samples`)")
    ap.add_argument("--engine-binary", default=None)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = ap.parse_args(argv)
    only = {x for x in args.only.split(",") if x}
    try:
        adapter = engine_identity(resolve_engine_binary(args.engine_binary))
    except SystemExit as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    failures = 0
    checked = 0
    sidecars = 0
    orphans = 0
    witness_done = False
    for name, inputs in documents(only):
        try:
            raw = extract(inputs)
            emitted = json.loads(raw)
            carried = sum(1 for fn in emitted.get("functions", []) if "guarded_facts" in fn)
            sidecars += carried
            carrier = len(emitted.get("guarded_functions", []))
            orphans += carrier
            variants = {
                "emitted": raw,
                "stripped": json.dumps(stripped(emitted)).encode("utf-8"),
                "orphans_stripped": json.dumps(orphans_stripped(emitted)).encode("utf-8"),
                "contradictory": json.dumps(contradictory(emitted)).encode("utf-8"),
            }
            captured = {label: capture_both(b, adapter, args.timeout)
                        for label, b in variants.items()}
        except (RuntimeError, OSError, ValueError) as exc:
            failures += 1
            print(f"FAIL[{name}]: {exc}")
            continue
        problems: list[str] = identity_problems(emitted)
        if not witness_done and emitted.get("functions"):
            # Once per run, on the first document that has a functions[] record to repeat.
            witness_done = True
            witness = refusal_witness(inputs)
            if witness:
                problems.append(f"refusal witness: {witness}")
        base_py, base_rs = captured["emitted"]
        for layer in LAYERS:
            for label, (py, rs) in captured.items():
                if layer not in py or layer not in rs:
                    problems.append(f"{label}: no {layer} layer")
                    continue
                if py[layer] != base_py[layer]:
                    problems.append(f"python {layer} differs between emitted and {label}")
                if rs[layer] != base_rs[layer]:
                    problems.append(f"rust {layer} differs between emitted and {label}")
                if py[layer] != rs[layer]:
                    problems.append(f"{label}: python and rust {layer} layers differ")
        checked += 1
        if problems:
            failures += 1
            print(f"FAIL[{name}]: " + "; ".join(sorted(set(problems))))
        else:
            print(f"ok[{name}] {len(inputs)} file(s), {carried} sidecar(s), {carrier} orphan(s): "
                  f"emitted == stripped == orphans_stripped == contradictory on {len(LAYERS)} "
                  f"layers, python == rust")
    if checked and sidecars == 0:
        failures += 1
        print("FAIL[non-vacuous]: no function carried a sidecar, so nothing was tested")
    if checked and not only and orphans == 0:
        failures += 1
        print("FAIL[non-vacuous-carrier]: no document carried an orphan, so the carrier's "
              "inertness was not tested")
    if checked and not only and not witness_done:
        failures += 1
        print("FAIL[refusal-witness]: no document had a functions[] record to repeat")
    if failures:
        print(f"RESULT: {failures} inertness control(s) failed")
        return 1
    print(f"RESULT: the guarded-fact sidecar and the orphan carrier are inert on both engines "
          f"({checked} document(s), {sidecars} sidecar(s), {orphans} orphan(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
