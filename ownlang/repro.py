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
  "projection", "status", "document" | "error"}`. `status` is `produced` or
  `refused`;
  `document` is present exactly when produced, `error` exactly when refused.
  A produced layer's document is carried **verbatim** — including the
  `lowered_version`/`verdicts_version` its own surface stamps, which
  `surface_version` therefore duplicates on purpose: lifting it is what lets
  a *refused* layer still name the surface it refused on. `summaries` has no
  surface version of its own (its document carries `ownir_version`), so its
  `surface_version` is `null` — absence is data.
* **`projection` says what the engine could produce** (the engine protocol,
  checkpoint 2). Either `{"kind": "full"}` — the engine emits the whole frozen
  surface — or `{"kind": "partial", "members": [...], "reason": "..."}`, naming
  the members it does emit and why the rest are absent. This is the cp4
  discipline generalized: *a replay declares what it compares, and the golden
  always carries everything*. Without it the format would have exactly two bad
  options for a port that is mid-migration — emit a short document and let a
  later comparison silently score the missing members as agreement, or refuse
  a layer it can in fact mostly produce. The reference declares `full` on all
  three layers by definition: its surfaces *are* the frozen ones.
* **An engine writes only its own entry, never another's.** `--write` on
  either side preserves the foreign engine entries it finds in a committed
  artifact and replaces only its own. An artifact where one engine authored
  another's capture would be a comparison of one implementation against
  itself.
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

## The `AnalysisTrace` (#269; frozen)

An artifact **pairs** two engines' captures; it does not make them comparable.
Two things stand in the way, and the trace is the normalization that removes
exactly one of them and *declares* the other.

```text
{"trace_version": 1,
 "engine": "python-ownlang",
 "input": {"algorithm": ..., "digest": ..., "bytes": ...},
 "layers": [{"layer": "lowered", "status": "produced", "projection": {...},
             "order": "significant",
             "steps": [{"id": "<stable address>", "value": <json>}, ...]}]}
