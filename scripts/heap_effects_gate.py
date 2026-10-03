#!/usr/bin/env python3
"""H0 heap-effect summaries: the real extractor behind the committed sidecar, and inertness.

`tests/test_heap_effects_fixtures.py` and `own-bridge/tests/heap_effects.rs` replay the
committed sidecar with zero `dotnet`. This script is the producer half (needs `dotnet` on
PATH; zero Python dependencies):

1. **samples** — `frontend/roslyn/heap-effects-samples/HeapEffects.cs` is run through
   the extractor with `--heap-effects`; the sidecar must equal the committed
   `tests/fixtures/heap_effects/samples.sidecar.json` (JSON-equal: the extractor writes
   platform newlines), and the reference solver must accept it.

2. **inert** — for every input below the extractor runs twice, without and with
   `--heap-effects`: the exit code, stderr and the facts document must be
   BYTE-identical. The flag writes a separate file and nothing else; no spelling of it
   can move a fact, a verdict or a refusal. Inputs: every state-protocol case (with the
   sample API, `--flow-locals`), the protocol refusals (the refusal text must not
   move either), the heap-effect samples, and `examples/` as one scan.

Run:  python scripts/heap_effects_gate.py            (verify)
      python scripts/heap_effects_gate.py --write    (regenerate the samples sidecar)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from ownlang.heap_effects import HeapEffectsError, render  # noqa: E402

EXTRACTOR = os.path.join(ROOT, "frontend", "roslyn", "OwnSharp.Extractor")
SAMPLE_REL = "frontend/roslyn/heap-effects-samples/HeapEffects.cs"
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "heap_effects", "samples.sidecar.json")
PROTO_REL = "frontend/roslyn/protocol-samples"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def _extractor_dll() -> str:
    built = _run(["dotnet", "build", EXTRACTOR, "-c", "Release", "-nologo", "-v", "q"])
    if built.returncode != 0:
        print(built.stdout[-2000:])
        raise SystemExit("FAIL: the extractor does not build")
    return os.path.join(EXTRACTOR, "bin", "Release", "net8.0", "ownsharp-extract.dll")


def samples(dll: str, write: bool, fails: list[str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sidecar = os.path.join(tmp, "he.json")
        done = _run(["dotnet", dll, SAMPLE_REL, "-o", os.path.join(tmp, "facts.json"),
                     "--heap-effects", sidecar])
        if done.returncode != 0:
            fails.append(f"samples: the extractor exited {done.returncode}: {done.stderr[-300:]}")
            return
        with open(sidecar, encoding="utf-8") as f:
            doc = json.load(f)
    if write:
        with open(FIXTURE, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    else:
        with open(FIXTURE, encoding="utf-8") as f:
            if json.load(f) != doc:
                fails.append("samples: the extractor no longer emits the committed sidecar "
                             "(tests/fixtures/heap_effects/samples.sidecar.json); run with --write")
    try:
        render(json.dumps(doc))
    except HeapEffectsError as e:
        fails.append(f"samples: the reference rejects the extractor's sidecar: {e}")


def _inputs() -> list[tuple[str, list[str]]]:
    runs: list[tuple[str, list[str]]] = []
    cases = os.path.join(ROOT, PROTO_REL, "cases")
    for name in sorted(os.listdir(cases)):
        if name.endswith(".cs"):
            runs.append((f"cases/{name}", [f"{PROTO_REL}/Api", f"{PROTO_REL}/cases/{name}",
                                           "--flow-locals"]))
    runs.append(("heap-effects-samples", [SAMPLE_REL, "--flow-locals"]))
    runs.append(("heap-effects-samples (no flow)", [SAMPLE_REL]))
    runs.append(("examples/", ["examples", "--flow-locals"]))
    return runs


def _refusal_inputs(tmp: str) -> list[tuple[str, list[str]]]:
    """The protocol refusals (exit 2): a refusal must be the same refusal with the flag."""
    runs: list[tuple[str, list[str]]] = []
    refused = os.path.join(ROOT, PROTO_REL, "refused")
    for name in sorted(os.listdir(refused)):
        if name.endswith(".cs.txt"):
            staged = os.path.join(tmp, name[: -len(".txt")])
            shutil.copyfile(os.path.join(refused, name), staged)
            runs.append((f"refused/{name}", [f"{PROTO_REL}/Api", staged, "--flow-locals"]))
    return runs


def inert(dll: str, fails: list[str]) -> int:
    count = 0
    with tempfile.TemporaryDirectory() as tmp:
        for label, args in _inputs() + _refusal_inputs(tmp):
            plain_out = os.path.join(tmp, "plain.json")
            flag_out = os.path.join(tmp, "flag.json")
            sidecar = os.path.join(tmp, "sidecar.json")
            for path in (plain_out, flag_out, sidecar):
                if os.path.exists(path):
                    os.remove(path)
            plain = _run(["dotnet", dll, *args, "-o", plain_out])
            flag = _run(["dotnet", dll, *args, "-o", flag_out, "--heap-effects", sidecar])
            count += 1
            if (plain.returncode, plain.stderr) != (flag.returncode, flag.stderr):
                fails.append(f"inert {label}: exit/stderr moved with --heap-effects "
                             f"({plain.returncode} -> {flag.returncode})")
                continue
            if os.path.exists(plain_out) != os.path.exists(flag_out):
                fails.append(f"inert {label}: a facts file appeared or vanished with the flag")
                continue
            if os.path.exists(plain_out):
                with open(plain_out, "rb") as a, open(flag_out, "rb") as b:
                    if a.read() != b.read():
                        fails.append(f"inert {label}: the facts document moved with --heap-effects")
                with open(sidecar, encoding="utf-8") as f:
                    try:
                        render(f.read())
                    except HeapEffectsError as e:
                        fails.append(f"inert {label}: the reference rejects the sidecar: {e}")
    return count


def main() -> int:
    write = "--write" in sys.argv[1:]
    dll = _extractor_dll()
    fails: list[str] = []
    samples(dll, write, fails)
    n = inert(dll, fails)
    for f in fails:
        print(f"FAIL: {f}")
    print(f"heap-effects gate: samples sidecar + {n} inertness runs — "
          f"{'FAIL' if fails else 'PASS'}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
