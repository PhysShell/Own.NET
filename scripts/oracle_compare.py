#!/usr/bin/env python3
"""
Oracle comparison — cross-check Own.NET's leak findings against mature C#
analysers (Infer#, CodeQL) on the same codebase. See docs/notes/oracle.md.

We are *not* the first resource-leak detector: Infer# and CodeQL are strong at
it. That is exactly what makes them an **oracle** — run all three on one repo and
diff the leak-class findings:

  - agree        a (file, line) flagged by Own.NET AND an oracle  -> high confidence
  - own-only     flagged by us, by no oracle  -> candidate false positive, OR a
                 defect class the oracle's leak query can't express (double-dispose)
  - oracle-only  flagged by an oracle, not by us  -> our recall gap (what we missed)

Own.NET findings come from `own-check` (human format; same parser as the miner).
Infer# and CodeQL both emit SARIF, so a single parser reads both oracles.

dotnet-free: the three tools run upstream (the oracle workflow / CI); this only
reads their outputs and diffs them, so it runs anywhere. `--selftest` exercises
the diff on embedded fixtures.

Usage:
  oracle_compare.py --own own.txt --infersharp infer-out/report.sarif \\
                    --codeql codeql.sarif --strip "$PWD/target" \\
                    --target owner/repo --commit SHA [--json out.json]
  oracle_compare.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_titles() -> dict[str, str]:
    """OWN-code -> human title, for labelling Own.NET-only defect classes. Imported
    from the core when this runs inside the checkout; an empty map is a fine
    fallback when it is not importable."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from ownlang.diagnostics import TITLES
    except Exception:
        return {}
    return dict(TITLES)


TITLES = _load_titles()

# Which rule of each tool is the comparable "resource leak / not disposed" class.
# Only these are diffed three ways; everything else is reported as context.
OWN_LEAK = {"OWN001", "OWN014"}        # not released on a path / promoted to a
                                       # longer-lived region (subscription escape)
OWN_USE_AFTER = {"OWN002", "OWN009"}   # use after release (definite / maybe)
OWN_DOUBLE = {"OWN003"}                # double release
INFER_LEAK = {"PULSE_RESOURCE_LEAK", "DOTNET_RESOURCE_LEAK", "RESOURCE_LEAK",
              "MEMORY_LEAK", "PULSE_MEMORY_LEAK"}  # canonical ids; matched by substring
# CodeQL ids vary by suite/version; match the dispose/leak family by id too.
CODEQL_LEAK = {
    "cs/local-not-disposed",
    "cs/missing-dispose",
    "cs/dispose-not-called-on-throw",
    "cs/late-dispose",
}


@dataclass
class Finding:
    tool: str        # "own" | "infersharp" | "codeql" | ...
    path: str        # normalised, repo-relative where possible
    line: int
    rule: str        # OWN001 / DOTNET_RESOURCE_LEAK / cs/local-not-disposed / ...
    message: str
    cls: str         # "leak" | "use-after" | "double" | "other"
    fkey: str = field(init=False, default="")

    def __post_init__(self) -> None:
        # File identity for cross-tool matching is the basename, lower-cased:
        # robust to the path-prefix differences between tools (one reports
        # `src/Dapper/X.cs`, another `Dapper/X.cs`, a third an absolute path).
        self.fkey = self.path.lower().rsplit("/", 1)[-1]


def _own_class(code: str) -> str:
    if code in OWN_LEAK:
        return "leak"
    if code in OWN_USE_AFTER:
        return "use-after"
    if code in OWN_DOUBLE:
        return "double"
    return "other"


def _oracle_class(tool: str, rule: str) -> str:
    r = rule or ""
    if tool == "own":
        # own-check emitting SARIF (--format sarif): classify by OWN code, exactly
        # like the human-text path (build_own), so the two own input formats bucket
        # identically.
        return _own_class(r)
    if tool == "infersharp":
        # Infer's Pulse engine renamed the rule (RESOURCE_LEAK -> PULSE_RESOURCE_LEAK);
        # match the family by substring so version drift doesn't silence it.
        ru = r.upper()
        return "leak" if "RESOURCE_LEAK" in ru or "MEMORY_LEAK" in ru else "other"
    # codeql (and any other SARIF oracle): the dispose/leak family by id.
    rl = r.lower()
    if r in CODEQL_LEAK or "not-disposed" in rl or "dispose" in rl:
        return "leak"
    return "other"


