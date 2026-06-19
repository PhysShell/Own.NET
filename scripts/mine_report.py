#!/usr/bin/env python3
"""
Mining report aggregator — corpus mining (see docs/notes/mining.md).

Reads own-check findings — its human text **or** a `--format sarif` log — over a
real C# repo and turns them into a structured Markdown summary: counts by OWN
code, severity (errors = candidate leaks, warnings = advisory / OWN050
"unchecked"), resource kind, the noisiest files, and a triage list of the
error-severity findings to eyeball.

This is evaluation tooling for the analyser itself: a clean run is a precision
signal; a pile of OWN001s is either real bugs or a false-positive pattern to
harden; a high OWN050 count flags a coverage gap (unresolved external refs).

dotnet-free: the extractor (own-check) runs upstream; this only reads its output.

Usage:
  own-check.sh --format sarif -- <repo> | mine_report.py --repo owner/name --commit SHA
  mine_report.py findings.{txt,sarif} --repo owner/name --commit SHA [--json out.json]
  mine_report.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_titles() -> dict[str, str]:
    """The OWN-code -> human title map, for labelling the report. Imported from the
    core when this script runs inside the repo checkout (its parent dir is the repo
    root); an empty map is a fine fallback when it is not importable."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from ownlang.diagnostics import TITLES
    except Exception:
        return {}
    return dict(TITLES)


TITLES = _load_titles()

# own-check human header: "<file>:<line>: <sev>: [<CODE>] <msg>[ [resource: <kind>]]".
# The trailing `[resource: kind]` tag is OPTIONAL and, for a multi-line finding (an
# inline lambda handler echoed across lines), lands on the LAST line — so the header
# must match with or without it, and `msg` is non-greedy so a tag on the header line
# is split out rather than swallowed.
_LINE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+): (?P<sev>error|warning): "
    r"\[(?P<code>[A-Z]+\d+)\] (?P<msg>.*?)"
    r"(?: \[resource: (?P<kind>[^\]]*)\])?\s*$"
)
# the trailing `[resource: kind]` tag wherever it lands — recovers the kind from the
# last line of a multi-line finding.
_RESOURCE_TAIL = re.compile(r"\[resource: (?P<kind>[^\]]*)\]\s*$")
# the core's trailing chatter ("N findings.", "... ok — no ...") is not a finding.
_CHATTER = re.compile(r"\b\d+ (finding|error)s?\b|: ok | no ownership| no subscription")


def _net_open(s: str) -> int:
    """Net unclosed (){}[] in `s`. A multi-line finding's header (an inline lambda
    handler echoed across lines) is left unbalanced; a complete finding is balanced —
    so this distinguishes a continuation line from stray drift after a finished one."""
    return (s.count("(") - s.count(")")
            + s.count("{") - s.count("}")
            + s.count("[") - s.count("]"))


def _as_dict(x: Any) -> dict[str, Any]:
    """`x` if it is a dict, else an empty one — lets the SARIF field walk be written
    as plain `.get()` chains that degrade (rather than crash) on a malformed node,
    since the findings file is external input."""
    return x if isinstance(x, dict) else {}


def _sarif_finding(res: dict[str, Any]) -> dict[str, Any]:
    """Turn one SARIF result into the same finding dict the human-text parser yields
    (file / line / severity / code / message / kind), so the aggregation is
    format-agnostic. The SARIF level maps to the human severity (`error` -> error,
    `warning`/`note` -> warning), so an advisory OWN050 `note` and an injected-source
    `warning` both count as advisory exactly as in the text path; the resource kind
    comes from `properties.resourceKind`, and a trailing ` [resource: kind]` is split
    off the message for parity with the human format. Every access is shape-guarded
    so a garbage sub-node yields a default, not a crash."""
    locs = res.get("locations")
    first = locs[0] if isinstance(locs, list) and locs else {}
    phys = _as_dict(_as_dict(first).get("physicalLocation"))
    uri = _as_dict(phys.get("artifactLocation")).get("uri", "")
    line = _as_dict(phys.get("region")).get("startLine", 0)
    msg = _as_dict(res.get("message")).get("text")
    msg = msg if isinstance(msg, str) else ""
    kind = _as_dict(res.get("properties")).get("resourceKind")
    kind = kind if isinstance(kind, str) else ""
    tail = _RESOURCE_TAIL.search(msg)
    if tail:
        kind = kind or tail["kind"]
        msg = msg[:tail.start()].rstrip()
    code = res.get("ruleId")
    return {
        "file": uri if isinstance(uri, str) else "",
        "line": line if isinstance(line, int) else 0,
        "severity": "error" if res.get("level") == "error" else "warning",
        "code": code if isinstance(code, str) else "",
        "message": msg,
        "kind": kind,
    }


