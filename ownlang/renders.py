"""Layer 3, rendered: the bridge's output surfaces (P-022 #259 checkpoint 5.3).

`ownlang/verdicts.py` freezes what the bridge CONCLUDES — the `Finding` list.
This module freezes what a consumer SEES: the same list through
`ownir.render_finding` (the human CLI line, the GitHub Actions annotation, the
MSBuild/VS Error List line) and through `ownir.build_sarif` (the one SARIF
2.1.0 log per run). Those are BR-V9's surfaces, and until this family they had
no golden of any kind — `tests/test_ownir.py` pinned a handful of their rules
against hand-written strings, which is not the same thing as freezing the bytes
a run emits.

Strictly an OBSERVER, like `ownlang/verdicts.py` and `ownlang/lowered.py`: it
never mutates facts, never changes a verdict or a rendering, and is imported by
nothing in the production path. It calls the production renderers and records
what they returned.

Normalization decisions (frozen; changing any is a parity-contract change):

* **Both host severities, always.** `severity` is a presentation choice that
  the CLI passes through (`--severity`), and it is the one input to these
  surfaces besides the findings. Every case renders at `"error"` and at
  `"warning"` so the pass-through and the SARIF level mapping (BR-V6: an
  advisory stays `note`, an intrinsic warning stays `warning`, a provable leak
  drops from `error` to `warning`) are both visible in the golden.
* **One entry per finding, in the bridge's order** (BR-V8), for the three
  line-per-finding surfaces. The list is never re-sorted here.
* **The unknown format is rendered, not assumed.** `render_finding` falls back
  to the human line for any format it does not know; the golden carries that
  rendering under its own key rather than a claim that it equals `human`.
* **SARIF is carried as the value `build_sarif` returned**, re-serialized by
  this module's own `json.dumps`. The log is a JSON document, not a byte
  stream the reference emits, so key ORDER is what the golden pins (Python
  dicts preserve insertion order, and the Rust replay reproduces it).
* **A refusal** (`OwnIRError` from `check_facts`) projects as
  `{"renders_version": ..., "error": "<message>"}` — the same shape the Layer 3
  verdict surface uses, because a document the bridge refuses has no findings
  to render and the refusal is what a consumer would see.
* Rendering is `json.dumps(indent=2, ensure_ascii=False)` + a trailing newline;
  regeneration is deterministic for identical input.

What this surface deliberately does NOT carry: a diagnostic's `subject`.
`ownir.Finding` has no such member, so no bridge surface can serialize one —
and `tests/test_verdict_render_fixtures.py` asserts that over the rendered
bytes rather than restating it (the checkpoint-4 note left that re-check to
this checkpoint).

Fixture sharing: `tests/fixtures/verdict_renders/manifest.json` is the frozen
case ledger. Each case names its own facts document beside the manifest and the
BR-V9 rules it pins, which is what `tests/verdict_surface_inventory.py` reads
to say whether a rule has a control.
"""

from __future__ import annotations

import json
from typing import Any

from .ownir import OwnIRError, build_sarif, check_facts, render_finding

# The rendered-surface version. Bump on ANY normalization change above — the
# committed goldens and the Rust replay are both keyed to it.
RENDERS_VERSION = 1

# The host severities every case is rendered at (see the docstring).
SEVERITIES: tuple[str, ...] = ("error", "warning")
# The `render_finding` formats, plus one the function does not know: the
# fallback is a rule, so it is rendered rather than asserted.
FORMATS: tuple[str, ...] = ("human", "github", "msbuild", "unknown-format")


def project_renders(facts: dict[str, Any]) -> dict[str, Any]:
    """Project one facts document's rendered surfaces into the canonical dict.
    A bridge refusal projects as `{"renders_version": ..., "error": <message>}`.
    Never mutates `facts`."""
    try:
        findings = check_facts(facts)
    except OwnIRError as e:
        return {"renders_version": RENDERS_VERSION, "error": str(e)}
    out: dict[str, Any] = {"renders_version": RENDERS_VERSION}
    for fmt in FORMATS:
        out[fmt] = {
            severity: [render_finding(f, fmt, severity) for f in findings]
            for severity in SEVERITIES
        }
    out["sarif"] = {severity: build_sarif(findings, severity) for severity in SEVERITIES}
    return out


def render_renders(facts: dict[str, Any]) -> str:
    """The canonical serialized form: fixed key order, 2-space indent, non-ASCII
    preserved, trailing newline. Byte-identical on re-run."""
    return json.dumps(project_renders(facts), indent=2, ensure_ascii=False) + "\n"