def norm_path(raw: str, strips: list[str]) -> str:
    """Normalise a finding path to a repo-relative-ish form: forward slashes, no
    `file://` scheme, and the longest matching `--strip` prefix removed. Matching
    ultimately keys on the basename, so this is mostly for readable output."""
    p = raw.replace("\\", "/")
    for scheme in ("file://", "file:"):
        if p.startswith(scheme):
            p = p[len(scheme):]
    prefixes = sorted((s.replace("\\", "/").rstrip("/") for s in strips),
                      key=len, reverse=True)
    for pre in prefixes:
        if pre and p.startswith(pre):
            p = p[len(pre):]
            break
    if p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def build_own(text: str, strips: list[str]) -> tuple[list[Finding], int]:
    """Parse own-check output into Findings, in either format it emits:

    - **SARIF** (own-check `--format sarif`): read through the *same* `parse_sarif`
      as the Infer#/CodeQL oracles. No bespoke text parser, so no parser-drift —
      the class of bug that silently dropped 38 lines on the ScreenToGif run.
    - **human text** (legacy default): the miner's regex parser.

    The second tuple element is the unparsed-line count (always 0 for SARIF), so
    text-format drift is surfaced rather than silently dropped (which would inflate
    `oracle-only`)."""
    if text.lstrip().startswith("{"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict) and isinstance(doc.get("runs"), list):
            return parse_sarif(text, "own", strips), 0
        # {-leading but not a SARIF log (wrong file? malformed JSON): fall through
        # to the text parser, which surfaces it as unparsed drift rather than
        # silently reporting "clean" (0 findings, 0 unparsed).
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mine_report import parse  # local import: scripts/ is on the path now
    raw, unparsed = parse(text)
    findings = [
        Finding("own", norm_path(f["file"], strips), int(f["line"]),
                f["code"], f["message"], _own_class(f["code"]))
        for f in raw
    ]
    return findings, unparsed


def _first_location(res: dict[str, Any]) -> tuple[str, int] | None:
    """The primary (uri, startLine) of a SARIF result, or None if it has none."""
    for loc in res.get("locations", []):
        phys = loc.get("physicalLocation") or {}
        uri = (phys.get("artifactLocation") or {}).get("uri")
        if not uri:
            continue
        line = (phys.get("region") or {}).get("startLine")
        return uri, line if isinstance(line, int) else 0
    return None


def parse_sarif(text: str, tool: str, strips: list[str]) -> list[Finding]:
    """Parse a SARIF log (Infer# or CodeQL) into Findings."""
    data = json.loads(text)
    out: list[Finding] = []
    for run in data.get("runs", []):
        for res in run.get("results", []):
            rule = res.get("ruleId") or (res.get("rule") or {}).get("id") or ""
            msg = ((res.get("message") or {}).get("text") or "").strip()
            loc = _first_location(res)
            if loc is None:
                continue
            uri, line = loc
            out.append(Finding(tool, norm_path(uri, strips), line, rule, msg,
                               _oracle_class(tool, rule)))
    return out


def compare(own: list[Finding], oracles: list[Finding], tol: int) -> dict[str, Any]:
    """Bucket the leak-class findings three ways (agree / own-only / oracle-only),
    plus file overlap, Own.NET-only defect classes, and out-of-scope oracle hits."""
    own_leak = [f for f in own if f.cls == "leak"]
    ora_leak = [g for g in oracles if g.cls == "leak"]

    def near(a: Finding, b: Finding) -> bool:
        return a.fkey == b.fkey and abs(a.line - b.line) <= tol

    agree: list[tuple[Finding, list[Finding]]] = []
    own_only: list[tuple[Finding, list[Finding]]] = []
    for f in own_leak:
        hits = [g for g in ora_leak if near(f, g)]
        (agree if hits else own_only).append((f, hits))
    oracle_only = [g for g in ora_leak if not any(near(f, g) for f in own_leak)]

    own_files = {f.fkey for f in own_leak}
    ora_files = {g.fkey for g in ora_leak}
    return {
        "own_leak": own_leak,
        "oracle_leak": ora_leak,
        "agree": agree,
        "own_only": own_only,
        "oracle_only": oracle_only,
        "own_unique": [f for f in own if f.cls in ("use-after", "double")],
        "oracle_other": [g for g in oracles if g.cls == "other"],
        "files_both": own_files & ora_files,
        "files_own_only": own_files - ora_files,
        "files_oracle_only": ora_files - own_files,
    }


