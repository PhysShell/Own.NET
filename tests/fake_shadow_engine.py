#!/usr/bin/env python3
"""A misbehaving stand-in for `own-shadow-engine`, for the compare driver's
controls (P-022 step 7a, #260 acceptance).

**It is a test double, never a second engine.** It computes no verdict, ports
nothing and stands in for nothing: its layer records are the `rust-own-bridge`
entry a REAL run already wrote into `tests/fixtures/repro/canonical_minimal.
repro.json`, replayed verbatim. What each mode changes is exactly one thing the
driver is supposed to notice — and the driver noticing is the whole of what
these controls measure.

Replaying a recorded capture rather than emulating the port matters twice
over. It keeps the controls honest: nothing here invents an engine's answer,
which is the rule (owner decision B-3) the artifact format itself enforces. And
it keeps them runnable in the Python-only test matrix, where there is no cargo
and therefore no adapter — a control that could only run where the toolchain
exists is a control that stops running.

The mode comes from `OWN_FAKE_ENGINE_MODE`, because the real adapter takes no
arguments and the driver must invoke this the same way it invokes that.

Modes:

  faithful           the recorded capture, with `consumed` and `canonical`
                     computed over the bytes actually received — the baseline
                     the other modes are perturbations of
  canonical_consumed `consumed` computed over the CANONICAL bytes instead of
                     the raw ones: the trap B-2 exists to catch
  foreign_consumed   `consumed` computed over bytes this run never saw
  no_consumed        no `consumed` at all — a pre-v3 capture
  renderer_drop      a correct capture whose derived SARIF has one
                     `relatedLocations` entry removed, digest recomputed:
                     equal verdict layers, different rendered bytes
  crash              exit non-zero with a message on stderr
  hang               never terminate
  garbage            write something that is not JSON
  bad_protocol       a capture in a protocol version the driver does not speak
  rewrite_input      overwrite the file named by `OWN_FAKE_ENGINE_REWRITE`,
                     then behave faithfully — so a driver that re-read its
                     input would pick up different bytes after this point
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ownlang.repro import ENGINE_RUST, canonical_hash, hash_bytes, load_bytes

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDED = os.path.join(HERE, "fixtures", "repro", "canonical_minimal.repro.json")


def _recorded_entry() -> dict[str, object]:
    with open(RECORDED, encoding="utf-8") as f:
        artifact = json.load(f)
    for engine in artifact["engines"]:
        if engine["id"] == ENGINE_RUST:
            entry: dict[str, object] = copy.deepcopy(engine)
            return entry
    raise SystemExit("fake_shadow_engine: the recorded artifact carries no port entry")


def main() -> int:
    mode = os.environ.get("OWN_FAKE_ENGINE_MODE", "faithful")
    raw = sys.stdin.buffer.read()

    if mode == "crash":
        print("fake_shadow_engine: pretending the port crashed", file=sys.stderr)
        return 9
    if mode == "hang":
        while True:
            time.sleep(3600)
    if mode == "garbage":
        sys.stdout.write("this is not a capture\n")
        return 0
    if mode == "rewrite_input":
        target = os.environ.get("OWN_FAKE_ENGINE_REWRITE")
        if target:
            with open(target, "wb") as f:
                f.write(b'{"ownir_version": 0, "module": "RewrittenUnderneath"}\n')

    entry = _recorded_entry()
    entry["consumed"] = hash_bytes(raw)
    try:
        canonical: object = canonical_hash(load_bytes(raw))
        canonical_error: object = None
    except Exception as e:  # a double reports what happened; it does not classify it
        canonical, canonical_error = None, str(e)

    if mode == "canonical_consumed":
        # The exact trap owner decision B-2 exists to catch: an engine that
        # hashes what it PARSED rather than what it READ. Every raw variant of
        # one document would then attest the same identity, and "both engines
        # consumed the identical byte sequence" would be back to being a claim
        # about canonical equivalence.
        entry["consumed"] = dict(canonical) if isinstance(canonical, dict) else {}
    elif mode == "foreign_consumed":
        entry["consumed"] = hash_bytes(b"bytes this run never saw")
    elif mode == "no_consumed":
        entry.pop("consumed", None)

    derived_documents = None
    sarif = _recorded_sarif(entry)
    if sarif is not None:
        if mode == "renderer_drop":
            sarif = _drop_one_related_location(sarif)
            derived = entry.get("derived")
            if isinstance(derived, dict) and isinstance(derived.get("sarif"), dict):
                derived["sarif"]["canonical"] = canonical_hash(sarif)
        derived_documents = {"sarif": sarif}

    envelope = {
        "own_shadow_engine": 7 if mode == "bad_protocol" else 1,
        "engine": entry,
        "canonical": canonical,
        "canonical_error": canonical_error,
        "derived_documents": derived_documents,
    }
    sys.stdout.write(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n")
    return 0


def _recorded_sarif(entry: dict[str, object]) -> dict[str, object] | None:
    """Re-render the SARIF the recorded entry's identity names.

    The recorded artifact carries identities, not documents (owner decision
    D-6), so the document is rebuilt from the recorded verdict layer — through
    the reference's own renderer, which is fine here for the same reason the
    layers are replayed: this double asserts nothing about either engine."""
    from ownlang.repro import derived_sarif_document

    layers = entry.get("layers")
    if not isinstance(layers, list):
        return None
    verdicts = next((lyr for lyr in layers
                     if isinstance(lyr, dict) and lyr.get("layer") == "verdicts"), None)
    if verdicts is None or verdicts.get("status") != "produced":
        return None
    document = verdicts.get("document")
    if not isinstance(document, dict):
        return None
    out = derived_sarif_document(document)
    return out


def _drop_one_related_location(sarif: dict[str, object]) -> dict[str, object]:
    """Remove one `relatedLocations` entry — the BR-V9 rule whose renderer this
    control exists to break. A finding's identity, anchor and message are
    untouched, so the verdict layers stay equal and only the rendered bytes
    move: `renderer-only divergence` by construction."""
    out = copy.deepcopy(sarif)
    for run in out.get("runs", []):
        for result in run.get("results", []):
            related = result.get("relatedLocations")
            if isinstance(related, list) and related:
                del related[0]
                return out
    # Nothing to drop: perturb a message instead, so the mode always produces a
    # renderer difference rather than silently producing none.
    for run in out.get("runs", []):
        for result in run.get("results", []):
            message = result.get("message")
            if isinstance(message, dict) and isinstance(message.get("text"), str):
                message["text"] += " (renderer control)"
                return out
    out["$rendererControl"] = hashlib.sha256(b"no results to perturb").hexdigest()
    return out


if __name__ == "__main__":
    raise SystemExit(main())