def _parse_sarif(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Every result across every run of a SARIF log, as finding dicts. Malformed
    nodes (a non-dict run/result, a non-list `results`) are skipped rather than
    crashed on — own-check emits well-formed SARIF, but the input file is external."""
    out: list[dict[str, Any]] = []
    runs = doc.get("runs")
    if not isinstance(runs, list):
        return out
    for run in runs:
        results = run.get("results") if isinstance(run, dict) else None
        if not isinstance(results, list):
            continue
        out.extend(_sarif_finding(res) for res in results if isinstance(res, dict))
    return out


def parse(text: str) -> tuple[list[dict[str, Any]], int]:
    """Parse own-check output into finding dicts; return (findings, unparsed).

    Accepts either format own-check emits. **SARIF** (`--format sarif`, a `{`-leading
    log with a `runs` array) is read structurally — no regex, `unparsed` is always 0.
    Otherwise the **human text**: a finding may span several lines — an inline lambda
    handler body is echoed across lines, with the trailing `[resource: kind]` tag
    (when present) on the last. A non-header line extends the current finding's message
    ONLY while that message's brackets are still unbalanced (i.e. we are inside the
    lambda body); once balanced, the finding is complete and a further non-matching
    line is stray drift, counted — not silently absorbed. Build chatter shouldn't reach
    here (own-check sends it to stderr); a stray line that does and isn't chatter is
    counted, not dropped."""
    if text.lstrip().startswith("{"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict) and isinstance(doc.get("runs"), list):
            return _parse_sarif(doc), 0
        # {-leading but not a SARIF log: fall through to the text parser, which
        # surfaces it as unparsed drift rather than silently reporting "clean".
    findings: list[dict[str, Any]] = []
    unparsed = 0
    cur: dict[str, Any] | None = None
    cur_open = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        m = _LINE.match(line)
        if m is None:
            if cur is not None and cur_open > 0:        # inside a multi-line body
                cur["message"] += "\n" + line
                cur_open += _net_open(line)
                tail = _RESOURCE_TAIL.search(line)
                if tail and not cur["kind"]:
                    cur["kind"] = tail["kind"]
            elif not _CHATTER.search(line):
                unparsed += 1
            continue
        cur = {
            "file": m["file"],
            "line": int(m["line"]),
            "severity": m["sev"],
            "code": m["code"],
            "message": m["msg"],
            "kind": m["kind"] or "",
        }
        cur_open = _net_open(m["msg"])
        findings.append(cur)
    return findings, unparsed


def aggregate(findings: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts the report is built from (also returned as JSON)."""
    errors = [f for f in findings if f["severity"] == "error"]
    advisories = [f for f in findings if f["severity"] != "error"]
    return {
        "total": len(findings),
        "errors": len(errors),
        "advisories": len(advisories),
        "by_code": dict(Counter(f["code"] for f in findings).most_common()),
        "by_kind": dict(Counter(f["kind"] for f in findings).most_common()),
        "by_file": dict(Counter(f["file"] for f in findings).most_common()),
        "files_with_findings": len({f["file"] for f in findings}),
    }


