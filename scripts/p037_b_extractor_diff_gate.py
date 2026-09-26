#!/usr/bin/env python3
"""P-037 Phase B / B1-F2 (widened by B1-F2-F2): the mechanical
production-diff gate on the extractor's legacy-consume-shortcut seam
(frontend/roslyn/OwnSharp.Extractor/).

B1 originally classified frontend/roslyn/OwnSharp.Extractor/ as measurement
INSTRUMENT, in full, with no carve-out (p037_evidence_b.INSTRUMENT_PATHS).
B2.0 then found -- and the owner independently re-verified against raw
extractor output, not just the source -- that the frozen A1 acceptance
matrix (docs/notes/p037-formal-kernel.md #8.1, items 5 and 8) requires an
extractor-side semantic change: `ConsumesParam`'s flow-insensitive "the
callee disposes this parameter SOMEWHERE, therefore this call releases its
argument" classification fabricates an unconditional `release` op at the
call site for a guard-sensitive callee, before either engine ever sees the
JSON (confirmed directly: `own-check.sh --emit-facts` is a byte copy of the
extractor's own output, `scripts/p037_controls.py`'s `release_lines()`
reads that copy). A treatment surface cannot simultaneously be frozen
measurement instrument -- that is B1-F2's own defect, not the original B1
brief's.

This gate is the item-level half of the repair (the other half is
p037_evidence_b.py's INSTRUMENT_PATHS/INSTRUMENT_CARVE_OUTS, corrected to
carve this exact unit out and rely on THIS gate to close the hole, the same
composition A2.2-D and B1 already use for mos.rs/lower.rs):

    path-level provenance carve-out  +  item-level production diff gate
    =  the actual permitted semantic boundary

Unit: frontend/roslyn/OwnSharp.Extractor/. Frozen file (byte-identical):
OwnSharp.Extractor.csproj (no new dependency may be added this way -- the
same discipline Cargo.toml gets in the Rust gate). Mutable, at NAMED-METHOD
granularity inside Program.cs: `EmitFlowExpr` ALONE (B1-F2-F4, correcting
B1-F2-F2's four-method seam). `ConsumeReleaseArgs`, `ConsumesParam` and
`CallReleasesReceiver` are FROZEN AGAIN.

WHY THE SEAM NARROWS BACK DOWN. B1-F2-F2 widened it to four methods
because its own design still needed the extractor to DECIDE, per call
site, whether a callee was "guard territory": a two-role split where
`ConsumeReleaseArgs`/`ConsumesParam` kept answering the tracking question
and `EmitFlowExpr` alone would ABSTAIN from fabricating `release` when the
callee's own guard shape made the legacy answer untrustworthy. Deriving
that abstention test hit an unresolved gap (B1-F2-F2's own Finding B):
G-V4-rejected guard candidates are invisible in the emitted `guarded_facts`
sidecar BY DESIGN (no entry at all, "not eligible" -- confirmed directly
on the real `gv4-control-aliased-self-null` fixture), so no rule reading
only the emitted sidecar could tell a rejected-guard callee from a
genuinely unguarded one; covering both would need `BuildGuardedFacts`
itself factored into a shared recognizer -- turning the sidecar's own
silence into a signal it was never built to carry.

B1-F2-F3a/F3a-R1/F3b (docs/notes/p037-formal-kernel.md, the B1-F2-F4
section) replaced that whole design. The extractor makes NO guard-
territory decision at all, ever, in either direction: `EmitFlowExpr`
uniformly turns every `ConsumeReleaseArgs`/`ConsumesParam`-derived
`release` into a `use` at the SAME call site, unconditionally -- no guard
inspection, no sidecar read, no eligibility test, no path-sensitivity.
`ConsumeReleaseArgs`/`ConsumesParam`'s TRACKING role (the escape/tracking
check at Program.cs's `consumedArg`) is therefore completely untouched --
B1-F2-F2's own proof that changing those two corrupts tracking is simply
avoided by never touching them again. Rust becomes the SOLE authority
deciding real interprocedural consume, reading the caller's own already-
emitted `guarded_facts.calls[]`/`guards[]` -- facts A2.2 already emits for
EVERY relevant call, including the ones the legacy heuristic wrongly
consumed (frozen note §10.3). `scripts/p037_delegation_closure.py` is the
governed, machine-derived proof that every legacy-fabricated release
already has exactly one such call fact waiting for Rust to read, over the
FULL frozen population -- the seam's own correctness proof, not this
gate's job to repeat.

`DisposesLocal`, `ParameterIsStable` (the existing G-V4 whole-body write-
exposure test), `CallReleasesReceiver` and `BuildGuardedFacts` (the
guarded_facts producer) all stay FROZEN: the owner's standing warning is
unchanged by this correction -- this gate must never license a second
guarded-summary engine written inside Roslyn. `CallReleasesReceiver`'s own
pre-existing field-path false positive (`corpus/p037-shapes/
extension-receiver`: an unconditionally-disposing extension method's
RECEIVER, not its argument, so this seam's argument-consume machinery
never reaches it at all) is explicitly out of A1's scope, not something
this narrower seam needs to, or may, touch.

Method extraction (`csharp_items`) does not attempt a general C# parser.
It only ever looks for a small, named set of top-level `static` method
definitions (the policy's mutable + registered keys) by signature, then
brace-balances each one's body using a conservative same-file character
classifier (line/block comments, char literals, regular/verbatim/
interpolated strings). Everything in the file NOT covered by one of those
named spans is a single opaque "remainder" item compared byte-for-byte --
this is what makes "any unrelated change in Program.cs is a violation"
correct without needing to enumerate every member of a 7000+-line file.
Round-trip losslessness (the named spans plus the remainder reconstruct
the original file exactly) is checked before any comparison runs, the
same discipline `p037_door_diff_gate.rust_items` uses for Rust.

Verdicts: IDENTICAL, WITHIN_ALLOWLIST, VIOLATION, REFUSED (exit 2) -- the
same four names as both existing production-diff gates, reusing
`p037_door_diff_gate`'s generic `compare_items`/`Tree`/`snapshot`/
`UnitReport`/`Refused` machinery unchanged (see that module's own
`compare_python` for the precedent this gate's `compare_csharp` mirrors:
one unit, one item-bearing file, one generic comparison call).

`IMMUTABLE_POLICY_FIELDS`/`policy_drift()` close the self-authorization
hole B1-F1 found in the Rust gate BEFORE this gate ever had the chance to
repeat it: `check()` never trusts the checked head's own recorded policy
without cross-checking it against this module's OWN hardcoded
`frozen_policy()`.

Run:  python scripts/p037_b_extractor_diff_gate.py check --reference <sha> [--head <sha>]
      python scripts/p037_b_extractor_diff_gate.py selftest
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Reused verbatim from the A2.2-D gate -- generic, not Rust-specific. See
# that module's own `compare_python`/`python_items` pair for the precedent
# this module's `compare_csharp`/`csharp_items` follows for a third
# language. compare_items in particular is the ONE language-agnostic law
# ("a mutable key may differ once; a registered key is new; everything
# else must match exactly or be a violation") every one of these gates
# shares.
from p037_door_diff_gate import (  # noqa: E402
    IDENTICAL,
    VIOLATION,
    WITHIN,
    WORKTREE,
    Refused,
    UnitReport,
    _normalize,
    compare_items,
    memory_tree,
    resolve,
    snapshot,
)

SCHEMA = "p037-b-extractor-diff-gate/1"
DEFAULT_RECORD = "docs/evidence/p037-b-epoch.json"
UNIT = "frontend/roslyn/OwnSharp.Extractor/"

FROZEN_FILES: tuple[str, ...] = ("OwnSharp.Extractor.csproj",)

# B1-F2-F4: EmitFlowExpr alone. B1-F2-F2 had widened this to four methods
# (ConsumeReleaseArgs, ConsumesParam, CallReleasesReceiver, EmitFlowExpr)
# for a "two decoupled roles" design that turned out to hit an unresolved
# gap (Finding B: G-V4-rejected guards are invisible in guarded_facts by
# design, so no sidecar-only rule can abstain correctly for them either).
# B1-F2-F3a/F3a-R1/F3b replaced that design with uniform delegation: the
# extractor never decides guard territory at all, in either direction.
# EmitFlowExpr alone still needs to be mutable (it is the ONE place that
# turns ConsumeReleaseArgs's answer into the fabricated `release` op, and
# the one place whose `consumed` set suppresses the matching `use`);
# ConsumeReleaseArgs/ConsumesParam/CallReleasesReceiver are FROZEN AGAIN,
# because uniform delegation never changes their tracking-facing answer at
# all -- B1-F2-F2's own proof that changing them corrupts caller tracking
# is avoided by construction, not by a narrower rule for changing them
# safely. See this module's own docstring and docs/notes/
# p037-formal-kernel.md's B1-F2-F4 section for the full history.
MUTABLE_METHODS: tuple[str, ...] = (
    "EmitFlowExpr",
)

REMAINDER_KEY = "(the rest of Program.cs)"


@dataclass(frozen=True)
class CSharpPolicy:
    unit: str
    frozen_files: tuple[str, ...]
    mutable_methods: tuple[str, ...]
    registered_methods: tuple[str, ...] = ()


# --------------------------------------------------------------------------- extraction


def _classify_csharp(src: str, path: str) -> list[str]:
    """One class per character: 'c' code, 'k' comment, 's' string/char literal.

    Deliberately conservative, not a full C# lexer: line/block comments (C#
    block comments do not nest), char literals, plain and verbatim (`@"..."`)
    strings, and interpolated (`$"..."`/`$@"..."`) strings where a single
    `{expr}` re-enters code classification (recursively, so a string literal
    INSIDE an interpolation is itself classified correctly) while a doubled
    `{{`/`}}` is the literal-brace escape. This is exactly the escape/nesting
    vocabulary the three target methods and their surrounding file actually
    use; selftest() proves it against the live source rather than trusting
    it in the abstract.
    """
    n = len(src)
    cls = ["c"] * n

    def mark(a: int, b: int, k: str) -> None:
        for idx in range(a, b):
            cls[idx] = k

    def is_ident_char(ch: str) -> bool:
        return ch.isalnum() or ch == "_"

    def scan_plain_string(i: int, quote: str = '"') -> int:
        """`i` is the opening quote's index; returns the index AFTER the closing quote."""
        j = i + 1
        while j < n:
            if src[j] == "\\" and j + 1 < n:
                mark(j, j + 2, "s")
                j += 2
                continue
            if src[j] == quote:
                return j + 1
            j += 1
        raise Refused(f"{path}: unterminated string literal at offset {i}")

    def scan_verbatim_string(i: int) -> int:
        """`i` is the opening quote's index (after `@`); "" is the escape."""
        j = i + 1
        while j < n:
            if src[j] == '"':
                if j + 1 < n and src[j + 1] == '"':
                    j += 2
                    continue
                return j + 1
            j += 1
        raise Refused(f"{path}: unterminated verbatim string literal at offset {i}")

    def scan_interpolated(i: int, verbatim: bool) -> int:
        """`i` is the opening quote's index; handles `{{`/`}}` escapes and a
        single `{...}` re-entering code classification (brace-balanced,
        recursively re-classified so nested strings are handled right)."""
        j = i + 1
        while j < n:
            ch = src[j]
            if not verbatim and ch == "\\" and j + 1 < n:
                mark(j, j + 2, "s")
                j += 2
                continue
            if verbatim and ch == '"':
                if j + 1 < n and src[j + 1] == '"':
                    j += 2
                    continue
                return j + 1
            if not verbatim and ch == '"':
                return j + 1
            if ch == "{" and j + 1 < n and src[j + 1] == "{":
                j += 2
                continue
            if ch == "}" and j + 1 < n and src[j + 1] == "}":
                j += 2
                continue
            if ch == "{":
                depth = 1
                k = j + 1
                while k < n and depth > 0:
                    if src[k] == "{":
                        depth += 1
                        k += 1
                    elif src[k] == "}":
                        depth -= 1
                        k += 1
                    elif src[k] == '"':
                        k = scan_plain_string(k)
                    elif src[k] == "'":
                        maybe = _try_char_literal(src, k, n)
                        k = maybe if maybe is not None else k + 1
                    else:
                        k += 1
                if depth != 0:
                    raise Refused(f"{path}: unterminated interpolation at offset {j}")
                j = k
                continue
            j += 1
        raise Refused(f"{path}: unterminated interpolated string literal at offset {i}")

    def _try_char_literal(s: str, i: int, length: int) -> int | None:
        if i + 1 < length and s[i + 1] == "\\":
            k = i + 2
            while k < length and s[k] != "'":
                k += 1
            if k < length:
                return k + 1
            return None
        if i + 2 < length and s[i + 2] == "'" and s[i + 1] != "'":
            return i + 3
        return None

    i = 0
    while i < n:
        ch = src[i]
        if ch == "/" and src.startswith("//", i):
            end = src.find("\n", i)
            end = n if end < 0 else end
            mark(i, end, "k")
            i = end
            continue
        if ch == "/" and src.startswith("/*", i):
            end = src.find("*/", i + 2)
            if end < 0:
                raise Refused(f"{path}: unterminated block comment at offset {i}")
            mark(i, end + 2, "k")
            i = end + 2
            continue
        prev_ident = i > 0 and is_ident_char(src[i - 1])
        if ch == "$" and not prev_ident and i + 1 < n and src[i + 1] in ('"', "@"):
            verbatim = src[i + 1] == "@"
            start = i + 2 if not verbatim else i + 3
            if verbatim and (i + 2 >= n or src[i + 2] != '"'):
                i += 1
                continue
            mark(i, start, "s")
            end = scan_interpolated(start - 1, verbatim)
            mark(start - 1, end, "s")
            i = end
            continue
        if ch == "@" and not prev_ident and i + 1 < n and src[i + 1] == '"':
            mark(i, i + 2, "s")
            end = scan_verbatim_string(i + 1)
            mark(i + 1, end, "s")
            i = end
            continue
        if ch == '"':
            end = scan_plain_string(i)
            mark(i, end, "s")
            i = end
            continue
        if ch == "'" and not prev_ident:
            maybe = _try_char_literal(src, i, n)
            if maybe is not None:
                mark(i, maybe, "s")
                i = maybe
                continue
        i += 1
    return cls


