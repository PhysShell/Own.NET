"""Shadow-mode infrastructure, layer 0: the same-input capture and the
reproduction artifact (P-022 step 7a, #260/#269 — *infrastructure*, not
shadow mode).

This module answers two questions that must be settled **before** two engines
can be compared at all:

1. **Did both engines see the same input?** — a canonical form for an `OwnIR`
   facts document and a hash over it, so "same input" is a checkable fact
   rather than an assumption about which file was passed where.
2. **What does a reproduction look like?** — one self-contained JSON document
   carrying the input, its schema version, its hash, the engine identifiers
   and each engine's outputs *per layer*, so a divergence can be re-run from
   the artifact alone.

It builds **no comparison and no verdict**. Comparing end diagnostics as an
acceptance surface is #260's *acceptance*, which is blocked on #259 (cp5 and
4b); nothing here may be read as shadow mode having been achieved.

Strictly an OBSERVER, like `ownlang/lowered.py` and `ownlang/verdicts.py`:
this module never mutates facts, never changes a verdict, and is imported by
nothing in the production path. It composes the three frozen layer surfaces —
it never re-encodes them.

## The canonical form (frozen; changing any line is a contract change)

The canonical form exists for **one** job: to name an input. It is deliberately
*not* the artifact's own rendering (see below) — two serializations, two jobs.

* It is defined over the **parsed** document, never over the file's bytes.
  Whitespace, key order and a duplicate key resolved by the parser are
  insignificant text formatting; a change to any *parsed value* is not. Two
  files that parse to the same document are the same input, and the hash says
  so.
* **The value domain is closed**: object, array, string, integer in
  `[-2**63, 2**63 - 1]`, `true`, `false`, `null`. A float, a non-finite, an
  integer outside that range, the literal `-0`, or a non-string object key is
  **refused**, never hashed. This is a deliberate boundary, not a limitation
  worked around: cross-language byte-agreement is only *provable* over the
  domain both engines represent identically. `spec/OwnIR.md` §4.2 already
  bounds every validated coordinate to signed 64 bits, so the closed domain
  costs the contract nothing.
* **Why `-0` is refused, and why the domain is enforced at PARSE.** The
  literal `-0` is where two conforming JSON parsers disagree about what
  "parsed" means: CPython's `json` reads it as the **integer** `0`,
  `serde_json` as the **float** `-0.0`. A canonical form that hashed it would
  be asserting "the two engines saw the same document" while the two engines
  held different values — the exact lie this surface exists to prevent. It is
  refused rather than reconciled, because reconciling would mean picking one
  parser's reading and calling the other wrong. Since the disagreement is
  *invisible after parsing* on the reference side (`-0` is already `0` by
  then), the domain is enforced where each engine can still see the literal:
  [`load_document`] here (through `json`'s `parse_int`/`parse_float`/
  `parse_constant` hooks), and the typed value's `Deserialize` on the Rust
  side. [`canonical_bytes`] keeps the value-level check as a backstop for a
  document that arrives already parsed. `NaN`/`Infinity`/`-Infinity` — which
  CPython accepts and `serde_json` rejects as invalid JSON — are refused on
  the same rule.

  The two enforcement points say **which one fired**: a literal-level refusal
  names "the integer/float/non-finite literal", a value-level one names the
  path it walked to. That is not decoration — the round-1 mutation campaign
  (M05/M06/M07, `docs/notes/p022-shadow-infra-checkpoint1-data/`) removed the
  literal-level check three times and the suite stayed green, because the
  backstop refused the same documents and the controls only asked *that*
  something refused. Distinguishable messages are what let a control pin the
  surface it claims to protect (P-022 discipline 2).
* **A declared boundary: nesting depth.** The two parsers cap recursion
  differently (CPython's interpreter recursion limit; `serde_json`'s 128).
  The canonical form does not attempt to unify them. `spec/OwnIR.md` §4.2
  bounds an OwnIR document at 32 nested bodies and 128 raw levels, which sits
  inside both caps, so no conforming document reaches the difference — but a
  non-conforming one could be refused by one engine and not the other, and
  that is recorded here rather than claimed away.
* **Serialization**: keys sorted by code point, no insignificant whitespace,
  UTF-8. String escaping is `"` → `\\"`, `\\` → `\\\\`, `U+0008` → `\\b`,
  `U+0009` → `\\t`, `U+000A` → `\\n`, `U+000C` → `\\f`, `U+000D` → `\\r`,
  every other code point below `U+0020` → `\\u00xx` with **lowercase** hex,
  and **every other code point raw** (no `\\u` escaping of non-ASCII, no
  escaping of `U+007F`, `U+2028`, `U+2029`). This is `json.dumps(...,
  sort_keys=True, separators=(",", ":"), ensure_ascii=False)`; the rule is
  written out because the Rust side implements it directly rather than
  inheriting it from a library, and `tests/fixtures/repro/canonical_torture.
  facts.json` holds both sides to it.
* **The hash** is SHA-256 over those bytes, lowercase hex, carried beside the
  byte length. Both are recomputed on verification, so a changed byte in the
  embedded document is a refusal.

## The reproduction artifact (frozen)

```text
{
  "repro_version": 1,
  "input": {"ownir_version": <verbatim or null>,
            "canonical": {"algorithm": "sha256", "digest": ..., "bytes": ...},
            "document": <the parsed facts document>},
  "engines": [{"id": "python-ownlang", "layers": [...]}]
}
```

* **Self-contained.** The input document is *embedded*, not referenced by
  path, so an artifact reproduces without the corpus it came from — and the
  hash is what makes the embedded copy trustworthy.
* **`engines` is an ordered array** over the frozen vocabulary
  `ENGINE_ORDER`, deduplicated; **`layers` is an ordered array** over the
  frozen `LAYER_ORDER` (`lowered` → `summaries` → `verdicts`), deduplicated.
  Neither is a JSON object: key order is not a sound carrier of semantic
  order for a byte-exact cross-language contract (the Layer 2 handle-array
  decision, for the same reason). The layer order is the *pipeline* order,
  which is what a first-divergence reduction walks.
* **One layer envelope for all three layers**: `{"layer", "surface_version",
  "status", "document" | "error"}`. `status` is `produced` or `refused`;
  `document` is present exactly when produced, `error` exactly when refused.
  A produced layer's document is carried **verbatim** — including the
  `lowered_version`/`verdicts_version` its own surface stamps, which
  `surface_version` therefore duplicates on purpose: lifting it is what lets
  a *refused* layer still name the surface it refused on. `summaries` has no
  surface version of its own (its document carries `ownir_version`), so its
  `surface_version` is `null` — absence is data.
* **One door for all three layers.** Every layer is projected from the same
  in-memory document through the **tolerant** door (`to_module` /
  `dump_summaries` / `check_facts` on the dict — never `load()`), because a
  reproduction artifact must describe what the layers did with *one and the
  same* input; mixing the strict and tolerant doors across layers would mean
  the three entries no longer describe one capture. Strict-door behaviour is
  Layer 1's own family (`own-ir`'s validation controls), not this surface's.
* **No engine build identity.** The artifact names *which* engine, never
  which build of it: a git SHA or a version stamp would make the artifact
  non-reproducible from the same inputs, and every surface it carries is
  already versioned (`repro_version`, `surface_version`, `ownir_version`).
  Recorded as a boundary, not an oversight.
* **Rendering** is `json.dumps(indent=2, ensure_ascii=False)` + a trailing
  newline, in construction order — the same rule as the Layer 2/3 families,
  and *not* the canonical form. Byte-identical on re-run.

The Rust side (`rust/crates/own-shadow`) parses these artifacts, recomputes
the same digest from the same embedded document, and re-renders them
byte-for-byte with zero Python.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .lowered import project_lowered
from .ownir import dump_summaries
from .verdicts import project_verdicts

# The artifact format version. Bump on ANY change to the frozen decisions
# above — the committed artifacts and the Rust replay are both keyed to it.
REPRO_VERSION = 1

# The digest over the canonical form. One algorithm, named in the artifact so
# a future change is a visible contract change rather than a silent reinterpretation
# of the same hex string.
CANONICAL_ALGORITHM = "sha256"

# The closed engine vocabulary, in the order `engines` carries them: the
# reference first. `rust-own-bridge` is declared here — the format has a slot
# for it from the start — and filled by the engine protocol (a later
# checkpoint), so an artifact carrying one engine is a capture, never a
# comparison.
ENGINE_PYTHON = "python-ownlang"
ENGINE_RUST = "rust-own-bridge"
ENGINE_ORDER: tuple[str, ...] = (ENGINE_PYTHON, ENGINE_RUST)

# The closed layer vocabulary, in pipeline order — the order a first-divergence
# reduction walks.
LAYER_ORDER: tuple[str, ...] = ("lowered", "summaries", "verdicts")

STATUS_PRODUCED = "produced"
STATUS_REFUSED = "refused"

_I64_MIN = -(2**63)
_I64_MAX = 2**63 - 1


class ReproError(Exception):
    """A document that cannot be canonically named: a value outside the closed
    canonical domain, or an artifact that fails its own verification."""


def _check_domain(value: Any, path: str) -> None:
    """Refuse anything outside the closed canonical value domain, naming the
    path so a refusal is actionable rather than a bare type error."""
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int):  # bool already returned above
        if not (_I64_MIN <= value <= _I64_MAX):
            raise ReproError(
                f"{path}: integer {value} is outside the canonical domain "
                f"[-2**63, 2**63-1]; spec/OwnIR.md §4.2 bounds every validated "
                f"coordinate to signed 64 bits")
        return
    if isinstance(value, float):
        raise ReproError(
            f"{path}: a floating-point value ({value!r}) is outside the canonical "
            f"domain — the OwnIR vocabulary has no float, and cross-language "
            f"byte-agreement is not provable over one")
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check_domain(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReproError(f"{path}: object key {key!r} is not a string")
            _check_domain(item, f"{path}.{key}")
        return
    raise ReproError(
        f"{path}: value of type {type(value).__name__} is outside the canonical "
        f"domain (object, array, string, i64 integer, bool, null)")


def _parse_int_literal(literal: str) -> int:
    """`json`'s `parse_int` hook: the only place the reference can still see an
    integer LITERAL, which is where the domain has to be enforced."""
    value = int(literal)
    if not (_I64_MIN <= value <= _I64_MAX):
        raise ReproError(
            f"the integer literal {literal} is outside the canonical domain "
            f"[-2**63, 2**63-1]; spec/OwnIR.md §4.2 bounds every validated "
            f"coordinate to signed 64 bits")
    if value == 0 and literal.lstrip().startswith("-"):
        raise ReproError(
            "the literal '-0' is outside the canonical domain: this reference "
            "reads it as the integer 0 and serde_json reads it as the float "
            "-0.0, so hashing it would assert that two engines saw the same "
            "document while they held different values")
    return value


def _parse_float_literal(literal: str) -> float:
    raise ReproError(
        f"the float literal {literal} is outside the canonical domain: the "
        f"OwnIR vocabulary has no float, and cross-language byte-agreement is "
        f"not provable over one")


def _parse_constant(literal: str) -> float:
    raise ReproError(
        f"the non-finite literal {literal} is outside the canonical domain: this "
        f"reference's JSON reader accepts it as an extension and serde_json "
        f"rejects it as invalid JSON, so the two engines do not agree that "
        f"the document parses at all")


def load_document(text: str) -> Any:
    """Parse one JSON document over the closed canonical domain.

    The domain is enforced **at parse**, on the literals, because that is the
    last point at which the reference can still tell `-0` from `0` (see the
    module docstring). Raises `ReproError` for a value outside the domain and
    `json.JSONDecodeError` for malformed JSON — never a rounded, truncated or
    silently re-typed value."""
    value = json.loads(
        text,
        parse_int=_parse_int_literal,
        parse_float=_parse_float_literal,
        parse_constant=_parse_constant,
    )
    _check_domain(value, "<root>")
    return value


def canonical_bytes(value: Any) -> bytes:
    """The canonical byte form of a parsed JSON document (see the module
    docstring). Raises `ReproError` for anything outside the closed domain —
    never a best-effort encoding of a value the other engine cannot hold."""
    _check_domain(value, "<root>")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_hash(value: Any) -> dict[str, Any]:
    """`{"algorithm", "digest", "bytes"}` over the canonical form."""
    raw = canonical_bytes(value)
    return {
        "algorithm": CANONICAL_ALGORITHM,
        "digest": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _layer(name: str, surface_version: Any, doc: dict[str, Any]) -> dict[str, Any]:
    """One layer envelope. A surface that encodes its own refusal as
    `{"error": ...}` is LIFTED into the envelope's `refused` status; a produced
    document is carried verbatim."""
    entry: dict[str, Any] = {"layer": name, "surface_version": surface_version}
    error = doc.get("error")
    if error is not None:
        entry["status"] = STATUS_REFUSED
        entry["error"] = error
    else:
        entry["status"] = STATUS_PRODUCED
        entry["document"] = doc
    return entry


def project_layers(facts: dict[str, Any]) -> list[dict[str, Any]]:
    """The reference engine's per-layer outputs for one facts document, in
    `LAYER_ORDER`, all through the tolerant door. Never mutates `facts`."""
    lowered = project_lowered(facts)
    verdicts = project_verdicts(facts)
    # `dump_summaries` folds a solver failure into the document's `degraded`
    # branch rather than raising (INF-F6), so this layer has no refusal today —
    # the envelope carries one because the *format* is uniform across layers,
    # not because this surface is expected to use it.
    summaries = dump_summaries(facts)
    return [
        _layer("lowered", lowered.get("lowered_version"), lowered),
        _layer("summaries", None, summaries),
        _layer("verdicts", verdicts.get("verdicts_version"), verdicts),
    ]


def project_repro(facts: dict[str, Any]) -> dict[str, Any]:
    """Project one facts document into the canonical reproduction artifact,
    carrying the reference engine's capture. Never mutates `facts`."""
    return {
        "repro_version": REPRO_VERSION,
        "input": {
            # The document's OWN declared schema version, verbatim. Absent and
            # explicitly-null both read as `null` here; the distinction stays
            # recoverable from the embedded document itself.
            "ownir_version": facts.get("ownir_version"),
            "canonical": canonical_hash(facts),
            "document": facts,
        },
        "engines": [{"id": ENGINE_PYTHON, "layers": project_layers(facts)}],
    }


