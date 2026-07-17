"""Preflight for the aggregate test runner.

run_tests.py discovers every `test_*.py` and imports it with importlib. A single
import-time `sys.exit(...)` / `raise SystemExit(...)` in ANY of them ends the whole process
before the aggregate return code is collected — and the offender can sort BEFORE whatever
module is meant to police it, so a policing test module cannot catch it. The check must
therefore run as a PREFLIGHT, before the first test import (run_tests.run() calls
check_test_files() first and aborts on any violation).

The invariant is deliberately strict and purely LOCATION-based — no call-graph analysis,
which an immediately-invoked helper or lambda defeats:

    a test_*.py may use sys.exit / raise SystemExit ONLY inside the body of a standalone
    top-level `if __name__ == "__main__":` guard — nowhere else (not module scope, not a
    function/lambda/class body, not a decorator or default).
"""

from __future__ import annotations

import ast
import os


def _is_main_guard(test: ast.expr) -> bool:
    """Structurally EXACTLY `__name__ == "__main__"`."""
    return (isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name) and test.left.id == "__name__"
            and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__")


def _is_systemexit(exc: ast.expr | None) -> bool:
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "SystemExit"


def _is_sys_exit(func: ast.expr) -> bool:
    return (isinstance(func, ast.Attribute) and func.attr == "exit"
            and isinstance(func.value, ast.Name) and func.value.id == "sys")


def _guard_body_ids(module: ast.Module) -> set[int]:
    """Every AST node lexically inside a standalone top-level `if __name__ == "__main__":`
    BODY (its `else`/`elif` are NOT included — they run on import)."""
    allowed: set[int] = set()
    for stmt in module.body:
        if isinstance(stmt, ast.If) and _is_main_guard(stmt.test):
            for s in stmt.body:
                for node in ast.walk(s):
                    allowed.add(id(node))
    return allowed


def exit_violations(tree: ast.Module) -> list[ast.AST]:
    """Every sys.exit call / raise SystemExit that sits OUTSIDE a main-guard body — which,
    for a module imported by the runner, is any that could run at import (directly or via a
    helper called at module scope). No exemption for function/lambda/class bodies."""
    allowed = _guard_body_ids(tree)
    bad: list[ast.AST] = []
    for node in ast.walk(tree):
        if id(node) in allowed:
            continue
        if isinstance(node, ast.Raise) and _is_systemexit(node.exc):
            bad.append(node)
        elif isinstance(node, ast.Call) and _is_sys_exit(node.func):
            bad.append(node)
    return bad


def check_test_files(tests_dir: str) -> list[str]:
    """Return a list of human-readable violations across every test_*.py in `tests_dir`.
    Empty means every test module is safe for the runner to import."""
    problems: list[str] = []
    for fname in sorted(os.listdir(tests_dir)):
        if not (fname.startswith("test_") and fname.endswith(".py")):
            continue
        path = os.path.join(tests_dir, fname)
        try:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=fname)
        except (OSError, SyntaxError) as exc:
            problems.append(f"{fname}: cannot parse ({exc})")
            continue
        for node in exit_violations(tree):
            problems.append(
                f"{fname}:{node.lineno}: sys.exit / raise SystemExit outside the "
                "`if __name__ == \"__main__\"` guard body — it would end the aggregate "
                "runner at import time"
            )
    return problems