def csharp_items(source: str, path: str, names: tuple[str, ...]) -> list[tuple[str, str]]:
    """(key, normalized body) pairs: one per named top-level method found in
    `names` (by signature `static ... <Name>(`), plus exactly one
    REMAINDER_KEY item covering everything else in the file, in original
    file order collapsed to a single string. Bodies are returned in
    NORMALIZED form (p037_door_diff_gate._normalize: comments dropped,
    whitespace runs collapsed to one space) -- the same whitespace/comment
    -insensitive comparison rust_items already uses for every Rust item
    (RustItem.norm). Without this, reformatting or adding a blank line next
    to a genuinely new REGISTERED method would leave scar tissue in the
    surrounding text that masquerades as an unrelated change to "the rest
    of Program.cs" -- a real bug this function's own selftest() caught
    (registered-helper-is-allowed) before this docstring was corrected to
    describe it.

    Round-trip losslessness of the RAW spans (every extracted span plus the
    remainder, back in file order, reconstruct `source` exactly, byte for
    byte) is checked FIRST, before anything is normalized -- a silent
    mis-scope here would recreate exactly the kind of instrument bug B1-F2
    exists to close, so this is not optional. Normalization only changes
    what gets COMPARED; it never changes what extraction is proven to
    cover.
    """
    cls = _classify_csharp(source, path)
    n = len(source)
    spans: list[tuple[int, int, str]] = []  # (start, end, name)
    for name in names:
        pat = re.compile(
            r"static\s+[A-Za-z_][\w<>\[\],\.\?\s]*?\b" + re.escape(name) + r"\s*\(")
        found_at: int | None = None
        pos = 0
        while True:
            m = pat.search(source, pos)
            if m is None:
                break
            # only a match sitting entirely in 'c' (code) class counts --
            # skip a hit inside a comment or a string literal.
            if all(cls[k] == "c" for k in range(m.start(), m.end())):
                found_at = m.start()
                break
            pos = m.end()
        if found_at is None:
            continue  # legal: a registered-but-not-yet-defined name, or absent from this side
        paren = 0
        j = m.end() - 1  # at the '('
        while j < n:
            if source[j] == "(" and cls[j] == "c":
                paren += 1
            elif source[j] == ")" and cls[j] == "c":
                paren -= 1
                if paren == 0:
                    j += 1
                    break
            j += 1
        else:
            raise Refused(f"{path}: unterminated parameter list for {name!r}")
        while j < n and source[j] != "{":
            j += 1
        if j >= n:
            raise Refused(f"{path}: no body found for {name!r}")
        body_start = j
        brace = 0
        end = -1
        k = body_start
        while k < n:
            if source[k] == "{" and cls[k] == "c":
                brace += 1
            elif source[k] == "}" and cls[k] == "c":
                brace -= 1
                if brace == 0:
                    end = k + 1
                    break
            k += 1
        if end < 0:
            raise Refused(f"{path}: unbalanced braces in {name!r} starting at offset {found_at}")
        spans.append((found_at, end, name))
    spans.sort()
    for (_s1, e1, n1), (s2, _e2, n2) in itertools.pairwise(spans):
        if s2 < e1:
            raise Refused(f"{path}: {n1!r} and {n2!r} extraction spans overlap")

    # Raw round-trip losslessness FIRST, in raw bytes, before any
    # normalization: proves the named spans plus the gaps between/around
    # them exactly cover `source` with no overlap and no missing byte.
    raw_parts: list[str] = []
    cursor = 0
    for start, end, _name in spans:
        raw_parts.append(source[cursor:start])
        raw_parts.append(source[start:end])
        cursor = end
    raw_parts.append(source[cursor:])
    if "".join(raw_parts) != source:
        raise Refused(f"{path}: the item split is not lossless")

    items: list[tuple[str, str]] = []
    cursor = 0
    remainder_text_parts: list[str] = []
    remainder_cls_parts: list[list[str]] = []
    for start, end, name in spans:
        remainder_text_parts.append(source[cursor:start])
        remainder_cls_parts.append(cls[cursor:start])
        items.append((f"static {name}", _normalize(source, cls, start, end)))
        cursor = end
    remainder_text_parts.append(source[cursor:])
    remainder_cls_parts.append(cls[cursor:])
    remainder_text = "".join(remainder_text_parts)
    remainder_cls = [c for part in remainder_cls_parts for c in part]
    items.append((REMAINDER_KEY, _normalize(remainder_text, remainder_cls, 0, len(remainder_text))))
    return items


