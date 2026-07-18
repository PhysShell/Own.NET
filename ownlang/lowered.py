"""Layer 2 parity surface: the normalized lowered representation (P-022 #259).

A read-only, canonical JSON projection of what the OwnIR bridge *lowered* —
the `Module` AST and handle map that `to_module()` produced — taken BEFORE any
analysis runs. This is the seam where a wrong lowering is visible on its own,
instead of hiding behind an unrelated silence at the diagnostics layer
(spec/Bridge.md §6, layer 2). The Rust `own-bridge` (#259) replays the same
facts fixtures and must reproduce these documents byte-for-byte; until then
Python is authoritative and `tests/test_lowered_fixtures.py --write`
regenerates the committed goldens.

Strictly an OBSERVER: this module never mutates facts, never changes lowering,
and is imported by nothing in the production verdict path.

Normalization decisions (frozen; changing any is a parity-contract change):

* **Field order** is fixed by construction order in this file; arrays keep the
  bridge's semantic order (document order for records, lowering order for
  statements — BR-D4: input order is semantic, outputs are not sorted).
* **Statement shapes are closed**: every statement kind serializes a fixed
  field set under a `stmt` discriminator (`acquire`, `release`, `use`,
  `overspan`, `return`, `alias_join`, `call`, `subscribe`, `if`, `while`).
  There are no optional statement fields; `null` marks the one meaningful
  absence (a bare `return`). An AST node the bridge never emits (a `Move`, a
  `BorrowBlock`, a non-`Acquire` `Let` rhs, an `IntLit` argument) fails loud —
  the projection must not silently shadow an unknown lowering.
* **Conditions** are serialized verbatim (`cond`); the bridge always emits the
  opaque `"?"`, and the projection records rather than assumes that.
* **Callee strings** are serialized exactly as the lowering emitted them (a
  first-party name as written on the fact, a channel as `$consume`/`$borrow`/
  `$borrow_mut`); `global::` canonicalization is a routing input, not a
  projection transform.
* **The prelude resources and sink externs** are serialized always (they are
  unconditionally part of the lowered Module); **lifetime declarations** appear
  exactly when the bridge emitted them (some capture was minted) — an empty
  `lifetimes` array is the observable "no capture" state.
* **The handle map** is normalized, not a copy of the facts document: each
  handle serializes only the identity-relevant keys, in a fixed order, and
  only when present on the record: `component`, `file`, `line`, `event`,
  `handler`, `resource`, `released`, `source`, `source_type`,
  `di_source_life`, `type`, `ever_released`, `pool`. Handles appear in mint
  order.
* **Fail-loud lowerings** (`OwnIRError` from vocabulary skew) project as
  `{"error": "<message>"}` so the rejection text is part of the surface.
* Rendering is `json.dumps(indent=2, ensure_ascii=False)` + a trailing
  newline; regeneration is deterministic for identical input.
"""

from __future__ import annotations

import json
from typing import Any

from .ast_nodes import (
    Acquire,
    AliasJoin,
    Call,
    ExternDecl,
    FnDecl,
    If,
    Let,
    LifetimeDecl,
    Module,
    Overspan,
    Param,
    Release,
    ResourceDecl,
    Return,
    Stmt,
    Subscribe,
    TypeRef,
    Use,
    VarRef,
    While,
)
from .ownir import OwnIRError, to_module

# The Layer 2 surface version. Bump on ANY normalization change above — the
# committed goldens and the Rust replay are both keyed to it.
LOWERED_VERSION = 1

# The handle-map key allowlist, in serialization order (see the docstring).
_HANDLE_KEYS = (
    "component", "file", "line", "event", "handler", "resource", "released",
    "source", "source_type", "di_source_life", "type", "ever_released", "pool",
)


def _type(t: TypeRef | None) -> dict[str, Any] | None:
    if t is None:
        return None
    return {"name": t.name, "borrowed": t.borrowed, "mutable": t.mutable}


def _arg(a: Any) -> str:
    if isinstance(a, VarRef):
        return a.name
    raise ValueError(
        f"unprojectable call argument {type(a).__name__} — the bridge emits "
        f"VarRef arguments only; a new shape must extend the Layer 2 contract")


