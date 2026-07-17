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


def _is_main_guard(test: ast.expr) -> bool:
    """Structurally recognise EXACTLY `__name__ == "__main__"` — not any top-level `if`,
    so `if True: sys.exit(0)` is NOT waved through."""
    return (isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name) and test.left.id == "__name__"
            and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__")


def _module_scope_exit(node: ast.AST) -> bool:
    """True if a sys.exit(...) / raise SystemExit(...) would fire at IMPORT time. Descends
    through module-scope compound statements (if / try / with / for / while) but NOT into
    a new scope (function / class / lambda) and NOT into the `if __name__ == "__main__"`
    entrypoint — so an exit inside `if True:` or a top-level `try:` IS caught, while the
    real guard and any function body are not."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.Lambda, ast.ClassDef)):
            continue  # a new scope: its body does not run on import
        if isinstance(child, ast.If) and _is_main_guard(child.test):
            continue  # the sanctioned entrypoint
        if isinstance(child, ast.Raise) and _is_systemexit(child.exc):
            return True
        if isinstance(child, ast.Call) and _is_sys_exit(child.func):
            return True
        if _module_scope_exit(child):
            return True
    return False


def _is_systemexit(exc: ast.expr | None) -> bool:
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "SystemExit"


def _is_sys_exit(func: ast.expr) -> bool:
    return (isinstance(func, ast.Attribute) and func.attr == "exit"
            and isinstance(func.value, ast.Name) and func.value.id == "sys")


_SELFTEST_MUST_CATCH = (
    ("bare sys.exit at module scope", "import sys\nsys.exit(0)\n"),
    ("exit inside `if True:`", "import sys\nif True:\n    sys.exit(0)\n"),
    ("exit inside a top-level try",
     "import sys\ntry:\n    sys.exit(0)\nexcept Exception:\n    pass\n"),
    ("raise SystemExit at module scope", "raise SystemExit(1)\n"),
    ("exit inside a for loop", "import sys\nfor _ in range(1):\n    sys.exit(0)\n"),
)
_SELFTEST_MUST_PASS = (
    ("guarded entrypoint", "import sys\nif __name__ == '__main__':\n    sys.exit(0)\n"),
    ("exit inside a function", "import sys\ndef run():\n    sys.exit(0)\n"),
    ("exit inside a lambda", "f = lambda: __import__('sys').exit(0)\n"),
)


def run() -> int:
    global checks
    # Self-test the guard first: it must catch the ways the original bug could recur, and
    # must NOT flag the sanctioned entrypoint or an exit that only lives inside a scope.
    for label, src in _SELFTEST_MUST_CATCH:
        checks += 1
        if not _module_scope_exit(ast.parse(src)):
            failures.append(f"guard self-test: failed to catch {label}")
    for label, src in _SELFTEST_MUST_PASS:
        checks += 1
        if _module_scope_exit(ast.parse(src)):
            failures.append(f"guard self-test: wrongly flagged {label}")

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