def compare_csharp(ref: Any, head: Any, pol: CSharpPolicy) -> UnitReport:
    """The C# analogue of p037_door_diff_gate.compare_python: one unit, one
    item-bearing file (Program.cs, at named-method granularity), one
    frozen file (the .csproj), everything else a violation if it appears
    at all -- the same exhaustiveness compare_rust's own final `else`
    branch enforces."""
    unit = pol.unit
    rep = UnitReport(unit)
    for rel in pol.frozen_files:
        if unit + rel not in ref:
            raise Refused(f"{unit}{rel}: named by the policy, absent from the reference")
    program_cs = unit + "Program.cs"
    if program_cs not in ref:
        raise Refused(f"{program_cs}: absent from the reference")
    paths = sorted({p for p in ref if p.startswith(unit)} | {p for p in head if p.startswith(unit)})
    all_names = tuple(dict.fromkeys((*pol.mutable_methods, *pol.registered_methods)))
    for path in paths:
        rel = path[len(unit):]
        in_ref, in_head = path in ref, path in head
        same = in_ref and in_head and ref[path].oid == head[path].oid
        if rel in pol.frozen_files:
            if not in_head:
                rep.violate(f"{path} removed (frozen)")
            elif not same:
                rep.violate(f"{path} changed (frozen)")
            continue
        if rel == "Program.cs":
            if not in_head:
                rep.violate(f"{path} removed")
                continue
            ref_items = csharp_items(_text(ref, path), path, all_names)
            head_items = csharp_items(_text(head, path), path, all_names)
            mutable_keys = tuple(f"static {name}" for name in pol.mutable_methods)
            registered_keys = tuple(f"static {name}" for name in pol.registered_methods)
            compare_items(ref_items, head_items, mutable_keys, registered_keys, rep, path)
            continue
        if in_ref:
            raise Refused(f"{path}: a production file of the reference that "
                          f"p037_b_extractor_diff_gate does not cover")
        rep.violate(f"{path} added (production file outside the allowlist)")
    return rep