def render_repro(facts: dict[str, Any]) -> str:
    """The canonical serialized artifact: construction order, 2-space indent,
    non-ASCII preserved, trailing newline. Byte-identical on re-run."""
    return json.dumps(project_repro(facts), indent=2, ensure_ascii=False) + "\n"


def verify_repro(artifact: Any) -> list[str]:
    """Verify an artifact against itself and return the problems found (empty
    == verified). This is the gate a tampered artifact fails: the digest and
    the byte length are RECOMPUTED from the embedded document, so a single
    changed byte in the input is a refusal rather than a silently different
    reproduction.

    Structural rules checked, in order: the format version; the input envelope;
    the recomputed canonical hash; the engine array against the frozen
    vocabulary and order; each engine's layer array against the frozen layer
    order; and each layer envelope's status/payload agreement."""
    problems: list[str] = []
    if not isinstance(artifact, dict):
        return [f"artifact is {type(artifact).__name__}, not an object"]
    if artifact.get("repro_version") != REPRO_VERSION:
        problems.append(
            f"repro_version {artifact.get('repro_version')!r} != "
            f"REPRO_VERSION {REPRO_VERSION}")
    extra = sorted(set(artifact) - {"repro_version", "input", "engines"})
    if extra:
        problems.append(f"unknown artifact member(s): {extra}")

    inp = artifact.get("input")
    if not isinstance(inp, dict):
        problems.append("input is missing or not an object")
    else:
        extra = sorted(set(inp) - {"ownir_version", "canonical", "document"})
        if extra:
            problems.append(f"unknown input member(s): {extra}")
        if "document" not in inp:
            problems.append("input.document is missing")
        else:
            claimed = inp.get("canonical")
            if not isinstance(claimed, dict):
                problems.append("input.canonical is missing or not an object")
            else:
                try:
                    actual = canonical_hash(inp["document"])
                except ReproError as e:
                    problems.append(f"input.document is not canonicalizable: {e}")
                else:
                    if claimed != actual:
                        problems.append(
                            f"input.canonical does not describe input.document: "
                            f"claimed {claimed}, recomputed {actual}")

    engines = artifact.get("engines")
    if not isinstance(engines, list):
        problems.append("engines is missing or not an array")
        return problems
    if not engines:
        problems.append("engines is empty — an artifact captures at least one engine")
    seen: list[str] = []
    for i, engine in enumerate(engines):
        if not isinstance(engine, dict):
            problems.append(f"engines[{i}] is not an object")
            continue
        extra = sorted(set(engine) - {"id", "layers"})
        if extra:
            problems.append(f"engines[{i}]: unknown member(s): {extra}")
        eid = engine.get("id")
        if not isinstance(eid, str) or eid not in ENGINE_ORDER:
            problems.append(
                f"engines[{i}]: id {eid!r} is not in the frozen engine "
                f"vocabulary {list(ENGINE_ORDER)}")
        else:
            if eid in seen:
                problems.append(f"engines[{i}]: engine {eid!r} appears twice")
            elif seen and ENGINE_ORDER.index(eid) < ENGINE_ORDER.index(seen[-1]):
                problems.append(
                    f"engines[{i}]: engine {eid!r} is out of the frozen order "
                    f"{list(ENGINE_ORDER)}")
            seen.append(eid)
        problems += _verify_layers(engine.get("layers"), f"engines[{i}]")
    return problems