def _fmt_files(s: set[str], cap: int = 12) -> str:
    items = sorted(s)
    shown = ", ".join(f"`{x}`" for x in items[:cap])
    if len(items) > cap:
        shown += f", … (+{len(items) - cap})"
    return shown or "—"


def render_md(result: dict[str, Any], target: str, commit: str,
              oracles: list[str], tol: int, own_unparsed: int = 0,
              excluded_tests: int = 0, exclude_tests_mode: bool = False,
              max_list: int = 50) -> str:
    """The human-facing comparison report."""
    own_leak = result["own_leak"]
    ora_leak = result["oracle_leak"]
    agree = result["agree"]
    own_only = result["own_only"]
    oracle_only = result["oracle_only"]
    own_unique = result["own_unique"]
    oracle_other = result["oracle_other"]
    by_tool = Counter(g.tool for g in ora_leak)

    out: list[str] = [
        f"# Oracle comparison — `{target or '?'}`",
        "",
        f"- commit: `{commit or '?'}`",
        f"- generated: {datetime.now(UTC):%Y-%m-%d %H:%M UTC}",
        f"- tools: Own.NET + {', '.join(oracles) or '(no oracle SARIF supplied)'}",
        f"- file match: basename + line within ±{tol}",
    ]
    if own_unparsed:
        out.append(f"- **warning:** {own_unparsed} own-check line(s) did not parse "
                   "(format drift?) — Own.NET findings may be incomplete")
    if exclude_tests_mode:
        out.append(f"- scope: **product code only** — {excluded_tests} finding(s) under "
                   "test/benchmark/sample/example paths excluded (set `include_tests` to keep)")
    out += [
        "",
        "Leak / not-disposed class only — the question all three tools can answer. "
        "Own.NET's use-after-release and double-release are listed separately: the "
        "oracle leak queries have no equivalent.",
        "",
        "## Leak-class totals",
        "",
        "| tool | leak findings |",
        "|---|---:|",
        f"| Own.NET | {len(own_leak)} |",
    ]
    out += [f"| {t} | {by_tool.get(t, 0)} |" for t in oracles]

    out += ["", f"## Agree — {len(agree)} (Own.NET and an oracle; high confidence)", ""]
    out += ["_(none)_"] if not agree else [
        f"- `{f.path}:{f.line}` **[{f.rule}]** — also: "
        f"{', '.join(sorted({h.tool for h in hits}))}"
        for f, hits in agree[:max_list]
    ]

    out += ["", f"## Own.NET only — {len(own_only)} "
            "(candidate FP, or a catch the oracle misses)", ""]
    out += ["_(none)_"] if not own_only else [
        f"- `{f.path}:{f.line}` **[{f.rule}]** {f.message}" for f, _ in own_only[:max_list]
    ]

    out += ["", f"## Oracle only — {len(oracle_only)} (our recall gap, or an oracle FP)", ""]
    out += ["_(none)_"] if not oracle_only else [
        f"- `{g.path}:{g.line}` **[{g.tool}:{g.rule}]** {g.message}"
        for g in oracle_only[:max_list]
    ]

    fb, fo, fx = (result["files_both"], result["files_own_only"],
                  result["files_oracle_only"])
    out += [
        "", "## File overlap (leak class)", "",
        f"- both: {len(fb)} — {_fmt_files(fb)}",
        f"- Own.NET only: {len(fo)} — {_fmt_files(fo)}",
        f"- oracle only: {len(fx)} — {_fmt_files(fx)}",
    ]

    out += ["", f"## Own.NET-only defect classes — {len(own_unique)} "
            "(no oracle leak-query equivalent)", ""]
    if not own_unique:
        out += ["_(none)_"]
    else:
        out += [f"- **{rule}** x{n} — {TITLES.get(rule, '')}"
                for rule, n in Counter(f.rule for f in own_unique).most_common()]

    out += ["", f"## Oracle findings outside our leak scope — {len(oracle_other)} (context)", ""]
    if not oracle_other:
        out += ["_(none)_"]
    else:
        out += [f"- {k} x{n}" for k, n in
                Counter(f"{g.tool}:{g.rule}" for g in oracle_other).most_common(20)]

    out += [
        "", "## How to read this", "",
        "- **Agree** is the high-confidence set: two independent models flag the same spot.",
        "- **Own.NET only** is the triage queue — each is a candidate false positive to "
        "harden, *or* a real catch the oracle's leak query can't express (double-dispose, "
        "use-after-dispose, a non-allowlisted owning type).",
        "- **Oracle only** is our recall gap: reduce one to a minimal `.cs`, decide if it "
        "is in scope (interprocedural? a field? a loop/`try` shape we skip?), then model "
        "it or record it as a known limitation.",
        "- File match is by basename + a line window, so cross-tool path prefixes do not "
        "matter; same-named files in different directories can theoretically collide "
        "(rare — the line number disambiguates in practice).",
        "",
    ]
    return "\n".join(out)


