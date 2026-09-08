#!/usr/bin/env python3
"""TEMPORARY — #261 H.0: measure `python -m ownlang ownir` on this platform.

The implementing environment for #261 is Linux-only, and three of the
reference's behaviours are platform-shaped:

* **non-ASCII output**, because the reference `print`s through the console or
  pipe encoding, so a Windows run may emit different bytes than a Linux one —
  or fail outright with a `UnicodeEncodeError`, which would land on the exit-70
  catch-all;
* **closed stdout**, which on Linux is a deterministic `BrokenPipeError` and
  exit 70;
* **interruption**, which #261 rules must be *measured* on both platforms
  before anything is written down, and where `130` is explicitly not to be
  invented as a universal contract.

This script asserts nothing and gates nothing. It prints what it saw and exits
0, so the run's log is the record. It is deleted together with
`.github/workflows/cli-reference-measurement.yml` once
`docs/notes/p022-cli-ownir.md` carries the numbers.

Usage:  python scripts/measure_cli_reference.py {streams|closed-stdout|interrupt}
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURES = os.path.join(_ROOT, "tests", "fixtures")
# The synthesized large document lives in the system temp dir, never in the
# tree: it is an input to a measurement, not an artifact of one.
_SCRATCH = os.path.join(tempfile.gettempdir(), "cli-reference-measurement")


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "OWNLANG_DEBUG"}
    env["PYTHONPATH"] = _ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _banner() -> None:
    print(f"platform            : {platform.platform()}")
    print(f"python              : {sys.version.split()[0]}")
    print(f"sys.stdout.encoding : {sys.stdout.encoding}")
    print(f"filesystem encoding : {sys.getfilesystemencoding()}")
    print("-" * 72)


def _run(argv: list[str], cwd: str) -> tuple[int, bytes, bytes]:
    proc = subprocess.run(
        [sys.executable, "-m", "ownlang", "ownir", *argv],
        capture_output=True, check=False, env=_env(), cwd=cwd)
    return proc.returncode, proc.stdout, proc.stderr


def _show(label: str, code: int, out: bytes, err: bytes) -> None:
    print(f"### {label}")
    print(f"    exit   : {code}")
    print(f"    stdout : {out!r}")
    print(f"    stderr : {err!r}")
    print(f"    stdout is pure ASCII: {all(b < 128 for b in out)}")
    print()


def streams() -> int:
    """Every case whose bytes could depend on the console encoding, plus the
    two whose text is the platform's own."""
    cli = os.path.join(_FIXTURES, "cli_ownir")
    cases: list[tuple[str, list[str]]] = [
        ("non-ASCII `file`, human", ["inputs/nonascii_file.facts.json"]),
        ("non-ASCII `file`, github",
         ["inputs/nonascii_file.facts.json", "--format", "github"]),
        ("non-ASCII `file`, sarif",
         ["inputs/nonascii_file.facts.json", "--format", "sarif"]),
        ("non-ASCII + space in the PATH", ["inputs/pa th ünïcødé/facts.json"]),
        ("the em dash in the ok line", ["../verdict_renders/render_empty.facts.json"]),
        ("a missing file (OS error text)", ["inputs/no_such_facts.json"]),
        ("a directory (OS error text)", ["inputs"]),
    ]
    for label, argv in cases:
        _show(label, *_run(argv, cli))
    return 0


def closed_stdout() -> int:
    """What the reference does when the consumer goes away. On Linux this is a
    deterministic `BrokenPipeError` and exit 70."""
    cli = os.path.join(_FIXTURES, "cli_ownir")
    big = os.path.join(_SCRATCH, "big.facts.json")
    os.makedirs(_SCRATCH, exist_ok=True)
    document = {"ownir_version": 0, "module": "Big", "components": [
        {"name": f"Vm{c}", "file": f"Vm{c}.cs", "subscriptions": [
            {"event": f"Bus{c}.E{s}", "handler": f"On{s}", "line": s + 1,
             "source": "static"} for s in range(40)]}
        for c in range(400)]}
    with open(big, "w", encoding="utf-8") as handle:
        json.dump(document, handle)

    for trial in range(3):
        producer = subprocess.Popen(
            [sys.executable, "-m", "ownlang", "ownir", big, "--format", "sarif"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env(), cwd=cli)
        # Read one byte and close: the producer is still writing megabytes.
        assert producer.stdout is not None
        producer.stdout.read(1)
        producer.stdout.close()
        _, err = producer.communicate()
        print(f"### closed stdout, trial {trial}")
        print(f"    exit   : {producer.returncode}")
        print(f"    stderr : {err[:400]!r}")
        print()
    return 0


def interrupt() -> int:
    """Interruption, measured rather than assumed.

    On Windows a console Ctrl+C cannot be aimed at one child, so the child is
    started in its own process group and sent `CTRL_BREAK_EVENT` — which
    CPython raises as `KeyboardInterrupt` exactly as Ctrl+C does. On Unix the
    equivalent is `SIGINT` to the child's own session.
    """
    import signal
    cli = os.path.join(_FIXTURES, "cli_ownir")
    big = os.path.join(_SCRATCH, "big.facts.json")
    if not os.path.exists(big):
        closed_stdout()

    windows = os.name == "nt"
    for trial in range(3):
        kwargs: dict[str, object] = {}
        if windows:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        child = subprocess.Popen(
            [sys.executable, "-m", "ownlang", "ownir", big, "--format", "sarif"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=_env(), cwd=cli,
            **kwargs)  # type: ignore[arg-type]
        time.sleep(0.6)
        try:
            if windows:
                os.kill(child.pid, signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(os.getpgid(child.pid), signal.SIGINT)
        except OSError as exc:
            print(f"### interrupt trial {trial}: could not signal: {exc}")
            child.kill()
            child.communicate()
            continue
        out, err = child.communicate()
        text = err.decode("utf-8", "replace")
        print(f"### interrupt trial {trial}")
        print(f"    returncode : {child.returncode}")
        print(f"    stdout     : {len(out)} bytes")
        print(f"    stderr tail: {text[-300:]!r}")
        print()
    return 0


_MODES = {"streams": streams, "closed-stdout": closed_stdout,
          "interrupt": interrupt}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in _MODES:
        print(f"usage: measure_cli_reference.py {{{'|'.join(_MODES)}}}",
              file=sys.stderr)
        return 2
    _banner()
    return _MODES[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
