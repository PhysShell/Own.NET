#!/usr/bin/env python3
"""
Own.NET Audit — static layer orchestrator (Plan.md §3.3/§3.5).

Runs the build-free tier of analyzers over a target, collects each tool's SARIF,
then normalizes → scores → renders the health report. Build-required runners
(Roslyn packs, Infer#) run on the local Windows machine and drop their SARIF into
the same artifacts directory; this orchestrator picks up whatever is present, so a
partial run still produces a (partial, honestly-labelled) report.

Every runner is best-effort: an unavailable tool (no dotnet, no codeql, a build
that did not compile) is recorded as a tier gap in the coverage section, never a
crash — the continue-on-error discipline of Plan.md §3.2.

Usage:
  run_static.py --target /path/to/legacy --profile desktop-wpf --out artifacts/own-audit
  run_static.py --selftest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_AUDIT = _HERE.parent
sys.path.insert(0, str(_AUDIT / "aggregate"))
sys.path.insert(0, str(_HERE / "tools"))

from normalize import coverage, load_taxonomy, normalize_results  # noqa: E402
from owncheck import run_own_check  # noqa: E402
from report import render_html, render_json, render_markdown, render_sarif  # noqa: E402
from score import score  # noqa: E402
from xaml_check import run_xaml_check  # noqa: E402
from xaml_join import run_join  # noqa: E402

try:
    from oracle_compare import parse_sarif
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(_AUDIT.parent / "scripts"))
    from oracle_compare import parse_sarif

DEFAULT_TAXONOMY = _AUDIT / "static" / "taxonomy" / "categories.yml"
DEFAULT_PROFILE_DIR = _AUDIT / "config" / "profiles"


def load_profile(name_or_path: str) -> dict[str, Any]:
    import yaml

    p = Path(name_or_path)
    if not p.exists():
        p = DEFAULT_PROFILE_DIR / f"{name_or_path}.yml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def aggregate(sarif_inputs: list[tuple[str, str]], out_dir: Path, meta: dict[str, Any],
              taxonomy: Path = DEFAULT_TAXONOMY, line_tol: int = 3) -> dict[str, Any]:
    """Normalize → score → render the SARIFs in ``sarif_inputs``, writing all four
    report artifacts to ``out_dir``: ``report.md``, ``report.json``,
    ``report.sarif`` (merged SARIF for code scanning) and ``report.html``. Returns
    a dict with ``totals``, ``coverage`` and the four ``report_{md,json,sarif,html}``
    paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tax = load_taxonomy(taxonomy)
    raw: list[Any] = []
    for tool, path in sarif_inputs:
        raw += parse_sarif(Path(path).read_text(encoding="utf-8"), tool, meta.get("strip", []))
    findings = normalize_results(raw, tax)
    cov = coverage(findings)
    scored = score(findings, tax, line_tol)
    meta = {**meta, "line_tol": line_tol}

    (out_dir / "report.md").write_text(render_markdown(meta, cov, scored), encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(render_json(meta, cov, scored), indent=2), encoding="utf-8")
    (out_dir / "report.sarif").write_text(
        json.dumps(render_sarif(meta, cov, scored), indent=2), encoding="utf-8")
    (out_dir / "report.html").write_text(render_html(meta, cov, scored), encoding="utf-8")
    return {"totals": scored["totals"], "coverage": cov,
            "report_md": str(out_dir / "report.md"),
            "report_json": str(out_dir / "report.json"),
            "report_sarif": str(out_dir / "report.sarif"),
            "report_html": str(out_dir / "report.html")}


def _run_codeql(target: str, out_dir: Path) -> dict[str, Any]:
    """Best-effort build-free CodeQL via the runner shell. Exit 3 = NO-TOOL."""
    runner = _HERE / "tools" / "codeql.sh"
    status: dict[str, Any] = {"tool": "codeql", "tier": "build-free",
                              "available": False, "sarif": None, "reason": ""}
    if not runner.exists():
        status["reason"] = "codeql.sh runner missing"
        return status
    proc = subprocess.run([str(runner), "--target", target, "--out", str(out_dir)],
                          capture_output=True, text=True, check=False)
    sarif = out_dir / "codeql.sarif"
    if proc.returncode == 0 and sarif.exists():
        status.update(available=True, sarif=str(sarif))
    else:
        status["reason"] = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else \
            f"codeql runner exit {proc.returncode}"
    return status


