#!/usr/bin/env python3
"""
Own.NET Audit — Security profile: minimal SARIF 2.1.0 writer (P-024 §v0.1).

The security adapters turn each external tool's *raw* output (testssl.sh JSON,
``dotnet list package`` JSON, ZAP JSON) into SARIF that flows into the SAME
aggregate pipeline as every other tool (``audit/aggregate/normalize.py`` →
``score.py`` → ``report.py``). This module is the one place that knows the SARIF
shape they must emit, so no adapter hand-rolls JSON.

It is deliberately tiny: the aggregate pipeline reads SARIF through
``scripts/oracle_compare.parse_sarif``, which only needs
``runs[].tool.driver.name`` and ``runs[].results[]`` with a ``ruleId``,
``message.text``, ``level`` and one ``physicalLocation``. We emit exactly that —
plus a ``rules`` catalogue in ``driver.rules`` so a viewer (and GitHub code
scanning) can render names/help without the adapters inventing extra structure.

No detection logic lives here (P-024 non-goals): adapters map a finding a tool
*already reported* into a record; they never decide whether something is a
vulnerability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# SARIF severity is carried on ``result.level`` (error/warning/note). Security
# tools speak CVSS-ish words (critical/high/medium/low/info); this is the single
# mapping every adapter shares, so "high" means the same thing across tools.
_LEVEL_BY_SEVERITY = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "moderate": "warning",
    "low": "note",
    "info": "note",
    "informational": "note",
    "none": "note",
    "unknown": "warning",
}


def level_for(severity: str) -> str:
    """Map a tool's severity word to a SARIF level. Unknown words are treated as
    ``warning`` (surfaced, never silently dropped to ``note``)."""
    return _LEVEL_BY_SEVERITY.get((severity or "").strip().lower(), "warning")


@dataclass
class Result:
    """One finding, tool-agnostic. ``uri``/``line`` locate it; for target-scoped
    findings with no file (a live TLS endpoint, a remote header) use a synthetic
    ``uri`` such as ``tls://host:443`` so the aggregate heatmap still groups it."""

    rule_id: str
    message: str
    severity: str = "medium"
    uri: str = ""
    line: int = 1
    help_uri: str = ""

    @property
    def level(self) -> str:
        return level_for(self.severity)


@dataclass
class SarifRun:
    """Accumulates results for one tool, then renders a SARIF 2.1.0 log. The
    ``tool_name`` is what appears as the SARIF driver and the cross-tool label in
    the aggregate report — keep it stable and matching the manifest's ``tool``."""

    tool_name: str
    information_uri: str = ""
    results: list[Result] = field(default_factory=list)

    def add(self, result: Result) -> None:
        self.results.append(result)

    def _rules_catalogue(self) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for r in self.results:
            if r.rule_id in seen:
                continue
            rule: dict[str, Any] = {"id": r.rule_id, "name": r.rule_id}
            if r.help_uri:
                rule["helpUri"] = r.help_uri
            seen[r.rule_id] = rule
        return list(seen.values())

    def to_dict(self) -> dict[str, Any]:
        driver: dict[str, Any] = {"name": self.tool_name, "rules": self._rules_catalogue()}
        if self.information_uri:
            driver["informationUri"] = self.information_uri
        return {
            "version": "2.1.0",
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{
                "tool": {"driver": driver},
                "results": [{
                    "ruleId": r.rule_id,
                    "level": r.level,
                    "message": {"text": r.message},
                    "locations": [{"physicalLocation": {
                        "artifactLocation": {"uri": r.uri or self.tool_name},
                        "region": {"startLine": max(1, r.line)},
                    }}],
                } for r in self.results],
            }],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _selftest() -> int:
    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:
        checks.append("" if ok else msg)

    check(level_for("CRITICAL") == "error", "critical must map to error")
    check(level_for("Medium") == "warning", "medium must map to warning")
    check(level_for("informational") == "note", "informational must map to note")
    check(level_for("weird-word") == "warning", "unknown severity must default to warning")

    run = SarifRun("testssl", information_uri="https://testssl.sh")
    run.add(Result("SSL-PROTO-TLS1_0", "TLS 1.0 offered", "high", "tls://host:443", 1,
                   "https://ciphersuite.info"))
    run.add(Result("SSL-PROTO-TLS1_0", "TLS 1.0 offered again", "high", "tls://host2:443"))
    doc = run.to_dict()

    check(doc["version"] == "2.1.0", "version must be 2.1.0")
    run0 = doc["runs"][0]
    check(run0["tool"]["driver"]["name"] == "testssl", "driver name lost")
    check(run0["tool"]["driver"]["informationUri"] == "https://testssl.sh",
          "informationUri lost")
    # two results, one deduped rule in the catalogue
    check(len(run0["results"]) == 2, "both results must be emitted")
    check(len(run0["tool"]["driver"]["rules"]) == 1, "duplicate ruleId must collapse in catalogue")
    check(run0["tool"]["driver"]["rules"][0].get("helpUri") == "https://ciphersuite.info",
          "helpUri must reach the rules catalogue")
    r0 = run0["results"][0]
    check(r0["level"] == "error", "high severity result must be level error")
    check(r0["message"]["text"] == "TLS 1.0 offered", "message text lost")
    loc = r0["locations"][0]["physicalLocation"]
    check(loc["artifactLocation"]["uri"] == "tls://host:443", "uri lost")
    check(loc["region"]["startLine"] == 1, "line clamp/emit wrong")

    # the whole doc must round-trip through the aggregate SARIF reader
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    try:
        from oracle_compare import parse_sarif
    except ImportError as exc:  # pragma: no cover
        check(False, f"cannot import parse_sarif to verify shape: {exc}")
    else:
        parsed = parse_sarif(run.to_json(), "testssl", [])
        check(len(parsed) == 2, f"parse_sarif must read both results, got {len(parsed)}")
        check(parsed[0].rule == "SSL-PROTO-TLS1_0", "parse_sarif lost the ruleId")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"SARIFLIB SELFTEST FAIL: {f}")
    print(f"sariflib selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("sariflib is a helper module; run with --selftest to verify.", file=sys.stderr)
    raise SystemExit(2)
