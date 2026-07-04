#!/usr/bin/env python3
"""
Own.NET Audit — Security profile runner (P-024 §v0.1).

Runs a *security profile*: a set of **tool-run manifests** that each name an
external security tool, how to invoke it, and how its output becomes SARIF. This
is an orchestrator, not a scanner (P-024): it decides which tools can run, runs
the ones it can, converts their output through the adapters, and — above all —
emits an honest **coverage map** so a run says exactly what it checked and what
it skipped and why.

A manifest is data, never detection logic (P-024 non-goals). Each entry declares:

  id/title   — stable identifier + human label
  tool       — the cross-tool name (matches the SARIF driver / adapter TOOL)
  executable — the binary that must be on PATH for this to run
  category   — web / tls / supply-chain / dotnet-config …
  requires   — prerequisites: ``runtime`` (a reachable target) and/or ``auth``
               (credentials). Unmet prerequisites downgrade the status honestly.
  sarif      — ``native`` (tool writes SARIF itself) or ``{adapter: <module>}``
               (adapter converts the tool's raw output)
  args       — the argv template (documented; execution is out of CI scope)

Coverage statuses (the honesty ledger, mirroring the static layer's NO-TOOL rule):

  CHECKED       — tool available and prerequisites met (it ran / would run)
  SKIPPED       — executable not found: NO-TOOL, never faked
  NEEDS-RUNTIME — needs a reachable target, none configured this run
  NEEDS-AUTH    — needs credentials, none configured this run
  DEFERRED      — no tool yet (``tool: none``): a planned check (e.g. v0.2
                  dotnet-config), reported as pending, not pretended

The *plan* (manifest → decision) is a pure function and is what CI selftests
cover; actually invoking Nuclei/ZAP/testssl/Trivy needs network + live targets
and runs on an operator machine, not in Own.NET's Linux CI (same split as the
static layer analyzing the target only on Windows — audit/README.md).

Usage:
  run_security_profile.py --profile baseline [--target https://host] [--auth] \\
                          --out artifacts/security
  run_security_profile.py --selftest
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_SECURITY = _HERE.parent
sys.path.insert(0, str(_SECURITY / "adapters"))

DEFAULT_PROFILE_DIR = _SECURITY / "profiles"

CHECKED = "CHECKED"
SKIPPED = "SKIPPED"
NEEDS_RUNTIME = "NEEDS-RUNTIME"
NEEDS_AUTH = "NEEDS-AUTH"
DEFERRED = "DEFERRED"


@dataclass
class Manifest:
    id: str
    title: str
    tool: str
    executable: str = ""
    category: str = "other"
    requires: list[str] = field(default_factory=list)
    sarif: Any = "native"          # "native" | {"adapter": "<module>"}
    args: list[str] = field(default_factory=list)
    fp_policy: str = "external-tool"
    internal: bool = False         # own analyzer shipping in-repo (no PATH executable)
    module: str = ""               # module name for an internal analyzer

    @property
    def adapter(self) -> str | None:
        if isinstance(self.sarif, dict):
            return str(self.sarif.get("adapter") or "") or None
        return None


@dataclass
class Decision:
    manifest: Manifest
    status: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.manifest.id, "title": self.manifest.title,
                "tool": self.manifest.tool, "category": self.manifest.category,
                "status": self.status, "reason": self.reason}


def load_profile(name_or_path: str) -> dict[str, Any]:
    import yaml  # scoped dep — see audit/requirements.txt

    p = Path(name_or_path)
    if not p.exists():
        p = DEFAULT_PROFILE_DIR / f"{name_or_path}.yml"
    if not p.exists():
        p = DEFAULT_PROFILE_DIR / f"{name_or_path}.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def parse_manifests(profile: dict[str, Any]) -> list[Manifest]:
    out: list[Manifest] = []
    for m in profile.get("manifests") or []:
        if not isinstance(m, dict):
            continue
        out.append(Manifest(
            id=str(m.get("id") or "?"),
            title=str(m.get("title") or m.get("id") or "?"),
            tool=str(m.get("tool") or "none"),
            executable=str(m.get("executable") or ""),
            category=str(m.get("category") or "other"),
            requires=list(m.get("requires") or []),
            sarif=m.get("sarif", "native"),
            args=list(m.get("args") or []),
            fp_policy=str((m.get("confidence") or {}).get("fpPolicy")
                          if isinstance(m.get("confidence"), dict) else "external-tool"),
            internal=bool(m.get("internal")),
            module=str(m.get("module") or ""),
        ))
    return out


def plan(manifests: list[Manifest], available: set[str], *, has_target: bool,
         has_auth: bool) -> list[Decision]:
    """Resolve each manifest to a coverage decision. Pure: availability and the
    target/auth context are passed in, so CI can exercise every branch without a
    single external tool. Prerequisite gaps are reported *before* the tool gap —
    NEEDS-RUNTIME/AUTH describe the run's configuration, and a missing binary is
    reported as SKIPPED regardless; we surface the most actionable reason."""
    decisions: list[Decision] = []
    for m in manifests:
        if m.tool == "none":
            decisions.append(Decision(m, DEFERRED,
                             "no reliable tool yet — planned check, not faked"))
            continue
        # Internal analyzers (our own code) ship in-repo, so they are never a PATH
        # NO-TOOL; only their `requires` gate them.
        if not m.internal and m.executable and m.executable not in available:
            decisions.append(Decision(m, SKIPPED,
                             f"executable {m.executable!r} not on PATH (NO-TOOL)"))
            continue
        if "runtime" in m.requires and not has_target:
            decisions.append(Decision(m, NEEDS_RUNTIME,
                             "needs a reachable target; none configured this run"))
            continue
        if "auth" in m.requires and not has_auth:
            decisions.append(Decision(m, NEEDS_AUTH,
                             "needs credentials; none configured this run"))
            continue
        decisions.append(Decision(m, CHECKED, "tool available, prerequisites met"))
    return decisions


def coverage_map(decisions: list[Decision]) -> dict[str, Any]:
    from collections import Counter

    by_status = Counter(d.status for d in decisions)
    return {
        "total": len(decisions),
        "by_status": dict(by_status),
        "checked": [d.to_dict() for d in decisions if d.status == CHECKED],
        "skipped": [d.to_dict() for d in decisions if d.status != CHECKED],
    }


def convert_raw(adapter_module: str, raw_path: Path, out_path: Path,
                target: str = "") -> dict[str, int]:
    """Run one adapter's ``convert`` on a tool's raw output, writing SARIF. Kept
    generic so the runner never hard-codes a tool's schema — the adapter owns it."""
    import importlib
    import inspect

    mod = importlib.import_module(adapter_module)
    raw = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
    # Dispatch by the adapter's real arity (testssl's convert takes a target
    # fallback; others take just raw). Inspecting the signature — rather than
    # catching TypeError — means a genuine TypeError raised *inside* convert is not
    # swallowed and the adapter silently re-run.
    accepts_target = len(inspect.signature(mod.convert).parameters) >= 2
    run, tally = mod.convert(raw, target) if accepts_target else mod.convert(raw)
    out_path.write_text(run.to_json(), encoding="utf-8")
    return tally


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run a security profile (orchestrator).")
    ap.add_argument("--profile", default="baseline", help="profile name or path")
    ap.add_argument("--target", default="", help="target URL/host (enables runtime tools)")
    ap.add_argument("--auth", action="store_true", help="credentials are configured")
    ap.add_argument("--out", default="artifacts/security", help="artifacts directory")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    profile = load_profile(args.profile)
    manifests = parse_manifests(profile)
    available = {m.executable for m in manifests
                 if m.executable and shutil.which(m.executable)}
    decisions = plan(manifests, available, has_target=bool(args.target), has_auth=args.auth)
    cov = coverage_map(decisions)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "coverage-map.json").write_text(
        json.dumps({"profile": profile.get("name", args.profile), "coverage": cov},
                   indent=2), encoding="utf-8")
    print(json.dumps(cov["by_status"], indent=2))
    print(f"coverage map -> {out_dir / 'coverage-map.json'}")
    print("note: tool execution runs on an operator machine (network + live target); "
          "this run resolved the plan and wrote the coverage map.")
    return 0