def run(target: str, profile: dict[str, Any], out_dir: Path, target_name: str = "",
        commit: str = "", line_tol: int = 3) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    severity = profile.get("severity_floor", "warning")
    build_free = (profile.get("tiers") or {}).get("build_free") or []

    tiers: list[dict[str, Any]] = []
    sarif_inputs: list[tuple[str, str]] = []
    ownir_facts: str | None = None   # OwnIR facts produced by own-check THIS run
    xaml_facts: str | None = None    # xaml-facts.json produced by the xaml pass THIS run
    if "own-check" in build_free:
        st = run_own_check(target, out_dir, severity)
        tiers.append(st)
        if st["available"] and st["sarif"]:
            sarif_inputs.append(("own-check", st["sarif"]))
        ownir_facts = st.get("facts")
    if "codeql" in build_free:
        st = _run_codeql(target, out_dir)
        tiers.append(st)
        if st["available"] and st["sarif"]:
            sarif_inputs.append(("codeql", st["sarif"]))
    if "xaml" in build_free:
        # The markup-only XAML pass (docs/notes/xaml-analyzer-design.md, phase 1):
        # pure stdlib XML, so it has no toolchain prerequisite and always runs here,
        # emitting the same SARIF record into the same aggregate pipeline.
        st = run_xaml_check(target, out_dir)
        tiers.append(st)
        if st["available"] and st["sarif"]:
            sarif_inputs.append(("xaml", st["sarif"]))
        xaml_facts = st.get("facts")

    # XAML Phase-2 join (docs/notes/xaml-analyzer-design.md → "Phase 2 mechanics"):
    # link xaml-facts.json to the OwnIR facts own-check emitted (--emit-facts) and
    # fold the XAML2xx link findings into the same pipeline. Gate on the fact files
    # THIS run produced (the statuses' `facts` paths), never on bare existence — a
    # re-run into an existing --out, or a profile without xaml/own-check (or no SDK),
    # must not join a previous target's stale facts.
    if (xaml_facts and Path(xaml_facts).exists()
            and ownir_facts and Path(ownir_facts).exists()):
        st = run_join(Path(xaml_facts), Path(ownir_facts), out_dir)
        tiers.append(st)
        if st["available"] and st["sarif"]:
            sarif_inputs.append(("xaml-join", st["sarif"]))

    # Pick up any build-required SARIFs already dropped here by the Windows runners.
    # Roslyn writes ONE SARIF PER PROJECT under roslyn/ (see the injected props's
    # $(MSBuildProjectName).sarif), so glob the directory; Infer# writes a single file.
    roslyn_dir = out_dir / "roslyn"
    roslyn_sarifs = sorted(roslyn_dir.glob("*.sarif")) if roslyn_dir.is_dir() else []
    for p in roslyn_sarifs:
        sarif_inputs.append(("roslyn-pack", str(p)))
    if roslyn_sarifs:
        tiers.append({"tool": "roslyn-pack", "tier": "build-required", "available": True,
                      "sarif": f"{len(roslyn_sarifs)} project SARIF(s) under roslyn/",
                      "reason": ""})
    infer = out_dir / "infersharp.sarif"
    if infer.exists():
        sarif_inputs.append(("infersharp", str(infer)))
        tiers.append({"tool": "infersharp", "tier": "build-required", "available": True,
                      "sarif": str(infer), "reason": ""})

    # Runtime tier (Plan.md §4): SARIFs produced by audit/runtime/ingest.py from each
    # runtime tool's JSON are folded in here, so a runtime-confirmed finding clusters
    # with its static OWN014/OWN001 -> high confidence (§3.5) through the orchestrator,
    # not only the lower-level aggregate().
    for fname, tool in (("leak-harness.sarif", "leak-harness"),
                        ("duplicate-detector.sarif", "duplicate-detector"),
                        ("propertychanged-storm.sarif", "propertychanged-storm")):
        rt = out_dir / fname
        if rt.exists():
            sarif_inputs.append((tool, str(rt)))
            tiers.append({"tool": tool, "tier": "runtime", "available": True,
                          "sarif": str(rt), "reason": ""})

    meta = {
        "target": target_name or target, "commit": commit,
        "generated": f"{datetime.now(UTC):%Y-%m-%d %H:%M UTC}",
        "profile": profile.get("name", "?"),
        "tiers": ", ".join(f"{t['tool']}={'ok' if t['available'] else 'NO-TOOL'}" for t in tiers)
        or "(no runners)",
        "no_tool_static": profile.get("no_tool_static") or [],
    }
    result = aggregate(sarif_inputs, out_dir, meta, line_tol=line_tol)
    result["tiers"] = tiers
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the static audit layer over a target.")
    ap.add_argument("--target", help="path to the target source tree")
    ap.add_argument("--profile", default="desktop-wpf", help="profile name or path")
    ap.add_argument("--out", default="artifacts/own-audit", help="artifacts/report directory")
    ap.add_argument("--target-name", default="", help="owner/repo label for the report header")
    ap.add_argument("--commit", default="", help="commit SHA for the report header")
    ap.add_argument("--line-tol", type=int, default=3)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.target:
        ap.error("--target is required (or use --selftest)")

    profile = load_profile(args.profile)
    result = run(args.target, profile, Path(args.out), args.target_name,
                 args.commit, args.line_tol)
    print(json.dumps({"totals": result["totals"],
                      "tiers": [{"tool": t["tool"], "available": t["available"],
                                 "reason": t["reason"]} for t in result["tiers"]],
                      "report_md": result["report_md"]}, indent=2))
    return 0


