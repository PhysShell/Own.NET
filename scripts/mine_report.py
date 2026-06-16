#!/usr/bin/env python3
"""
Mining report aggregator — corpus mining (see docs/notes/mining.md).

Reads the human-format findings that `own-check` prints over a real C# repo and
turns them into a structured Markdown summary: counts by OWN code, severity
(errors = candidate leaks, warnings = advisory / OWN050 "unchecked"), resource
kind, the noisiest files, and a triage list of the error-severity findings to
eyeball.

This is evaluation tooling for the analyser itself: a clean run is a precision
signal; a pile of OWN001s is either real bugs or a false-positive pattern to
harden; a high OWN050 count flags a coverage gap (unresolved external refs).

dotnet-free: the extractor (own-check) runs upstream; this only reads its text.

Usage:
  own-check.sh --format human -- <repo> | mine_report.py --repo owner/name --commit SHA
  mine_report.py findings.txt --repo owner/name --commit SHA [--json out.json]
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

# own-check human line: "<file>:<line>: <sev>: [<CODE>] <msg> [resource: <kind>]"
_LINE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+): (?P<sev>error|warning): "
    r"\[(?P<code>[A-Z]+\d+)\] (?P<msg>.*) \[resource: (?P<kind>[^\]]*)\]\s*$"
)
# the core's trailing chatter ("N findings.", "... ok — no ...") is not a finding.
_CHATTER = re.compile(r"\b\d+ (finding|error)s?\b|: ok | no ownership| no subscription")


def parse(text: str) -> tuple[list[dict[str, Any]], int]:
    """Parse own-check human output into finding dicts; return (findings, unparsed).
    Build chatter shouldn't reach here (own-check sends it to stderr), but if a
    stray line does, count it rather than silently dropping it."""
    findings: list[dict[str, Any]] = []
    unparsed = 0
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        m = _LINE.match(line)
        if m is None:
            if not _CHATTER.search(line):
                unparsed += 1
            continue
        findings.append({
            "file": m["file"],
            "line": int(m["line"]),
            "severity": m["sev"],
            "code": m["code"],
            "message": m["msg"],
            "kind": m["kind"],
        })
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
              commit: str, max_list: int = 60) -> str:
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
        "",
    ]

    if agg["total"] == 0:
        out += ["**Clean** — no findings. (A clean run on real code is a precision "
                "signal; pair it with the extractor's `--stats` coverage once that "
                "lands to know how much was actually analysed vs honestly skipped.)",
                ""]
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
    print(render_md(findings, unparsed, args.repo, args.commit))
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
    for f in fails:
        print(f"MINE SELFTEST FAIL: {f}")
    print(f"mine_report selftest: {7 - len(fails)}/7 checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
