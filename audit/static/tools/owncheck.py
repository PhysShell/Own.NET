#!/usr/bin/env python3
"""
Own.NET Audit — own-check runner (build-free tier).

A thin wrapper around the existing ``scripts/own-check.sh --format sarif`` (Plan.md
§3.3: reused as-is, consumed only via its CLI). own-check uses an error-tolerant
Roslyn ``SemanticModel``, so it runs even on a solution that does not compile —
hence build-free. It is the one runner that expresses the subscription / timer /
region-escape leak classes the oracle tools cannot (Plan.md §2, cat. 2-4).

Requires a .NET SDK on PATH for the C# fact extractor. If ``dotnet`` is missing the
runner reports the tier as unavailable (a partial, honest result) instead of
crashing — the ``continue-on-error`` discipline from Plan.md §3.2.

Usage:
  owncheck.py --target /path/to/legacy/src --out artifacts/own-audit [--severity warning]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]  # audit/static/tools/ -> repo root
OWN_CHECK_SH = _REPO / "scripts" / "own-check.sh"


def run_own_check(target: str, out_dir: Path, severity: str = "warning",
                  root: Path | None = None) -> dict[str, Any]:
    """Run own-check over ``target`` and write its SARIF to ``out_dir``.

    Returns a status dict: tool, tier, available, and (on success) the SARIF path
    plus a finding count, or (on failure) a reason — never raises for an
    unavailable toolchain."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sarif_path = out_dir / "own-check.sarif"
    facts_path = out_dir / "own-check.facts.json"
    status: dict[str, Any] = {"tool": "own-check", "tier": "build-free",
                              "available": False, "sarif": None, "reason": ""}

    if not OWN_CHECK_SH.exists():
        status["reason"] = f"own-check.sh not found at {OWN_CHECK_SH}"
        return status
    if shutil.which("dotnet") is None:
        status["reason"] = "dotnet SDK not on PATH (needed by the C# fact extractor)"
        return status

    # Persist the OwnIR facts too (--emit-facts): the XAML Phase-2 join consumes them
    # alongside xaml-facts.json. Harmless if unused.
    cmd = [str(OWN_CHECK_SH), "--format", "sarif", "--severity", severity,
           "--emit-facts", str(facts_path), "--", target]
    if root is not None:
        cmd[1:1] = ["--root", str(root)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=900)
    except subprocess.TimeoutExpired:
        status["reason"] = "own-check timed out (>900s) — partial/unavailable result"
        return status
    sarif_text = proc.stdout.strip()
    if not sarif_text.startswith("{"):
        status["reason"] = (f"own-check did not emit SARIF (exit {proc.returncode}): "
                            f"{proc.stderr.strip()[:200]}")
        return status

    sarif_path.write_text(sarif_text, encoding="utf-8")
    try:
        doc = json.loads(sarif_text)
        n = sum(len(r.get("results", [])) for r in doc.get("runs", []))
    except json.JSONDecodeError:
        n = 0
    status.update(available=True, sarif=str(sarif_path), findings=n)
    if facts_path.exists():
        status["facts"] = str(facts_path)
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run own-check (build-free) -> SARIF.")
    ap.add_argument("--target", required=True, help="path to the target source tree")
    ap.add_argument("--out", default="artifacts/own-audit", help="SARIF output directory")
    ap.add_argument("--severity", default="warning", choices=["error", "warning"])
    ap.add_argument("--root", default=None, help="Own.NET checkout (own-check --root)")
    args = ap.parse_args(argv)

    status = run_own_check(args.target, Path(args.out), args.severity,
                           Path(args.root) if args.root else None)
    print(json.dumps(status, indent=2))
    return 0 if status["available"] else 1


if __name__ == "__main__":
    sys.exit(main())
