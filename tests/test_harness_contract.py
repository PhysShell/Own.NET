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


def _future_annotations(module: ast.AST) -> bool:
    body = getattr(module, "body", [])
    for stmt in body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
            if any(alias.name == "annotations" for alias in stmt.names):
                return True
    return False


def _annotation_exprs(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    a = func.args
    exprs = [arg.annotation for arg in
             (*a.posonlyargs, *a.args, *a.kwonlyargs) if arg.annotation]
    for extra in (a.vararg, a.kwarg):
        if extra is not None and extra.annotation is not None:
            exprs.append(extra.annotation)
    if func.returns is not None:
        exprs.append(func.returns)
    return exprs


def _module_scope_exit(node: ast.AST, ann_eager: bool | None = None) -> bool:
    """True if a sys.exit(...) / raise SystemExit(...) would fire at IMPORT time. Only the
    genuinely DEFERRED subtrees are pruned: a function / async-function / lambda BODY, and
    the `if __name__ == "__main__"` body. Everything else runs on import and is scanned —
    class bodies + bases + keywords, decorators, argument defaults, lambda defaults, and
    (unless `from __future__ import annotations` is in force) annotations. The node itself
    is checked BEFORE its children, so a decorator / default that IS `sys.exit(...)` is
    caught, not just its arguments."""
    if ann_eager is None:  # decided once, at the module root, then threaded down
        ann_eager = not _future_annotations(node)

    if isinstance(node, ast.Raise) and _is_systemexit(node.exc):
        return True
    if isinstance(node, ast.Call) and _is_sys_exit(node.func):
        return True
    if isinstance(node, ast.If) and _is_main_guard(node.test):
        # ONLY the guard's body is exempt — its `else:` (and `elif`) still run on import.
        return any(_module_scope_exit(s, ann_eager) for s in node.orelse)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        eager = [*node.decorator_list, *node.args.defaults,
                 *[d for d in node.args.kw_defaults if d is not None]]
        if ann_eager:
            eager += _annotation_exprs(node)
        return any(_module_scope_exit(e, ann_eager) for e in eager)
    if isinstance(node, ast.Lambda):
        eager = [*node.args.defaults, *[d for d in node.args.kw_defaults if d is not None]]
        return any(_module_scope_exit(e, ann_eager) for e in eager)
    # Everything else — module body, class body/bases/keywords/decorators, module-scope
    # control flow — executes on import; scan every child.
    return any(_module_scope_exit(c, ann_eager) for c in ast.iter_child_nodes(node))


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
    ("sys.exit in a main-guard else",
     "import sys\nif __name__ == '__main__':\n    pass\nelse:\n    sys.exit(0)\n"),
    ("raise SystemExit in a main-guard else",
     "if __name__ == '__main__':\n    pass\nelse:\n    raise SystemExit(1)\n"),
    ("exit in a main-guard elif",
     "import sys\nif __name__ == '__main__':\n    pass\nelif True:\n    sys.exit(0)\n"),
    # Declarations that run code AT IMPORT — the trapdoors that skipping a whole
    # FunctionDef / ClassDef / Lambda node would miss.
    ("exit in a class body", "import sys\nclass C:\n    sys.exit(7)\n"),
    ("exit in a class base", "import sys\nclass C(sys.exit(7)):\n    pass\n"),
    ("exit in a class decorator", "import sys\n@sys.exit(7)\nclass C:\n    pass\n"),
    ("exit in a function default", "import sys\ndef f(value=sys.exit(7)):\n    pass\n"),
    ("exit in a function decorator", "import sys\n@sys.exit(7)\ndef f():\n    pass\n"),
    ("exit in a keyword-only default",
     "import sys\ndef f(*, value=sys.exit(7)):\n    pass\n"),
    ("exit in a lambda default", "import sys\nf = lambda value=sys.exit(7): None\n"),
    ("exit in an eager annotation", "import sys\ndef f(x: sys.exit(7)):\n    pass\n"),
)
_SELFTEST_MUST_PASS = (
    ("guarded entrypoint", "import sys\nif __name__ == '__main__':\n    sys.exit(0)\n"),
    ("exit inside a function", "import sys\ndef run():\n    sys.exit(0)\n"),
    ("exit inside a lambda", "f = lambda: __import__('sys').exit(0)\n"),
    ("exit inside a class method body",
     "import sys\nclass C:\n    def m(self):\n        sys.exit(0)\n"),
    ("stringified annotation under future-annotations",
     "from __future__ import annotations\nimport sys\ndef f(x: sys.exit(7)):\n    pass\n"),
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