def _verify_layers(layers: Any, where: str) -> list[str]:
    problems: list[str] = []
    if not isinstance(layers, list):
        return [f"{where}.layers is missing or not an array"]
    names = [layer.get("layer") if isinstance(layer, dict) else None for layer in layers]
    if names != list(LAYER_ORDER):
        problems.append(
            f"{where}.layers carries {names} — every engine reports exactly the "
            f"frozen layers {list(LAYER_ORDER)}, in that order")
    for i, layer in enumerate(layers):
        at = f"{where}.layers[{i}]"
        if not isinstance(layer, dict):
            problems.append(f"{at} is not an object")
            continue
        allowed = {"layer", "surface_version", "status", "document", "error"}
        extra = sorted(set(layer) - allowed)
        if extra:
            problems.append(f"{at}: unknown member(s): {extra}")
        if "surface_version" not in layer:
            problems.append(f"{at}: surface_version is missing (null when the "
                            f"surface has none)")
        status = layer.get("status")
        if status == STATUS_PRODUCED:
            if "document" not in layer:
                problems.append(f"{at}: status 'produced' without a document")
            if "error" in layer:
                problems.append(f"{at}: status 'produced' carries an error")
        elif status == STATUS_REFUSED:
            if not isinstance(layer.get("error"), str) or not layer.get("error"):
                problems.append(f"{at}: status 'refused' needs a non-empty error text")
            if "document" in layer:
                problems.append(f"{at}: status 'refused' carries a document")
        else:
            problems.append(
                f"{at}: status {status!r} is neither {STATUS_PRODUCED!r} nor "
                f"{STATUS_REFUSED!r}")
    return problems