def _fd(f: Finding) -> dict[str, Any]:
    return {"tool": f.tool, "path": f.path, "line": f.line,
            "rule": f.rule, "cls": f.cls, "message": f.message}


def to_json(result: dict[str, Any], target: str, commit: str) -> dict[str, Any]:
    return {
        "target": target,
        "commit": commit,
        "totals": {
            "own_leak": len(result["own_leak"]),
            "oracle_leak": len(result["oracle_leak"]),
            "agree": len(result["agree"]),
            "own_only": len(result["own_only"]),
            "oracle_only": len(result["oracle_only"]),
            "own_unique": len(result["own_unique"]),
            "oracle_other": len(result["oracle_other"]),
        },
        "agree": [{"finding": _fd(f), "oracles": [_fd(h) for h in hits]}
                  for f, hits in result["agree"]],
        "own_only": [_fd(f) for f, _ in result["own_only"]],
        "oracle_only": [_fd(g) for g in result["oracle_only"]],
        "own_unique": [_fd(f) for f in result["own_unique"]],
        "oracle_other": [_fd(g) for g in result["oracle_other"]],
        "files": {
            "both": sorted(result["files_both"]),
            "own_only": sorted(result["files_own_only"]),
            "oracle_only": sorted(result["files_oracle_only"]),
        },
    }