def _text(tree: Any, path: str) -> str:
    try:
        return tree[path].read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refused(f"{path}: not UTF-8: {exc}") from exc


# --------------------------------------------------------------------------- policy


def frozen_policy() -> dict[str, Any]:
    """The B1-F2 production_diff_gate.extractor section this module ships
    with -- the same object docs/evidence/p037-b-epoch.json's
    production_diff_gate.extractor must equal, so the record and this
    module cannot silently drift apart (the exact self-authorization hole
    B1-F1 found and fixed in the Rust gate, closed here from the start)."""
    return {
        "unit": UNIT,
        "frozen_files": list(FROZEN_FILES),
        "mutable_methods": list(MUTABLE_METHODS),
        "registered_methods": [],
    }


IMMUTABLE_POLICY_FIELDS: tuple[str, ...] = ("unit", "frozen_files", "mutable_methods")


def policy_drift(record_extractor: dict[str, Any]) -> list[str]:
    """Refuses a record whose IMMUTABLE_POLICY_FIELDS disagree with this
    module's own frozen_policy() -- see scripts/p037_b_production_diff_gate.
    py's policy_drift() for the identical mechanism and the exact
    self-authorization hole it exists to close: check() must never accept
    the allowlist it reads from the very head it is validating."""
    frozen = frozen_policy()
    problems = []
    for field_name in IMMUTABLE_POLICY_FIELDS:
        if record_extractor.get(field_name) != frozen[field_name]:
            problems.append(
                f"production_diff_gate.extractor.{field_name} differs from this module's own "
                f"frozen_policy(): record={record_extractor.get(field_name)!r} "
                f"frozen={frozen[field_name]!r}")
    return problems


