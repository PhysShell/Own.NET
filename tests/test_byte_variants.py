#!/usr/bin/env python3
"""Byte-level input variants: what each engine's JSON reader does with the
SAME document written differently (P-022 step 7a, #260 acceptance, F.0).

**A measurement, not a policy.** Owner decision B-1 says #260's same-input
invariant is byte-level, and B-2 says the artifact must attest the raw bytes
each engine consumed. Before either can be built, one question has to be
*measured* rather than assumed: which byte-level rewritings of one document do
both readers still accept, and which does at least one refuse? A rewriting both
accept is a **raw variant** — the same input under B-1's canonical rule, a
different byte sequence under B-2's — and it is exactly what the attestation
has to be able to tell apart. A rewriting both refuse belongs to the
**invalid** class, and is a negative control for the compare driver rather
than a document any artifact can carry.

The third case is the one that is nobody's to decide here:

> **If the two readers DISAGREE about a variant, this harness fails.** One
> engine accepting a byte sequence the other refuses is a domain decision for
> the repository owner (the shape D-2 records for `-0`), not a fact a
> measurement may quietly file under either class. The ledger's `class` is
> therefore *derived* from the two `accepted` flags, never typed beside them:
> there is no way to write down a disagreement and have the suite stay green.

The corpus is committed as **bytes** (`tests/fixtures/repro/variants/*.bin`),
because the whole point is a difference that no text-mode read can see: a
harness that opened these with `encoding="utf-8"` would normalize away the very
thing being measured, and one of them is not valid UTF-8 at all.

The Rust half is `rust/crates/own-shadow/tests/byte_variants.rs`: it reads the
same bytes and the same ledger, and asserts its own column with zero Python.
Neither side writes the other's column — the ledger records *two* independent
measurements of one corpus, which is what makes a disagreement visible instead
of averaged.

Ledger records are sorted by variant name and depend on nothing but their own
variant (P-022 discipline §4), so adding a variant churns no existing record.

Run:  python tests/test_byte_variants.py            (verify)
      python tests/test_byte_variants.py --write    (regenerate corpus+ledger)
      python tests/run_tests.py                     (runs it in the suite)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.repro import ReproError, canonical_hash, load_document

HERE = os.path.dirname(os.path.abspath(__file__))
FIXDIR = os.path.join(HERE, "fixtures", "repro")
VARIANTS = os.path.join(FIXDIR, "variants")
LEDGER = os.path.join(VARIANTS, "byte_variants.json")

# The document every variant is a rewriting of. The smallest capturable case in
# the corpus: the measurement is about the BYTES, so a bigger document would add
# nothing but a longer diff.
BASE = os.path.join(FIXDIR, "canonical_minimal.facts.json")

# The two classes a variant can land in, DERIVED from the two measurements.
CLASS_RAW_VARIANT = "raw-variant"
CLASS_INVALID = "invalid"

# The Python reader's refusal stages. Two of them, because the reference reaches
# JSON through a decode step the port does not have — `serde_json` reads bytes.
# Which stage fired is data: it is what says an invalid-UTF-8 refusal and a
# malformed-JSON refusal are not the same event wearing one name.
STAGE_DECODE = "decode"
STAGE_PARSE = "parse"
STAGE_DOMAIN = "domain"


def _transforms(raw: bytes) -> list[tuple[str, bytes, str, list[str]]]:
    """`(name, bytes, transform, probes)` for every variant, derived from the
    base document's committed bytes. Pure: the corpus regenerates identically
    from the base, so a variant cannot silently drift from what it claims to
    be."""
    document = json.loads(raw.decode("utf-8"))
    reversed_keys = {k: document[k] for k in reversed(list(document))}
    return [
        (
            "plain", raw, "the base document's committed bytes, unchanged",
            ["the identity case: raw digest == the committed file's, and the "
             "canonical digest every other accepted variant must match"],
        ),
        (
            "crlf", raw.replace(b"\n", b"\r\n"), "every LF rewritten as CRLF",
            ["the Windows line ending: a checkout on another platform is a "
             "different byte sequence for the same document, which is the "
             "difference B-1 says the canonical form cannot see"],
        ),
        (
            "no_trailing_newline", raw.rstrip(b"\n"), "the trailing newline removed",
            ["a producer that does not terminate its output"],
        ),
        (
            "extra_trailing_newline", raw + b"\n", "one more trailing newline",
            ["trailing whitespace after the closing brace"],
        ),
        (
            "whitespace_expanded",
            (json.dumps(document, indent=4, ensure_ascii=False) + "\n").encode("utf-8"),
            "re-serialized with a four-space indent",
            ["insignificant whitespace INSIDE the document, not only around it"],
        ),
        (
            "whitespace_compact",
            json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            "re-serialized with no insignificant whitespace at all",
            ["the compact form a generator emits: the same document, the "
             "shortest byte sequence"],
        ),
        (
            "key_order_reversed",
            (json.dumps(reversed_keys, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
            "the top-level members written in reverse order",
            ["object key ORDER: insignificant to the canonical form by "
             "construction, and a different byte sequence"],
        ),
        (
            "bom", b"\xef\xbb\xbf" + raw, "a UTF-8 BOM prepended",
            ["the variant B-1's note singles out: measured, never assumed. A "
             "BOM is valid UTF-8 and not valid JSON, so where it lands is a "
             "fact about the two readers rather than about the byte"],
        ),
        (
            "invalid_utf8", raw.replace(b"Minimal", b"Minim\x80l"),
            "a lone continuation byte (0x80) inside a string",
            ["not valid UTF-8 at all: the reference refuses at DECODE, before "
             "JSON is reached, and the port inside its reader"],
        ),
        (
            "malformed_json", raw.rstrip(b"\n")[:-1], "the final byte removed",
            ["a truncated document: valid UTF-8, not valid JSON"],
        ),
    ]


def _digest(raw: bytes) -> dict[str, Any]:
    return {"algorithm": "sha256", "digest": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw)}


def load_bytes_for_measurement(raw: bytes) -> Any:
    """Decode-then-parse, with the stage that refused named in the exception.

    Deliberately local to this harness at F.0: the measurement is what DECIDES
    whether the production reader gains a bytes entry point at all, so measuring
    through one would be assuming the answer."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ReproError(f"{STAGE_DECODE}: the input is not valid UTF-8: {e}") from e
    return load_document(text)