# --------------------------------------------------------------------------- #
# Selftest — full normalize→score→render pipeline on embedded SARIF fixtures,    #
# no external tools needed (so it gates on Linux CI like oracle_compare).        #
# --------------------------------------------------------------------------- #

def _fixture_sarifs(tmp: Path) -> list[tuple[str, str]]:
    own = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "Own.NET"}}, "results": [
        {"ruleId": "OWN001", "level": "warning",
         "message": {"text": "event subscribed, no -= [resource: subscription token]"},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/Vm/Customer.cs"},
                                             "region": {"startLine": 12}}}]},
        {"ruleId": "OWN001", "level": "warning",
         "message": {"text": "local IDisposable never disposed"},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/Util/Io.cs"},
                                             "region": {"startLine": 9}}}]},
    ]}]}
    codeql = {"runs": [{"results": [
        {"ruleId": "cs/local-not-disposed", "message": {"text": "not disposed"},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/Util/Io.cs"},
                                             "region": {"startLine": 10}}}]},
        {"ruleId": "cs/empty-block", "message": {"text": "empty"},
         "locations": [{"physicalLocation": {"artifactLocation": {"uri": "DevExpress.Xpf/G.cs"},
                                             "region": {"startLine": 4}}}]},
    ]}]}
    (tmp / "own-check.sarif").write_text(json.dumps(own), encoding="utf-8")
    (tmp / "codeql.sarif").write_text(json.dumps(codeql), encoding="utf-8")
    return [("own-check", str(tmp / "own-check.sarif")), ("codeql", str(tmp / "codeql.sarif"))]


