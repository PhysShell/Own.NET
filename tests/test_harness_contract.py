"""Guard the aggregate test-runner contract itself.

The bug this pins down: a `test_*.py` that executes its checks at import time and ends with
`sys.exit(...)` ends the WHOLE process when run_tests.py imports it, silently dropping every
module discovered after it and the aggregate return code. This module statically proves that
CANNOT happen — every sibling `test_*.py` exposes `run()` and never calls sys.exit /
raise SystemExit at module scope (only under an `if __name__ == "__main__"` guard).
"""

from __future__ import annotations

import ast
import os

failures: list[str] = []
checks = 0

_HERE = os.path.dirname(os.path.abspath(__file__))


def _module_scope_exit(tree: ast.AST) -> bool:
    """True if a sys.exit(...) / raise SystemExit(...) sits at module scope (i.e. would
    fire on import) rather than inside a function or an `if __name__ == '__main__'` guard."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.If):
            continue  # the `if __name__ == "__main__"` entrypoint is fine
        for sub in ast.walk(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # do not descend into nested scopes for THIS module-scope check
                break
            if isinstance(sub, ast.Raise) and _is_systemexit(sub.exc):
                return True
            if isinstance(sub, ast.Call) and _is_sys_exit(sub.func):
                return True
    return False


def _is_systemexit(exc: ast.expr | None) -> bool:
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "SystemExit"


def _is_sys_exit(func: ast.expr) -> bool:
    return (isinstance(func, ast.Attribute) and func.attr == "exit"
            and isinstance(func.value, ast.Name) and func.value.id == "sys")


def run() -> int:
    global checks
    for fname in sorted(os.listdir(_HERE)):
        if not (fname.startswith("test_") and fname.endswith(".py")):
            continue
        if fname == os.path.basename(__file__):
            continue
        checks += 1
        src = open(os.path.join(_HERE, fname), encoding="utf-8").read()
        tree = ast.parse(src)
        has_run = any(isinstance(n, ast.FunctionDef) and n.name == "run"
                      for n in ast.iter_child_nodes(tree))
        if not has_run:
            failures.append(f"{fname}: has no module-level run()")
        if _module_scope_exit(tree):
            failures.append(f"{fname}: calls sys.exit/raise SystemExit at import scope "
                            "(would short-circuit the aggregate runner)")
    print(f"harness contract: {checks - len(failures)}/{checks} test modules honour run()")
    for f in failures:
        print(f"  FAIL: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
