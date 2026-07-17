"""Guard the aggregate test-runner contract — the ENFORCEABLE version.

The real enforcement is a PREFLIGHT in run_tests.py: before importing any test_*.py it
calls _preflight.check_test_files(), which refuses any sys.exit / raise SystemExit that
is not inside a standalone `if __name__ == "__main__":` guard body. That runs first, so an
offender cannot sort ahead of the check and end the process during import.

This module proves the scanner behind that preflight: it exercises the location invariant
(no exemption for function/lambda/class bodies — an immediately-invoked helper defeats any
call-graph exemption), checks the live tests directory, and — the load-bearing regression —
builds a throwaway tests directory whose EARLIEST-sorting file exits at import and confirms
the preflight reports it (so the runner would return failure, not silent success).
"""

from __future__ import annotations

import ast
import os
import tempfile

from _preflight import check_test_files, exit_violations

failures: list[str] = []
checks = 0

_HERE = os.path.dirname(os.path.abspath(__file__))

# MUST be reported as violations — including exits buried in a function / lambda / class
# body, because a module-scope call (or an IIFE) runs them at import.
_MUST_CATCH = (
    ("bare module-scope exit", "import sys\nsys.exit(0)\n"),
    ("exit in `if True:`", "import sys\nif True:\n    sys.exit(0)\n"),
    ("exit in a top-level try",
     "import sys\ntry:\n    sys.exit(0)\nexcept Exception:\n    pass\n"),
    ("raise SystemExit at module scope", "raise SystemExit(1)\n"),
    ("exit in a for loop", "import sys\nfor _ in range(1):\n    sys.exit(0)\n"),
    ("exit in a main-guard else",
     "import sys\nif __name__ == '__main__':\n    pass\nelse:\n    sys.exit(0)\n"),
    ("raise SystemExit in a main-guard else",
     "if __name__ == '__main__':\n    pass\nelse:\n    raise SystemExit(1)\n"),
    ("exit in a main-guard elif",
     "import sys\nif __name__ == '__main__':\n    pass\nelif True:\n    sys.exit(0)\n"),
    ("exit in a class body", "import sys\nclass C:\n    sys.exit(7)\n"),
    ("exit in a class base", "import sys\nclass C(sys.exit(7)):\n    pass\n"),
    ("exit in a class decorator", "import sys\n@sys.exit(7)\nclass C:\n    pass\n"),
    ("exit in a function default", "import sys\ndef f(value=sys.exit(7)):\n    pass\n"),
    ("exit in a function decorator", "import sys\n@sys.exit(7)\ndef f():\n    pass\n"),
    ("exit in a lambda default", "import sys\nf = lambda value=sys.exit(7): None\n"),
    # The blocker-2 forms: a body that IS reached at import.
    ("exit in a helper called at module scope",
     "import sys\ndef abort():\n    sys.exit(7)\nabort()\n"),
    ("exit in an immediately-invoked lambda", "import sys\nv = (lambda: sys.exit(7))()\n"),
    # And even an UNCALLED body — the strict location rule refuses it regardless.
    ("exit in an uncalled function body", "import sys\ndef f():\n    sys.exit(7)\n"),
    ("exit in a class method body",
     "import sys\nclass C:\n    def m(self):\n        sys.exit(7)\n"),
)
# MUST be accepted: only the `__main__` guard body, or no exit at all, or a string literal.
_MUST_PASS = (
    ("guarded entrypoint", "import sys\nif __name__ == '__main__':\n    sys.exit(0)\n"),
    ("guarded raise SystemExit(run())",
     "def run():\n    return 0\nif __name__ == '__main__':\n    raise SystemExit(run())\n"),
    ("guarded exit nested under an inner if",
     "import sys\nif __name__ == '__main__':\n    if '--x' in sys.argv:\n"
     "        raise SystemExit(0)\n"),
    ("no exit at all", "def run():\n    return 0\n"),
    ("exit only as a string literal", "MSG = 'call sys.exit(0) to quit'\n"),
)


def _violates(src: str) -> bool:
    return bool(exit_violations(ast.parse(src)))


def run() -> int:
    global checks
    for label, src in _MUST_CATCH:
        checks += 1
        if not _violates(src):
            failures.append(f"scanner self-test: failed to catch {label}")
    for label, src in _MUST_PASS:
        checks += 1
        if _violates(src):
            failures.append(f"scanner self-test: wrongly flagged {label}")

    # The live tests directory must itself be clean (this is what the runner enforces).
    checks += 1
    live = check_test_files(_HERE)
    if live:
        failures.append("live tests directory has import-time-exit violations: "
                        + "; ".join(live))

    # The load-bearing regression: an offender that sorts BEFORE any policing module must be
    # caught by the preflight, so the runner returns failure instead of a silent green. Also
    # a helper invoked at module scope — the blocker-2 case call-graph pruning would miss.
    checks += 1
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "test_aaa_offender.py"), "w", encoding="utf-8") as fh:
            fh.write("import sys\nsys.exit(0)\n")
        with open(os.path.join(tmp, "test_zzz_helper.py"), "w", encoding="utf-8") as fh:
            fh.write("import sys\n\n\ndef _boom():\n    sys.exit(0)\n\n\n_boom()\n")
        with open(os.path.join(tmp, "test_mmm_clean.py"), "w", encoding="utf-8") as fh:
            fh.write("def run():\n    return 0\n\n\nif __name__ == '__main__':\n"
                     "    raise SystemExit(run())\n")
        found = check_test_files(tmp)
        offenders = {p.split(":", 1)[0] for p in found}
        if offenders != {"test_aaa_offender.py", "test_zzz_helper.py"}:
            failures.append(f"preflight regression: flagged {sorted(offenders)}, expected "
                            "the bare-exit and helper-invoked offenders only "
                            "(the guarded module must pass)")

    print(f"harness contract: {checks - len(failures)}/{checks} checks pass")
    for f in failures:
        print(f"  FAIL: {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