def _selftest() -> int:
    import tempfile

    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:  # total derives from the call count
        checks.append("" if ok else msg)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        inputs = _fixture_sarifs(tmp)
        meta = {"target": "acme/legacy", "commit": "abc123", "profile": "desktop-wpf",
                "tiers": "own-check=ok, codeql=ok", "no_tool_static": [6, 11]}
        result = aggregate(inputs, tmp / "report", meta)

        # the agreed Io.cs leak is high-confidence; Customer.cs subscription is a candidate
        check(result["totals"]["high_confidence"] == 1,
              f"expected 1 high-confidence cluster, got {result['totals']}")
        check(result["totals"]["candidates"] == 1, f"expected 1 candidate, got {result['totals']}")

        md = Path(result["report_md"]).read_text(encoding="utf-8")
        check("# Own.NET Audit — health report" in md, "report.md missing title")
        check("## Where it hurts most" in md and "## Coverage / honesty" in md,
              "report.md missing a required section")
        check("third-party: DevExpress." in md,
              "report.md must report the suppressed DevExpress finding")
        # src/Util (agreed leak) must outrank src/Vm (lone subscription) in the heatmap
        check(md.find("`src/Util`") != -1 and not (md.find("`src/Vm`") != -1
              and md.find("`src/Util`") > md.find("`src/Vm`")),
              "heatmap ordering: src/Util must precede src/Vm")

        js = json.loads(Path(result["report_json"]).read_text(encoding="utf-8"))
        check(js["coverage"]["suppressed"] == 1, "report.json coverage lost the suppressed count")
        check(js["meta"]["target"] == "acme/legacy", "report.json lost meta")
        for art in ("report.md", "report.json", "report.sarif", "report.html"):
            check((tmp / "report" / art).exists(), f"aggregate did not write {art}")

    # Roslyn build-required tier writes one SARIF PER PROJECT under roslyn/; run()
    # must glob the directory, not a single fixed filename (Codex review on #100).
    with tempfile.TemporaryDirectory() as td2:
        out2 = Path(td2)
        (out2 / "roslyn").mkdir()
        rosl = {"runs": [{"results": [{"ruleId": "CA2000", "message": {"text": "undisposed"},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/App/Svc.cs"},
                                                "region": {"startLine": 5}}}]}]}]}
        (out2 / "roslyn" / "ProjA.sarif").write_text(json.dumps(rosl), encoding="utf-8")
        # a runtime leak-harness SARIF in the SAME file -> must be folded in by run()
        # and cluster with the static finding -> high confidence (Plan.md §3.5 / #102).
        leak = {"runs": [{"tool": {"driver": {"name": "leak-harness"}}, "results": [
            {"ruleId": "RUNTIME-LEAK-SUBSCRIPTION", "level": "error",
             "message": {"text": "retained Svc grew 1->11"},
             "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/App/Svc.cs"},
                                                 "region": {"startLine": 6}}}]}]}]}
        (out2 / "leak-harness.sarif").write_text(json.dumps(leak), encoding="utf-8")
        # a runtime duplicate-detector SARIF (heap-wide, file-level) must be folded in
        # too, so a filename/tool-name typo in the runtime pickup loop fails CI here,
        # not only on a Windows run (CodeRabbit review on #103).
        dup = {"runs": [{"tool": {"driver": {"name": "duplicate-detector"}}, "results": [
            {"ruleId": "RUNTIME-DUP-IMMUTABLE", "level": "warning",
             "message": {"text": '48211 duplicate "Country" strings (~1.6 MB wasted)'},
             "locations": [{"physicalLocation": {"artifactLocation": {
                 "uri": "heap://System.String/0000-Country"}}}]}]}]}
        (out2 / "duplicate-detector.sarif").write_text(json.dumps(dup), encoding="utf-8")
        # a runtime propertychanged-storm SARIF must be folded in by the same loop.
        storm = {"runs": [{"tool": {"driver": {"name": "propertychanged-storm"}}, "results": [
            {"ruleId": "RUNTIME-PROPCHANGED-STORM", "level": "warning",
             "message": {"text": "Total raised PropertyChanged 4200x/op"},
             "locations": [{"physicalLocation": {"artifactLocation": {
                 "uri": "inpc://Acme.Vm.DeclarationViewModel/0000-Total"}}}]}]}]}
        (out2 / "propertychanged-storm.sarif").write_text(json.dumps(storm), encoding="utf-8")
        profile = {"name": "t", "severity_floor": "warning", "tiers": {"build_free": []}}
        res2 = run("/nonexistent-target", profile, out2, target_name="t/p")
        check(any(t["tool"] == "roslyn-pack" for t in res2["tiers"]),
              "roslyn per-project SARIF under roslyn/ must be picked up")
        check(any(t["tool"] == "leak-harness" for t in res2["tiers"]),
              "runtime leak-harness.sarif must be folded in by run()")
        check(any(t["tool"] == "duplicate-detector" for t in res2["tiers"]),
              "runtime duplicate-detector.sarif must be folded in by run()")
        check(any(t["tool"] == "propertychanged-storm" for t in res2["tiers"]),
              "runtime propertychanged-storm.sarif must be folded in by run()")
        check(res2["totals"]["high_confidence"] >= 1,
              "runtime leak + static finding in one file must form a high-confidence cluster")

    # The build-free XAML tier must wire in like own-check/codeql: with "xaml" in
    # build_free and a .xaml under the target, run() reports a xaml tier and the
    # markup finding rides the pipeline through to a scored cluster — all on Linux,
    # no SDK (the whole point of the markup-only phase).
    with tempfile.TemporaryDirectory() as td3:
        out3 = Path(td3) / "out"
        src3 = Path(td3) / "src" / "Views"
        src3.mkdir(parents=True)
        (src3 / "Main.xaml").write_text(
            '<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"\n'
            '             xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">\n'
            '  <ListBox VirtualizingStackPanel.IsVirtualizing="False" />\n'
            '</UserControl>\n', encoding="utf-8")
        profile3 = {"name": "t", "severity_floor": "warning",
                    "tiers": {"build_free": ["xaml"]}}
        res3 = run(str(Path(td3) / "src"), profile3, out3, target_name="t/p")
        check(any(t["tool"] == "xaml" and t["available"] for t in res3["tiers"]),
              "xaml build-free tier must run and be reported by run()")
        check(res3["totals"]["candidates"] >= 1,
              "a XAML107 markup finding must flow through to a scored cluster")

    # The XAML Phase-2 join must wire in when BOTH fact sources are produced THIS run:
    # a view with a Loaded handler + an OwnIR component with an unreleased subscription
    # -> a XAML203 cluster. own-check needs an SDK we don't have on Linux CI, so stub it
    # to drop fresh OwnIR facts the way an --emit-facts run would (this also exercises
    # the freshness gate: the join keys off the status's `facts` path, not bare
    # existence).
    _self = sys.modules[__name__]  # the running module (own-check is a module global)

    def _fake_own_check(target_, out_dir_, severity_, root=None):
        facts = Path(out_dir_) / "own-check.facts.json"
        facts.write_text(json.dumps({"ownir_version": 0, "module": "App", "components": [
            {"name": "CustomerView", "file": "Views/CustomerView.xaml.cs", "subscriptions": [
                {"event": "_bus.Changed", "handler": "OnChanged", "line": 21,
                 "released": False}]}]}), encoding="utf-8")
        sarif = Path(out_dir_) / "own-check.sarif"
        sarif.write_text('{"version":"2.1.0","runs":[{"results":[]}]}', encoding="utf-8")
        return {"tool": "own-check", "tier": "build-free", "available": True,
                "sarif": str(sarif), "facts": str(facts), "findings": 0, "reason": ""}

    with tempfile.TemporaryDirectory() as td4:
        out4 = Path(td4) / "out"
        src4 = Path(td4) / "src" / "Views"
        src4.mkdir(parents=True)
        (src4 / "CustomerView.xaml").write_text(
            '<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"\n'
            '             xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"\n'
            '             x:Class="App.Views.CustomerView" Loaded="OnLoaded" />\n',
            encoding="utf-8")
        profile4 = {"name": "t", "severity_floor": "warning",
                    "tiers": {"build_free": ["own-check", "xaml"]}}
        real_own_check = _self.run_own_check
        _self.run_own_check = _fake_own_check
        try:
            res4 = run(str(Path(td4) / "src"), profile4, out4, target_name="t/p")
        finally:
            _self.run_own_check = real_own_check
        check(any(t["tool"] == "xaml-join" and t["available"] for t in res4["tiers"]),
              "xaml-join tier must run when this run produced both fact sources")
        check(res4["totals"]["clusters"] >= 1,
              "a XAML203 join finding must flow through to a scored cluster")

    # The join must NOT run on stale facts: a re-run with own-check NOT a producer this
    # time (and no SDK) must skip the join even though own-check.facts.json is on disk.
    with tempfile.TemporaryDirectory() as td5:
        out5 = Path(td5) / "out"
        out5.mkdir(parents=True)
        src5 = Path(td5) / "src" / "Views"
        src5.mkdir(parents=True)
        (src5 / "CustomerView.xaml").write_text(
            '<UserControl xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"\n'
            '             xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"\n'
            '             x:Class="App.Views.CustomerView" Loaded="OnLoaded" />\n',
            encoding="utf-8")
        (out5 / "own-check.facts.json").write_text(json.dumps({
            "ownir_version": 0, "module": "Stale", "components": [
                {"name": "CustomerView", "file": "Views/CustomerView.xaml.cs",
                 "subscriptions": [{"event": "_bus.Changed", "handler": "OnChanged",
                                    "line": 21, "released": False}]}]}), encoding="utf-8")
        res5 = run(str(Path(td5) / "src"),
                   {"name": "t", "severity_floor": "warning", "tiers": {"build_free": ["xaml"]}},
                   out5, target_name="t/p")
        check(not any(t["tool"] == "xaml-join" for t in res5["tiers"]),
              "xaml-join must NOT run on a stale own-check.facts.json this run did not produce")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"RUN_STATIC SELFTEST FAIL: {f}")
    print(f"run_static selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
