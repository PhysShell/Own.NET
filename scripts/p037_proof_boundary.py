#!/usr/bin/env python3
"""P-037 Phase B entry gate: the §10.4 proof-boundary audit.

docs/notes/p037-formal-kernel.md §10.4, verbatim: "Phase B may not begin
semantic wiring until the P-037 proof-boundary audit is green. The audit
must derive the Kani harness inventory from source/Kani, check that the
fast and heavy CI sets are disjoint and their union equals the source set,
record the human claim and production subject for every harness, and make
every load-bearing assumption traceable to either a production guarantor
or an explicit OUTSIDE_KANI_BOUNDARY entry."

This script is the audit. Every fact it reports is derived from the live
tree at run time -- the Kani harness inventory from
formal/p037-kernel/src/properties/*.rs, the fast set from
.github/workflows/ci.yml's formal-p037 job, the heavy set from
.github/workflows/formal-p037-gate.yml -- never hand-copied and never
trusted from a prior run. The two ledgers under docs/evidence/
(p037-b-ledger-harnesses.json, p037-b-ledger-assumptions.json) carry the
one thing a scanner cannot derive by itself: what each harness claims,
what production concept it constrains, and why each load-bearing
kani::assume is either a production-backed fact or an explicitly named
obligation outside this crate's proof boundary. This script checks the
ledgers account for exactly the source it finds -- no more, no fewer rows
-- it does not author their content.

Ambiguous source structure is refused, never guessed through (exit 2,
REFUSED): an unrecognized shape between #[kani::proof] and its fn, an
unbalanced kani::assume(...) call, a CI harness loop this script cannot
parse. A clean run that finds real problems is RED (exit 1), not REFUSED
-- REFUSED means the audit could not even form an opinion; RED means it
formed one and it says something is missing. Per §10.4's own words, this
audit does not demand one kani::cover per kani::assume; it demands a named
non-vacuity witness per load-bearing restriction, and says GAP plainly
where none was found rather than inventing one.

Both source derivations run over LEXICALLY MASKED text (_mask_non_code):
// and /* nested */ comments, "strings" (with backslash escapes), br#"raw
strings"# at any hash depth, and 'c' char literals are blanked to spaces
(length- and newline-preserving) before either #[kani::proof] or
kani::assume( is searched for -- so `kani::assume(...)` inside a comment
or a string is prose, not a call site, and cannot manufacture a phantom
assumption the way one did during this audit's own development (a design
comment that named the call literally, in prose, was briefly read back as
a 24th assume site). An unterminated comment, string, raw string, or
char-literal escape is refused (exit 2), same as an unbalanced
kani::assume( -- never guessed past. Lifetimes ('a, 'static) are left
unmasked: they are real code, not opaque lexical content.

Run:  python scripts/p037_proof_boundary.py
      python tests/test_p037_proof_boundary.py   (adversarial self-tests)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PROPERTIES_DIR = ROOT / "formal" / "p037-kernel" / "src" / "properties"
CI_FAST_FILE = ROOT / ".github" / "workflows" / "ci.yml"
CI_HEAVY_FILE = ROOT / ".github" / "workflows" / "formal-p037-gate.yml"
HARNESS_LEDGER = ROOT / "docs" / "evidence" / "p037-b-ledger-harnesses.json"
ASSUMPTION_LEDGER = ROOT / "docs" / "evidence" / "p037-b-ledger-assumptions.json"

# The properties/*.rs files that declare #[kani::proof] harnesses. mod.rs
# declares none itself (verified: 0 #[kani::proof] there) but its
# `symbolic` module holds kani::assume sites reached by harnesses in the
# files below, so it is scanned for assumes only, separately.
HARNESS_FILES = (
    "application.rs", "election.rs", "lattice.rs",
    "refinement.rs", "solver.rs", "transforms.rs",
)
ASSUME_FILES = (*HARNESS_FILES, "mod.rs")

VALID_DISPOSITIONS = {"PRODUCTION_GUARANTOR", "OUTSIDE_KANI_BOUNDARY"}


class Refused(Exception):
    """Source or CI structure this scanner declines to guess through."""


def _read(path: Path) -> str:
    if not path.is_file():
        raise Refused(f"{path} does not exist")
    return path.read_text(encoding="utf-8")


# --- lexical masking: comments/strings/chars are prose, not source ---------

_RAW_STRING_OPENER = re.compile(r'b?r(#*)"')
_ASSUME_TOKEN = re.compile(r"kani\s*::\s*assume\s*\(")


def _line_at(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _char_literal_end(text: str, i: int, label: str) -> int | None:
    """`text[i] == "'"`. Returns the index just past a char literal's
    closing quote, or None if `'` starts a lifetime (`'a`, `'static`) or is
    otherwise not a char literal -- left as ordinary code, never masked.
    An escape-form literal (`'\\n'`, `'\\''`, `'\\u{...}'`, ...) whose
    closing quote is not found within a short, generous bound is refused:
    no valid escape needs more than a few characters, so this is malformed
    input, not a long-distance lifetime coincidence."""
    n = len(text)
    if i + 1 >= n:
        return None
    if text[i + 1] == "\\":
        close = text.find("'", i + 2, min(n, i + 2 + 16))
        if close == -1:
            raise Refused(f"{label}:{_line_at(text, i)}: unterminated char literal "
                          f"(escape opens at column {i + 1}); refusing to guess its extent")
        return close + 1
    if i + 2 < n and text[i + 2] == "'":
        return i + 3
    return None  # a lifetime, or a lone quote that is not a char literal


def _mask_non_code(text: str, label: str) -> str:
    """`text` with every // and /* nested */ comment, "string" (\\-escaped),
    br#"raw string"# (any hash depth) and 'c' char literal replaced by
    spaces -- same length, newlines preserved, so a match found in the
    result indexes directly into `text` for both offset and line number.
    Lifetimes are left untouched (real code, not opaque content). Refuses
    (does not guess through) an unterminated comment, string or raw string.
    """
    out = list(text)
    n = len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    i = 0
    while i < n:
        c = text[i]
        if text[i:i + 2] == "//":
            end = text.find("\n", i)
            end = n if end == -1 else end
            blank(i, end)
            i = end
            continue
        if text[i:i + 2] == "/*":
            depth = 1
            j = i + 2
            while j < n and depth:
                two = text[j:j + 2]
                if two == "/*":
                    depth += 1
                    j += 2
                elif two == "*/":
                    depth -= 1
                    j += 2
                else:
                    j += 1
            if depth:
                raise Refused(f"{label}:{_line_at(text, i)}: unterminated block comment "
                              f"(opens here); refusing to guess its extent")
            blank(i, j)
            i = j
            continue
        m = _RAW_STRING_OPENER.match(text, i)
        if m:
            closer = '"' + m.group(1)
            j = text.find(closer, m.end())
            if j == -1:
                raise Refused(f"{label}:{_line_at(text, i)}: unterminated raw string "
                              f"(opens here); refusing to guess its extent")
            end = j + len(closer)
            blank(i, end)
            i = end
            continue
        if c == '"':
            j, closed = i + 1, False
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    closed = True
                    break
                j += 1
            if not closed:
                raise Refused(f"{label}:{_line_at(text, i)}: unterminated string "
                              f"(opens here); refusing to guess its extent")
            blank(i, j)
            i = j
            continue
        if c == "'":
            end = _char_literal_end(text, i, label)
            if end is not None:
                blank(i, end)
                i = end
                continue
        i += 1
    return "".join(out)


# --- source-derived Kani harness inventory ---------------------------------


def derive_source_harnesses() -> dict[str, tuple[str, int]]:
    """harness name -> (relative file, 1-based line of its `fn`).

    Scans for a line that is EXACTLY `#[kani::proof]` (stripped), then skips
    any further bare attribute lines (`#[kani::unwind(21)]` and the like,
    confirmed present in this tree) and blank lines, and requires the next
    non-blank line to start with a plain `fn NAME(`. Anything else -- no
    following fn, a doc comment, a differently-shaped attribute -- is
    refused rather than guessed past.
    """
    found: dict[str, tuple[str, int]] = {}
    for fname in HARNESS_FILES:
        path = PROPERTIES_DIR / fname
        lines = _read(path).splitlines()
        for i, line in enumerate(lines):
            if line.strip() != "#[kani::proof]":
                continue
            j = i + 1
            while j < len(lines):
                stripped = lines[j].strip()
                if stripped == "":
                    j += 1
                    continue
                if re.fullmatch(r"#\[[^\[\]]*\]", stripped):
                    j += 1
                    continue
                break
            if j >= len(lines):
                raise Refused(
                    f"{fname}:{i + 1}: #[kani::proof] has no following fn before end of file")
            m = re.match(r"fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", lines[j].strip())
            if not m:
                raise Refused(
                    f"{fname}:{i + 1}: #[kani::proof] is not followed by a recognizable "
                    f"`fn NAME(` line (line {j + 1} is {lines[j].strip()!r}); refusing to guess")
            name = m.group(1)
            if name in found:
                raise Refused(
                    f"duplicate harness name {name!r} at {fname}:{j + 1} and {found[name]}")
            found[name] = (f"properties/{fname}", j + 1)
    return found


# --- source-derived kani::assume inventory ---------------------------------


def _extract_call_args(text: str, open_paren_pos: int) -> tuple[str, int] | None:
    """`text[open_paren_pos]` must be '('. Returns (argument text, index just
    past the matching ')'), or None if the parens never balance in `text`."""
    depth = 0
    for i in range(open_paren_pos, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren_pos + 1:i], i + 1
    return None


def derive_source_assumes() -> list[dict[str, Any]]:
    """[{file, line, expression}] for every `kani::assume(...)` call site.

    Operates on whole-file text (not line-by-line) so a multi-line
    expression is captured correctly by paren balance rather than an
    arbitrary line window; an assume whose parens never close in the file
    is refused, not truncated.
    """
    results: list[dict[str, Any]] = []
    for fname in ASSUME_FILES:
        path = PROPERTIES_DIR / fname
        text = _read(path)
        masked = _mask_non_code(text, f"properties/{fname}")
        for m in _ASSUME_TOKEN.finditer(masked):
            open_paren = m.end() - 1
            extracted = _extract_call_args(text, open_paren)
            line_no = text.count("\n", 0, m.start()) + 1
            if extracted is None:
                raise Refused(
                    f"properties/{fname}:{line_no}: kani::assume( never closes in this file "
                    f"(unbalanced parens); refusing to guess its extent")
            expr, _end = extracted
            results.append({
                "file": f"properties/{fname}",
                "line": line_no,
                "expression": " ".join(expr.split()),
            })
    return results


# --- CI-derived fast/heavy harness sets ------------------------------------


def _extract_for_h_loop(text: str, window_start: int, window_len: int, source: str) -> list[str]:
    """Find the first `for h in ... ; do` shell loop in
    `text[window_start:window_start+window_len]` and return its
    whitespace-separated, backslash-continuation-joined harness names."""
    window = text[window_start:window_start + window_len]
    m = re.search(r"for h in\b(.*?);\s*do\b", window, re.DOTALL)
    if not m:
        raise Refused(f"{source}: no `for h in ... ; do` loop found in the expected region")
    joined = m.group(1).replace("\\\n", " ")
    names = joined.split()
    if not names:
        raise Refused(f"{source}: the `for h in ... ; do` loop names no harnesses")
    bad = [n for n in names if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n)]
    if bad:
        raise Refused(f"{source}: non-identifier token(s) inside the harness loop: {bad}")
    return names


def derive_fast_harnesses() -> list[str]:
    text = _read(CI_FAST_FILE)
    marker = "\n  formal-p037:\n"
    idx = text.find(marker)
    if idx < 0:
        raise Refused(f"{CI_FAST_FILE}: no top-level 'formal-p037:' job found")
    return _extract_for_h_loop(text, idx, 6000, f"{CI_FAST_FILE} (formal-p037 job)")


def derive_heavy_harnesses() -> list[str]:
    text = _read(CI_HEAVY_FILE)
    return _extract_for_h_loop(text, 0, len(text), str(CI_HEAVY_FILE))


# --- ledgers ----------------------------------------------------------------


def _load_json(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise Refused(f"{path} does not exist")
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows = doc.get(key)
    if not isinstance(rows, list):
        raise Refused(f"{path}: {key!r} is not a list")
    return rows


# --- the audit itself --------------------------------------------------------


def run() -> tuple[list[str], dict[str, Any]]:
    """Returns (problems, summary_counters). Raises Refused on ambiguous input."""
    problems: list[str] = []

    source = derive_source_harnesses()
    assumes = derive_source_assumes()
    fast = derive_fast_harnesses()
    heavy = derive_heavy_harnesses()

    source_names = set(source)
    fast_set, heavy_set = set(fast), set(heavy)
    if len(fast) != len(fast_set):
        problems.append(f"FAST list names a harness more than once: {fast}")
    if len(heavy) != len(heavy_set):
        problems.append(f"HEAVY list names a harness more than once: {heavy}")

    overlap = fast_set & heavy_set
    union = fast_set | heavy_set
    missing_from_ci = source_names - union
    unknown_ci_names = union - source_names
    if overlap:
        problems.append(f"FAST and HEAVY are not disjoint: {sorted(overlap)}")
    if missing_from_ci:
        problems.append(f"source harnesses in neither CI set: {sorted(missing_from_ci)}")
    if unknown_ci_names:
        problems.append(f"CI names harnesses absent from source: {sorted(unknown_ci_names)}")

    harness_ledger = _load_json(HARNESS_LEDGER, "harnesses")
    ledger_names = [h.get("harness") for h in harness_ledger]
    if len(ledger_names) != len(set(ledger_names)):
        problems.append("harness ledger has a duplicate harness row")
    ledger_name_set = set(ledger_names)
    missing_ledger_rows = source_names - ledger_name_set
    orphan_ledger_rows = ledger_name_set - source_names
    if missing_ledger_rows:
        problems.append(f"source harnesses with no ledger row: {sorted(missing_ledger_rows)}")
    if orphan_ledger_rows:
        problems.append(f"ledger rows naming no source harness: {sorted(orphan_ledger_rows)}")
    for h in harness_ledger:
        if not h.get("claim") or not h.get("production_subject"):
            problems.append(
                f"harness ledger row {h.get('harness')!r} lacks a claim or production_subject")

    assumption_ledger = _load_json(ASSUMPTION_LEDGER, "assumptions")
    source_assume_keys = {(a["file"], a["line"]) for a in assumes}
    ledger_assume_key_list = [(a.get("file"), a.get("line")) for a in assumption_ledger]
    if len(ledger_assume_key_list) != len(set(ledger_assume_key_list)):
        problems.append("assumption ledger has a duplicate (file, line) row")
    ledger_assume_keys = set(ledger_assume_key_list)
    missing_assume_rows = source_assume_keys - ledger_assume_keys
    orphan_assume_rows = ledger_assume_keys - source_assume_keys
    if missing_assume_rows:
        problems.append(
            f"source kani::assume sites with no ledger row: {sorted(missing_assume_rows)}")
    if orphan_assume_rows:
        problems.append(
            f"ledger assumption rows naming no source site: {sorted(orphan_assume_rows)}")

    n_guarantor = n_outside = n_unclassified = 0
    for a in assumption_ledger:
        key = (a.get("file"), a.get("line"))
        disp = a.get("disposition")
        if disp == "PRODUCTION_GUARANTOR":
            n_guarantor += 1
            if not a.get("guarantor"):
                problems.append(
                    f"assumption {key} is PRODUCTION_GUARANTOR but names no concrete guarantor")
        elif disp == "OUTSIDE_KANI_BOUNDARY":
            n_outside += 1
            if not a.get("reason") or not a.get("residual_production_obligation"):
                problems.append(
                    f"assumption {key} is OUTSIDE_KANI_BOUNDARY but lacks a reason "
                    f"or a residual_production_obligation")
        else:
            n_unclassified += 1
            problems.append(f"assumption {key} has no valid disposition (got {disp!r})")

    n_witnessed = 0
    n_restrictions = len(assumption_ledger)
    for a in assumption_ledger:
        key = (a.get("file"), a.get("line"))
        status = a.get("non_vacuity_status")
        witness = str(a.get("non_vacuity_witness") or "")
        if status == "witnessed" and witness:
            n_witnessed += 1
        elif status == "gap":
            problems.append(f"assumption {key} has no complete non-vacuity witness ({witness!r})")
        else:
            problems.append(f"assumption {key} has an invalid non_vacuity_status (got {status!r}); "
                            f"must be exactly 'witnessed' or 'gap'")

    summary = {
        "source_harnesses": len(source_names),
        "fast_ci": len(fast_set),
        "heavy_ci": len(heavy_set),
        "overlap": len(overlap),
        "unassigned": len(missing_from_ci),
        "unknown_ci_names": len(unknown_ci_names),
        "harness_ledger_matched": len(source_names & ledger_name_set),
        "harness_ledger_total": len(source_names),
        "assumptions_total": len(assumption_ledger),
        "assumptions_production_guarantor": n_guarantor,
        "assumptions_outside_boundary": n_outside,
        "assumptions_unclassified": n_unclassified,
        "restrictions_with_witness": n_witnessed,
        "restrictions_total": n_restrictions,
    }
    return problems, summary


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"SOURCE_HARNESSES        {summary['source_harnesses']}")
    print(f"FAST_CI                 {summary['fast_ci']}")
    print(f"HEAVY_CI                {summary['heavy_ci']}")
    print(f"OVERLAP                 {summary['overlap']}")
    print(f"UNASSIGNED              {summary['unassigned']}")
    print(f"UNKNOWN_CI_NAMES        {summary['unknown_ci_names']}")
    print()
    matched, total = summary["harness_ledger_matched"], summary["harness_ledger_total"]
    print(f"HARNESS_LEDGER          {matched}/{total}")
    print(f"ASSUMPTIONS             {summary['assumptions_total']}")
    print(f"  production_guarantor  {summary['assumptions_production_guarantor']}")
    print(f"  outside_boundary      {summary['assumptions_outside_boundary']}")
    print(f"  unclassified          {summary['assumptions_unclassified']}")
    print()
    print("LOAD_BEARING_RESTRICTIONS")
    witnessed, restrictions = summary["restrictions_with_witness"], summary["restrictions_total"]
    print(f"  with non-vacuity witness {witnessed}/{restrictions}")


def main() -> int:
    try:
        problems, summary = run()
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    _print_summary(summary)
    print()
    if problems:
        for p in problems:
            print(f"FAIL[proof-boundary]: {p}")
        print()
        print("PROOF_BOUNDARY")
        print("  RED")
        print(f"RESULT: p037-proof-boundary RED problems={len(problems)}")
        return 1

    print("PROOF_BOUNDARY")
    print("  GREEN")
    print("RESULT: p037-proof-boundary GREEN "
          f"harnesses={summary['source_harnesses']} assumptions={summary['assumptions_total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