def render_md(findings: list[dict[str, Any]], unparsed: int, repo: str,
              commit: str, coverage: str = "", max_list: int = 60) -> str:
    """Render the Markdown report (the human-facing miner output)."""
    agg = aggregate(findings)
    errors = [f for f in findings if f["severity"] == "error"]
    own050 = agg["by_code"].get("OWN050", 0)
    out: list[str] = [
        f"# Mining report — `{repo or '?'}`",
        "",
        f"- commit: `{commit or '?'}`",
        f"- generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- findings: **{agg['total']}** "
        f"({agg['errors']} error / {agg['advisories']} advisory) "
        f"across {agg['files_with_findings']} file(s)"
        + (f"; {unparsed} unparsed line(s)" if unparsed else ""),
    ]
    if coverage:
        out.append(f"- {coverage}")
    out.append("")

    if agg["total"] == 0:
        tail = (f" The extractor reports — {coverage}." if coverage else
                " Pair it with the extractor's `--stats` (analysed vs "
                "honestly-skipped methods) to know how much was actually looked at.")
        out += ["**Clean** — no findings. A clean run on real code is a precision "
                "signal." + tail, ""]
        return "\n".join(out)

    out += ["## By code", "", "| code | n | what |", "|---|---:|---|"]
    for code, n in agg["by_code"].items():
        out.append(f"| {code} | {n} | {TITLES.get(code, '')} |")
    out += ["", "## By resource kind", "", "| kind | n |", "|---|---:|"]
    for kind, n in agg["by_kind"].items():
        out.append(f"| {kind} | {n} |")

    top_files = list(agg["by_file"].items())[:15]
    out += ["", "## Noisiest files", "", "| file | n |", "|---|---:|"]
    out += [f"| `{f}` | {n} |" for f, n in top_files]

    out += ["", f"## Candidate leaks — error severity ({len(errors)}) — review these",
            ""]
    shown = errors[:max_list]
    out += [f"- `{f['file']}:{f['line']}` **[{f['code']}]** {f['message']}"
            for f in shown]
    if len(errors) > len(shown):
        out.append(f"- … and {len(errors) - len(shown)} more (see findings.txt)")

    out += ["", "## Coverage signal", "",
            f"- **OWN050** (unchecked — declaring type is an unresolved external "
            f"reference): **{own050}**. These are honestly *not* analysed; resolving "
            f"more references (or a deeper compile) would let the checker reach them.",
            ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aggregate own-check findings into a "
                                             "Markdown mining report.")
    ap.add_argument("findings", nargs="?",
                    help="own-check human output file (default: stdin)")
    ap.add_argument("--repo", default="", help="owner/repo (for the report header)")
    ap.add_argument("--commit", default="", help="commit SHA (for the report header)")
    ap.add_argument("--json", dest="json_out", default="",
                    help="also write the raw aggregates as JSON to this path")
    ap.add_argument("--coverage", default="",
                    help="extractor --stats coverage line to surface in the report")
    ap.add_argument("--selftest", action="store_true",
                    help="run built-in parser/aggregator checks and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    text = (open(args.findings, encoding="utf-8").read() if args.findings
            else sys.stdin.read())
    findings, unparsed = parse(text)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"repo": args.repo, "commit": args.commit,
                       "unparsed": unparsed, "findings": findings,
                       **aggregate(findings)}, f, indent=2)
    print(render_md(findings, unparsed, args.repo, args.commit, args.coverage))
    return 0


