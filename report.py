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

from . import ast_nodes as A
from .buffers import resolve as resolve_buffer, Policy
from .diagnostics import Diagnostic


# Diagnostics that, if present for a given buffer, mean a specific check failed.
_CHECK_CODES = {
    "noEscape": {"OWN015", "OWN016"},
    "releaseOnAllPaths": {"OWN001"},
    "noUseAfterRelease": {"OWN002", "OWN009"},
    "noActiveLoansAtRelease": {"OWN008"},
}


def _walk_buffers(stmts: list[A.Stmt]):
    """Yield (let_name, BufferIntent) for every buffer intent in a statement
    tree, descending into if-branches and borrow blocks."""
    for st in stmts:
        if isinstance(st, A.Let) and isinstance(st.rhs, A.BufferIntent):
            yield st.name, st.rhs
        elif isinstance(st, A.If):
            yield from _walk_buffers(st.then_body)
            yield from _walk_buffers(st.else_body)
        elif isinstance(st, A.BorrowBlock):
            yield from _walk_buffers(st.body)


def build_report(mod: A.Module, diags: list[Diagnostic]) -> dict:
    policies: dict[str, Policy] = {
        p.name: Policy(p.name, dict(p.settings), p.line) for p in mod.policies
    }
    # function line spans, so a buffer named `buf` in fn A does not pick up a
    # diagnostic about a buffer named `buf` in fn B.
    ordered = sorted(mod.functions, key=lambda f: f.line)
    spans: dict[int, tuple[int, int]] = {}
    for i, fn in enumerate(ordered):
        hi = ordered[i + 1].line if i + 1 < len(ordered) else 1 << 30
        spans[id(fn)] = (fn.line, hi)

    entries: list[dict] = []
    for fn in mod.functions:
        lo, hi = spans[id(fn)]
        fn_diags = [d for d in diags if lo <= d.line < hi]
        for name, intent in _walk_buffers(fn.body):
            info, _ = resolve_buffer(intent, policies)
            mine = [d for d in fn_diags if f"'{name}'" in d.message]
            mine_codes = {d.code for d in mine}
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
                "trace": info.trace,
                "counters": info.counters,
                "policy": info.policy_name,
                "branches": info.branches(),
                "checks": checks,
            })
    return {"module": mod.name, "buffers": entries}


def render_report(report: dict) -> str:
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
        if e["policy"]:
            lines.append(f"  Policy: {e['policy']}")
        lines.append("  Generated branches:")
        for b in e["branches"]:
            lines.append(f"    {b['condition']:<18} -> {b['backend']}")
        lines.append("  Checks:")
        for k, v in e["checks"].items():
            lines.append(f"    {'ok ' if v else 'FAIL'} {k}")
    return "\n".join(lines)