def _policy(record_extractor: dict[str, Any]) -> CSharpPolicy:
    registered = tuple(record_extractor.get("registered_methods", ()))
    overlap = set(registered) & set(MUTABLE_METHODS)
    if overlap:
        raise Refused(f"registered_methods names already-mutable method(s): {sorted(overlap)}")
    return CSharpPolicy(
        unit=str(record_extractor["unit"]),
        frozen_files=tuple(record_extractor.get("frozen_files", ())),
        mutable_methods=tuple(record_extractor.get("mutable_methods", ())),
        registered_methods=registered,
    )


def load_record(rev: str, record_path: str, repo: Path = ROOT) -> dict[str, Any]:
    if rev == WORKTREE:
        text = (repo / record_path).read_text(encoding="utf-8")
    else:
        from p037_door_diff_gate import _show  # deliberately narrow, WORKTREE-only import
        text = _show(rev, record_path, repo).decode("utf-8")
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise Refused(f"{record_path}: not an object")
    return doc


def check(reference: str, head: str, record_path: str = DEFAULT_RECORD,
          repo: Path = ROOT) -> dict[str, Any]:
    ref_sha = resolve(reference, repo)
    head_sha = resolve(head, repo)
    if ref_sha == WORKTREE:
        raise Refused("the reference must be a commit")
    doc = load_record(head_sha, record_path, repo)
    if doc.get("epoch") != "b":
        raise Refused(f"{record_path} at {head_sha[:12]} names epoch {doc.get('epoch')!r}, "
                      "not 'b'; this gate measures Phase B only")
    gate_section = doc.get("production_diff_gate")
    if not isinstance(gate_section, dict) or not isinstance(gate_section.get("extractor"), dict):
        raise Refused(f"{record_path}: no production_diff_gate.extractor section")
    drift = policy_drift(gate_section["extractor"])
    if drift:
        raise Refused("; ".join(drift))
    pol = _policy(gate_section["extractor"])
    ref_tree = snapshot(ref_sha, [pol.unit], repo)
    head_tree = snapshot(head_sha, [pol.unit], repo)
    unit = compare_csharp(ref_tree, head_tree, pol)
    return {
        "schema": SCHEMA,
        "reference": ref_sha,
        "head": head_sha,
        "record": f"{head_sha}:{record_path}",
        "verdict": unit.verdict,
        "unit": unit.as_dict(),
    }


