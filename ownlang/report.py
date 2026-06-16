"""
Compile-time buffer report — the first of the three logging surfaces.

The whole point of the scratch/stack line is that it must not be magic. A buffer
that "smartly" chose the pool while the developer thought it lived on the stack
is exactly the kind of abstraction that lies. So at generation time we write down,
per buffer: the mode the user asked for, the inline limit, the fallback, the
escape policy, whether it is cleared on release, the runtime branches codegen
emitted, and which ownership checks held. It goes to stdout for a human and to
`.ownreport.json` for review tooling / CI.

(The other two surfaces are runtime: the OwnTrace text hook and the OwnCounters,
both emitted into the generated C# by codegen.py under [Conditional] guards.)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from . import ast_nodes as A
from .buffers import MODE_NAMES, Policy
from .buffers import resolve as resolve_buffer
from .diagnostics import Diagnostic

# Diagnostics that, if present for a given buffer, mean a specific check failed.
_CHECK_CODES = {
    "noEscape": {"OWN015", "OWN016", "OWN017"},
    "releaseOnAllPaths": {"OWN001"},
    "noUseAfterRelease": {"OWN002", "OWN009"},
    "noActiveLoansAtRelease": {"OWN008"},
}


def _walk_buffers(
    stmts: list[A.Stmt],
) -> Iterator[tuple[str, A.BufferIntent]]:
    """Yield (let_name, BufferIntent) for every buffer intent in a statement
    tree, descending into if-branches and borrow blocks."""
    for st in stmts:
        if isinstance(st, A.Let) and isinstance(st.rhs, A.BufferIntent):
            yield st.name, st.rhs
        elif isinstance(st, A.If):
            yield from _walk_buffers(st.then_body)
            yield from _walk_buffers(st.else_body)
        elif isinstance(st, (A.While, A.BorrowBlock)):
            yield from _walk_buffers(st.body)


def build_report(mod: A.Module, diags: list[Diagnostic]) -> dict[str, Any]:
    policies: dict[str, Policy] = {
        p.name: Policy(p.name, dict(p.settings), p.line) for p in mod.policies
    }
    # diagnostics are attributed to a buffer by its stable identity (name#line),
    # carried on Diagnostic.subject — NOT by matching the name in the message,
    # which would conflate same-named buffers in sibling scopes. Move-aliases
    # already share the original buffer's subject (set in the checker).
    by_subject: dict[str, set[str]] = {}
    for d in diags:
        if d.subject is not None:
            by_subject.setdefault(d.subject, set()).add(d.code)

    entries: list[dict[str, Any]] = []
    for fn in mod.functions:
        for name, intent in _walk_buffers(fn.body):
            # skip a malformed intent (bad namespace or mode, e.g. Foo.stack /
            # Buffer.bogus); the checker already reported OWN030, and resolving an
            # unknown mode would throw.
            if intent.ns != "Buffer" or intent.mode not in MODE_NAMES:
                continue
            info, _ = resolve_buffer(intent, policies)
            mine_codes = by_subject.get(f"{name}#{intent.line}:{intent.col}", set())
            checks = {
                check: not (codes & mine_codes)
                for check, codes in _CHECK_CODES.items()
            }
            entries.append({
                "function": fn.name,
                "buffer": name,
                "mode": info.mode.value,
                "inlineBytes": info.inline_bytes,
                "fallback": ("ArrayPool" if info.fallback_pool
                             else ("NativeMemory" if info.mode.value == "native"
                                   else "forbidden")),
                "escapePolicy": info.escape_policy,
                "clearOnRelease": info.clear_on_release,
                "sensitive": info.sensitive,
                "trace": info.trace,
                "counters": info.counters,
                "policy": info.policy_name,
                "branches": info.branches(),
                "checks": checks,
            })
    return {"module": mod.name, "buffers": entries}


def render_report(report: dict[str, Any]) -> str:
    lines: list[str] = [f"buffer report for module '{report['module']}'"]
    if not report["buffers"]:
        lines.append("  (no buffers)")
        return "\n".join(lines)
    for e in report["buffers"]:
        lines.append("")
        lines.append(f"Function: {e['function']}")
        lines.append(f"Buffer: {e['buffer']}")
        lines.append(f"  Mode: {e['mode']}")
        lines.append(f"  InlineLimit: {e['inlineBytes']} bytes")
        lines.append(f"  Fallback: {e['fallback']}")
        lines.append(f"  EscapePolicy: {e['escapePolicy']}")
        lines.append(f"  ClearOnRelease: {str(e['clearOnRelease']).lower()}")
        lines.append(f"  Sensitive: {str(e['sensitive']).lower()}")
        if e["policy"]:
            lines.append(f"  Policy: {e['policy']}")
        lines.append("  Generated branches:")
        for b in e["branches"]:
            lines.append(f"    {b['condition']:<18} -> {b['backend']}")
        lines.append("  Checks:")
        for k, v in e["checks"].items():
            lines.append(f"    {'ok ' if v else 'FAIL'} {k}")
    return "\n".join(lines)
