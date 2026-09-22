#!/usr/bin/env python3
"""P-037 A2.2-D: the mechanical production-diff gate on the door treatment.

The a2d treatment units are wide on purpose (docs/evidence/p037-a2d-epoch.json,
formal note 10.6.14): ownlang/ownir.py, rust/crates/own-ir/ and spec/ are the
smallest git-addressable units that hold the two OwnIR doors today, and the
freeze declined to refactor a door out of a 3600-line file before its baseline
exists. That leaves the D production diff wider than the door, and "held by
review" is not a boundary. This gate is the boundary. It reads the record's
`production_diff_gate` and applies it between a reference (T_D once the R_D
manifest names it; the integration head until then) and a head:

* Python, ownlang/ownir.py: every top-level definition other than the mutable
  ones (`load`) must be structurally identical, compared as AST with positions
  ignored and docstrings included; a new top-level definition is allowed only if
  its name is registered in the record as a door-only helper (a function or a
  module-level constant, never a class); nothing may be removed. Line numbers
  and hunks play no part: a comment or a reformat is invisible, a moved
  docstring is not.
* Rust, rust/crates/own-ir/: src/strict.rs may change freely; in src/lib.rs only
  the items the record names (`struct Function`, `struct OwnIr`) may change and
  only registered new items may appear, every other item compared token-wise
  with plain comments dropped and its `///` docs kept; the remaining production
  files of the crate are byte-identical by git object id; tests/ are controls
  and move freely; a production file the policy does not cover is a violation,
  not a gap.
* spec/: only spec/OwnIR.md and spec/ownir.schema.json may change; every other
  tracked file under spec/ is byte-identical.

Verdicts: IDENTICAL (no production surface moved), WITHIN_ALLOWLIST (only
allowed surfaces moved), VIOLATION. Anything the gate cannot decide (an
unparseable file, a policy naming a definition the reference lacks, a
registration naming a definition the reference already has, a production file
the policy does not cover, a missing or unknown `measurement_policy.fact_diff`)
is REFUSED with exit 2, never a pass. The record is read from the head revision
by default: the policy in force for a head is the one that head carries, and the
epoch test pins its non-registration fields so a head cannot loosen it.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORD = "docs/evidence/p037-a2d-epoch.json"
SCHEMA = "p037-door-diff-gate/1"
WORKTREE = "WORKTREE"

# The closed vocabulary of `measurement_policy.fact_diff`. The cumulative driver
# reads the record's value against this set and REFUSES anything else; nobody
# parses the prose of `claims_preregistered`.
FACT_DIFF_POLICIES: frozenset[str] = frozenset({"unchanged", "allowed_surfaces"})

IDENTICAL = "IDENTICAL"
WITHIN = "WITHIN_ALLOWLIST"
VIOLATION = "VIOLATION"
RANK = {IDENTICAL: 0, WITHIN: 1, VIOLATION: 2}


class Refused(Exception):
    """The gate cannot decide. That is never a pass."""


# --------------------------------------------------------------------------- policy


@dataclass(frozen=True)
class Policy:
    python_unit: str
    python_mutable: tuple[str, ...]
    python_helpers: tuple[str, ...]
    rust_unit: str
    rust_mutable_files: tuple[str, ...]
    rust_mutable_items: dict[str, tuple[str, ...]]
    rust_registered_items: dict[str, tuple[str, ...]]
    rust_frozen_files: tuple[str, ...]
    rust_controls: tuple[str, ...]
    spec_unit: str
    spec_mutable_files: tuple[str, ...]
    fact_diff: str
    digest: str


def _str_list(obj: Any, where: str) -> tuple[str, ...]:
    if not isinstance(obj, list) or not all(isinstance(x, str) for x in obj):
        raise Refused(f"{where} must be a list of strings")
    return tuple(obj)


def _str_list_map(obj: Any, where: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(obj, dict):
        raise Refused(f"{where} must map file paths to lists of item keys")
    return {str(k): _str_list(v, f"{where}[{k!r}]") for k, v in obj.items()}


def _section(parent: dict[str, Any], key: str, where: str) -> dict[str, Any]:
    obj = parent.get(key)
    if not isinstance(obj, dict):
        raise Refused(f"{where} lacks the object {key!r}")
    return obj


def load_policy(record: dict[str, Any]) -> Policy:
    """The gate policy and the measurement policy, both closed. Anything off-shape is REFUSED."""
    gate = _section(record, "production_diff_gate", "epoch record")
    py = _section(gate, "python", "production_diff_gate")
    rs = _section(gate, "rust", "production_diff_gate")
    sp = _section(gate, "spec", "production_diff_gate")
    mp = _section(record, "measurement_policy", "epoch record")
    fact_diff = mp.get("fact_diff")
    if not isinstance(fact_diff, str) or fact_diff not in FACT_DIFF_POLICIES:
        raise Refused(f"measurement_policy.fact_diff {fact_diff!r} is not one of "
                      f"{sorted(FACT_DIFF_POLICIES)}")
    for name, obj in (("python.unit", py.get("unit")), ("rust.unit", rs.get("unit")),
                      ("spec.unit", sp.get("unit"))):
        if not isinstance(obj, str) or not obj:
            raise Refused(f"production_diff_gate.{name} must be a path")
    mutable_items = _str_list_map(rs.get("mutable_items"), "rust.mutable_items")
    registered_items = _str_list_map(rs.get("registered_new_items", {}),
                                     "rust.registered_new_items")
    unknown = sorted(set(registered_items) - set(mutable_items))
    if unknown:
        raise Refused(f"rust.registered_new_items names files outside mutable_items: {unknown}")
    canon = json.dumps({"production_diff_gate": gate, "measurement_policy": mp},
                       sort_keys=True, separators=(",", ":")).encode("utf-8")
    return Policy(
        python_unit=str(py["unit"]),
        python_mutable=_str_list(py.get("mutable_top_level"), "python.mutable_top_level"),
        python_helpers=_str_list(py.get("registered_helpers", []), "python.registered_helpers"),
        rust_unit=str(rs["unit"]),
        rust_mutable_files=_str_list(rs.get("mutable_files"), "rust.mutable_files"),
        rust_mutable_items=mutable_items,
        rust_registered_items=registered_items,
        rust_frozen_files=_str_list(rs.get("frozen_files"), "rust.frozen_files"),
        rust_controls=_str_list(rs.get("controls"), "rust.controls"),
        spec_unit=str(sp["unit"]),
        spec_mutable_files=_str_list(sp.get("mutable_files"), "spec.mutable_files"),
        fact_diff=fact_diff,
        digest=hashlib.sha256(canon).hexdigest(),
    )


# --------------------------------------------------------------------------- trees


@dataclass(frozen=True)
class Entry:
    oid: str
    read: Callable[[], bytes]


Tree = dict[str, Entry]


def _git_bytes(*args: str, repo: Path = ROOT) -> bytes:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise Refused(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def _git(*args: str, repo: Path = ROOT) -> str:
    return _git_bytes(*args, repo=repo).decode("utf-8").strip()


def _show(rev: str, path: str, repo: Path) -> bytes:
    return _git_bytes("show", f"{rev}:{path}", repo=repo)


def resolve(rev: str, repo: Path = ROOT) -> str:
    if rev == WORKTREE:
        return WORKTREE
    return _git("rev-parse", "--verify", f"{rev}^{{commit}}", repo=repo)


def snapshot(rev: str, prefixes: Iterable[str], repo: Path = ROOT) -> Tree:
    """Every tracked blob under the prefixes at `rev`: object id plus a lazy reader.

    WORKTREE reads the working tree (tracked and untracked-but-not-ignored files),
    hashing each through `git hash-object --path` so the clean filter a checkout
    would apply is applied and a CRLF working copy compares like its blob.
    """
    tree: Tree = {}
    specs = list(prefixes)
    if rev == WORKTREE:
        listed = _git_bytes("ls-files", "-z", "--", *specs, repo=repo)
        others = _git_bytes("ls-files", "-z", "--others", "--exclude-standard", "--", *specs,
                            repo=repo)
        for raw in sorted(set(listed.split(b"\0")) | set(others.split(b"\0"))):
            if not raw:
                continue
            path = raw.decode("utf-8")
            file = repo / path
            if not file.is_file():
                continue
            oid = _git("hash-object", "--path", path, "--", str(file), repo=repo)
            tree[path] = Entry(oid, file.read_bytes)
        return tree
    out = _git_bytes("ls-tree", "-r", "-z", rev, "--", *specs, repo=repo)
    for raw in out.split(b"\0"):
        if not raw:
            continue
        meta, path_b = raw.split(b"\t", 1)
        _mode, kind, oid = meta.decode("utf-8").split()
        if kind != "blob":
            continue
        path = path_b.decode("utf-8")
        tree[path] = Entry(oid, partial(_show, rev, path, repo))
    return tree


def memory_tree(files: dict[str, str]) -> Tree:
    """An in-memory tree for the selftest; object ids are content digests."""
    tree: Tree = {}
    for path, text in files.items():
        data = text.encode("utf-8")
        tree[path] = Entry(hashlib.sha256(data).hexdigest(), partial(bytes, data))
    return tree


def _text(tree: Tree, path: str) -> str:
    try:
        return tree[path].read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Refused(f"{path}: not UTF-8: {exc}") from exc


# --------------------------------------------------------------------------- reports


@dataclass
class UnitReport:
    unit: str
    verdict: str = IDENTICAL
    allowed: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    controls_moved: list[str] = field(default_factory=list)

    def allow(self, what: str) -> None:
        self.allowed.append(what)
        if RANK[self.verdict] < RANK[WITHIN]:
            self.verdict = WITHIN

    def violate(self, what: str) -> None:
        self.violations.append(what)
        self.verdict = VIOLATION

    def as_dict(self) -> dict[str, Any]:
        return {"unit": self.unit, "verdict": self.verdict, "allowed": list(self.allowed),
                "violations": list(self.violations), "controls_moved": list(self.controls_moved)}


def compare_items(ref: list[tuple[str, str]], head: list[tuple[str, str]],
                  mutable: Iterable[str], registered: Iterable[str],
                  report: UnitReport, where: str) -> None:
    """The one item law, shared by both languages.

    `ref` and `head` are (key, body) lists: the key names a top-level definition,
    the body is its structural identity. A mutable key must exist exactly once on
    both sides and may differ; a registered key must not exist in the reference
    and may appear in the head; every other reference key must appear in the head
    with an identical body and multiplicity; every other head key is a violation.
    """
    mutable_keys = tuple(mutable)
    registered_keys = set(registered)
    ref_by: dict[str, list[str]] = {}
    head_by: dict[str, list[str]] = {}
    for key, body in ref:
        ref_by.setdefault(key, []).append(body)
    for key, body in head:
        head_by.setdefault(key, []).append(body)
    for key in mutable_keys:
        if len(ref_by.get(key, [])) != 1:
            raise Refused(f"{where}: the policy names mutable {key!r}, which the reference "
                          f"defines {len(ref_by.get(key, []))} time(s), not once")
    for key in sorted(registered_keys):
        if key in ref_by:
            raise Refused(f"{where}: registered new definition {key!r} already exists in the "
                          f"reference; a registration cannot unfreeze an existing definition")
    for key, bodies in ref_by.items():
        found = head_by.get(key, [])
        if key in mutable_keys:
            if len(found) != 1:
                report.violate(f"{where}: mutable {key} defined {len(found)} time(s) in the head, "
                               f"not once")
            elif found[0] != bodies[0]:
                report.allow(f"{where}: {key} differs (mutable)")
            continue
        if Counter(found) == Counter(bodies):
            continue
        if not found:
            report.violate(f"{where}: {key} removed (frozen)")
        else:
            report.violate(f"{where}: {key} changed (frozen)")
    for key in head_by:
        if key in ref_by or key in mutable_keys:
            continue
        if key in registered_keys:
            report.allow(f"{where}: {key} added (registered)")
        else:
            report.violate(f"{where}: {key} added (not registered)")


# --------------------------------------------------------------------------- python


def _py_key(node: ast.stmt) -> str:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return f"def {node.name}"
    if isinstance(node, ast.ClassDef):
        return f"class {node.name}"
    if isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
        return "assign " + ",".join(t.id for t in node.targets if isinstance(t, ast.Name))
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return f"assign {node.target.id}"
    if isinstance(node, ast.Import):
        return "import " + ", ".join(a.name + (f" as {a.asname}" if a.asname else "")
                                     for a in node.names)
    if isinstance(node, ast.ImportFrom):
        names = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in node.names)
        return f"from {'.' * node.level}{node.module or ''} import {names}"
    digest = hashlib.sha256(ast.dump(node).encode("utf-8")).hexdigest()[:12]
    return f"{type(node).__name__} {digest}"


def python_items(source: str, path: str) -> list[tuple[str, str]]:
    """(key, structural body) per top-level statement; positions ignored, docstrings kept."""
    try:
        module = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        raise Refused(f"{path}: cannot parse: {exc}") from exc
    return [(_py_key(node), ast.dump(node)) for node in module.body]


def compare_python(ref: Tree, head: Tree, pol: Policy) -> UnitReport:
    unit = pol.python_unit
    rep = UnitReport(unit)
    if unit not in ref:
        raise Refused(f"{unit}: absent from the reference")
    if unit not in head:
        rep.violate(f"{unit} removed")
        return rep
    ref_items = python_items(_text(ref, unit), unit)
    head_items = python_items(_text(head, unit), unit)
    ref_names = {key.split(" ", 1)[1] for key, _ in ref_items
                 if key.split(" ", 1)[0] in ("def", "class", "assign")}
    for helper in pol.python_helpers:
        if helper in ref_names:
            raise Refused(f"{unit}: registered helper {helper!r} names an existing top-level "
                          f"definition of the reference")
    mutable = tuple(f"def {name}" for name in pol.python_mutable)
    registered = [f"def {name}" for name in pol.python_helpers]
    registered += [f"assign {name}" for name in pol.python_helpers]
    compare_items(ref_items, head_items, mutable, registered, rep, unit)
    return rep


# --------------------------------------------------------------------------- rust


BLOCK_KINDS = frozenset({"fn", "struct", "enum", "union", "trait", "mod", "impl",
                         "macro_rules", "macro", "extern_block"})
STATEMENT_KINDS = frozenset({"use", "type", "const", "static", "extern_crate"})
MODIFIERS = frozenset({"pub", "unsafe", "async", "default", "auto"})
_TOKEN = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*|\S)")


@dataclass(frozen=True)
class RustItem:
    kind: str
    name: str
    text: str
    norm: str

    @property
    def key(self) -> str:
        return f"{self.kind} {self.name}"


def _escape_end(src: str, j: int, path: str) -> int:
    """`j` is the index after a backslash; return the index after the escape."""
    n = len(src)
    if j >= n:
        raise Refused(f"{path}: dangling escape at end of file")
    if src[j] == "u" and j + 1 < n and src[j + 1] == "{":
        close = src.find("}", j + 2)
        if close < 0:
            raise Refused(f"{path}: unterminated unicode escape at offset {j}")
        return close + 1
    if src[j] == "x":
        return min(j + 3, n)
    return j + 1


def _string_end(src: str, j: int, path: str) -> int:
    n = len(src)
    while j < n:
        ch = src[j]
        if ch == "\\":
            j = _escape_end(src, j + 1, path)
            continue
        if ch == '"':
            return j + 1
        j += 1
    raise Refused(f"{path}: unterminated string literal")


def _char_end(src: str, i: int, path: str) -> int | None:
    """`i` is the index of a quote; the index after a char literal, or None for a lifetime."""
    n = len(src)
    if i + 1 < n and src[i + 1] == "\\":
        j = _escape_end(src, i + 2, path)
        if j < n and src[j] == "'":
            return j + 1
        raise Refused(f"{path}: unterminated char literal at offset {i}")
    if i + 2 < n and src[i + 2] == "'" and src[i + 1] != "'":
        return i + 3
    return None


def classify_chars(src: str, path: str) -> list[str]:
    """One class per character: c code, k plain comment, d outer doc comment, s literal.

    Inner docs (`//!`, `/*! */`) document the enclosing module, not an item, and
    are dropped with the plain comments; outer docs (`///`, `/** */`) belong to
    the item they precede and count toward its identity, as a Python docstring
    does. Block comments nest, as in Rust.
    """
    n = len(src)
    cls = ["c"] * n

    def mark(a: int, b: int, k: str) -> None:
        for idx in range(a, b):
            cls[idx] = k

    i = 0
    while i < n:
        ch = src[i]
        if ch == "/" and src.startswith("//", i):
            end = src.find("\n", i)
            end = n if end < 0 else end
            doc = src.startswith("///", i) and not src.startswith("////", i)
            mark(i, end, "d" if doc else "k")
            i = end
            continue
        if ch == "/" and src.startswith("/*", i):
            depth = 0
            j = i
            while j < n:
                if src.startswith("/*", j):
                    depth += 1
                    j += 2
                    continue
                if src.startswith("*/", j):
                    depth -= 1
                    j += 2
                    if depth == 0:
                        break
                    continue
                j += 1
            if depth:
                raise Refused(f"{path}: unterminated block comment at offset {i}")
            doc = src.startswith("/**", i) and not src.startswith("/**/", i)
            mark(i, j, "d" if doc else "k")
            i = j
            continue
        prev_ident = i > 0 and (src[i - 1].isalnum() or src[i - 1] == "_")
        if ch in "rb" and not prev_ident:
            k = i + 1
            raw = ch == "r"
            if ch == "b" and k < n and src[k] == "r":
                raw = True
                k += 1
            if raw:
                hashes = 0
                while k < n and src[k] == "#":
                    hashes += 1
                    k += 1
                if k < n and src[k] == '"':
                    close = '"' + "#" * hashes
                    end = src.find(close, k + 1)
                    if end < 0:
                        raise Refused(f"{path}: unterminated raw string at offset {i}")
                    mark(i, end + len(close), "s")
                    i = end + len(close)
                    continue
            elif k < n and src[k] == '"':
                end = _string_end(src, k + 1, path)
                mark(i, end, "s")
                i = end
                continue
            elif k < n and src[k] == "'":
                end_or_none = _char_end(src, k, path)
                if end_or_none is not None:
                    mark(i, end_or_none, "s")
                    i = end_or_none
                    continue
            i += 1
            continue
        if ch == '"':
            end = _string_end(src, i + 1, path)
            mark(i, end, "s")
            i = end
            continue
        if ch == "'":
            end_or_none = _char_end(src, i, path)
            if end_or_none is not None:
                mark(i, end_or_none, "s")
                i = end_or_none
                continue
            i += 1
            continue
        i += 1
    return cls


def _normalize(src: str, cls: list[str], a: int, b: int) -> str:
    """Tokens and literals of src[a:b] with plain comments dropped and whitespace collapsed."""
    out: list[str] = []
    pending = False
    for idx in range(a, b):
        k = cls[idx]
        ch = src[idx]
        if k == "s":
            if pending and out:
                out.append(" ")
            pending = False
            out.append(ch)
        elif k == "k" or ch.isspace():
            pending = True
        else:
            if pending and out:
                out.append(" ")
            pending = False
            out.append(ch)
    return "".join(out)


def _match_bracket(text: str, open_at: int, path: str) -> int:
    """Index of the bracket closing text[open_at] in a comment-and-literal-blanked text."""
    pairs = {"[": "]", "(": ")", "{": "}"}
    opener = text[open_at]
    closer = pairs[opener]
    depth = 0
    for idx in range(open_at, len(text)):
        if text[idx] == opener:
            depth += 1
        elif text[idx] == closer:
            depth -= 1
            if depth == 0:
                return idx
    raise Refused(f"{path}: unbalanced {opener!r} at offset {open_at}")


def _next_token(text: str, pos: int) -> tuple[str, int]:
    m = _TOKEN.match(text, pos)
    if m is None:
        return "", len(text)
    return m.group(1), m.end()


def _ident(text: str, pos: int, path: str, what: str) -> tuple[str, int]:
    tok, after = _next_token(text, pos)
    if tok == "r" and after < len(text) and text[after] == "#":
        raw, after2 = _next_token(text, after + 1)
        return f"r#{raw}", after2
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tok):
        raise Refused(f"{path}: expected {what} name at offset {pos}, found {tok!r}")
    return tok, after


def _item_head(text: str, pos: int, path: str) -> tuple[str, str | None, int]:
    """Kind, name (None when the name is the head text itself) and the cursor after the name."""
    tok, after = _next_token(text, pos)
    while True:
        if tok == "pub":
            peek, after_peek = _next_token(text, after)
            if peek == "(":
                after = _match_bracket(text, after_peek - 1, path) + 1
            pos = after
            tok, after = _next_token(text, pos)
            continue
        if tok in MODIFIERS:
            pos = after
            tok, after = _next_token(text, pos)
            continue
        break
    if tok == "extern":
        peek, after_peek = _next_token(text, after)
        if peek == "crate":
            name, after_name = _ident(text, after_peek, path, "crate")
            return "extern_crate", name, after_name
        if peek == "{":
            return "extern_block", "extern", after
        tok, after = peek, after_peek  # `extern "C" fn`: the ABI string is blanked
    if tok == "const":
        peek, after_peek = _next_token(text, after)
        if peek == "fn":
            name, after_name = _ident(text, after_peek, path, "fn")
            return "fn", name, after_name
        if peek == "_":
            return "const", "_", after_peek
        name, after_name = _ident(text, after, path, "const")
        return "const", name, after_name
    if tok == "static":
        peek, after_peek = _next_token(text, after)
        if peek == "mut":
            after = after_peek
        name, after_name = _ident(text, after, path, "static")
        return "static", name, after_name
    if tok == "macro_rules":
        bang, after_bang = _next_token(text, after)
        if bang != "!":
            raise Refused(f"{path}: macro_rules without '!' at offset {pos}")
        name, after_name = _ident(text, after_bang, path, "macro")
        return "macro_rules", name, after_name
    if tok in ("fn", "struct", "enum", "union", "trait", "mod", "type", "macro"):
        name, after_name = _ident(text, after, path, tok)
        return tok, name, after_name
    if tok in ("impl", "use"):
        return tok, None, after
    raise Refused(f"{path}: unclassifiable item at offset {pos}: {text[pos:pos + 40]!r}")


def rust_items(src: str, path: str) -> list[RustItem]:
    """Top-level items of a Rust source file, split losslessly, each keyed and normalized."""
    cls = classify_chars(src, path)
    n = len(src)
    blanked = "".join(ch if k == "c" else " " for ch, k in zip(src, cls, strict=True))
    items: list[RustItem] = []
    prev_end = 0
    cursor = 0
    while True:
        start = cursor
        while start < n and blanked[start].isspace():
            start += 1
        if start >= n:
            break
        pos = start
        inner_attr_end = -1
        while pos < n and blanked[pos] == "#":
            open_at = blanked.find("[", pos)
            if open_at < 0 or blanked[pos + 1:open_at].strip() not in ("", "!"):
                raise Refused(f"{path}: malformed attribute at offset {pos}")
            close_at = _match_bracket(blanked, open_at, path)
            if blanked[pos + 1:open_at].strip() == "!":
                inner_attr_end = close_at + 1
                break
            pos = close_at + 1
            while pos < n and blanked[pos].isspace():
                pos += 1
        if inner_attr_end >= 0:
            norm = _normalize(src, cls, prev_end, inner_attr_end)
            items.append(RustItem("inner_attribute", norm, src[prev_end:inner_attr_end], norm))
            prev_end = cursor = inner_attr_end
            continue
        kind, name, after_name = _item_head(blanked, pos, path)
        brace = paren = bracket = 0
        end = -1
        body_open = -1
        for idx in range(after_name, n):
            ch = blanked[idx]
            if ch == "{":
                if brace == 0 and paren == 0 and bracket == 0 and body_open < 0:
                    body_open = idx
                brace += 1
            elif ch == "}":
                brace -= 1
                if brace < 0:
                    raise Refused(f"{path}: unbalanced '}}' at offset {idx}")
                if brace == 0 and paren == 0 and bracket == 0 and kind in BLOCK_KINDS:
                    end = idx + 1
                    break
            elif ch == "(":
                paren += 1
            elif ch == ")":
                paren -= 1
            elif ch == "[":
                bracket += 1
            elif ch == "]":
                bracket -= 1
            elif ch == ";" and brace == 0 and paren == 0 and bracket == 0:
                end = idx + 1
                break
        if end < 0:
            raise Refused(f"{path}: unterminated {kind} item at offset {pos}")
        if name is None:
            head_stop = body_open if (kind == "impl" and body_open >= 0) else end - 1
            name = " ".join(blanked[after_name:head_stop].split())
        norm = _normalize(src, cls, prev_end, end)
        items.append(RustItem(kind, name, src[prev_end:end], norm))
        prev_end = cursor = end
    if blanked[prev_end:].strip():
        raise Refused(f"{path}: trailing code after the last item")
    if "".join(it.text for it in items) != src[:prev_end]:
        raise Refused(f"{path}: the item split is not lossless")
    return items


def compare_rust(ref: Tree, head: Tree, pol: Policy) -> UnitReport:
    unit = pol.rust_unit
    rep = UnitReport(unit)
    for rel in (*pol.rust_mutable_files, *pol.rust_mutable_items, *pol.rust_frozen_files):
        if unit + rel not in ref:
            raise Refused(f"{unit}{rel}: named by the policy, absent from the reference")
    paths = sorted({p for p in ref if p.startswith(unit)} | {p for p in head if p.startswith(unit)})
    for path in paths:
        rel = path[len(unit):]
        in_ref, in_head = path in ref, path in head
        same = in_ref and in_head and ref[path].oid == head[path].oid
        if any(rel.startswith(prefix) for prefix in pol.rust_controls):
            if not same:
                rep.controls_moved.append(path)
            continue
        if rel in pol.rust_mutable_files:
            if not in_head:
                rep.violate(f"{path} removed (mutable file must stay)")
            elif not same:
                rep.allow(f"{path} differs (mutable file)")
            continue
        if rel in pol.rust_mutable_items:
            if not in_head:
                rep.violate(f"{path} removed")
                continue
            ref_items = [(it.key, it.norm) for it in rust_items(_text(ref, path), path)]
            head_items = [(it.key, it.norm) for it in rust_items(_text(head, path), path)]
            compare_items(ref_items, head_items, pol.rust_mutable_items[rel],
                          pol.rust_registered_items.get(rel, ()), rep, path)
            continue
        if rel in pol.rust_frozen_files:
            if not in_head:
                rep.violate(f"{path} removed (frozen)")
            elif not same:
                rep.violate(f"{path} changed (frozen)")
            continue
        if in_ref:
            raise Refused(f"{path}: a production file of the reference that "
                          f"production_diff_gate does not cover")
        rep.violate(f"{path} added (production file outside the allowlist)")
    return rep


# --------------------------------------------------------------------------- spec


def compare_spec(ref: Tree, head: Tree, pol: Policy) -> UnitReport:
    unit = pol.spec_unit
    rep = UnitReport(unit)
    for rel in pol.spec_mutable_files:
        if unit + rel not in ref:
            raise Refused(f"{unit}{rel}: named by the policy, absent from the reference")
    paths = sorted({p for p in ref if p.startswith(unit)} | {p for p in head if p.startswith(unit)})
    for path in paths:
        rel = path[len(unit):]
        in_ref, in_head = path in ref, path in head
        same = in_ref and in_head and ref[path].oid == head[path].oid
        if rel in pol.spec_mutable_files:
            if not in_head:
                rep.violate(f"{path} removed (mutable file must stay)")
            elif not same:
                rep.allow(f"{path} differs (mutable file)")
            continue
        if not in_ref:
            rep.violate(f"{path} added (frozen unit)")
        elif not in_head:
            rep.violate(f"{path} removed (frozen)")
        elif not same:
            rep.violate(f"{path} changed (frozen)")
    return rep


# --------------------------------------------------------------------------- gate


def gate(ref: Tree, head: Tree, pol: Policy) -> tuple[str, list[UnitReport]]:
    units = [compare_python(ref, head, pol), compare_rust(ref, head, pol),
             compare_spec(ref, head, pol)]
    verdict = max((u.verdict for u in units), key=lambda v: RANK[v])
    return verdict, units


def load_record(rev: str, record_path: str, repo: Path = ROOT) -> dict[str, Any]:
    if rev == WORKTREE:
        text = (repo / record_path).read_text(encoding="utf-8")
    else:
        text = _show(rev, record_path, repo).decode("utf-8")
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise Refused(f"{record_path}: not an object")
    return doc


def check(reference: str, head: str, record_path: str, record_file: str | None,
          repo: Path = ROOT) -> dict[str, Any]:
    ref_sha = resolve(reference, repo)
    head_sha = resolve(head, repo)
    if ref_sha == WORKTREE:
        raise Refused("the reference must be a commit")
    if record_file is not None:
        doc = json.loads(Path(record_file).read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise Refused(f"{record_file}: not an object")
        record_source = record_file
    else:
        doc = load_record(head_sha, record_path, repo)
        record_source = f"{head_sha}:{record_path}"
    pol = load_policy(doc)
    prefixes = [pol.python_unit, pol.rust_unit, pol.spec_unit]
    ref_tree = snapshot(ref_sha, prefixes, repo)
    head_tree = snapshot(head_sha, prefixes, repo)
    verdict, units = gate(ref_tree, head_tree, pol)
    return {
        "schema": SCHEMA,
        "reference": ref_sha,
        "head": head_sha,
        "record": record_source,
        "policy_sha256": pol.digest,
        "measurement_policy": {"fact_diff": pol.fact_diff},
        "verdict": verdict,
        "units": [u.as_dict() for u in units],
        "allowed": sum(len(u.allowed) for u in units),
        "violations": sum(len(u.violations) for u in units),
    }


def print_report(rep: dict[str, Any]) -> None:
    for unit in rep["units"]:
        print(f"unit {unit['unit']}: {unit['verdict']}")
        for line in unit["allowed"]:
            print(f"  allowed: {line}")
        for line in unit["violations"]:
            print(f"  VIOLATION: {line}")
        for line in unit["controls_moved"]:
            print(f"  control moved: {line}")
    print(f"RESULT: p037-door-diff-gate {rep['verdict']} reference={rep['reference'][:12]} "
          f"head={rep['head'][:12]} allowed={rep['allowed']} violations={rep['violations']} "
          f"fact_diff={rep['measurement_policy']['fact_diff']}")


def satisfied(verdict: str, require: str) -> bool:
    if require == "identical":
        return verdict == IDENTICAL
    return verdict in (IDENTICAL, WITHIN)


# --------------------------------------------------------------------------- selftest

_PY_REF = '''"""module doc"""
import json
from typing import Any

_KNOWN = frozenset({"a", "b"})
LIMIT: int = 3


class Finding:
    """a class"""
    def __init__(self, x: int) -> None:
        self.x = x


def _check(v: Any, where: str) -> None:
    """frozen helper"""
    if v is None:
        raise ValueError(where)


def load(path: str) -> dict[str, Any]:
    """the door"""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    _check(doc, "root")
    return doc


def to_own(facts: dict[str, Any]) -> str:
    return json.dumps(facts)
'''

_RS_LIB_REF = '''//! crate docs that may change
#![deny(missing_docs)]

pub mod protocol;
mod strict;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// The schema version.
pub const OWNIR_VERSION: i64 = 0;

pub const KNOWN: [&str; 2] = ["a", "b"];

fn reject_null<'de, D, T>(de: D) -> Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    let quote = if true { '\\'' } else { '{' }; // a char literal with a brace
    let _ = (quote, "a } string { with braces", r#"raw "quoted" }"#, b'{');
    T::deserialize(de).map(Some)
}

/// A parameter.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Param {
    pub name: String,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// One per-method flow body.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct Function {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sig: Option<String>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

/// The document root.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct OwnIr {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub functions: Option<Vec<Function>>,
    #[serde(flatten)]
    pub extra: Map<String, Value>,
}

impl OwnIr {
    /// The strict door.
    pub fn from_json(text: &str) -> Result<Self, String> {
        let raw: Value = serde_json::from_str(text).map_err(|e| format!("{e}"))?;
        strict::validate_document(raw.as_object().ok_or("root")?)?;
        serde_json::from_value(raw).map_err(|e| format!("{e}"))
    }
}

impl std::fmt::Display for Param {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name)
    }
}
'''


def _rs_replace(src: str, old: str, new: str) -> str:
    if old not in src:
        raise AssertionError(f"selftest fixture lacks {old!r}")
    return src.replace(old, new, 1)


def _synthetic_record(**overrides: Any) -> dict[str, Any]:
    gate_policy: dict[str, Any] = {
        "python": {"unit": "ownlang/ownir.py", "mutable_top_level": ["load"],
                   "registered_helpers": []},
        "rust": {"unit": "rust/crates/own-ir/", "mutable_files": ["src/strict.rs"],
                 "mutable_items": {"src/lib.rs": ["struct Function", "struct OwnIr"]},
                 "registered_new_items": {"src/lib.rs": []},
                 "frozen_files": ["Cargo.toml", "src/protocol.rs", "src/pyrepr.rs",
                                  "src/span.rs"],
                 "controls": ["tests/"]},
        "spec": {"unit": "spec/", "mutable_files": ["OwnIR.md", "ownir.schema.json"]},
    }
    record: dict[str, Any] = {"production_diff_gate": gate_policy,
                              "measurement_policy": {"fact_diff": "unchanged"}}
    for dotted, value in overrides.items():
        node: Any = record
        parts = dotted.split("__")
        for part in parts[:-1]:
            node = node[part]
        if value is _DELETE:
            del node[parts[-1]]
        else:
            node[parts[-1]] = value
    return record


_DELETE = object()


def _synthetic_ref() -> dict[str, str]:
    return {
        "ownlang/ownir.py": _PY_REF,
        "rust/crates/own-ir/Cargo.toml": "[package]\nname = \"own-ir\"\n",
        "rust/crates/own-ir/src/lib.rs": _RS_LIB_REF,
        "rust/crates/own-ir/src/strict.rs": "//! strict\npub fn validate_document() {}\n",
        "rust/crates/own-ir/src/protocol.rs": "//! protocol\npub fn grammar() {}\n",
        "rust/crates/own-ir/src/pyrepr.rs": "//! pyrepr\npub fn repr() {}\n",
        "rust/crates/own-ir/src/span.rs": "//! span\npub struct Span;\n",
        "rust/crates/own-ir/tests/validation_replay.rs": "#[test]\nfn replay() {}\n",
        "spec/OwnIR.md": "# OwnIR\n",
        "spec/ownir.schema.json": "{}\n",
        "spec/Grammar.md": "# Grammar\n",
        "spec/README.md": "# spec\n",
    }


def selftest(repo: Path = ROOT) -> int:
    failures: list[str] = []

    def control(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'ok' if ok else 'FAIL'}[{name}]{'' if ok else ': ' + detail}")
        if not ok:
            failures.append(name)

    def verdict_of(head_files: dict[str, str], record: dict[str, Any] | None = None) -> str:
        pol = load_policy(record if record is not None else _synthetic_record())
        return gate(memory_tree(_synthetic_ref()), memory_tree(head_files), pol)[0]

    def refused(fn: Callable[[], Any]) -> str | None:
        try:
            fn()
        except Refused as exc:
            return str(exc)
        return None

    base = _synthetic_ref()
    control("identical-trees-are-IDENTICAL", verdict_of(dict(base)) == IDENTICAL)

    # Python: the door may move, nothing else.
    py = dict(base)
    py["ownlang/ownir.py"] = _PY_REF.replace('_check(doc, "root")', '_check(doc, "root")\n'
                                             '    if "guarded_functions" in doc:\n'
                                             '        _check(doc["guarded_functions"], "gf")')
    control("python-load-body-change-is-WITHIN", verdict_of(py) == WITHIN)
    py["ownlang/ownir.py"] = _PY_REF.replace('raise ValueError(where)', 'raise TypeError(where)')
    control("python-frozen-helper-change-is-VIOLATION", verdict_of(py) == VIOLATION)
    py["ownlang/ownir.py"] = _PY_REF.replace('"""frozen helper"""', '"""edited docstring"""')
    control("python-frozen-docstring-change-is-VIOLATION", verdict_of(py) == VIOLATION)
    py["ownlang/ownir.py"] = _PY_REF.replace("if v is None:", "if v is None:  # a comment")
    control("python-comment-only-change-is-IDENTICAL", verdict_of(py) == IDENTICAL)
    py["ownlang/ownir.py"] = _PY_REF.replace("def to_own(facts: dict[str, Any]) -> str:\n",
                                             "def to_own(\n    facts: dict[str, Any],\n) -> str:\n")
    control("python-reformat-is-IDENTICAL", verdict_of(py) == IDENTICAL)
    py["ownlang/ownir.py"] = _PY_REF.replace('_KNOWN = frozenset({"a", "b"})',
                                             '_KNOWN = frozenset({"a", "b", "c"})')
    control("python-frozen-constant-change-is-VIOLATION", verdict_of(py) == VIOLATION)
    py["ownlang/ownir.py"] = _PY_REF + "\n\ndef _guarded_keys() -> set[str]:\n    return set()\n"
    control("python-new-unregistered-top-level-is-VIOLATION", verdict_of(py) == VIOLATION)
    registered = _synthetic_record(
        production_diff_gate__python__registered_helpers=["_guarded_keys"])
    control("python-new-registered-helper-is-WITHIN", verdict_of(py, registered) == WITHIN)
    py["ownlang/ownir.py"] = _PY_REF + '\n_guarded_keys = frozenset({"guarded_facts"})\n'
    control("python-registered-constant-is-WITHIN", verdict_of(py, registered) == WITHIN)
    py["ownlang/ownir.py"] = _PY_REF + "\n\nclass _guarded_keys:\n    pass\n"
    control("python-registered-name-as-class-is-VIOLATION", verdict_of(py, registered) == VIOLATION)
    existing = _synthetic_record(production_diff_gate__python__registered_helpers=["_check"])
    control("python-registering-existing-definition-is-REFUSED",
            refused(lambda: verdict_of(dict(base), existing)) is not None)
    py["ownlang/ownir.py"] = _PY_REF.replace("def load(", "def load_document(")
    control("python-door-renamed-or-removed-is-VIOLATION", verdict_of(py) == VIOLATION)
    py["ownlang/ownir.py"] = _PY_REF.replace("def to_own(facts: dict[str, Any]) -> str:\n"
                                             "    return json.dumps(facts)\n", "")
    control("python-frozen-definition-removed-is-VIOLATION", verdict_of(py) == VIOLATION)
    py["ownlang/ownir.py"] = _PY_REF + "\n\ndef load(path: str) -> dict[str, Any]:\n    return {}\n"
    control("python-door-duplicated-is-VIOLATION", verdict_of(py) == VIOLATION)
    py["ownlang/ownir.py"] = "def load(:\n"
    control("python-unparseable-head-is-REFUSED", refused(lambda: verdict_of(py)) is not None)
    py = dict(base)
    del py["ownlang/ownir.py"]
    control("python-unit-removed-is-VIOLATION", verdict_of(py) == VIOLATION)

    # Rust: strict.rs free, lib.rs only the two models, everything else frozen.
    lib = "rust/crates/own-ir/src/lib.rs"
    rs = dict(base)
    rs["rust/crates/own-ir/src/strict.rs"] = ("//! strict\n"
                                              "pub fn validate_document() { let _ = 1; }\n")
    control("rust-strict-rs-change-is-WITHIN", verdict_of(rs) == WITHIN)
    rs = dict(base)
    rs[lib] = _rs_replace(_RS_LIB_REF, "    pub sig: Option<String>,\n",
                          "    pub sig: Option<String>,\n"
                          "    #[serde(default, skip_serializing_if = \"Option::is_none\")]\n"
                          "    pub guarded_facts: Option<Vec<String>>,\n")
    control("rust-function-model-field-is-WITHIN", verdict_of(rs) == WITHIN)
    rs[lib] = _rs_replace(_RS_LIB_REF, "    pub functions: Option<Vec<Function>>,\n",
                          "    pub functions: Option<Vec<Function>>,\n"
                          "    pub guarded_functions: Option<Vec<String>>,\n")
    control("rust-ownir-model-field-is-WITHIN", verdict_of(rs) == WITHIN)
    door_call = 'strict::validate_document(raw.as_object().ok_or("root")?)?;'
    rs[lib] = _rs_replace(_RS_LIB_REF, door_call, door_call + " let _ = 0;")
    control("rust-impl-ownir-change-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs[lib] = _rs_replace(_RS_LIB_REF, "T::deserialize(de).map(Some)",
                          "T::deserialize(de).map(Some).map(|x| x)")
    control("rust-frozen-fn-change-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs[lib] = _rs_replace(_RS_LIB_REF, 'pub const KNOWN: [&str; 2] = ["a", "b"];',
                          'pub const KNOWN: [&str; 3] = ["a", "b", "c"];')
    control("rust-frozen-const-change-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs[lib] = _rs_replace(_RS_LIB_REF, "    pub name: String,\n",
                          "    pub name: String,\n    pub kind: String,\n")
    control("rust-frozen-struct-field-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs[lib] = _rs_replace(_RS_LIB_REF, "/// A parameter.",
                          "/// A parameter, documented differently.")
    control("rust-frozen-item-doc-change-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs[lib] = _rs_replace(_RS_LIB_REF, "//! crate docs that may change",
                          "//! crate docs, rewritten")
    control("rust-crate-inner-doc-change-is-IDENTICAL", verdict_of(rs) == IDENTICAL)
    rs[lib] = _rs_replace(_RS_LIB_REF, "// a char literal with a brace",
                          "// a different plain comment")
    control("rust-plain-comment-change-is-IDENTICAL", verdict_of(rs) == IDENTICAL)
    signature = "fn reject_null<'de, D, T>(de: D) -> Result<Option<T>, D::Error>\n"
    rs[lib] = _rs_replace(_RS_LIB_REF, signature + "where\n", signature + "    where\n")
    control("rust-reformat-is-IDENTICAL", verdict_of(rs) == IDENTICAL)
    rs[lib] = _rs_replace(_RS_LIB_REF, '"a } string { with braces"', '"a } string {  with braces"')
    control("rust-string-literal-whitespace-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs[lib] = _RS_LIB_REF + ("\n/// A guarded fact.\n"
                             "pub struct GuardedFact {\n    pub ordinal: u32,\n}\n")
    control("rust-new-unregistered-item-is-VIOLATION", verdict_of(rs) == VIOLATION)
    reg_rs = _synthetic_record(production_diff_gate__rust__registered_new_items={
        "src/lib.rs": ["struct GuardedFact"]})
    control("rust-new-registered-item-is-WITHIN", verdict_of(rs, reg_rs) == WITHIN)
    bad_reg = _synthetic_record(production_diff_gate__rust__registered_new_items={
        "src/lib.rs": ["struct Param"]})
    control("rust-registering-existing-item-is-REFUSED",
            refused(lambda: verdict_of(dict(base), bad_reg)) is not None)
    rs[lib] = _rs_replace(_RS_LIB_REF, "pub struct OwnIr {", "pub struct OwnIrDocument {")
    control("rust-mutable-model-renamed-is-VIOLATION", verdict_of(rs) == VIOLATION)
    display_impl = _RS_LIB_REF[_RS_LIB_REF.index("impl std::fmt::Display for Param {"):]
    rs[lib] = _rs_replace(_RS_LIB_REF, display_impl, "")
    control("rust-frozen-impl-removed-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs[lib] = _RS_LIB_REF + "\nfn dangling( {\n"
    control("rust-unparseable-head-is-REFUSED", refused(lambda: verdict_of(rs)) is not None)
    rs = dict(base)
    rs["rust/crates/own-ir/src/protocol.rs"] = "//! protocol\npub fn grammar() { let _ = 2; }\n"
    control("rust-frozen-file-change-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs = dict(base)
    rs["rust/crates/own-ir/Cargo.toml"] = "[package]\nname = \"own-ir\"\nversion = \"0.2.0\"\n"
    control("rust-cargo-toml-change-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs = dict(base)
    rs["rust/crates/own-ir/src/guarded.rs"] = "pub fn x() {}\n"
    control("rust-new-production-file-is-VIOLATION", verdict_of(rs) == VIOLATION)
    rs = dict(base)
    rs["rust/crates/own-ir/tests/validation_replay.rs"] = "#[test]\nfn replay() { let _ = 3; }\n"
    rs["rust/crates/own-ir/tests/guarded_doors.rs"] = "#[test]\nfn refuses() {}\n"
    control("rust-tests-move-freely-and-stay-IDENTICAL", verdict_of(rs) == IDENTICAL)
    rs = dict(base)
    del rs["rust/crates/own-ir/src/strict.rs"]
    control("rust-mutable-file-removed-is-VIOLATION", verdict_of(rs) == VIOLATION)
    uncovered = dict(base)
    uncovered["rust/crates/own-ir/src/extra.rs"] = "pub fn y() {}\n"
    control("rust-uncovered-reference-file-is-REFUSED",
            refused(lambda: gate(memory_tree(uncovered), memory_tree(uncovered),
                                 load_policy(_synthetic_record()))) is not None)

    # Spec: two files may move, the rest of spec/ is frozen.
    sp = dict(base)
    sp["spec/OwnIR.md"] = "# OwnIR\n\n## 5.2 guarded facts\n"
    sp["spec/ownir.schema.json"] = '{"guarded_functions": []}\n'
    control("spec-contract-files-change-is-WITHIN", verdict_of(sp) == WITHIN)
    sp = dict(base)
    sp["spec/Grammar.md"] = "# Grammar, edited\n"
    control("spec-frozen-file-change-is-VIOLATION", verdict_of(sp) == VIOLATION)
    sp = dict(base)
    sp["spec/Guarded.md"] = "# new\n"
    control("spec-new-file-is-VIOLATION", verdict_of(sp) == VIOLATION)
    sp = dict(base)
    del sp["spec/README.md"]
    control("spec-file-removed-is-VIOLATION", verdict_of(sp) == VIOLATION)
    sp = dict(base)
    del sp["spec/OwnIR.md"]
    control("spec-contract-file-removed-is-VIOLATION", verdict_of(sp) == VIOLATION)

    # Policy: closed, and REFUSED when it is not.
    control("policy-missing-measurement-policy-is-REFUSED",
            refused(lambda: load_policy(_synthetic_record(measurement_policy=_DELETE))) is not None)
    control("policy-unknown-fact-diff-is-REFUSED",
            refused(lambda: load_policy(_synthetic_record(
                measurement_policy__fact_diff="UNCHANGED on every document"))) is not None)
    control("policy-fact-diff-prose-is-not-a-value",
            "UNCHANGED" not in FACT_DIFF_POLICIES and "unchanged" in FACT_DIFF_POLICIES)
    control("policy-missing-gate-is-REFUSED",
            refused(lambda: load_policy(_synthetic_record(production_diff_gate=_DELETE)))
            is not None)
    control("policy-registration-outside-mutable-items-is-REFUSED",
            refused(lambda: load_policy(_synthetic_record(
                production_diff_gate__rust__registered_new_items={"src/span.rs": ["struct X"]})))
            is not None)
    control("policy-mutable-definition-absent-from-reference-is-REFUSED",
            refused(lambda: verdict_of(dict(base), _synthetic_record(
                production_diff_gate__python__mutable_top_level=["load_document"]))) is not None)

    # The splitter against the real crate: lossless and fully classified on every source file.
    crate = repo / "rust" / "crates" / "own-ir"
    real_files = sorted(p for p in crate.rglob("*.rs") if p.is_file())
    control("real-crate-files-present", len(real_files) >= 5, f"{len(real_files)}")
    split_failures: list[str] = []
    real_keys: dict[str, list[str]] = {}
    for file in real_files:
        rel = file.relative_to(repo).as_posix()
        try:
            items = rust_items(file.read_text(encoding="utf-8"), rel)
        except Refused as exc:
            split_failures.append(f"{rel}: {exc}")
            continue
        real_keys[rel] = [it.key for it in items]
    control("real-crate-splits-losslessly", not split_failures, "; ".join(split_failures))
    lib_keys = real_keys.get("rust/crates/own-ir/src/lib.rs", [])
    expected = ["mod protocol", "mod strict", "const OWNIR_VERSION", "fn reject_null",
                "struct Function", "struct OwnIr", "impl OwnIr"]
    missing = [k for k in expected if k not in lib_keys]
    control("real-lib-rs-items-recognized", not missing, f"missing {missing} in {lib_keys[:12]}")
    control("real-lib-rs-models-unique",
            lib_keys.count("struct Function") == 1 and lib_keys.count("struct OwnIr") == 1)

    # The real door parses and the real policy validates against the real reference tree.
    door = repo / "ownlang" / "ownir.py"
    real_py = python_items(door.read_text(encoding="utf-8"), "ownlang/ownir.py")
    control("real-python-door-has-load", sum(1 for k, _ in real_py if k == "def load") == 1)

    if failures:
        print(f"RESULT: p037-door-diff-gate selftest: {len(failures)} control(s) failed")
        return 1
    print("RESULT: p037-door-diff-gate selftest: all controls behaved")
    return 0


# --------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    chk = sub.add_parser("check", help="gate a head against a reference")
    chk.add_argument("--reference", required=True, help="commit whose production surface is frozen")
    chk.add_argument("--head", default="HEAD", help=f"commit to gate, or {WORKTREE}")
    chk.add_argument("--record", default=DEFAULT_RECORD,
                     help="path of the epoch record inside the head revision")
    chk.add_argument("--record-file", default=None,
                     help="read the policy from this file instead of the head revision")
    chk.add_argument("--require", choices=("identical", "allowlist"), default="allowlist")
    chk.add_argument("--json", default=None, help="write the report here")
    items = sub.add_parser("items", help="list the item keys the gate sees in a source file")
    items.add_argument("--rev", default="HEAD")
    items.add_argument("--path", required=True)
    sub.add_parser("selftest", help="run the synthetic controls")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "selftest":
            return selftest()
        if args.cmd == "items":
            source = _text(snapshot(args.rev, [args.path]), args.path) if args.rev != WORKTREE \
                else (ROOT / args.path).read_text(encoding="utf-8")
            if args.path.endswith(".rs"):
                for item in rust_items(source, args.path):
                    print(item.key)
            else:
                for key, _ in python_items(source, args.path):
                    print(key)
            return 0
        rep = check(args.reference, args.head, args.record, args.record_file)
        print_report(rep)
        if args.json:
            Path(args.json).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
        return 0 if satisfied(rep["verdict"], args.require) else 1
    except Refused as exc:
        print(f"REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
