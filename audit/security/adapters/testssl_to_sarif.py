#!/usr/bin/env python3
"""
Own.NET Audit — Security adapter: testssl.sh JSON -> SARIF (P-024 §v0.1).

testssl.sh owns TLS/SSL protocol, cipher and crypto-flaw testing; we do not
re-implement any of it (P-024 non-goals: "no own HTTP/TLS scanner"). This adapter
turns its ``--jsonfile-pretty`` output — a flat JSON array of findings, each with
``id``, ``ip``/``fqdn``, ``port``, ``severity``, ``finding`` and sometimes
``cve`` — into the shared SARIF shape.

testssl marks each line with its own severity. ``OK``/``INFO``/``DEBUG`` lines are
"this is fine" observations, not problems, so they are **not** emitted as
findings — but they are counted, so the adapter can report how much it read
versus surfaced (honest coverage, never a silent drop). Everything ``LOW`` and
above is passed through with the tool's own severity; the adapter makes no
vulnerability judgement of its own.

Usage:
  testssl_to_sarif.py --in testssl.json --out testssl.sarif [--target host:443]
  testssl_to_sarif.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sariflib import Result, SarifRun

TOOL = "testssl"
INFO_URI = "https://testssl.sh/"

# testssl severities that are observations, not findings. Kept out of results but
# counted in coverage. WARN means "could not test" — a scan gap, also not a finding.
_NON_FINDING = {"ok", "info", "debug", "warn"}


def _endpoint(rec: dict[str, Any], fallback: str) -> str:
    """A stable synthetic URI for a TLS endpoint so the aggregate heatmap groups
    findings by host:port (there is no source file for a live-endpoint finding)."""
    host = rec.get("fqdn") or rec.get("ip") or fallback or "endpoint"
    host = str(host).split("/", 1)[0]  # testssl writes "fqdn/ip"; keep the name
    port = str(rec.get("port") or "").strip()
    return f"tls://{host}:{port}" if port else f"tls://{host}"


def convert(raw: str, target: str = "") -> tuple[SarifRun, dict[str, int]]:
    """Parse testssl JSON text into a SarifRun plus a small coverage tally
    (``read`` / ``findings`` / ``observations``)."""
    data = json.loads(raw) if raw.strip() else []
    # testssl --jsonfile-pretty is a flat array; the plain --jsonfile can wrap it
    # under {"scanResult":[{"...":[...]}]} — accept either without guessing content.
    records = _flatten(data)

    run = SarifRun(TOOL, information_uri=INFO_URI)
    observations = 0
    for rec in records:
        if not isinstance(rec, dict):
            continue
        severity = str(rec.get("severity") or "").strip()
        rule_id = str(rec.get("id") or "TLS-FINDING").strip() or "TLS-FINDING"
        if severity.lower() in _NON_FINDING:
            observations += 1
            continue
        cve = str(rec.get("cve") or "").strip()
        help_uri = (f"https://nvd.nist.gov/vuln/detail/{cve.split()[0]}"
                    if cve else "")
        message = str(rec.get("finding") or rec.get("id") or "").strip()
        if cve:
            message = f"{message} ({cve})" if message else cve
        run.add(Result(rule_id=rule_id, message=message or rule_id,
                       severity=severity, uri=_endpoint(rec, target), help_uri=help_uri))
    return run, {"read": len(records), "findings": len(run.results),
                 "observations": observations}


def _flatten(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("scanResult"), list):
            out: list[Any] = []
            for host in data["scanResult"]:
                if isinstance(host, dict):
                    for v in host.values():
                        if isinstance(v, list):
                            out += v
            return out
        # a single finding object
        return [data]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert testssl.sh JSON to SARIF.")
    ap.add_argument("--in", dest="in_path", help="testssl --jsonfile[-pretty] output")
    ap.add_argument("--out", dest="out_path", help="SARIF output path")
    ap.add_argument("--target", default="", help="host:port fallback if records omit it")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.in_path or not args.out_path:
        ap.error("--in and --out are required (or use --selftest)")

    run, tally = convert(Path(args.in_path).read_text(encoding="utf-8"), args.target)
    Path(args.out_path).write_text(run.to_json(), encoding="utf-8")
    print(json.dumps(tally, indent=2))
    return 0


def _selftest() -> int:
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:
        checks.append("" if ok else msg)

    fixture = json.dumps([
        {"id": "TLS1", "fqdn": "www.example.com", "ip": "www.example.com/93.184.216.34",
         "port": "443", "severity": "MEDIUM", "finding": "TLS 1.0 offered"},
        {"id": "TLS1_1", "fqdn": "www.example.com", "port": "443",
         "severity": "LOW", "finding": "TLS 1.1 offered"},
        {"id": "heartbleed", "fqdn": "www.example.com", "port": "443",
         "severity": "CRITICAL", "finding": "vulnerable", "cve": "CVE-2014-0160"},
        {"id": "TLS1_2", "fqdn": "www.example.com", "port": "443",
         "severity": "OK", "finding": "TLS 1.2 offered"},
        {"id": "scanTime", "severity": "INFO", "finding": "42s"},
    ])

    run, tally = convert(fixture, "www.example.com:443")
    check(tally["read"] == 5, f"must read all 5 records, got {tally['read']}")
    check(tally["findings"] == 3, f"OK/INFO must not be findings, got {tally['findings']}")
    check(tally["observations"] == 2, f"OK+INFO must be counted, got {tally['observations']}")

    doc = run.to_dict()["runs"][0]
    ids = [r["ruleId"] for r in doc["results"]]
    check(ids == ["TLS1", "TLS1_1", "heartbleed"], f"wrong finding set: {ids}")
    levels = {r["ruleId"]: r["level"] for r in doc["results"]}
    check(levels["TLS1"] == "warning", "MEDIUM -> warning")
    check(levels["heartbleed"] == "error", "CRITICAL -> error")

    hb = next(r for r in doc["results"] if r["ruleId"] == "heartbleed")
    check("CVE-2014-0160" in hb["message"]["text"], "CVE must be woven into the message")
    hb_rule = next(r for r in doc["tool"]["driver"]["rules"] if r["id"] == "heartbleed")
    check(hb_rule.get("helpUri", "").endswith("CVE-2014-0160"),
          "CVE must become an NVD helpUri")

    uri = next(r for r in doc["results"] if r["ruleId"] == "TLS1"
               )["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    check(uri == "tls://www.example.com:443", f"endpoint uri wrong: {uri}")

    # empty input must not crash and must yield an empty (valid) run
    empty, etally = convert("", "")
    check(etally["read"] == 0 and not empty.results, "empty input must yield empty run")

    # the plain (nested) testssl schema must flatten too
    nested = json.dumps({"scanResult": [{"protocols": [
        {"id": "SSLv3", "fqdn": "h", "port": "443", "severity": "HIGH", "finding": "SSLv3 on"}]}]})
    nrun, ntally = convert(nested)
    check(ntally["findings"] == 1 and nrun.results[0].rule_id == "SSLv3",
          "nested scanResult schema must flatten to findings")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"TESTSSL ADAPTER SELFTEST FAIL: {f}")
    print(f"testssl_to_sarif selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