def _stmt(s: Stmt) -> dict[str, Any]:
    if isinstance(s, Let):
        if not isinstance(s.rhs, Acquire):
            raise ValueError(
                f"unprojectable Let rhs {type(s.rhs).__name__} — the bridge "
                f"lowers only `Let(Acquire)`; a new shape must extend the "
                f"Layer 2 contract")
        return {"stmt": "acquire", "handle": s.name,
                "resource": s.rhs.resource, "line": s.line}
    if isinstance(s, Release):
        return {"stmt": "release", "handle": s.var, "line": s.line}
    if isinstance(s, Use):
        return {"stmt": "use", "handle": s.var, "line": s.line}
    if isinstance(s, Overspan):
        return {"stmt": "overspan", "handle": s.var, "line": s.line}
    if isinstance(s, Return):
        return {"stmt": "return", "handle": s.var, "line": s.line}
    if isinstance(s, AliasJoin):
        return {"stmt": "alias_join", "handle": s.name, "src": s.src,
                "line": s.line}
    if isinstance(s, Call):
        return {"stmt": "call", "callee": s.callee,
                "args": [_arg(a) for a in s.args], "line": s.line}
    if isinstance(s, Subscribe):
        return {"stmt": "subscribe", "source": s.source, "line": s.line}
    if isinstance(s, If):
        return {"stmt": "if", "cond": s.cond_text,
                "then": [_stmt(x) for x in s.then_body],
                "else": [_stmt(x) for x in s.else_body], "line": s.line}
    if isinstance(s, While):
        return {"stmt": "while", "cond": s.cond_text,
                "body": [_stmt(x) for x in s.body], "line": s.line}
    raise ValueError(
        f"unprojectable statement {type(s).__name__} — the bridge never emits "
        f"it; a new shape must extend the Layer 2 contract")


def _param(p: Param) -> dict[str, Any]:
    return {"handle": p.name, "type": _type(p.type), "line": p.line,
            "lifetime": p.lifetime}


def _function(fn: FnDecl) -> dict[str, Any]:
    return {
        "name": fn.name,
        "lifetime": fn.lifetime,
        "params": [_param(p) for p in fn.params],
        "ret": _type(fn.ret),
        "body": [_stmt(s) for s in fn.body],
    }


def _resource(r: ResourceDecl) -> dict[str, Any]:
    return {
        "name": r.name,
        "kind": r.kind,
        "members": [{"role": m.role, "name": m.name} for m in r.members],
    }


def _extern(e: ExternDecl) -> dict[str, Any]:
    return {
        "name": e.name,
        "params": [{"effect": p.effect.name.lower(), "type": p.type_name}
                   for p in e.params],
    }


def _lifetime(lt: LifetimeDecl) -> dict[str, Any]:
    return {"name": lt.name, "longer": lt.longer}


def _handle(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: rec[k] for k in _HANDLE_KEYS if k in rec}


def project_lowered(facts: dict[str, Any]) -> dict[str, Any]:
    """Project one facts document's lowered Module + handle map into the
    canonical Layer 2 dict. A lowering rejection (`OwnIRError`) projects as
    `{"lowered_version": ..., "error": <message>}` — the rejection text is
    part of the parity surface. Never mutates `facts`."""
    try:
        mod, handles = to_module(facts)
    except OwnIRError as e:
        return {"lowered_version": LOWERED_VERSION, "error": str(e)}
    assert isinstance(mod, Module)
    return {
        "lowered_version": LOWERED_VERSION,
        "module": mod.name,
        "resources": [_resource(r) for r in mod.resources],
        "externs": [_extern(e) for e in mod.externs],
        "lifetimes": [_lifetime(lt) for lt in mod.lifetimes],
        "functions": [_function(fn) for fn in mod.functions],
        "handles": {h: _handle(rec) for h, rec in handles.items()},
    }


def render_lowered(facts: dict[str, Any]) -> str:
    """The canonical serialized form: fixed field order, 2-space indent,
    non-ASCII preserved, trailing newline. Byte-identical on re-run."""
    return json.dumps(project_lowered(facts), indent=2, ensure_ascii=False) + "\n"
