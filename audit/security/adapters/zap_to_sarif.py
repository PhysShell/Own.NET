#!/usr/bin/env python3
"""
Own.NET Audit — Security adapter: OWASP ZAP baseline JSON -> SARIF (P-024 §v0.1).

The ZAP *baseline* scan (spider + passive rules, no active attacks) is the safe
web pass; ZAP owns the rules, we consume its JSON report (``-J report.json``).
P-024 keeps this at *baseline* deliberately — no active/attacking scan.

ZAP groups ``alerts`` under each ``site``. Each alert has a ``pluginid`` (the rule),
an ``alert`` title, a ``riskcode`` (0 Informational … 3 High), a ``count`` of
instances, and ``instances`` with the URIs. We emit one SARIF result per alert,
anchored on the site (so the aggregate heatmap groups by host) with the first
instance URI and count in the message. ZAP's ``riskcode`` is passed through as
the severity; ``Informational`` alerts are counted but not emitted as findings.

Usage:
  zap_to_sarif.py --in zap.json --out zap.sarif
  zap_to_sarif.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sariflib import Result, SarifRun

TOOL = "zap-baseline"
INFO_URI = "https://www.zaproxy.org/docs/docker/baseline-scan/"

_SEVERITY_BY_RISKCODE = {"0": "info", "1": "low", "2": "medium", "3": "high"}


def convert(raw: str) -> tuple[SarifRun, dict[str, int]]:
    data = json.loads(raw) if raw.strip() else {}
    run = SarifRun(TOOL, information_uri=INFO_URI)
    informational = 0
    n_sites = 0
    sites = data.get("site") if isinstance(data, dict) else None
    if isinstance(sites, dict):  # ZAP emits a bare object for a single site
        sites = [sites]
    for site in sites or []:
        if not isinstance(site, dict):
            continue
        n_sites += 1
        site_name = str(site.get("@name") or site.get("@host") or "site")
        for alert in site.get("alerts") or []:
            if not isinstance(alert, dict):
                continue
            riskcode = str(alert.get("riskcode") or "").strip()
            severity = _SEVERITY_BY_RISKCODE.get(riskcode, "medium")
            if severity == "info":
                informational += 1
                continue
            _emit_alert(run, site_name, severity, alert)
    return run, {"sites": n_sites, "findings": len(run.results),
                 "informational": informational}


def _emit_alert(run: SarifRun, site_name: str, severity: str,
                alert: dict[str, Any]) -> None:
    rule_id = str(alert.get("pluginid") or alert.get("alertRef") or "ZAP-ALERT")
    title = str(alert.get("alert") or alert.get("name") or rule_id)
    count = str(alert.get("count") or "").strip()
    instances = alert.get("instances") or []
    first_uri = ""
    if instances and isinstance(instances[0], dict):
        first_uri = str(instances[0].get("uri") or "")
    cwe = str(alert.get("cweid") or "").strip()
    help_uri = (f"https://cwe.mitre.org/data/definitions/{cwe}.html"
                if cwe and cwe != "-1" else "")
    suffix = f" ({count} instance(s))" if count and count not in ("0", "1") else ""
    message = f"{title}{suffix}"
    run.add(Result(rule_id=rule_id, message=message, severity=severity,
                   uri=first_uri or site_name, help_uri=help_uri))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert OWASP ZAP baseline JSON to SARIF.")
    ap.add_argument("--in", dest="in_path", help="ZAP -J JSON report")
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

    fixture = json.dumps({"site": [{
        "@name": "https://app.example.com", "@host": "app.example.com", "@port": "443",
        "alerts": [
            {"pluginid": "10035", "alert": "Strict-Transport-Security Header Not Set",
             "riskcode": "1", "count": "3", "cweid": "319",
             "instances": [{"uri": "https://app.example.com/", "method": "GET"}]},
            {"pluginid": "40012", "alert": "Cross Site Scripting (Reflected)",
             "riskcode": "3", "count": "1", "cweid": "79",
             "instances": [{"uri": "https://app.example.com/search", "method": "GET"}]},
            {"pluginid": "10096", "alert": "Timestamp Disclosure",
             "riskcode": "0", "count": "5", "instances": []},
        ],
    }]})

    run, tally = convert(fixture)
    check(tally["sites"] == 1, f"one site expected, got {tally['sites']}")
    check(tally["findings"] == 2, f"Informational must be excluded, got {tally['findings']}")
    check(tally["informational"] == 1, f"Informational counted, got {tally['informational']}")

    doc = run.to_dict()["runs"][0]
    by_rule = {r["ruleId"]: r for r in doc["results"]}
    check("10035" in by_rule and "40012" in by_rule, "HSTS + XSS alerts must be emitted")
    check(by_rule["10035"]["level"] == "note", "riskcode 1 (Low) -> note")
    check(by_rule["40012"]["level"] == "error", "riskcode 3 (High) -> error")
    check("3 instance(s)" in by_rule["10035"]["message"]["text"],
          "instance count should be in the message when >1")
    check("instance" not in by_rule["40012"]["message"]["text"],
          "single instance should not add a count suffix")
    check(by_rule["10035"]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
          == "https://app.example.com/", "alert must anchor on the first instance uri")
    hsts_rule = next(r for r in doc["tool"]["driver"]["rules"] if r["id"] == "10035")
    check(hsts_rule.get("helpUri", "").endswith("319.html"), "cweid must become a CWE helpUri")

    # single-site-as-object and empty input must both be safe
    obj = json.dumps({"site": {"@name": "h", "alerts": [
        {"pluginid": "1", "alert": "x", "riskcode": "2", "instances": []}]}})
    _orun, otally = convert(obj)
    check(otally["findings"] == 1, "single site given as an object must be handled")
    erun, etally = convert("")
    check(etally["findings"] == 0 and not erun.results, "empty input must be safe")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"ZAP ADAPTER SELFTEST FAIL: {f}")
    print(f"zap_to_sarif selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