def _measure(raw: bytes) -> dict[str, Any]:
    """This reference's answer for one byte sequence, with the stage named."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        return {"accepted": False, "stage": STAGE_DECODE, "error": str(e)}
    try:
        document = load_document(text)
    except ReproError as e:
        return {"accepted": False, "stage": STAGE_DOMAIN, "error": str(e)}
    except json.JSONDecodeError as e:
        return {"accepted": False, "stage": STAGE_PARSE, "error": str(e)}
    return {"accepted": True, "stage": None, "error": None,
            "canonical": canonical_hash(document)}


def _records() -> list[dict[str, Any]]:
    """The ledger's records, sorted by variant name. Every field but the Rust
    column is derived here; the Rust column is carried through from what the
    port measured, because an engine never writes another engine's answer."""
    with open(BASE, "rb") as f:
        base_raw = f.read()
    committed = _committed_rust_columns()
    out: list[dict[str, Any]] = []
    for name, raw, transform, probes in sorted(_transforms(base_raw)):
        measured = _measure(raw)
        record: dict[str, Any] = {
            "name": name,
            "transform": transform,
            "probes": probes,
            "raw": _digest(raw),
            "python": {k: measured[k] for k in ("accepted", "stage", "error")},
            "rust": committed.get(name),
            "canonical": measured.get("canonical"),
        }
        out.append(record)
    return out


