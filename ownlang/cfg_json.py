"""Canonical CFG JSON export — the frozen CFG-layer oracle seam (P-022 step 0).

`python -m ownlang cfg file.own` prints a *human* dump (`_print_cfg`), which is a
debug format, not a contract. The Rust-migration differential oracle needs a
CFG-layer seam it can diff exactly, so this module projects a lowered `CFG` into
a **canonical, deterministic JSON shape** that both implementations can emit:

  * blocks in id order, fields in a fixed vocabulary, no volatile values;
  * every `Symbol` reference is an **index into a per-function symbol table**
    (first-appearance order: params, then instruction operands). Python's
    in-memory symbol identity is `id(sym)` — meaningless across processes — but
    the *identity structure* (two same-named symbols in sibling scopes are
    distinct; a moved alias shares nothing with its source) is exactly what a
    port must reproduce, and indices express it portably;
  * the shape is versioned (`ownlang_cfg_version`) like OwnIR: additive optional
    fields are tolerated, vocabulary changes must fail loudly.

Pure projection: no analysis, no mutation, dependency-free beyond the CFG/buffer
types it reads (mirrors `evidence.py` / `diag_sarif.py`).
"""

from __future__ import annotations

from typing import Any

from .buffers import BufferInfo
from .cfg import (
    CFG,
    Acquire,
    AcquireBuffer,
    AliasJoin,
    BorrowEnd,
    BorrowStart,
    Instr,
    Invoke,
    MoveInto,
    Overspan,
    Release,
    Return,
    Symbol,
    Use,
)

# Version gate for the seam itself, independent of OwnIR's: bump on any
# incompatible vocabulary change, never for additive optional fields.
CFG_JSON_VERSION = 0


def _buffer_json(info: BufferInfo | None) -> dict[str, Any] | None:
    if info is None:
        return None
    return {
        "mode": info.mode.value,
        "elem": info.elem,
        "size_const": info.size_const,
        "size_var": info.size_var,
        "inline_bytes": info.inline_bytes,
        "fallback_pool": info.fallback_pool,
        "fallback_forbidden": info.fallback_forbidden,
        "clear_on_release": info.clear_on_release,
        "sensitive": info.sensitive,
        "trace": info.trace,
        "counters": info.counters,
        "policy_name": info.policy_name,
        "line": info.line,
    }


class _SymTable:
    """Symbol -> stable index, in first-appearance order. Keyed by object
    identity (the same identity the analysis keys on), so aliasing structure
    survives the projection even between same-named symbols."""

    def __init__(self) -> None:
        self._index: dict[int, int] = {}
        self.rows: list[dict[str, Any]] = []

    def ref(self, sym: Symbol | None) -> int | None:
        if sym is None:
            return None
        got = self._index.get(id(sym))
        if got is not None:
            return got
        idx = len(self.rows)
        self._index[id(sym)] = idx
        self.rows.append({
            "name": sym.name,
            "kind": sym.kind.name.lower(),
            "def_line": sym.def_line,
            "is_param_borrow": sym.is_param_borrow,
            "borrow_is_mut": sym.borrow_is_mut,
            "type_name": sym.type_name,
            "resource_kind": sym.resource_kind,
            "origin": sym.origin,
            "buffer": _buffer_json(sym.buffer),
        })
        return idx


def _instr_json(ins: Instr, syms: _SymTable) -> dict[str, Any]:
    """One instruction as {op, ...fields, line}. The op vocabulary is part of
    the frozen contract; adding a CFG instruction means a new op string AND a
    version review, exactly like an OwnIR vocabulary change."""
    if isinstance(ins, Acquire):
        return {"op": "acquire", "sym": syms.ref(ins.sym),
                "resource": ins.resource, "line": ins.line}
    if isinstance(ins, AcquireBuffer):
        return {"op": "acquire_buffer", "sym": syms.ref(ins.sym),
                "buffer": _buffer_json(ins.info), "line": ins.line}
    if isinstance(ins, MoveInto):
        return {"op": "move_into", "dst": syms.ref(ins.dst),
                "src": syms.ref(ins.src), "line": ins.line}
    if isinstance(ins, Release):
        return {"op": "release", "sym": syms.ref(ins.sym), "line": ins.line}
    if isinstance(ins, Use):
        return {"op": "use", "sym": syms.ref(ins.sym), "line": ins.line}
    if isinstance(ins, Overspan):
        return {"op": "overspan", "sym": syms.ref(ins.sym), "line": ins.line}
    if isinstance(ins, Invoke):
        return {"op": "invoke", "callee": ins.callee,
                "args": [{"sym": syms.ref(s), "effect": e.name.lower()}
                         for s, e in ins.args],
                "line": ins.line}
    if isinstance(ins, BorrowStart):
        return {"op": "borrow_start", "owner": syms.ref(ins.owner),
                "binding": syms.ref(ins.binding), "mut": ins.mut,
                "line": ins.line}
    if isinstance(ins, BorrowEnd):
        return {"op": "borrow_end", "owner": syms.ref(ins.owner),
                "binding": syms.ref(ins.binding), "mut": ins.mut,
                "line": ins.line}
    if isinstance(ins, AliasJoin):
        return {"op": "alias_join", "handle": syms.ref(ins.handle),
                "src": syms.ref(ins.src), "line": ins.line}
    # Return is the last variant; keeping the explicit check (rather than a bare
    # else) preserves the exhaustiveness shape of the analysis dispatchers.
    if isinstance(ins, Return):
        return {"op": "return", "sym": syms.ref(ins.sym), "line": ins.line}
    raise AssertionError(f"unhandled CFG instruction: {ins!r}")


def cfg_json(cfg: CFG) -> dict[str, Any]:
    """One function's CFG as a canonical JSON object. Deterministic: blocks in
    id order, symbols in first-appearance order, no volatile fields."""
    syms = _SymTable()
    params = [syms.ref(p) for p in cfg.params]
    blocks = [
        {
            "id": b.id,
            "label": b.label,
            "succ": list(b.succ),
            "instrs": [_instr_json(i, syms) for i in b.instrs],
        }
        for b in sorted(cfg.blocks, key=lambda b: b.id)
    ]
    return {
        "name": cfg.fn_name,
        "entry": cfg.entry,
        "has_return_type": cfg.has_return_type,
        "params": params,
        "symbols": syms.rows,
        "blocks": blocks,
    }


def module_cfg_json(cfgs: list[CFG]) -> dict[str, Any]:
    """The whole module's CFGs as one versioned document — the unit the oracle
    diffs at the CFG layer."""
    return {
        "ownlang_cfg_version": CFG_JSON_VERSION,
        "functions": [cfg_json(c) for c in cfgs],
    }