def _is_test_path(path: str) -> bool:
    """True if a finding path lives under a non-product tree — tests, benchmarks,
    samples, examples, or documentation snippets. `--exclude-tests` drops these so
    the three tools are diffed on product code only (Infer# builds just the product
    project, so without this own-check/CodeQL would also count leaks the others
    can't). `doc`/`snippet` trees carry intentionally-undisposed illustrative code
    (e.g. Polly's `src/Snippets/Docs/*`, where ~20 `HttpResponseMessage`/`HttpClient`
    examples are never disposed by design) — counting them as product leaks inflates
    the oracle-only recall gap with example code that was never meant to dispose."""
    for seg in path.lower().split("/"):
        if (seg in ("test", "tests", "doc", "docs")
                or seg.startswith(("benchmark", "sample", "example", "snippet"))):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Diff Own.NET leak findings against Infer#/CodeQL (oracle).")
    ap.add_argument("--own",
                    help="own-check output — human text or a --format sarif log")
    ap.add_argument("--infersharp", help="Infer# SARIF (e.g. infer-out/report.sarif)")
    ap.add_argument("--codeql", help="CodeQL SARIF")
    ap.add_argument("--sarif", action="append", default=[], metavar="TOOL=PATH",
                    help="extra SARIF oracle as tool=path (repeatable)")
    ap.add_argument("--strip", action="append", default=[], metavar="PREFIX",
                    help="path prefix to strip from finding paths (repeatable)")
    ap.add_argument("--target", default="", help="owner/repo (report header)")
    ap.add_argument("--commit", default="", help="commit SHA (report header)")
    ap.add_argument("--line-tol", type=int, default=3,
                    help="line window for a cross-tool match (default 3)")
    ap.add_argument("--exclude-tests", action="store_true",
                    help="drop findings under test/benchmark/sample/example paths, "
                         "comparing the product code only across all tools")
    ap.add_argument("--json", dest="json_out", default="",
                    help="also write the structured comparison as JSON")
    ap.add_argument("--selftest", action="store_true",
                    help="run built-in diff checks and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    own: list[Finding] = []
    own_unparsed = 0
    if args.own:
        own, own_unparsed = build_own(
            Path(args.own).read_text(encoding="utf-8"), args.strip)
        if own_unparsed:
            print(f"warning: {own_unparsed} own-check line(s) did not parse "
                  "(format drift?); Own.NET findings may be incomplete",
                  file=sys.stderr)
    sarif_inputs: list[tuple[str, str]] = []
    if args.infersharp:
        sarif_inputs.append(("infersharp", args.infersharp))
    if args.codeql:
        sarif_inputs.append(("codeql", args.codeql))
    for spec in args.sarif:
        tool, _, path = spec.partition("=")
        if not path:
            ap.error(f"--sarif expects tool=path, got {spec!r}")
        sarif_inputs.append((tool, path))

    oracles: list[Finding] = []
    present: list[str] = []
    for tool, path in sarif_inputs:
        present.append(tool)
        oracles += parse_sarif(Path(path).read_text(encoding="utf-8"), tool, args.strip)

    excluded = 0
    if args.exclude_tests:
        before = len(own) + len(oracles)
        own = [f for f in own if not _is_test_path(f.path)]
        oracles = [g for g in oracles if not _is_test_path(g.path)]
        excluded = before - len(own) - len(oracles)
        if excluded:
            print(f"--exclude-tests: dropped {excluded} finding(s) under "
                  "test/benchmark/sample/example paths", file=sys.stderr)

    result = compare(own, oracles, args.line_tol)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(to_json(result, args.target, args.commit), indent=2),
            encoding="utf-8")
    print(render_md(result, args.target, args.commit, present, args.line_tol,
                    own_unparsed, excluded, args.exclude_tests))
    return 0