def print_report(rep: dict[str, Any]) -> None:
    unit = rep["unit"]
    print(f"unit {unit['unit']}: {unit['verdict']}")
    for line in unit["allowed"]:
        print(f"  allowed: {line}")
    for line in unit["violations"]:
        print(f"  VIOLATION: {line}")
    for line in unit["controls_moved"]:
        print(f"  control moved: {line}")
    print(f"RESULT: p037-b-extractor-diff-gate {rep['verdict']} "
          f"reference={rep['reference'][:12]} head={rep['head'][:12]}")


# --------------------------------------------------------------------------- selftest

_failures = 0


def _selfcheck(name: str, ok: bool, detail: object = "") -> None:
    global _failures
    if ok:
        print(f"ok[{name}]")
    else:
        _failures += 1
        print(f"FAIL[{name}]: {detail}")


_REF_CSPROJ = ("<Project Sdk=\"Microsoft.NET.Sdk\">"
              "<TargetFramework>net8.0</TargetFramework></Project>\n")

_REF_PROGRAM = '''// header comment
using System;

static class Program
{
    static void Main(string[] args) { Console.WriteLine("hi"); }

    // an unrelated frozen helper -- must never move under this policy
    static bool DisposesLocal(string name)
    {
        return name.Length > 0;
    }

    static List<string> ConsumeReleaseArgs(int e, int model)
    {
        var consumed = new List<string>();
        return consumed;
    }

    static bool ConsumesParam(int method, int param)
    {
        return false;
    }

    static bool CallReleasesReceiver(int sym)
    {
        return false;
    }

    // B1-F2-F2: a void-returning, multi-parameter sentinel shaped like the
    // real EmitFlowExpr -- proves the extraction regex handles a `void`
    // return and more than one parameter, not just the three original
    // methods' shapes.
    static void EmitFlowExpr(int expr, int tracked, int model)
    {
        Console.WriteLine("noop");
    }
}
'''


