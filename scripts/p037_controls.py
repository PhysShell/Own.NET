#!/usr/bin/env python3
"""Verify the P-037 conformance controls (corpus/p036-bakeoff/*/expected.json)
against their recorded expectations, on two layers.

The controls are the executable form of P-037 §8 rows 18-19 (G-V4) and the
G-T2b class-3 shape. Three of them are KNOWN false positives of Owen today:
the extractor's flow-insensitive ``ConsumesParam`` lowers a call to a release
whenever the callee disposes on *some* path, so an honest defensive dispose is
charged OWN003. By owner ruling (2026-09-18) they are pre-A1 regression
anchors, not authorization for a pre-cutover fix: ``expected.json`` records
BOTH what Owen does today (``current``) and what A1 must make it do
(``post_a1``), so the evidence lies about neither.

Two layers, because the emitted facts show the defect is decided in the
extractor before either engine runs (docs/notes/p037-formal-kernel.md §8.2):

1. extractor-fact layer — whether the call site carries a fabricated
   ``release`` op in the facts ``scripts/own-check.sh --emit-facts`` produces;
2. end-to-end layer — the finding codes ``own-check`` reports at
   ``--severity warning``.

Default: check ``current`` (must pass today; a difference means Owen's
behaviour moved and the record must be re-measured, never silently). With
``--post-a1``: check ``post_a1`` (the acceptance A1 discharges after P-022
Stage 3; expected to FAIL until then). Non-production: reads the controls,
runs the launcher, changes nothing. Exit 0 on all-match, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONTROLS = ROOT / "corpus" / "p036-bakeoff"
FINDING = re.compile(r":(\d+): (?:warning|error): \[(\w+)\]")


def own_check(control: Path, facts: Path) -> str:
    """Run the launcher at warning severity, emitting facts; return stdout."""
    cmd = [
        str(ROOT / "scripts" / "own-check.sh"),
        "--format",
        "human",
        "--severity",
        "warning",
        "--emit-facts",
        str(facts),
        str(control),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.stdout


def release_lines(facts: Path) -> set[int]:
    """Every source line carrying a `release` op in the emitted facts."""
    doc: Any = json.loads(facts.read_text(encoding="utf-8"))
    out: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("op") == "release" and isinstance(node.get("line"), int):
                out.add(int(node["line"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    return out


def check(control: Path, post_a1: bool) -> tuple[bool, str]:
    """Compare one control against its recorded expectation; (ok, report line)."""
    spec: dict[str, Any] = json.loads((control / "expected.json").read_text(encoding="utf-8"))
    layer = "post_a1" if post_a1 else "current"
    want: dict[str, Any] = spec[layer]
    with tempfile.TemporaryDirectory() as tmp:
        facts = Path(tmp) / "facts.json"
        text = own_check(control, facts)
        codes = sorted({m.group(2) for m in FINDING.finditer(text)})
        fabricated = spec["call_site_line"] in release_lines(facts) if facts.exists() else None
    want_codes = sorted(want["findings"])
    want_fab = bool(want["fabricated_release_at_call_site"])
    ok = codes == want_codes and fabricated == want_fab
    verdict = "ok" if ok else "MISMATCH"
    return ok, (
        f"{verdict:8} {control.name:42} [{spec['classification']}] "
        f"findings={codes} (want {want_codes})  "
        f"fabricated release at line {spec['call_site_line']}={fabricated} (want {want_fab})"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--post-a1",
        action="store_true",
        help="check the post-A1 acceptance instead of today's record",
    )
    parser.add_argument("--only", default="", help="comma-separated control names")
    args = parser.parse_args(argv)
    names = {n for n in args.only.split(",") if n}
    controls = sorted(
        p.parent for p in CONTROLS.glob("*/expected.json") if not names or p.parent.name in names
    )
    if not controls:
        print("no controls found", file=sys.stderr)
        return 2
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    has_dotnet = any(os.access(os.path.join(p, "dotnet"), os.X_OK) for p in path_dirs)
    if not os.environ.get("DOTNET_ROOT") and not has_dotnet:
        print(
            "dotnet is not on PATH and DOTNET_ROOT is unset: the extractor cannot run",
            file=sys.stderr,
        )
        return 2
    layer = "post-A1 acceptance" if args.post_a1 else "current record (measured at 70189a3)"
    print(f"P-037 controls — checking the {layer}")
    all_ok = True
    for control in controls:
        ok, line = check(control, args.post_a1)
        all_ok &= ok
        print(line)
    verdict = "all match" if all_ok else "mismatch — re-measure and re-record, never silently"
    print("RESULT:", verdict)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
