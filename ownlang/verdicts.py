"""Layer 3 parity surface: the normalized verdict list (P-022 #259).

A read-only, canonical JSON projection of what the OwnIR bridge *concluded* —
the `Finding` list `check_facts()` returns for one facts document, every field,
in the dataclass's declaration order — or, when the bridge refuses the
document, the `OwnIRError` text (spec/Bridge.md §6, layer 3: "the outer
contract"). The Rust `own-bridge` replays the same facts through
`own_bridge::check_facts` and must reproduce these documents; until then Python
is authoritative and `tests/test_verdict_fixtures.py --write` regenerates the
committed goldens.

Strictly an OBSERVER, like `ownlang/lowered.py`: this module never mutates
facts, never changes a verdict, and is imported by nothing in the production
verdict path.

Normalization decisions (frozen; changing any is a parity-contract change):

* **One record per `Finding`, every field, in declaration order** — `file,
  line, code, component, event, handler, message, kind, advisory, severity,
  related, flow, ignore_reason, column`. A field added to `Finding` appears
  here automatically, which is the point: the Rust replay parses the golden
  strictly and goes red until it is taught the new member. Nothing is
  dropped to make a checkpoint look complete — a replay declares which
  members it compares (identity, anchor, kind and tiering at #259 cp4;
  message and evidence at cp5); the golden always carries them all.
* **Order is the bridge's** (BR-V8: a stable sort on `(file, line, column or 0,
  code)`, ties in construction order) — the list is serialized as returned,
  never re-sorted here, so an ordering defect is visible as a diff.
* **Evidence triples** (`related`, `flow`) serialize as `[file, line, label]`
  arrays; every optional scalar (`column`, `severity`, `ignore_reason`) is
  `null` when absent — absence is data (`column` is never invented, BR-V5).
* **A refusal** (`OwnIRError` from `check_facts`: vocabulary skew, an unknown
  resource kind, a core verdict the bridge cannot map back — BR-V3) projects
  as `{"verdicts_version": ..., "error": "<message>"}`, so the rejection text
  is part of the surface exactly as the Layer 2 family pins it.
* Rendering is `json.dumps(indent=2, ensure_ascii=False)` + a trailing
  newline; regeneration is deterministic for identical input.

Fixture sharing: `tests/fixtures/verdicts/manifest.json` is the frozen case
ledger — the swept facts corpora (`tests/fixtures/{ownir,lowered,summaries}`),
the verdict-specific synthetic cases beside the manifest, and the Rust-side
exclusion ledger (documents the Rust core refuses by declared boundary, each
with its reason and an executable expectation the Rust replay asserts).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from .ownir import Finding, OwnIRError, check_facts

# The Layer 3 surface version. Bump on ANY normalization change above — the
# committed goldens and the Rust replay are both keyed to it.
VERDICTS_VERSION = 1

# `Finding`'s members in declaration order — the record shape, derived rather
# than listed, so the surface cannot silently lag the dataclass.
_FIELDS: tuple[str, ...] = tuple(f.name for f in dataclasses.fields(Finding))


def _record(f: Finding) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in _FIELDS:
        value = getattr(f, name)
        if name in ("related", "flow"):
            value = [list(step) for step in value]
        out[name] = value
    return out


def project_verdicts(facts: dict[str, Any]) -> dict[str, Any]:
    """Project one facts document's verdict list into the canonical Layer 3
    dict. A bridge refusal (`OwnIRError`) projects as `{"verdicts_version":
    ..., "error": <message>}` — the rejection text is part of the parity
    surface. Never mutates `facts`."""
    try:
        findings = check_facts(facts)
    except OwnIRError as e:
        return {"verdicts_version": VERDICTS_VERSION, "error": str(e)}
    return {
        "verdicts_version": VERDICTS_VERSION,
        "findings": [_record(f) for f in findings],
    }


def render_verdicts(facts: dict[str, Any]) -> str:
    """The canonical serialized form: fixed field order, 2-space indent,
    non-ASCII preserved, trailing newline. Byte-identical on re-run."""
    return json.dumps(project_verdicts(facts), indent=2, ensure_ascii=False) + "\n"