def _selftest() -> int:
    sample = (
        "src/A.cs:12: error: [OWN001] IDisposable local 'uow' is never disposed "
        "(leak) [resource: disposable]\n"
        "src/A.cs:40: error: [OWN001] IDisposable local 'y' is never disposed "
        "(leak) [resource: disposable]\n"
        "src/A.cs:30: error: [OWN002] IDisposable local 'x' is used after it is "
        "disposed [resource: disposable]\n"
        "src/B.cs:5: warning: [OWN050] cannot verify 'Foo.Bar' — its declaring type "
        "is an unresolved reference (build the project or pass references); leakage "
        "analysis skipped [resource: unresolved reference]\n"
        "[dotnet build chatter that should be ignored if it leaks to stdout]\n"
        "4 findings.\n"
    )
    findings, unparsed = parse(sample)
    agg = aggregate(findings)
    fails: list[str] = []
    if len(findings) != 4:
        fails.append(f"expected 4 findings, got {len(findings)}")
    if unparsed != 1:
        fails.append(f"expected 1 unparsed line, got {unparsed}")
    if agg["by_code"] != {"OWN001": 2, "OWN002": 1, "OWN050": 1}:
        fails.append(f"by_code wrong: {agg['by_code']}")
    if (agg["errors"], agg["advisories"]) != (3, 1):
        fails.append(f"severity split wrong: {agg['errors']}/{agg['advisories']}")
    if agg["by_file"].get("src/A.cs") != 3:
        fails.append(f"by_file wrong: {agg['by_file']}")
    if "Mining report" not in render_md(findings, unparsed, "o/r", "abc123"):
        fails.append("markdown render missing header")
    # a clean run renders without crashing and says so.
    if "Clean" not in render_md([], 0, "o/r", "abc123"):
        fails.append("clean render missing 'Clean'")
    # the --stats coverage line is surfaced when supplied (header + clean note).
    if "42 methods" not in render_md([], 0, "o/r", "abc123", "coverage: 1/42 methods"):
        fails.append("coverage line not rendered")

    # own-check can also feed SARIF (--format sarif); parse() sniffs it and yields the
    # SAME finding dicts as the human path, so the aggregation is identical. The shape
    # mirrors ownlang.ownir.build_sarif (note level = advisory OWN050).
    def _res(code: str, level: str, uri: str, line: int, kind: str) -> dict[str, Any]:
        return {"ruleId": code, "level": level,
                "message": {"text": f"a leak [resource: {kind}]"},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": uri}, "region": {"startLine": line}}}],
                "properties": {"resourceKind": kind}}
    sarif_text = json.dumps({"version": "2.1.0", "runs": [{"tool": {"driver":
        {"name": "Own.NET"}}, "results": [
        _res("OWN001", "error", "src/A.cs", 12, "disposable"),
        _res("OWN001", "error", "src/A.cs", 40, "disposable"),
        _res("OWN002", "error", "src/A.cs", 30, "disposable"),
        _res("OWN050", "note", "src/B.cs", 5, "unresolved reference"),
    ]}]})
    sf, sf_unparsed = parse(sarif_text)
    sagg = aggregate(sf)
    if sf_unparsed != 0:
        fails.append(f"SARIF input must not report unparsed, got {sf_unparsed}")
    if sagg["by_code"] != {"OWN001": 2, "OWN002": 1, "OWN050": 1}:
        fails.append(f"SARIF by_code wrong: {sagg['by_code']}")
    if (sagg["errors"], sagg["advisories"]) != (3, 1):
        fails.append(f"SARIF severity split wrong: {sagg['errors']}/{sagg['advisories']}")
    if sagg["by_kind"].get("disposable") != 3 or sagg["by_file"].get("src/A.cs") != 3:
        fails.append(f"SARIF by_kind/by_file wrong: {sagg['by_kind']} {sagg['by_file']}")
    a0 = next(f for f in sf if f["code"] == "OWN050")
    if a0["kind"] != "unresolved reference" or "[resource:" in a0["message"]:
        fails.append(f"SARIF message/kind split wrong: {a0}")
    # a {-leading input that is NOT a SARIF log falls through to the text parser and
    # surfaces as unparsed drift, not a silent clean read.
    _, ns_drift = parse('{"notruns": 1}\n')
    if ns_drift != 1:
        fails.append(f"non-SARIF JSON should surface as drift, got {ns_drift} unparsed")
    # malformed SARIF nodes (non-dict run/result, non-list results, garbage
    # sub-fields) are skipped, not crashed on — valid results still come through.
    malformed = json.dumps({"runs": [
        1,                  # non-dict run -> skipped
        {"results": 7},     # non-list results -> skipped
        {"results": [
            2,              # non-dict result -> skipped
            {"ruleId": "OWN001", "level": "error", "message": "m",
             "locations": "nope", "properties": 5},  # garbage sub-fields -> defaults
        ]},
    ]})
    mf, mf_drift = parse(malformed)
    if mf_drift != 0 or [f["code"] for f in mf] != ["OWN001"]:
        fails.append(f"malformed SARIF not handled gracefully: {mf_drift} {mf}")

    for f in fails:
        print(f"MINE SELFTEST FAIL: {f}")
    print(f"mine_report selftest: {15 - len(fails)}/15 checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