def _selftest() -> int:
    import tempfile

    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:
        checks.append("" if ok else msg)

    manifests = [
        Manifest("OWNSEC-WEB-001", "Web baseline (Nuclei)", "nuclei", "nuclei",
                 "web", ["runtime"], "native"),
        Manifest("OWNSEC-TLS-001", "TLS (testssl.sh)", "testssl", "testssl.sh",
                 "tls", ["runtime"], {"adapter": "testssl_to_sarif"}),
        Manifest("OWNSEC-DEP-001", "Deps (Trivy)", "trivy", "trivy",
                 "supply-chain", [], "native"),
        Manifest("OWNSEC-CFG-001", ".NET config", "dotnet-config", "", "dotnet-config",
                 [], "native", internal=True, module="dotnet_config_audit"),
        Manifest("OWNSEC-DEFER", "future check", "none", "", "other", [], "native"),
    ]

    # 1) plan: nothing on PATH, no target -> external tools SKIPPED (NO-TOOL); the
    #    internal analyzer is CHECKED (ships in-repo); the tool:none one DEFERRED.
    d0 = {d.manifest.id: d for d in plan(manifests, set(), has_target=False, has_auth=False)}
    check(d0["OWNSEC-WEB-001"].status == SKIPPED, "missing nuclei -> SKIPPED")
    check(d0["OWNSEC-DEP-001"].status == SKIPPED, "missing trivy -> SKIPPED")
    check(d0["OWNSEC-CFG-001"].status == CHECKED,
          "internal analyzer must be CHECKED without a PATH executable")
    check(d0["OWNSEC-DEFER"].status == DEFERRED, "tool:none -> DEFERRED")

    # 2) plan: all executables available, but no target -> runtime tools NEEDS-RUNTIME,
    #    the filesystem tool (trivy, no runtime req) CHECKED.
    allexe = {"nuclei", "testssl.sh", "trivy"}
    d1 = {d.manifest.id: d for d in plan(manifests, allexe, has_target=False, has_auth=False)}
    check(d1["OWNSEC-WEB-001"].status == NEEDS_RUNTIME, "nuclei present, no target: NEEDS-RUNTIME")
    check(d1["OWNSEC-TLS-001"].status == NEEDS_RUNTIME, "testssl present, no target: NEEDS-RUNTIME")
    check(d1["OWNSEC-DEP-001"].status == CHECKED, "trivy (no runtime req) present -> CHECKED")

    # 3) plan: all available + target configured -> runtime tools CHECKED too.
    d2 = {d.manifest.id: d for d in plan(manifests, allexe, has_target=True, has_auth=False)}
    check(d2["OWNSEC-WEB-001"].status == CHECKED, "nuclei present + target -> CHECKED")
    check(d2["OWNSEC-TLS-001"].status == CHECKED, "testssl present + target -> CHECKED")

    # 4) auth requirement: an auth-gated manifest is NEEDS-AUTH until --auth.
    authman = [Manifest("OWNSEC-CFG-002", "Authenticated config", "owncfg", "owncfg",
                        "dotnet-config", ["auth"], "native")]
    da = plan(authman, {"owncfg"}, has_target=True, has_auth=False)[0]
    check(da.status == NEEDS_AUTH, "auth-gated tool without --auth -> NEEDS-AUTH")
    da2 = plan(authman, {"owncfg"}, has_target=True, has_auth=True)[0]
    check(da2.status == CHECKED, "auth-gated tool with --auth -> CHECKED")

    # 5) coverage map tallies and separates checked from the rest. In d1 (all exes
    #    present, no target): WEB/TLS NEEDS-RUNTIME, DEP + internal CFG CHECKED,
    #    DEFER DEFERRED.
    cov = coverage_map(list(d1.values()))
    check(cov["total"] == 5, f"coverage total wrong: {cov['total']}")
    check(cov["by_status"].get(NEEDS_RUNTIME) == 2, "two NEEDS-RUNTIME expected")
    check(cov["by_status"].get(CHECKED) == 2, "two CHECKED expected (trivy + internal)")
    check(len(cov["checked"]) == 2 and len(cov["skipped"]) == 3,
          "checked/skipped split wrong")

    # 6) convert_raw dispatches to an adapter by module name and writes SARIF that
    #    round-trips through parse_sarif — the runner's adapter seam actually works.
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "testssl.json"
        raw.write_text(json.dumps([{"id": "TLS1", "fqdn": "h", "port": "443",
                                    "severity": "MEDIUM", "finding": "TLS 1.0 offered"}]),
                       encoding="utf-8")
        out = Path(td) / "testssl.sarif"
        tally = convert_raw("testssl_to_sarif", raw, out, "h:443")
        check(tally["findings"] == 1, "convert_raw must drive the testssl adapter")
        doc = json.loads(out.read_text(encoding="utf-8"))
        check(doc["runs"][0]["tool"]["driver"]["name"] == "testssl",
              "convert_raw must write adapter SARIF")

    # 7) the shipped baseline profile must parse and be internally consistent:
    #    adapter/analyzer modules import, external tools name an executable, ids unique.
    import importlib
    prof = load_profile("baseline")
    mans = parse_manifests(prof)
    check(len(mans) >= 4, f"baseline profile should ship several manifests, got {len(mans)}")
    ids = [m.id for m in mans]
    check(len(ids) == len(set(ids)), f"manifest ids must be unique: {ids}")
    internal_seen = False
    for m in mans:
        if m.adapter:
            try:
                importlib.import_module(m.adapter)
            except ImportError as exc:  # pragma: no cover
                check(False, f"{m.id}: adapter {m.adapter} does not import: {exc}")
        if m.internal:
            internal_seen = True
            check(bool(m.module), f"{m.id}: an internal analyzer must name a module")
            try:
                importlib.import_module(m.module)
            except ImportError as exc:  # pragma: no cover
                check(False, f"{m.id}: internal module {m.module} does not import: {exc}")
        elif m.tool != "none":
            check(bool(m.executable), f"{m.id}: an external tool must name an executable")
    check(internal_seen, "baseline must ship the internal dotnet-config analyzer (v0.2)")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"RUN_SECURITY_PROFILE SELFTEST FAIL: {f}")
    print(f"run_security_profile selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
