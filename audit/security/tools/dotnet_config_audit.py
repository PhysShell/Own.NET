#!/usr/bin/env python3
"""
Own.NET Audit — Security: typed .NET configuration audit -> SARIF (P-024 §v0.2).

This is the one place P-024 sanctions *own* detection code: the niche no mature
tool covers well — reading .NET configuration files and flagging insecure
settings. It is held to a strict discipline, because "regex over config" is
exactly the FP factory the audit charter forbids:

  1. **No regex-first detection.** XML (`web.config`, `app.config`) is parsed with
     an XML parser and inspected by element/attribute; JSON (`appsettings*.json`)
     with a JSON parser and inspected by typed key. Text search is used *only* to
     locate an already-parsed finding's line for the report, never to detect it.
  2. **Needs-review without proven production context.** A single config file
     rarely proves it is the deployed/Release config. `debug="true"` is correct in
     a Debug build; `AllowedHosts: "*"` is the dev default. So a finding that only
     bites in production is **downgraded and marked `needs-review`** unless the
     file's name proves prod (``appsettings.Production.json``, ``web.Release.config``).
     Files that prove *dev* context suppress the finding (counted, not hidden).
  3. **SARIF only**, one finding per issue, each carrying a limitations note.
  4. **Honest skip.** Checks that genuinely require C# analysis (DataProtection key
     persistence, IdentityServer dev signing credential, `UseHsts`, forwarded
     headers) are **not faked** from config files — they are reported as a coverage
     note pointing at Roslyn (P-024), never emitted as guesses.

Output flows into the same aggregate pipeline as every other tool via the shared
SARIF writer (tool name ``dotnet-config``).

Usage:
  dotnet_config_audit.py --target /path/to/app --out dotnet-config.sarif
  dotnet_config_audit.py --selftest
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "adapters"))
from sariflib import Result, SarifRun

TOOL = "dotnet-config"
INFO_URI = "https://learn.microsoft.com/aspnet/core/fundamentals/configuration/"

# Checks that config files cannot honestly answer — they need C# analysis. Reported
# as a coverage note (NO-TOOL / deferred-to-Roslyn), never faked into findings.
NEEDS_CODE_ANALYSIS = [
    "DataProtection key persistence (ephemeral keys in production)",
    "IdentityServer AddDeveloperSigningCredential outside Development",
    "UseHsts / UseHttpsRedirection presence in the request pipeline",
    "ForwardedHeaders configuration behind a reverse proxy",
]

# severity downgrade applied when production context is unproven (needs-review).
_DOWNGRADE = {"high": "medium", "medium": "low", "low": "info", "info": "info"}


def prod_state(filename: str) -> str:
    """'prod' / 'dev' / 'unknown' inferred from the file name only — the honest
    signal a static config read actually has. Environment-specific transforms and
    the ASPNETCORE_ENVIRONMENT at deploy time are the authorities; the name is a
    proxy, hence 'unknown' -> needs-review rather than a confident verdict."""
    n = filename.lower()
    if ("production" in n or "prod" in n or ".release." in n
            or n.endswith("web.release.config")):
        return "prod"
    if ("development" in n or n.endswith(".dev.json")
            or ("debug" in n and n.endswith(".config"))):
        return "dev"
    return "unknown"


def _line_of(raw: str, *needles: str) -> int:
    """1-based line of the first needle found (report anchoring only, not detection).
    Returns 1 when nothing matches — the finding is real regardless of location."""
    for i, line in enumerate(raw.splitlines(), start=1):
        if any(nd and nd in line for nd in needles):
            return i
    return 1


def _apply_context(severity: str, state: str) -> tuple[str, str] | None:
    """Adjust a prod-only finding's severity by context. Returns
    ``(severity, note)`` or ``None`` when the finding should be suppressed (proven
    dev context)."""
    if state == "prod":
        return severity, ""
    if state == "dev":
        return None  # correct in a dev config — suppress (still counted in coverage)
    return _DOWNGRADE.get(severity, severity), " [needs-review: production context unproven]"


def audit_webconfig(raw: str, path: str, state: str) -> tuple[list[Result], int]:
    """Typed checks over a web.config/app.config. Returns (findings, suppressed)."""
    findings: list[Result] = []
    suppressed = 0
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return findings, suppressed
    sysweb = root.find("system.web")
    if sysweb is None:
        return findings, suppressed

    def emit(rule: str, base_sev: str, msg: str, *needles: str,
             prod_only: bool = True, help_frag: str = "") -> None:
        nonlocal suppressed
        if prod_only:
            adj = _apply_context(base_sev, state)
            if adj is None:
                suppressed += 1
                return
            sev, note = adj
        else:
            sev, note = base_sev, ""
        findings.append(Result(rule_id=rule, message=msg + note, severity=sev,
                               uri=path, line=_line_of(raw, *needles),
                               help_uri=help_frag or INFO_URI))

    comp = sysweb.find("compilation")
    if comp is not None and (comp.get("debug") or "").strip().lower() == "true":
        emit("SC-CFG-DEBUG", "high",
             "<compilation debug=\"true\"> ships debug symbols and disables "
             "optimizations", 'debug="true"', 'debug=\'true\'')

    ce = sysweb.find("customErrors")
    if ce is not None and (ce.get("mode") or "").strip().lower() == "off":
        emit("SC-CFG-CUSTOMERRORS", "high",
             "<customErrors mode=\"Off\"> exposes exception detail / stack traces "
             "to clients", 'mode="Off"', "mode='Off'")

    cookies = sysweb.find("httpCookies")
    if cookies is not None:
        if (cookies.get("requireSSL") or "").strip().lower() == "false":
            emit("SC-CFG-COOKIES-SSL", "medium",
                 "<httpCookies requireSSL=\"false\"> allows cookies over plain HTTP",
                 'requireSSL="false"', prod_only=True)
        if (cookies.get("httpOnlyCookies") or "").strip().lower() == "false":
            emit("SC-CFG-COOKIES-HTTPONLY", "medium",
                 "<httpCookies httpOnlyCookies=\"false\"> exposes cookies to script",
                 'httpOnlyCookies="false"', prod_only=False)

    mk = sysweb.find("machineKey")
    if mk is not None:
        vk = (mk.get("validationKey") or "").strip()
        if vk and "autogenerate" not in vk.lower():
            emit("SC-CFG-MACHINEKEY", "medium",
                 "explicit <machineKey validationKey> present — ensure keys are not "
                 "source-committed secrets and are rotated", "validationKey",
                 prod_only=False)

    tr = sysweb.find("trace")
    if (tr is not None and (tr.get("enabled") or "").strip().lower() == "true"
            and (tr.get("localOnly") or "true").strip().lower() != "true"):
        emit("SC-CFG-TRACE", "medium",
             "<trace enabled=\"true\" localOnly=\"false\"> exposes trace.axd to "
             "remote clients", 'enabled="true"')

    return findings, suppressed


def audit_appsettings(raw: str, path: str, state: str) -> tuple[list[Result], int]:
    """Typed checks over an appsettings*.json. Returns (findings, suppressed)."""
    findings: list[Result] = []
    suppressed = 0
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return findings, suppressed
    if not isinstance(data, dict):
        return findings, suppressed

    def emit(rule: str, base_sev: str, msg: str, *needles: str,
             prod_only: bool = True) -> None:
        nonlocal suppressed
        if prod_only:
            adj = _apply_context(base_sev, state)
            if adj is None:
                suppressed += 1
                return
            sev, note = adj
        else:
            sev, note = base_sev, ""
        findings.append(Result(rule_id=rule, message=msg + note, severity=sev,
                               uri=path, line=_line_of(raw, *needles), help_uri=INFO_URI))

    if str(data.get("AllowedHosts", "")).strip() == "*":
        emit("SC-CFG-ALLOWEDHOSTS", "medium",
             "AllowedHosts is \"*\" — the Host header is not restricted",
             '"AllowedHosts"')

    conns = data.get("ConnectionStrings")
    if isinstance(conns, dict):
        for name, value in conns.items():
            if isinstance(value, str) and _has_inline_secret(value):
                emit("SC-CFG-CONNSTR-SECRET", "medium",
                     f"connection string '{name}' contains an inline password — "
                     "move secrets out of config (user-secrets / key vault / env)",
                     f'"{name}"', prod_only=False)

    lvl = _log_default_level(data)
    if lvl in ("debug", "trace"):
        emit("SC-CFG-LOGLEVEL", "low",
             f"Logging:LogLevel:Default is '{lvl}' — verbose logs can leak data and "
             "hurt performance in production", '"Default"')

    return findings, suppressed


def _has_inline_secret(conn: str) -> bool:
    """A connection string carries an inline secret if it sets a non-empty
    password/pwd token. Typed parse of the ';'-delimited keywords — not a regex over
    the raw file."""
    for part in conn.split(";"):
        key, _, val = part.partition("=")
        if key.strip().lower() in ("password", "pwd") and val.strip():
            return True
    return False


def _log_default_level(data: dict[str, Any]) -> str:
    logging = data.get("Logging")
    if isinstance(logging, dict):
        lvl = logging.get("LogLevel")
        if isinstance(lvl, dict):
            return str(lvl.get("Default", "")).strip().lower()
    return ""


def analyze_tree(root_dir: Path) -> tuple[SarifRun, dict[str, Any]]:
    run = SarifRun(TOOL, information_uri=INFO_URI)
    tally = {"web_config": 0, "appsettings": 0, "findings": 0,
             "suppressed_dev": 0, "needs_code_analysis": list(NEEDS_CODE_ANALYSIS)}
    if not root_dir.exists():
        return run, tally

    for p in sorted(root_dir.rglob("*")):
        if not p.is_file():
            continue
        name = p.name.lower()
        rel = str(p.relative_to(root_dir))
        raw = _read(p)
        if raw is None:
            continue
        state = prod_state(p.name)
        if name in ("web.config", "app.config") or name.endswith(".config"):
            fs, sup = audit_webconfig(raw, rel, state)
            tally["web_config"] += 1
        elif name.startswith("appsettings") and name.endswith(".json"):
            fs, sup = audit_appsettings(raw, rel, state)
            tally["appsettings"] += 1
        else:
            continue
        for f in fs:
            run.add(f)
        tally["suppressed_dev"] += sup

    tally["findings"] = len(run.results)
    return run, tally


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Typed .NET configuration audit -> SARIF.")
    ap.add_argument("--target", help="root directory of the .NET app to audit")
    ap.add_argument("--out", dest="out_path", help="SARIF output path")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.target or not args.out_path:
        ap.error("--target and --out are required (or use --selftest)")

    run, tally = analyze_tree(Path(args.target))
    Path(args.out_path).write_text(run.to_json(), encoding="utf-8")
    print(json.dumps(tally, indent=2))
    return 0


def _selftest() -> int:
    import tempfile

    checks: list[str] = []

    def check(ok: bool, msg: str) -> None:
        checks.append("" if ok else msg)

    # prod-context inference from filenames
    check(prod_state("appsettings.Production.json") == "prod", "Production.json -> prod")
    check(prod_state("web.Release.config") == "prod", "web.Release.config -> prod")
    check(prod_state("appsettings.Development.json") == "dev", "Development.json -> dev")
    check(prod_state("appsettings.json") == "unknown", "base appsettings -> unknown")

    bad_web = (
        '<?xml version="1.0"?>\n<configuration>\n <system.web>\n'
        '  <compilation debug="true" targetFramework="4.7.2"/>\n'
        '  <customErrors mode="Off"/>\n'
        '  <httpCookies requireSSL="false" httpOnlyCookies="false"/>\n'
        '  <trace enabled="true" localOnly="false"/>\n'
        ' </system.web>\n</configuration>\n')

    # PROD context: debug + customErrors are their full severity, not downgraded
    f_prod, _ = audit_webconfig(bad_web, "web.Release.config", "prod")
    by = {r.rule_id: r for r in f_prod}
    check(by["SC-CFG-DEBUG"].severity == "high", "debug in prod must stay high")
    check("needs-review" not in by["SC-CFG-DEBUG"].message, "prod finding must not be needs-review")
    check(by["SC-CFG-CUSTOMERRORS"].severity == "high", "customErrors Off in prod -> high")
    check(by["SC-CFG-DEBUG"].line == 4, f"debug line anchor 4, got {by['SC-CFG-DEBUG'].line}")

    # UNKNOWN context: prod-only findings downgrade + needs-review; httpOnly (not
    # prod-only) stays medium and is always reported
    f_unk, _ = audit_webconfig(bad_web, "web.config", "unknown")
    byu = {r.rule_id: r for r in f_unk}
    check(byu["SC-CFG-DEBUG"].severity == "medium", "debug unknown-context -> downgraded to medium")
    check("needs-review" in byu["SC-CFG-DEBUG"].message, "downgraded finding must be needs-review")
    check(byu["SC-CFG-COOKIES-HTTPONLY"].severity == "medium",
          "httpOnly finding is context-independent (always medium)")
    check("needs-review" not in byu["SC-CFG-COOKIES-HTTPONLY"].message,
          "context-independent finding must not be needs-review")

    # DEV context: prod-only findings suppressed (counted), context-independent kept
    f_dev, sup = audit_webconfig(bad_web, "app.config", "dev")
    byd = {r.rule_id: r for r in f_dev}
    check("SC-CFG-DEBUG" not in byd, "debug in a dev config must be suppressed")
    check(sup >= 3, f"dev-suppressed prod-only findings must be counted, got {sup}")
    check("SC-CFG-COOKIES-HTTPONLY" in byd, "context-independent finding survives dev context")

    # a clean web.config yields nothing and does not crash
    clean_web = ('<configuration><system.web>'
                 '<compilation debug="false"/><customErrors mode="RemoteOnly"/>'
                 '</system.web></configuration>')
    fc, _ = audit_webconfig(clean_web, "web.config", "prod")
    check(not fc, f"clean web.config must yield no findings, got {[r.rule_id for r in fc]}")

    # malformed XML must be safe (no crash, no finding)
    fm, _ = audit_webconfig("<not-closed", "web.config", "prod")
    check(not fm, "malformed XML must be handled safely")

    # appsettings: AllowedHosts=* + inline secret + verbose log level
    bad_json = json.dumps({
        "AllowedHosts": "*",
        "ConnectionStrings": {"Main": "Server=db;Database=app;User Id=sa;Password=Sekret123;"},
        "Logging": {"LogLevel": {"Default": "Debug"}},
    })
    fj_prod, _ = audit_appsettings(bad_json, "appsettings.Production.json", "prod")
    byj = {r.rule_id: r for r in fj_prod}
    check(byj["SC-CFG-ALLOWEDHOSTS"].severity == "medium", "AllowedHosts * in prod -> medium")
    check("needs-review" not in byj["SC-CFG-ALLOWEDHOSTS"].message, "prod hosts not needs-review")
    check("SC-CFG-CONNSTR-SECRET" in byj, "inline password must be detected via typed parse")
    check(byj["SC-CFG-CONNSTR-SECRET"].severity == "medium",
          "connstr secret is context-independent")
    check("SC-CFG-LOGLEVEL" in byj, "verbose default log level must be flagged")

    # base appsettings.json (unknown): AllowedHosts downgrades + needs-review;
    # the secret (context-independent) stays medium
    fj_unk, _ = audit_appsettings(bad_json, "appsettings.json", "unknown")
    byju = {r.rule_id: r for r in fj_unk}
    check(byju["SC-CFG-ALLOWEDHOSTS"].severity == "low"
          and "needs-review" in byju["SC-CFG-ALLOWEDHOSTS"].message,
          "unknown-context AllowedHosts -> downgraded + needs-review")
    check(byju["SC-CFG-CONNSTR-SECRET"].severity == "medium", "secret stays medium in any context")

    # a connection string using integrated security must NOT trip the secret check
    safe_json = json.dumps({"ConnectionStrings":
                            {"Main": "Server=db;Integrated Security=SSPI;"}})
    fj_safe, _ = audit_appsettings(safe_json, "appsettings.json", "unknown")
    check(not any(r.rule_id == "SC-CFG-CONNSTR-SECRET" for r in fj_safe),
          "integrated-security connection string must not be a secret finding")

    # empty / malformed JSON must be safe
    check(audit_appsettings("", "appsettings.json", "unknown")[0] == []
          or not audit_appsettings("", "appsettings.json", "unknown")[0],
          "empty appsettings must be safe")
    check(not audit_appsettings("{bad", "appsettings.json", "unknown")[0],
          "malformed JSON must be handled safely")

    # end-to-end tree walk: discovers files, emits SARIF that round-trips, keeps
    # the honest code-analysis coverage note
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "web.config").write_text(bad_web, encoding="utf-8")
        (root / "appsettings.Production.json").write_text(bad_json, encoding="utf-8")
        (root / "appsettings.Development.json").write_text(
            json.dumps({"AllowedHosts": "*"}), encoding="utf-8")
        run, tally = analyze_tree(root)
        check(tally["web_config"] == 1 and tally["appsettings"] == 2,
              f"tree walk must find the config files, got {tally}")
        # dev appsettings AllowedHosts=* must be suppressed, prod one kept
        check(tally["suppressed_dev"] >= 1, "dev-context findings must be counted as suppressed")
        check(tally["findings"] >= 1, "prod findings must be emitted")
        check(NEEDS_CODE_ANALYSIS[0] in tally["needs_code_analysis"],
              "coverage note for code-level checks must be carried (honest skip)")
        doc = run.to_dict()["runs"][0]
        check(doc["tool"]["driver"]["name"] == "dotnet-config", "SARIF driver name wrong")

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        try:
            from oracle_compare import parse_sarif
        except ImportError:  # pragma: no cover
            pass
        else:
            parsed = parse_sarif(run.to_json(), TOOL, [])
            check(len(parsed) == tally["findings"], "SARIF must round-trip through parse_sarif")

    fails = [c for c in checks if c]
    for f in fails:
        print(f"DOTNET-CONFIG AUDIT SELFTEST FAIL: {f}")
    print(f"dotnet_config_audit selftest: {len(checks) - len(fails)}/{len(checks)} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