def _selftest() -> int:
    own_txt = (
        "src/A.cs:12: error: [OWN001] IDisposable local 'a' is never disposed "
        "(leak) [resource: disposable]\n"
        "src/B.cs:5: error: [OWN001] IDisposable local 'b' is never disposed "
        "(leak) [resource: disposable]\n"
        "src/C.cs:9: error: [OWN003] 'c' is disposed twice [resource: disposable]\n"
        "src/D.cs:3: warning: [OWN050] cannot verify 'X.Y' — unresolved "
        "[resource: unresolved reference]\n"
    )
    infer = json.dumps({"runs": [{"results": [
        {"ruleId": "DOTNET_RESOURCE_LEAK", "message": {"text": "resource leak"},
         "locations": [{"physicalLocation": {
             "artifactLocation": {"uri": "src/A.cs"}, "region": {"startLine": 12}}}]},
        {"ruleId": "NULL_DEREFERENCE", "message": {"text": "npe"},
         "locations": [{"physicalLocation": {
             "artifactLocation": {"uri": "src/D.cs"}, "region": {"startLine": 3}}}]},
    ]}]})
    codeql = json.dumps({"runs": [{"results": [
        {"ruleId": "cs/local-not-disposed", "message": {"text": "not disposed"},
         "locations": [{"physicalLocation": {
             "artifactLocation": {"uri": "A.cs"}, "region": {"startLine": 13}}}]},
        {"ruleId": "cs/local-not-disposed", "message": {"text": "not disposed"},
         "locations": [{"physicalLocation": {
             "artifactLocation": {"uri": "E.cs"}, "region": {"startLine": 7}}}]},
    ]}]})

    own, own_unparsed = build_own(own_txt, [])
    oracles = parse_sarif(infer, "infersharp", []) + parse_sarif(codeql, "codeql", [])
    r = compare(own, oracles, tol=3)

    fails: list[str] = []
    if len(r["own_leak"]) != 2:
        fails.append(f"own_leak: expected 2, got {len(r['own_leak'])}")
    if len(r["agree"]) != 1:
        fails.append(f"agree: expected 1, got {len(r['agree'])}")
    elif {h.tool for h in r["agree"][0][1]} != {"infersharp", "codeql"}:
        fails.append(f"agree oracles wrong: {[h.tool for h in r['agree'][0][1]]}")
    if [f.fkey for f, _ in r["own_only"]] != ["b.cs"]:
        fails.append(f"own_only wrong: {[f.fkey for f, _ in r['own_only']]}")
    if [g.fkey for g in r["oracle_only"]] != ["e.cs"]:
        fails.append(f"oracle_only wrong: {[g.fkey for g in r['oracle_only']]}")
    if [f.rule for f in r["own_unique"]] != ["OWN003"]:
        fails.append(f"own_unique wrong: {[f.rule for f in r['own_unique']]}")
    if [g.rule for g in r["oracle_other"]] != ["NULL_DEREFERENCE"]:
        fails.append(f"oracle_other wrong: {[g.rule for g in r['oracle_other']]}")
    if r["files_both"] != {"a.cs"}:
        fails.append(f"files_both wrong: {r['files_both']}")
    md = render_md(r, "o/r", "abc123", ["infersharp", "codeql"], 3)
    if "Oracle comparison" not in md or "## Agree" not in md:
        fails.append("markdown render missing sections")
    js = to_json(r, "o/r", "abc123")
    if js["totals"]["agree"] != 1 or js["totals"]["oracle_only"] != 1:
        fails.append(f"json totals wrong: {js['totals']}")
    # parser-drift surfacing: a clean input drops nothing; an unrecognised line
    # is counted and rendered as a header warning, not silently swallowed.
    if own_unparsed != 0:
        fails.append(f"clean own input should have 0 unparsed, got {own_unparsed}")
    _, drift = build_own("a line that is not a finding\n", [])
    if drift != 1:
        fails.append(f"parser drift not surfaced: expected 1 unparsed, got {drift}")
    if "warning:" not in render_md(r, "o/r", "abc123", ["infersharp"], 3, drift):
        fails.append("unparsed warning not rendered in header")
    # multi-line findings (an inline lambda handler echoed across lines) parse as ONE
    # finding, with the kind recovered from the last line; a missing/optional
    # `[resource:]` tag is fine. Neither shape counts as drift — this is the own-check
    # format that silently broke the ScreenToGif oracle run (38 lines "unparsed").
    ml_txt = (
        "src/V.xaml.cs:50: warning: [OWN001] event 'x' subscribed (handler '(_, e) =>\n"
        "        {\n"
        "            Do();\n"
        "        }') but never unsubscribed [resource: subscription token]\n"
        "src/N.cs:7: error: [OWN001] field 'f' is never released\n"
    )
    ml, ml_drift = build_own(ml_txt, [])
    if len(ml) != 2:
        fails.append(f"multi-line/untagged: expected 2 findings, got {len(ml)}")
    if ml_drift != 0:
        fails.append(f"multi-line finding miscounted as drift: {ml_drift}")
    if not any(f.rule == "OWN001" and f.fkey == "v.xaml.cs" for f in ml):
        fails.append("multi-line finding lost its file/line/code")
    # Infer#'s Pulse engine emits PULSE_RESOURCE_LEAK (not RESOURCE_LEAK) — it must
    # still classify as a leak, not out-of-scope context.
    pulse_sarif = json.dumps({"runs": [{"results": [
        {"ruleId": "PULSE_RESOURCE_LEAK", "message": {"text": "leak"},
         "locations": [{"physicalLocation": {
             "artifactLocation": {"uri": "Dapper/SqlMapper.cs"},
             "region": {"startLine": 10}}}]}]}]})
    pulse = parse_sarif(pulse_sarif, "infersharp", [])
    if [g.cls for g in pulse] != ["leak"]:
        fails.append(f"PULSE_RESOURCE_LEAK not classed as leak: {[g.cls for g in pulse]}")
    # --exclude-tests predicate: matches non-product trees, not product code.
    # Doc/snippet trees (Polly's src/Snippets/Docs/*) are non-product illustrative
    # code — intentionally-undisposed examples that would otherwise inflate oracle-only.
    if not all(_is_test_path(p) for p in
               ("tests/Foo/Bar.cs", "benchmarks/X/Y.cs", "src/Test/Z.cs",
                "src/Snippets/Docs/Fallback.cs", "src/MyLib/docs/Example.cs")):
        fails.append("_is_test_path should match test/benchmark/doc/snippet trees")
    if any(_is_test_path(p) for p in ("Dapper/SqlMapper.cs", "src/Lib/A.cs")):
        fails.append("_is_test_path should not match product paths")
    # the scope note is gated on mode, not count: a product-only run that excluded
    # nothing must still say so (else it reads like a full-scope run).
    if "product code only" not in render_md(r, "o/r", "abc", ["codeql"], 3, 0, 0, True):
        fails.append("scope note must render when exclude-tests mode is on (even at 0)")

    # own-check can now emit SARIF (--format sarif); build_own reads it through the
    # SAME parser as the oracles — no bespoke text parser, no drift. The shape
    # mirrors ownlang.ownir.build_sarif. Codes must classify exactly like the text
    # path, SARIF never reports "unparsed", and it diffs against an oracle the same.
    own_sarif = json.dumps({"version": "2.1.0", "runs": [{"tool": {"driver":
        {"name": "Own.NET"}}, "results": [
        {"ruleId": "OWN001", "level": "error",
         "message": {"text": "leak [resource: disposable]"}, "locations":
         [{"physicalLocation": {"artifactLocation": {"uri": "src/A.cs"},
                                "region": {"startLine": 12}}}]},
        {"ruleId": "OWN003", "level": "error",
         "message": {"text": "double [resource: disposable]"}, "locations":
         [{"physicalLocation": {"artifactLocation": {"uri": "src/C.cs"},
                                "region": {"startLine": 9}}}]},
        {"ruleId": "OWN050", "level": "note", "message": {"text": "skipped"},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/D.cs"},
                                             "region": {"startLine": 3}}}]},
    ]}]})
    own_s, own_s_drift = build_own(own_sarif, [])
    if own_s_drift != 0:
        fails.append(f"own SARIF must never report unparsed, got {own_s_drift}")
    cls_by_rule = {f.rule: f.cls for f in own_s}
    if cls_by_rule != {"OWN001": "leak", "OWN003": "double", "OWN050": "other"}:
        fails.append(f"own SARIF classes wrong: {cls_by_rule}")
    r_s = compare(own_s, parse_sarif(infer, "infersharp", []), tol=3)
    if len(r_s["agree"]) != 1 or (r_s["agree"] and r_s["agree"][0][0].fkey != "a.cs"):
        fails.append(f"own SARIF agree wrong: {[f.fkey for f, _ in r_s['agree']]}")
    if [f.rule for f in r_s["own_unique"]] != ["OWN003"]:
        fails.append(f"own SARIF own_unique wrong: {[f.rule for f in r_s['own_unique']]}")
    # a {-leading input that is NOT a SARIF log (wrong file / malformed JSON) must
    # not be silently treated as "clean" — it falls through to the text parser and
    # surfaces as unparsed drift, not 0 findings / 0 unparsed.
    not_sarif, ns_drift = build_own('{"notruns": []}\n', [])
    if not_sarif or ns_drift < 1:
        fails.append(f"non-SARIF JSON masked as clean: {len(not_sarif)} findings, "
                     f"{ns_drift} unparsed")

    total = 24
    for f in fails:
        print(f"ORACLE SELFTEST FAIL: {f}")
    print(f"oracle_compare selftest: {total - len(fails)}/{total} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
