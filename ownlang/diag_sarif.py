"""Flow diagnostics (``analysis.Diagnostic``) -> SARIF 2.1.0.

The C# extractor path already emits SARIF via ``ownir.build_sarif`` over
``ownir.Finding``. The ``.own`` flow-diagnostic path (parser -> analysis) had no
SARIF surface, so the structured ``Diagnostic.evidence`` slice (a stack buffer's
acquire->escape at OWN015/OWN016, move->use at OWN005, a leak's acquire site at
OWN001) reached only the human ``check`` render -- never GitHub code scanning.

This is the missing consumer. It maps each ``Diagnostic`` to a SARIF ``result``
and projects its evidence through the SAME ``ownlang.evidence`` builders the OwnIR
path uses (``relatedLocations`` for the unordered anchors, ``codeFlows`` for the
ordered slice), so both paths speak one SARIF vocabulary. The log shape mirrors
``ownir.build_sarif``: one ``run`` whose ``tool.driver`` is Owen with a
``rules`` catalogue of the OWN codes present, and one ``result`` per diagnostic.
"""

from __future__ import annotations

from typing import Any

from .diagnostics import TITLES, Diagnostic, Evidence, Severity
from .evidence import code_flow, related_locations

# Mirrors the constants in ``ownir.build_sarif`` -- both paths emit the same SARIF
# 2.1.0 shape from one tool. Kept as literals here (rather than imported from
# ``ownir``) so a ``check`` never has to load the heavier OwnIR module.
_SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
    "Schemata/sarif-schema-2.1.0.json"
)
_SARIF_INFO_URI = "https://github.com/PhysShell/Own.NET"


def _steps(evidence: tuple[Evidence, ...], filename: str) -> list[tuple[str, int, str]]:
    """Resolve each evidence step to a concrete ``(file, line, label)`` the SARIF
    builders can point at. ``Evidence.file is None`` means "same file as the
    diagnostic's anchor", so it resolves to ``filename`` -- an empty URI would make
    the whole log unprocessable for GitHub code scanning."""
    return [(e.file or filename, e.line, e.label) for e in evidence]


def _result(d: Diagnostic, filename: str, severity: str) -> dict[str, Any]:
    """One SARIF ``result`` for a diagnostic: the OWN code is the ``ruleId``, the
    ``.own`` location is a ``physicalLocation``, and the evidence slice rides along
    as ``relatedLocations`` + ``codeFlows``. ``severity`` is a presentation choice
    (it only sets the result ``level``); a diagnostic that is intrinsically a
    warning stays a warning regardless."""
    phys: dict[str, Any] = {"artifactLocation": {"uri": filename.replace("\\", "/")}}
    if d.line >= 1:  # SARIF region.startLine is 1-based; omit for a file-level finding
        phys["region"] = {"startLine": d.line}
    level = ("warning" if severity == "warning" or d.severity is Severity.WARNING
             else "error")
    kind = f" [resource: {d.resource_kind}]" if d.resource_kind else ""
    result: dict[str, Any] = {
        "ruleId": d.code,
        "level": level,
        "message": {"text": f"{d.message}{kind}"},
        "locations": [{"physicalLocation": phys}],
    }
    steps = _steps(d.evidence, filename)
    related = related_locations(steps)
    if related:
        result["relatedLocations"] = related
    flows = code_flow(steps)
    if flows:
        result["codeFlows"] = flows
    return result


def build_sarif(diags: list[Diagnostic], filename: str,
                severity: str = "error") -> dict[str, Any]:
    """Render flow diagnostics as a single SARIF 2.1.0 log: one ``run`` whose
    ``tool.driver`` is Owen (with a ``rules`` catalogue of the OWN codes present
    and their titles) and whose ``results`` carry each diagnostic's code, location,
    message and evidence slice. ``severity`` only sets each result's ``level``."""
    codes = sorted({d.code for d in diags})
    rules = [
        {"id": code, "shortDescription": {"text": TITLES.get(code, code)}}
        for code in codes
    ]
    return {
        "$schema": _SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Owen",
                        "informationUri": _SARIF_INFO_URI,
                        "rules": rules,
                    },
                },
                "results": [_result(d, filename, severity) for d in diags],
            },
        ],
    }
