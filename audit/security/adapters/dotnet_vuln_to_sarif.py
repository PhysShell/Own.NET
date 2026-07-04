#!/usr/bin/env python3
"""
Own.NET Audit — Security adapter: ``dotnet list package --vulnerable`` -> SARIF (P-024 §v0.1).

The .NET SDK's own package auditing is the authority on NuGet advisories; we
consume it, we do not maintain an advisory DB (P-024 non-goals: "no own CVE-check
corpus"). This adapter reads the JSON produced by

    dotnet list package --vulnerable --include-transitive --format json

``--include-transitive`` is mandatory here (Codex review on #169): without it the
SDK only reports vulnerable *direct* dependencies, so a vulnerable package pulled
in transitively would be silently absent and could even cost cross-tool agreement
against Trivy. The adapter marks transitive findings in the message so the report
distinguishes "you referenced this" from "something you reference did".

Each vulnerability the SDK reports carries a ``severity`` and an ``advisoryurl``;
we key the rule on the advisory id (the URL's last segment, e.g. ``GHSA-xxxx``)
so the same advisory clusters across projects, and pass the SDK's severity
through unchanged.

Usage:
  dotnet_vuln_to_sarif.py --in vulnerable.json --out dotnet-vuln.sarif
  dotnet_vuln_to_sarif.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sariflib import Result, SarifRun

TOOL = "dotnet-vuln"
INFO_URI = ("https://learn.microsoft.com/nuget/concepts/"
            "auditing-packages#dotnet-list-package---vulnerable")


def _advisory_id(url: str) -> str:
    seg = (url or "").rstrip("/").rsplit("/", 1)[-1].strip()
    return seg or "NUGET-VULN"


def convert(raw: str) -> tuple[SarifRun, dict[str, int]]:
    data = json.loads(raw) if raw.strip() else {}
    run = SarifRun(TOOL, information_uri=INFO_URI)
    projects = data.get("projects") if isinstance(data, dict) else None
    n_projects = 0
    for proj in projects or []:
        if not isinstance(proj, dict):
            continue
        n_projects += 1
        path = str(proj.get("path") or "unknown.csproj")
        for fw in proj.get("frameworks") or []:
            if not isinstance(fw, dict):
                continue
            framework = str(fw.get("framework") or "")
            for kind, key in (("direct", "topLevelPackages"),
                              ("transitive", "transitivePackages")):
                for pkg in fw.get(key) or []:
                    if not isinstance(pkg, dict):
                        continue
                    _emit_package(run, path, framework, kind, pkg)
    return run, {"projects": n_projects, "findings": len(run.results)}


def _emit_package(run: SarifRun, path: str, framework: str, kind: str,
                  pkg: dict[str, Any]) -> None:
    pkg_id = str(pkg.get("id") or "?")
    version = str(pkg.get("resolvedVersion") or pkg.get("requestedVersion") or "?")
    for vuln in pkg.get("vulnerabilities") or []:
        if not isinstance(vuln, dict):
            continue
        severity = str(vuln.get("severity") or "unknown")
        url = str(vuln.get("advisoryurl") or vuln.get("advisoryUrl") or "")
        origin = "transitive dependency" if kind == "transitive" else "direct dependency"
        fw_note = f", {framework}" if framework else ""
        message = (f"{pkg_id} {version} ({origin}{fw_note}) has a {severity} "
                   f"severity advisory")
        run.add(Result(rule_id=_advisory_id(url), message=message,
                       severity=severity, uri=path, help_uri=url))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Convert 'dotnet list package --vulnerable --format json' to SARIF.")
    ap.add_argument("--in", dest="in_path", help="dotnet list package JSON output")
    ap.add_argument("--out", dest="out_path", help="SARIF output path")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.in_path or not args.out_path:
        ap.error("--in and --out are required (or use --selftest)")

    run, tally = convert(Path(args.in_path).read_text(encoding="utf-8"))
    Path(args.out_path).write_text(run.to_json(), encoding="utf-8")
    print(json.dumps(tally, indent=2))
    return 0


def _selftest() -> int:
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:
        checks.append("" if ok else msg)

    fixture = json.dumps({
        "version": 1,
        "parameters": "--vulnerable --include-transitive",
        "projects": [{
            "path": "/repo/src/App/App.csproj",
            "frameworks": [{
                "framework": "net8.0",
                "topLevelPackages": [{
                    "id": "Newtonsoft.Json", "requestedVersion": "9.0.1",
                    "resolvedVersion": "9.0.1",
                    "vulnerabilities": [{
                        "severity": "High",
                        "advisoryurl": "https://github.com/advisories/GHSA-5crp-9r3c-p9vr"}]}],
                "transitivePackages": [{
                    "id": "System.Net.Http", "resolvedVersion": "4.3.0",
                    "vulnerabilities": [{
                        "severity": "Critical",
                        "advisoryurl": "https://github.com/advisories/GHSA-7jgj-8wvc-jh57"}]}],
            }],
        }],
    })

    run, tally = convert(fixture)
    check(tally["projects"] == 1, f"one project expected, got {tally['projects']}")
    check(tally["findings"] == 2, f"direct + transitive = 2 findings, got {tally['findings']}")

    doc = run.to_dict()["runs"][0]
    by_rule = {r["ruleId"]: r for r in doc["results"]}
    check("GHSA-5crp-9r3c-p9vr" in by_rule, "direct advisory id must be the rule id")
    check("GHSA-7jgj-8wvc-jh57" in by_rule, "transitive advisory id must be the rule id")

    trans = by_rule["GHSA-7jgj-8wvc-jh57"]
    check(trans["level"] == "error", "Critical -> error")
    check("transitive dependency" in trans["message"]["text"],
          "transitive origin must be labelled in the message (the whole point of #169)")
    check("net8.0" in trans["message"]["text"], "framework should be noted")
    direct = by_rule["GHSA-5crp-9r3c-p9vr"]
    check("direct dependency" in direct["message"]["text"], "direct origin must be labelled")
    check(direct["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
          == "/repo/src/App/App.csproj", "finding must anchor on the csproj")

    # a clean project (no vulnerabilities key) must yield zero findings, not crash
    clean = json.dumps({"projects": [{"path": "Clean.csproj",
                                      "frameworks": [{"framework": "net8.0"}]}]})
    _crun, ctally = convert(clean)
    check(ctally["projects"] == 1 and ctally["findings"] == 0,
          "clean project must be read but yield no findings")

    # empty / missing input must be safe
    erun, etally = convert("")
    check(etally["findings"] == 0 and not erun.results, "empty input must be safe")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"DOTNET-VULN ADAPTER SELFTEST FAIL: {f}")
    print(f"dotnet_vuln_to_sarif selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