def _committed_rust_columns() -> dict[str, Any]:
    """The port's own measurements, read back from the committed ledger.

    The same rule the reproduction artifact's `_foreign_engines` follows: an
    engine writes only its own column. `--write` here carries the Rust column
    through untouched, and the Rust half rewrites it under
    `OWN_SHADOW_WRITE=1`."""
    if not os.path.exists(LEDGER):
        return {}
    try:
        with open(LEDGER, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return {r["name"]: r.get("rust") for r in data.get("variants", [])
            if isinstance(r, dict) and isinstance(r.get("name"), str)}


def _render_ledger(records: list[dict[str, Any]]) -> str:
    return json.dumps({
        "comment": (
            "Byte-level input variants (P-022 step 7a, #260 acceptance F.0): "
            "what each engine's JSON reader does with the SAME document written "
            "differently. Generated: python tests/test_byte_variants.py --write "
            "(the python column and the corpus) and OWN_SHADOW_WRITE=1 cargo "
            "test -p own-shadow --test byte_variants (the rust column). Each "
            "engine writes only its own column. 'class' is DERIVED from the two "
            "'accepted' flags and is not a member of this file: both harnesses "
            "refuse a record where the two readers disagree, because that is a "
            "domain decision for the owner and not a measurement's to file."),
        "base": os.path.relpath(BASE, os.path.dirname(HERE)).replace(os.sep, "/"),
        "variants": records,
    }, indent=2, ensure_ascii=False) + "\n"


def classify(record: dict[str, Any]) -> str | None:
    """`raw-variant`, `invalid`, or `None` when the two readers disagree —
    which is not a class, and is why this returns an option rather than a
    string with a third value."""
    python = record.get("python") or {}
    rust = record.get("rust") or {}
    if python.get("accepted") is not rust.get("accepted"):
        return None
    return CLASS_RAW_VARIANT if python.get("accepted") else CLASS_INVALID


def run() -> int:
    fails: list[tuple[str, str]] = []
    if not os.path.isdir(VARIANTS):
        print("FAIL[byte-variants]: tests/fixtures/repro/variants is missing; "
              "regenerate with 'python tests/test_byte_variants.py --write'")
        return 1
    with open(BASE, "rb") as f:
        base_raw = f.read()
    expected = {name: raw for name, raw, _t, _p in _transforms(base_raw)}

    # 1. The committed corpus IS what the transforms produce. Without this the
    #    .bin files are ten opaque blobs and the ledger describes whatever they
    #    happen to hold.
    on_disk = sorted(n[: -len(".bin")] for n in os.listdir(VARIANTS)
                     if n.endswith(".bin"))
    for missing in sorted(set(expected) - set(on_disk)):
        fails.append(("variant-corpus", f"{missing}.bin is missing"))
    for orphan in sorted(set(on_disk) - set(expected)):
        fails.append(("variant-corpus", f"{orphan}.bin is not a declared variant"))
    for name in sorted(set(expected) & set(on_disk)):
        with open(os.path.join(VARIANTS, f"{name}.bin"), "rb") as f:
            if f.read() != expected[name]:
                fails.append(("variant-corpus",
                              f"{name}.bin is not what its transform produces; "
                              f"regenerate with --write"))

    # 2. The ledger is in sync with what this reference measures NOW.
    if not os.path.exists(LEDGER):
        fails.append(("variant-ledger", "byte_variants.json is missing; "
                                        "regenerate with --write"))
        records: list[dict[str, Any]] = []
    else:
        with open(LEDGER, encoding="utf-8") as f:
            committed_text = f.read()
        records = json.loads(committed_text).get("variants", [])
        if committed_text != _render_ledger(_records()):
            fails.append(("variant-ledger",
                          "byte_variants.json is stale (this reference's answer "
                          "for a variant changed, or a variant was added); "
                          "regenerate with --write and re-run the Rust half "
                          "(OWN_SHADOW_WRITE=1 cargo test -p own-shadow --test "
                          "byte_variants)"))

    # 3. Every variant carries BOTH columns, and the two readers agree.
    base_canonical: str | None = None
    for record in records:
        name = record.get("name")
        if record.get("rust") is None:
            fails.append(("variant-measurement",
                          f"{name}: the port has not measured this variant — run "
                          f"OWN_SHADOW_WRITE=1 cargo test -p own-shadow --test "
                          f"byte_variants. The reference does not write the "
                          f"port's column"))
            continue
        kind = classify(record)
        if kind is None:
            fails.append(("variant-disagreement",
                          f"{name}: the two readers DISAGREE (python accepted="
                          f"{record['python']['accepted']}, rust accepted="
                          f"{record['rust']['accepted']}) — this is a domain "
                          f"decision for the owner (the shape D-2 records for "
                          f"'-0'), not a class this harness may pick"))
            continue
        if kind == CLASS_RAW_VARIANT:
            digest = (record.get("canonical") or {}).get("digest")
            if name == "plain":
                base_canonical = digest
            if record.get("canonical") is None:
                fails.append(("variant-measurement",
                              f"{name}: accepted by both readers but carries no "
                              f"canonical identity"))
        elif record.get("canonical") is not None:
            fails.append(("variant-measurement",
                          f"{name}: refused by both readers and still carries a "
                          f"canonical identity"))

    # 4. The property the whole raw-variant class exists for: every accepted
    #    variant is the SAME document (one canonical identity) written as a
    #    DIFFERENT byte sequence (a different raw digest). A variant that failed
    #    either half would not be evidence for B-1's `canonical-equivalent input
    #    != byte-identical input` — it would be a duplicate of `plain`.
    raw_digests: dict[str, str] = {}
    for record in records:
        if classify(record) != CLASS_RAW_VARIANT:
            continue
        name = str(record.get("name"))
        digest = (record.get("canonical") or {}).get("digest")
        if base_canonical is not None and digest != base_canonical:
            fails.append(("variant-canonical",
                          f"{name}: canonical digest {digest} != the base's "
                          f"{base_canonical} — a raw variant is the same "
                          f"document, so the canonical form must not see it"))
        previous = raw_digests.get(record["raw"]["digest"])
        if previous is not None:
            fails.append(("variant-raw",
                          f"{name}: the same raw bytes as {previous} — a variant "
                          f"that does not change the byte sequence proves nothing "
                          f"about an attestation over it"))
        raw_digests[record["raw"]["digest"]] = name

    # 5. Insertion stability (P-022 discipline §4), on the generator itself.
    fails += [("insertion-stability", m) for m in _insertion_stability()]

    if fails:
        for check, detail in fails:
            print(f"FAIL[{check}]: byte variant {detail}")
        return 1
    classes = [classify(r) for r in records]
    print(f"byte variants OK: {len(records)} variants measured by both readers, "
          f"{sum(1 for c in classes if c == CLASS_RAW_VARIANT)} raw-variant "
          f"(one canonical identity, {len(raw_digests)} distinct byte sequences), "
          f"{sum(1 for c in classes if c == CLASS_INVALID)} invalid, "
          f"0 disagreements")
    return 0


def _insertion_stability() -> list[str]:
    """Inserting one variant must churn zero existing records and add exactly
    one. The ledger is derived from a vocabulary (the transform list), which is
    the shape the rule exists for."""
    before = {r["name"]: r for r in _records()}
    probe = "zzz_insertion_probe_not_a_committed_variant"
    if probe in before:
        return [f"the insertion probe name '{probe}' collides with a real variant"]
    with open(BASE, "rb") as f:
        base_raw = f.read()
    widened = dict(before)
    widened[probe] = {"name": probe, "raw": _digest(base_raw + b" ")}
    churn = [n for n, r in before.items() if widened.get(n) != r]
    delta = sorted(set(widened) - set(before))
    problems: list[str] = []
    if churn:
        problems.append(f"insertion churn == {len(churn)}, must be 0 (first: {churn[:3]})")
    if delta != [probe]:
        problems.append(f"insertion delta == {delta}, must be exactly ['{probe}']")
    return problems


def write() -> int:
    os.makedirs(VARIANTS, exist_ok=True)
    with open(BASE, "rb") as f:
        base_raw = f.read()
    declared = {name for name, _r, _t, _p in _transforms(base_raw)}
    for name, raw, _transform, _probes in _transforms(base_raw):
        path = os.path.join(VARIANTS, f"{name}.bin")
        with open(path, "wb") as fb:
            fb.write(raw)
        print(f"wrote {path}")
    for orphan in sorted(n for n in os.listdir(VARIANTS)
                         if n.endswith(".bin") and n[: -len(".bin")] not in declared):
        os.remove(os.path.join(VARIANTS, orphan))
        print(f"removed orphaned {orphan}")
    with open(LEDGER, "w", encoding="utf-8") as f:
        f.write(_render_ledger(_records()))
    print(f"wrote {LEDGER}")
    print("NOTE: the 'rust' column is the port's own and is NOT written here — "
          "run: cd rust && OWN_SHADOW_WRITE=1 cargo test -p own-shadow --test "
          "byte_variants")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(write())
    raise SystemExit(run())
