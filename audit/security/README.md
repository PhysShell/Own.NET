# Own.NET Audit — Security profile (P-024 §v0.1)

A **security profile** for the audit orchestrator. Not a scanner: it runs mature
external security tools, converts their output to SARIF, and folds the findings
into the same aggregate pipeline (`../aggregate/`) as every other tool — with an
honest coverage map that says exactly what was checked and what was skipped.

The design and the *decision not to build a scanner engine* are in
[`../../docs/proposals/P-024-security-audit-profile.md`](../../docs/proposals/P-024-security-audit-profile.md).
This subtree is the v0.1 slice of that proposal.

> **Why no own detection?** P-024 rejects the "Own.SecurityChecks" scanner engine
> (own YAML detection DSL, HTTP/TLS/SSH modules, a CVE corpus). Those duplicate
> Nuclei / testssl.sh / ZAP / Trivy and break the audit charter ("orchestrator,
> not analyzer; no regex heuristics; take ready tools"). Adding a check here means
> adding a *tool + adapter*, never a detection rule.

## Layout

```text
audit/security/
  profiles/
    baseline.yml            # the tool-run manifests (data, not code)
  adapters/
    sariflib.py             # shared minimal SARIF 2.1.0 writer
    testssl_to_sarif.py     # testssl.sh JSON  -> SARIF
    dotnet_vuln_to_sarif.py # dotnet list package --vulnerable JSON -> SARIF
    zap_to_sarif.py         # OWASP ZAP baseline JSON -> SARIF
  tools/
    run_security_profile.py # runner: plan -> coverage map (-> execute on operator machine)
  README.md
```

Nuclei and Trivy emit SARIF natively (`-sarif-export`, `--format sarif`), so they
need no adapter; testssl.sh, `dotnet list package`, and ZAP emit tool-specific
JSON, so each has a thin `raw → SARIF` adapter.

## The coverage map (honest by construction)

Every manifest resolves to one status, mirroring the static layer's NO-TOOL rule:

| Status | Meaning |
|---|---|
| `CHECKED` | tool on PATH and prerequisites met — it ran / would run |
| `SKIPPED` | executable not found — NO-TOOL, never faked |
| `NEEDS-RUNTIME` | needs a reachable/live target, none configured this run |
| `NEEDS-AUTH` | needs credentials, none configured this run |
| `DEFERRED` | no reliable tool yet (`tool: none`) — a planned check (e.g. v0.2 `.NET config`) |

## Running

```bash
# resolve the plan and write the coverage map (no tools needed to see the plan)
python audit/security/tools/run_security_profile.py --profile baseline \
    --out artifacts/security

# with tools installed + a live target, runtime manifests become CHECKED:
python audit/security/tools/run_security_profile.py --profile baseline \
    --target https://staging.example.com --out artifacts/security
```

Actually invoking Nuclei / ZAP / testssl.sh / Trivy needs network access and a
**live, authorized** target, so it runs on an operator machine — never against a
production host without permission, and never in Own.NET's Linux CI (same split
as the static layer, which analyzes the target only on a local Windows machine;
see [`../README.md`](../README.md)). CI gates the *plumbing*: that the profile
parses, the adapters import and convert fixtures correctly, and the runner plans
every branch.

## Tests

Each module has an embedded-fixture `--selftest` (no external tools, no network),
wired into the `audit aggregation selftests` CI job:

```bash
python audit/security/adapters/sariflib.py --selftest
python audit/security/adapters/testssl_to_sarif.py --selftest
python audit/security/adapters/dotnet_vuln_to_sarif.py --selftest
python audit/security/adapters/zap_to_sarif.py --selftest
python audit/security/tools/run_security_profile.py --selftest
```

## Not done yet (see P-024)

- **v0.2 — `OwnAudit.DotNetConfig`**: a *typed* .NET config auditor (web.config /
  appsettings / hosting) — the one place own code is justified, under a strict
  no-regex-first, SARIF-only, `needs-review`-without-prod-context policy. It is the
  `DEFERRED` `OWNSEC-CFG-001` manifest today.
- **v0.3 — cross-tool correlation**: reuse the aggregate oracle scorer so two tools
  agreeing on a finding raises confidence (ZAP + Nuclei on a header; Trivy + dotnet
  on a package).
- **Security taxonomy**: `../static/taxonomy/categories.yml` is leak-focused; security
  ruleIds land `uncategorized` in the aggregate report until a security taxonomy is
  added. The SARIF is emitted and consumable now; category mapping is the next step.
- Open questions (Nuclei template curation, the scan-target allowlist format) are
  tracked in P-024 §"Open questions".