def _mem_policy(**overrides: Any) -> CSharpPolicy:
    base: dict[str, Any] = {
        "unit": "crate/",
        "frozen_files": ("OwnSharp.Extractor.csproj",),
        "mutable_methods": ("EmitFlowExpr",),
        "registered_methods": (),
    }
    base.update(overrides)
    return CSharpPolicy(**base)


def selftest() -> int:
    ref = memory_tree({
        "crate/OwnSharp.Extractor.csproj": _REF_CSPROJ,
        "crate/Program.cs": _REF_PROGRAM,
    })
    pol = _mem_policy()

    rep = compare_csharp(ref, ref, pol)
    _selfcheck("identical-head-is-identical", rep.verdict == IDENTICAL, rep.as_dict())

    # B1-F2-F4: EmitFlowExpr is the sole mutable method -- proves the
    # narrowed policy still permits it to move, on its own dedicated shape
    # (void return, multiple parameters).
    head = memory_tree({
        "crate/OwnSharp.Extractor.csproj": _REF_CSPROJ,
        "crate/Program.cs": _REF_PROGRAM.replace(
            "static void EmitFlowExpr(int expr, int tracked, int model)\n"
            "    {\n        Console.WriteLine(\"noop\");\n    }",
            "static void EmitFlowExpr(int expr, int tracked, int model)\n"
            "    {\n        Console.WriteLine(\"changed\");\n    }"),
    })
    rep = compare_csharp(ref, head, pol)
    _selfcheck("emitflowexpr-is-the-sole-mutable-method", rep.verdict == WITHIN, rep.as_dict())

    # B1-F2-F4: the three methods B1-F2/B1-F2-F2 had authorized are FROZEN
    # AGAIN -- each must now VIOLATE if changed, folded back into "the rest
    # of Program.cs" opaque remainder exactly like every other frozen method
    # in the file (DisposesLocal, ParameterIsStable, BuildGuardedFacts).
    head = memory_tree({
        "crate/OwnSharp.Extractor.csproj": _REF_CSPROJ,
        "crate/Program.cs": _REF_PROGRAM.replace(
            "static bool ConsumesParam(int method, int param)\n    {\n        return false;\n    }",
            "static bool ConsumesParam(int method, int param)\n    {\n        return true;\n    }"),
    })
    rep = compare_csharp(ref, head, pol)
    _selfcheck("consumesparam-is-frozen-again", rep.verdict == VIOLATION, rep.as_dict())

    head = memory_tree({
        "crate/OwnSharp.Extractor.csproj": _REF_CSPROJ,
        "crate/Program.cs": _REF_PROGRAM.replace(
            "static List<string> ConsumeReleaseArgs(int e, int model)\n"
            "    {\n        var consumed = new List<string>();\n        return consumed;\n    }",
            "static List<string> ConsumeReleaseArgs(int e, int model)\n"
            "    {\n        return new List<string>();\n    }"),
    })
    rep = compare_csharp(ref, head, pol)
    _selfcheck("consumereleaseargs-is-frozen-again", rep.verdict == VIOLATION, rep.as_dict())

    head = memory_tree({
        "crate/OwnSharp.Extractor.csproj": _REF_CSPROJ,
        "crate/Program.cs": _REF_PROGRAM.replace(
            "static bool CallReleasesReceiver(int sym)\n    {\n        return false;\n    }",
            "static bool CallReleasesReceiver(int sym)\n    {\n        return true;\n    }"),
    })
    rep = compare_csharp(ref, head, pol)
    _selfcheck("callreleasesreceiver-is-frozen-again", rep.verdict == VIOLATION, rep.as_dict())

    head = memory_tree({
        "crate/OwnSharp.Extractor.csproj": _REF_CSPROJ,
        "crate/Program.cs": _REF_PROGRAM.replace(
            "return name.Length > 0;", "return name.Length >= 0;"),
    })
    rep = compare_csharp(ref, head, pol)
    _selfcheck("unrelated-item-changed-is-violation", rep.verdict == VIOLATION, rep.as_dict())

    head = memory_tree({
        "crate/OwnSharp.Extractor.csproj": _REF_CSPROJ,
        "crate/Program.cs": _REF_PROGRAM.replace(
            "static void Main(string[] args) { Console.WriteLine(\"hi\"); }",
            "static void Main(string[] args) { Console.WriteLine(\"hi\"); }\n\n"
            "    static bool NewHelper() { return true; }"),
    })
    rep = compare_csharp(ref, head, pol)
    _selfcheck("new-unregistered-helper-is-violation", rep.verdict == VIOLATION, rep.as_dict())

    reg_pol = _mem_policy(registered_methods=("NewHelper",))
    rep = compare_csharp(ref, head, reg_pol)
    _selfcheck("registered-helper-is-allowed", rep.verdict == WITHIN, rep.as_dict())

    frozen = frozen_policy()
    tampered = copy.deepcopy(frozen)
    tampered["mutable_methods"] = [*tampered["mutable_methods"], "SmuggledInTheSameCommit"]
    _selfcheck("policy-drift-catches-added-mutable-method", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["frozen_files"] = []
    _selfcheck("policy-drift-catches-emptied-frozen-files", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["unit"] = "frontend/roslyn/OwnSharp.Cli/"
    _selfcheck("policy-drift-catches-changed-unit", bool(policy_drift(tampered)),
              policy_drift(tampered))

    tampered = copy.deepcopy(frozen)
    tampered["registered_methods"] = ["SomeNewHelper"]
    _selfcheck("policy-drift-allows-registered-methods-alone", not policy_drift(tampered),
              policy_drift(tampered))

    _selfcheck("policy-drift-clean-on-frozen-policy-itself", not policy_drift(frozen),
              policy_drift(frozen))

    # a frozen file changing is a violation, matching the Rust gate's own control
    head = memory_tree({
        "crate/OwnSharp.Extractor.csproj": _REF_CSPROJ.replace("net8.0", "net9.0"),
        "crate/Program.cs": _REF_PROGRAM,
    })
    rep = compare_csharp(ref, head, pol)
    _selfcheck("frozen-csproj-changed-is-violation", rep.verdict == VIOLATION, rep.as_dict())

    # live-source sanity: the three named methods really exist, extraction is
    # lossless, and round-tripping them plus the remainder reproduces the file
    # exactly -- catches a future rename of any of the three silently
    # dropping out of this gate's protection.
    program_path = ROOT / "frontend" / "roslyn" / "OwnSharp.Extractor" / "Program.cs"
    live_src = program_path.read_text(encoding="utf-8")
    live_items = csharp_items(live_src, "Program.cs", MUTABLE_METHODS)
    live_keys = {k for k, _ in live_items}
    expected_keys = {f"static {name}" for name in MUTABLE_METHODS} | {REMAINDER_KEY}
    _selfcheck("live-source-mutable-methods-all-found", live_keys == expected_keys,
              f"found={sorted(live_keys)} expected={sorted(expected_keys)}")
    # csharp_items() itself already raises Refused on a lossy raw split
    # (checked in raw bytes before normalization -- see its docstring), so
    # reaching this line at all is the round-trip proof for the live file;
    # what's left to check here is that the three named bodies look right.
    for name in MUTABLE_METHODS:
        body = dict(live_items)[f"static {name}"]
        _selfcheck(f"live-source-{name}-starts-with-its-own-signature",
                  body.lstrip().startswith("static") and name in body.split("{", 1)[0],
                  body[:80])
        _selfcheck(f"live-source-{name}-body-is-balanced",
                  body.count("{") == body.count("}") and body.count("{") > 0,
                  (body.count("{"), body.count("}")))

    if _failures:
        print(f"RESULT: {_failures} check(s) failed")
        return 1
    print("RESULT: p037-b-extractor-diff-gate selftest: all checks pass")
    return 0


# --------------------------------------------------------------------------- CLI


def _cmd_check(args: argparse.Namespace) -> int:
    try:
        rep = check(args.reference, args.head, args.record)
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print_report(rep)
    if args.require == "identical":
        return 0 if rep["verdict"] == IDENTICAL else 1
    return 0 if rep["verdict"] in (IDENTICAL, WITHIN) else 1


def _cmd_frozen_policy(_: argparse.Namespace) -> int:
    print(json.dumps(frozen_policy(), indent=2, sort_keys=True))
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check")
    p.add_argument("--reference", required=True)
    p.add_argument("--head", default="HEAD")
    p.add_argument("--record", default=DEFAULT_RECORD)
    p.add_argument("--require", choices=("identical", "allowlist"), default="identical")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("frozen-policy",
                       help="print the production_diff_gate.extractor object this module "
                            "ships with")
    p.set_defaults(func=_cmd_frozen_policy)

    p = sub.add_parser("selftest")
    p.set_defaults(func=lambda _a: selftest())

    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