```

* **Internal identifiers are normalized away.** The lowered surface's handles
  (`sub_0`, `cap_1`, `parg_0`, `loc_3`) are minted from **global counters in
  document order** (BR-L2), so they are positions wearing the costume of
  names. `stable_handle_ids` rebuilds each from the record's own identity —
  `component | file | line | event | handler` — and every occurrence of the
  old name anywhere in the document is rewritten. The rename is a **bijection**
  and it is **total**: no counter-shaped name survives, which is asserted, not
  hoped for. The mint *kind* is not thrown away — it moves into the handle
  record as `mint`, so a routing difference (R5 minting `cap_` where R6 would
  mint `sub_`) stays a comparable **value** on one step instead of becoming a
  pair of "only in one engine" ids.
* **Order is declared, never normalized away.** `order` is `significant` for
  `lowered` (document order is semantic — BR-D4, BR-L5) and for `verdicts`
  (BR-V8 sorts by `(file, line, column, code)` and leaves ties in construction
  order, so position carries information), and `canonical` for `summaries`
  (INF-R1 sorts by method key, so position carries none beyond the id).
  Sorting a `significant` layer to make a comparison "pass" would delete the
  very defect the layer exists to expose; declaring the semantics is what lets
  a later comparison classify an ordering difference instead of breaking on it
  — or missing it.
* **Steps are addressed by identity, not position**, wherever the surface has
  one: resources/externs/lifetimes by name, functions by name, handles by
  their stable id, MOS summaries by method key, findings by
  `file:line:column:code`. The **one** place position leaks back in is a
  duplicate address, which takes a `~<n>` suffix in encounter order. The suffix
  goes **inside the bracket** — `functions[Take~1]`, never
  `functions[Take]~1` — uniformly for every addressed list, so that a nested
  prefix composes (`functions[Take~1].body[0]`). Recorded because a duplicate
  finding address is exactly the tie whose order `verdicts` declares
  significant.
* **Nested statement bodies stay inside their statement's value.** A `then`/
  `else`/`while` body is part of the enclosing step rather than a step of its
  own. Flattening deeper would need a path grammar, and the enclosing statement
  is already the smallest unit that names a lowering site; a difference inside
  a branch shows as a difference on that statement.
* A **refused** layer carries its error and **no steps** — there is nothing to
  address, and inventing an empty step list that compared equal to another
  engine's empty one would score a refusal as agreement.
* The trace carries the **input hash**, so a trace cannot be read against a
  document it did not come from.

Rendering is `json.dumps(indent=2, ensure_ascii=False)` + a trailing newline.

The Rust side (`rust/crates/own-shadow`) parses these artifacts, recomputes
the same digest from the same embedded document, re-renders them byte-for-byte,
produces its own capture through the same engine protocol, and projects the
same trace — all with zero Python.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .lowered import project_lowered
from .ownir import dump_summaries
from .verdicts import project_verdicts

# The artifact format version. Bump on ANY change to the frozen decisions
# above — the committed artifacts and the Rust replay are both keyed to it.
# 2 added the layer envelope's `projection` (checkpoint 2, the engine protocol).
REPRO_VERSION = 2

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

# The projection vocabulary (the engine protocol, checkpoint 2).
PROJECTION_FULL = "full"
PROJECTION_PARTIAL = "partial"
PROJECTION_KINDS = (PROJECTION_FULL, PROJECTION_PARTIAL)

# The reference emits the whole of every frozen surface, by definition: those
# surfaces are its own output. Written once and shared, so "full" is a single
# fact rather than three copies of a claim.
FULL: dict[str, Any] = {"kind": PROJECTION_FULL}

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


def _layer(name: str, surface_version: Any, doc: dict[str, Any],
           projection: dict[str, Any] | None = None) -> dict[str, Any]:
    """One layer envelope. A surface that encodes its own refusal as
    `{"error": ...}` is LIFTED into the envelope's `refused` status; a produced
    document is carried verbatim. `projection` defaults to the reference's
    `full` — it emits the whole of every frozen surface by definition."""
    entry: dict[str, Any] = {
        "layer": name,
        "surface_version": surface_version,
        "projection": dict(projection) if projection else dict(FULL),
    }
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


def project_repro(facts: dict[str, Any],
                  foreign: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Project one facts document into the canonical reproduction artifact,
    carrying the reference engine's capture — and any `foreign` engine captures
    handed in, carried through **verbatim**.

    An engine writes only its own entry: this function authors
    `python-ownlang` and never invents another engine's numbers. The foreign
    entries come from a previously committed artifact (`--write` reads them
    back before overwriting), which is what lets the two halves of the protocol
    be produced independently, each with zero of the other's runtime. Never
    mutates `facts`."""
    engines: list[dict[str, Any]] = [
        {"id": ENGINE_PYTHON, "layers": project_layers(facts)}]
    for entry in foreign or []:
        if isinstance(entry, dict) and entry.get("id") != ENGINE_PYTHON:
            engines.append(entry)
    engines.sort(key=lambda e: ENGINE_ORDER.index(e["id"])
                 if e.get("id") in ENGINE_ORDER else len(ENGINE_ORDER))
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
        "engines": engines,
    }


def render_repro(facts: dict[str, Any],
                 foreign: list[dict[str, Any]] | None = None) -> str:
    """The canonical serialized artifact: construction order, 2-space indent,
    non-ASCII preserved, trailing newline. Byte-identical on re-run."""
    return json.dumps(project_repro(facts, foreign), indent=2,
                      ensure_ascii=False) + "\n"


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


# --------------------------------------------------------------------------
# The AnalysisTrace (#269): stable-ID normalization + the comparable projection
# --------------------------------------------------------------------------

# The trace surface version. Bump on ANY change to the frozen decisions in the
# module docstring's AnalysisTrace section.
TRACE_VERSION = 1

ORDER_SIGNIFICANT = "significant"
ORDER_CANONICAL = "canonical"

# Per-layer ordering semantics, frozen. A comparison reads this to CLASSIFY an
# ordering difference; it never licenses sorting a layer to make one go away.
LAYER_ORDER_SEMANTICS: dict[str, str] = {
    "lowered": ORDER_SIGNIFICANT,    # BR-D4 / BR-L5: document + lowering order
    "summaries": ORDER_CANONICAL,    # INF-R1: sorted by method key
    "verdicts": ORDER_SIGNIFICANT,   # BR-V8: ties stay in construction order
}

# A minted handle: a global counter wearing the costume of a name (BR-L2).
_MINTED_HANDLE = re.compile(r"^(sub|cap|parg|loc)_\d+$")


def _identity(record: dict[str, Any]) -> str:
    """A handle's identity, from the record the bridge attached to it — never
    from the counter. The five fields are the ones every handle record carries
    or omits meaningfully; an absent one renders as the empty string so that
    "no handler" and "the empty handler" stay the same address (they are the
    same fact)."""
    return "|".join(str(record.get(k, "")) for k in
                    ("component", "file", "line", "event", "handler"))


def stable_handle_ids(handles: list[dict[str, Any]]) -> dict[str, str]:
    """`minted name -> stable id`, over a Layer 2 document's handle array.

    A bijection by construction: identities that repeat take a `~<n>` suffix in
    encounter order, which is the one place position leaks back into an
    address. Two records with the same component, file, line, event and handler
    are the same fact seen twice, and nothing but their order distinguishes
    them."""
    seen: dict[str, int] = {}
    out: dict[str, str] = {}
    for record in handles:
        minted = record.get("handle")
        if not isinstance(minted, str):
            continue
        identity = _identity(record)
        n = seen.get(identity, 0)
        seen[identity] = n + 1
        out[minted] = identity if n == 0 else f"{identity}~{n}"
    return out


def _rewrite(value: Any, rename: dict[str, str]) -> Any:
    """Rewrite every string that IS a minted handle. Total by design: handle
    names are `prefix_<digits>`, a shape no other Layer 2 string takes (module
    names, files, events and callees are C# identifiers, paths or `$channel`
    markers), so a whole-document rewrite cannot catch a bystander — and
    `normalize_handles` asserts that none survives."""
    if isinstance(value, str):
        return rename.get(value, value)
    if isinstance(value, list):
        return [_rewrite(v, rename) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite(v, rename) for k, v in value.items()}
    return value


def normalize_handles(document: dict[str, Any]) -> dict[str, Any]:
    """A Layer 2 document with every minted handle replaced by its stable id,
    and the mint KIND preserved as each handle record's `mint`.

    Raises `ReproError` if a counter-shaped name survives — the rename claims
    to be total, and a claim a test cannot fail is not a contract."""
    handles = document.get("handles")
    if not isinstance(handles, list):
        return document
    rename = stable_handle_ids(handles)
    out: dict[str, Any] = _rewrite(document, rename)
    for record, original in zip(out.get("handles", []), handles, strict=True):
        minted = original.get("handle")
        if isinstance(minted, str):
            match = _MINTED_HANDLE.match(minted)
            record["mint"] = match.group(1) if match else minted
    leftovers = _minted_leftovers(out)
    if leftovers:
        raise ReproError(
            f"stable-ID normalization is not total: {sorted(leftovers)[:5]} "
            f"survived the rewrite — a handle is referenced somewhere the "
            f"rename did not reach, and a comparison would report it as a "
            f"difference between engines rather than as a counter")
    return out


def _minted_leftovers(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value} if _MINTED_HANDLE.match(value) else set()
    if isinstance(value, list):
        return set().union(*(_minted_leftovers(v) for v in value)) if value else set()
    if isinstance(value, dict):
        return (set().union(*(_minted_leftovers(v) for v in value.values()))
                if value else set())
    return set()


def _disambiguate(seen: dict[str, int], address: str) -> str:
    """`address`, with a `~<n>` suffix when it repeats — the one place position
    leaks back into an address.

    The suffix goes INSIDE the bracket (`functions[Take~1]`, not
    `functions[Take]~1`), uniformly for every addressed list. It disambiguates
    *which of the repeated items*, which is a property of the item and not of
    the path, and it is what lets a nested prefix compose:
    `functions[Take~1].body[0]` addresses the second `Take`'s first statement.
    The rule is spelled out because the two implementations of this schema
    first read it two different ways — Python suffixed inside the bracket for
    functions and outside for everything else, which the port's independent
    reading caught."""
    n = seen.get(address, 0)
    seen[address] = n + 1
    return address if n == 0 else f"{address}~{n}"


def _steps(name: str, values: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    """Address a list of `(address, value)` pairs under one prefix."""
    seen: dict[str, int] = {}
    return [{"id": f"{name}[{_disambiguate(seen, address)}]", "value": value}
            for address, value in values]


def _lowered_steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    doc = normalize_handles(document)
    steps: list[dict[str, Any]] = [
        {"id": "lowered_version", "value": doc.get("lowered_version")},
        {"id": "module", "value": doc.get("module")},
    ]
    for key in ("resources", "externs", "lifetimes"):
        steps += _steps(key, [(str(e.get("name")), e)
                                      for e in doc.get(key, [])])
    # One disambiguator across ALL functions, and the body prefix inherits it:
    # `Fn<loc>` and a repeated C# name both put two functions under one address
    # (`mosdump_degraded_duplicate_key` has two `Take`s), and a per-function
    # counter would reset and collide. Found by this family's own step-id
    # control rather than by reading the code.
    seen: dict[str, int] = {}
    for fn in doc.get("functions", []):
        address = _disambiguate(seen, str(fn.get("name")))
        head = {k: v for k, v in fn.items() if k != "body"}
        steps.append({"id": f"functions[{address}]", "value": head})
        steps += _steps(f"functions[{address}].body",
                        [(str(i), s) for i, s in enumerate(fn.get("body", []))])
    steps += _steps("handles",
                    [(str(h.get("handle")), h) for h in doc.get("handles", [])])
    return steps


def _summaries_steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {"id": "module", "value": document.get("module")},
        {"id": "ownir_version", "value": document.get("ownir_version")},
        {"id": "degraded", "value": document.get("degraded")},
    ]
    steps += _steps("summaries",
                    [(str(s.get("method")), s) for s in document.get("summaries", [])])
    steps += _steps("unresolved",
                    [(str(u), u) for u in document.get("unresolved", [])])
    return steps


def _verdicts_steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {"id": "verdicts_version", "value": document.get("verdicts_version")},
    ]
    findings = document.get("findings", [])
    steps += _steps("findings",
                    [(f"{f.get('file')}:{f.get('line')}:{f.get('column')}:"
                      f"{f.get('code')}", f) for f in findings])
    return steps


_LAYER_STEPS = {
    "lowered": _lowered_steps,
    "summaries": _summaries_steps,
    "verdicts": _verdicts_steps,
}


def trace_layer(layer: dict[str, Any]) -> dict[str, Any]:
    """One capture layer as a trace layer. A REFUSED layer carries its error
    and no steps: there is nothing to address, and an empty step list that
    compared equal to another engine's empty one would score a refusal as
    agreement."""
    name = layer.get("layer")
    out: dict[str, Any] = {
        "layer": name,
        "status": layer.get("status"),
        "projection": layer.get("projection"),
        "order": LAYER_ORDER_SEMANTICS.get(str(name), ORDER_SIGNIFICANT),
    }
    if layer.get("status") == STATUS_REFUSED:
        out["error"] = layer.get("error")
        out["steps"] = []
        return out
    builder = _LAYER_STEPS.get(str(name))
    if builder is None:
        raise ReproError(
            f"no trace projection for layer {name!r} — a layer added to "
            f"LAYER_ORDER must be taught how to address its steps, or a "
            f"comparison would silently skip it")
    out["steps"] = builder(layer.get("document") or {})
    return out


def project_trace(artifact: dict[str, Any], engine_id: str) -> dict[str, Any]:
    """Project one engine's capture, out of a reproduction artifact, into the
    comparable `AnalysisTrace`. Carries the input hash so a trace cannot be
    read against a document it did not come from."""
    engines = artifact.get("engines", [])
    for engine in engines:
        if isinstance(engine, dict) and engine.get("id") == engine_id:
            return {
                "trace_version": TRACE_VERSION,
                "engine": engine_id,
                "input": artifact.get("input", {}).get("canonical"),
                "layers": [trace_layer(layer) for layer in engine.get("layers", [])],
            }
    raise ReproError(
        f"the artifact carries no capture for engine {engine_id!r} "
        f"(present: {[e.get('id') for e in engines if isinstance(e, dict)]})")


def project_traces(artifact: dict[str, Any], case: str) -> dict[str, Any]:
    """Every engine's capture in one artifact, projected into traces, in the
    artifact's engine order.

    Projecting an engine's capture is not authoring it: the trace is a pure
    normalization of a capture somebody else produced, and BOTH sides project
    BOTH engines so that the normalization itself is cross-checked. If the two
    implementations of the projection ever disagree, that disagreement is a
    finding about the projection, not about either engine."""
    return {
        "trace_version": TRACE_VERSION,
        "case": case,
        "traces": [project_trace(artifact, engine["id"])
                   for engine in artifact.get("engines", [])
                   if isinstance(engine, dict) and isinstance(engine.get("id"), str)],
    }


def render_traces(artifact: dict[str, Any], case: str) -> str:
    return json.dumps(project_traces(artifact, case), indent=2,
                      ensure_ascii=False) + "\n"


def _verify_projection(projection: Any, at: str) -> list[str]:
    """The engine protocol's one rule: a layer says what its engine could
    produce, and a partial projection must NAME the members it carries and say
    why the rest are absent. An unexplained partial is how a comparison would
    quietly score an unported member as agreement."""
    problems: list[str] = []
    if not isinstance(projection, dict):
        return [f"{at}: projection is missing or not an object — every layer "
                f"declares what its engine could produce"]
    extra = sorted(set(projection) - {"kind", "members", "reason"})
    if extra:
        problems.append(f"{at}.projection: unknown member(s): {extra}")
    kind = projection.get("kind")
    if kind == PROJECTION_FULL:
        for name in ("members", "reason"):
            if name in projection:
                problems.append(f"{at}.projection: a 'full' projection carries "
                                f"no {name!r} — it emits the whole surface")
    elif kind == PROJECTION_PARTIAL:
        members = projection.get("members")
        if not (isinstance(members, list) and members
                and all(isinstance(m, str) and m for m in members)):
            problems.append(f"{at}.projection: a 'partial' projection must NAME "
                            f"the members it carries")
        elif sorted(set(members)) != sorted(members):
            problems.append(f"{at}.projection: duplicate member names")
        reason = projection.get("reason")
        if not (isinstance(reason, str) and reason):
            problems.append(f"{at}.projection: a 'partial' projection must say "
                            f"WHY the remaining members are absent")
    else:
        problems.append(f"{at}.projection: kind {kind!r} is not one of "
                        f"{list(PROJECTION_KINDS)}")
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
        allowed = {"layer", "surface_version", "projection", "status",
                   "document", "error"}
        extra = sorted(set(layer) - allowed)
        if extra:
            problems.append(f"{at}: unknown member(s): {extra}")
        if "surface_version" not in layer:
            problems.append(f"{at}: surface_version is missing (null when the "
                            f"surface has none)")
        problems += _verify_projection(layer.get("projection"), at)
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
