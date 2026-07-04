# P-024 — Security audit profile (external tools + SARIF adapters)

- **Status:** in progress — v0.1 built (`audit/security/`: baseline profile, the
  three raw→SARIF adapters, the plan/coverage-map runner) and v0.2 built (typed
  `.NET` config auditor `tools/dotnet_config_audit.py`), all with CI-gated
  selftests. Supersedes and **rejects** the earlier "Own.SecurityChecks"
  scanner-engine idea (recorded below so it is not re-proposed). v0.3 (cross-tool
  correlation + security taxonomy) not started.
  - **Open question resolved:** v0.2 lives as a stdlib-Python analyzer in the audit
    subtree (XML/JSON parsers), not a separate .NET/MSBuild project — it keeps the
    subtree dependency-light and gating on the same Linux CI as the rest.
- **Depends on:** the audit orchestrator design ([`Plan.md`](../../Plan.md)) — SARIF
  normalization, cross-tool confidence scoring, coverage map. Relates to
  [P-015](P-015-configuration-surface.md) (check selection / severity) for how the
  profile's categories surface in configuration.
- **Where it lives:** the design is recorded here; per
  [`audit/README.md`](../../audit/README.md) active audit development currently
  happens in the `OwnAudit` repo, and this profile follows the audit code — it is an
  audit extension, not core. Same contract as everything else in the fleet:
  consumed through CLI + SARIF only, zero coupling to `ownlang/`.

## Decision (read this first)

**Do not build a security scanner.** A proposal was drafted for
"Own.SecurityChecks": a C# engine interpreting a custom YAML detection DSL
(request/expect matchers, HTTP/SSH/DB modules, its own severity model, an eventual
NASL/OpenVAS/Nessus export). It is rejected, permanently, for reasons that are
already codified as repository principles in `Plan.md`:

- **"Оркестратор, не анализатор"** — the audit layer runs mature external tools and
  aggregates evidence; it does not grow its own detectors.
- **"Ни одной собственной эвристики «на регулярках»"** — the engine's example checks
  were regex-over-config and regex-over-banner, exactly the FP factory the charter
  forbids. (A banner regex like `OpenSSL 1\.0\.` misses vulnerable `1.1.0` while the
  remediation demands `>=1.1.1` — the failure mode is intrinsic, not a draft bug.)
- **"Берём готовое"** — the niche is occupied. Nuclei *is* the "YAML checks with
  id/severity/matchers + CI + community corpus" product, with native SARIF export;
  testssl.sh owns TLS; ZAP baseline owns the safe web pass; Trivy and
  `dotnet list package --vulnerable` own dependencies. Rebuilding any of these is
  months of engine work plus an unbounded corpus-maintenance tail (Greenbone staffs
  a team for ~100k NVTs).

What survives from the old idea is **not** the engine but the *artifact model*: a
security check is a first-class, reviewable, versioned thing with an id, a
severity, and a defined FP policy. We keep that — as a **tool-run manifest**, not a
detection DSL.

> **Own.NET Audit Security Profile** — a set of profiles and thin adapters that run
> ready-made security tools inside the existing SARIF pipeline of the audit
> orchestrator. Not a new product; a new audit profile.

## Motivation

The audit orchestrator answers "where does the legacy target hurt" for code
health. The same fleet-of-tools / SARIF / cross-tool-agreement machinery applies
unchanged to a second question — "what is insecure in the deployed surface":
missing HSTS, legacy TLS, vulnerable packages, debug/detailed-errors leaking into
production, dev signing credentials. Today none of this is covered, and the honest
coverage map should say so (`NO-TOOL: skipped`) rather than pretend. The cheap,
charter-compliant fix is to add security tools to the fleet, not to write one.

## Scope

### v0.1 — the fleet (external tools only, no own detectors)

| Concern | Tool | Output |
|---|---|---|
| Web baseline (headers, exposures, known CVE templates) | Nuclei (`-sarif-export`) | SARIF native |
| Safe passive web scan (spider + passive rules, no attacks) | OWASP ZAP baseline | raw → adapter |
| TLS/SSL protocols, ciphers, crypto flaws | testssl.sh (JSON output) | raw → adapter |
| Dependencies, container images, IaC misconfig, secrets | Trivy (`--format sarif`) | SARIF native |
| .NET package vulnerabilities (incl. transitive) | `dotnet list package --vulnerable --include-transitive` | raw → adapter |

Deliverables:

- `audit/security/profiles/*.yaml` — run manifests (see Sketch), e.g.
  `baseline-web`, `tls`, `supply-chain`, `dotnet-config` (the last lands in v0.2).
- `audit/security/adapters/` — thin `raw → SARIF` converters for tools without
  native SARIF, same shape as the existing static-layer adapters.
- Findings enter the **existing** aggregation: normalize → score → report. No
  separate security report pipeline.
- Coverage map rows per category: `CHECKED` (tool ran), `SKIPPED` (no reliable
  tool), `NEEDS-RUNTIME` (target must be running/reachable), `NEEDS-AUTH`
  (credentialed scan not configured). Honest skip extends to security verbatim.

### v0.2 — `OwnAudit.DotNetConfig` (the one place own code is justified)

The single niche no mature tool covers well: **typed** .NET configuration audit.
Inputs: `web.config`, `app.config`, `appsettings*.json`, `launchSettings.json`,
`*.csproj`, `packages.config`, Kestrel/IIS hosting config where available.

Candidate checks (each ships with confidence + limitations, per finding):

- ASP.NET `compilation debug="true"` / detailed errors (`customErrors`) exposed
- cookie policy: missing `Secure` / `HttpOnly` / unsafe `SameSite` defaults
- DataProtection keys ephemeral in production; weak or hardcoded `machineKey`
- `AllowedHosts` wildcard in production profiles
- IdentityServer dev signing credential (`AddDeveloperSigningCredential`) outside dev
- forwarded-headers misconfiguration behind a proxy
- HTTPS redirection / HSTS absent in production profile

Discipline (non-negotiable, mirrors the core's culture):

1. **No regex-first rules.** XML via an XML parser, JSON via a JSON parser,
   `csproj` via MSBuild APIs or a resilient XML model.
2. Where production context cannot be proven (which `appsettings.*.json` wins,
   what the environment is), the finding is `needs-review`, never `high`.
3. Output is SARIF only; findings carry confidence and a limitations note.
4. No reliable signal ⇒ `NO-TOOL / skipped`, not a guess.
5. Test fixtures: paired good/bad configs (`web.config`, `appsettings.json`,
   IdentityServer setup) gating every rule in CI.

### v0.3 — cross-tool correlation

Direct reuse of the oracle pattern: ZAP **and** Nuclei both flag a header issue ⇒
confidence up; Trivy **and** `dotnet list package` both flag a package ⇒
confidence up; a single noisy tool ⇒ candidate / needs-review. No new machinery —
this is the existing cross-tool-agreement scorer fed with security findings.

## Non-goals

The most important section. None of the following will be built, and future
proposals re-introducing them should cite this section and explain what changed:

- an own YAML **detection** DSL (request/expect/matchers) or its interpreter
- an own HTTP/TLS/SSH/DB scanner or probe modules
- an own CVE-check corpus (that is Nuclei templates / Trivy DBs / GVM feeds)
- export or conversion of checks to NASL / OpenVAS / Nessus plugin formats
- regex heuristics as a primary detection mechanism anywhere in the profile
- active/attacking scans; the web pass stays at ZAP *baseline* (passive) and
  Nuclei templates vetted as non-intrusive
- scanning targets outside an explicit, configured allowlist (authorization is a
  precondition, and profiles must name their targets; nothing scans "the network")

## Sketch

A profile entry is a **tool-run manifest** — it says *what to run and how to file
the results*, never how to detect:

```yaml
id: OWNSEC-WEB-001
title: Web security baseline
tool: nuclei
target: web
sarifCategory: security/nuclei/web-baseline
command:
  executable: nuclei
  args:
    - "-l"
    - "targets/web.txt"
    - "-t"
    - "audit/security/nuclei-templates/"
    - "-sarif-export"
    - "artifacts/security/nuclei-web.sarif"
confidence:
  source: tool-native
  fpPolicy: external-tool
```

The contrast that keeps the design honest:

| Rejected (engine) | Adopted (profile) |
|---|---|
| `match regex: OpenSSL 1\.0\.` | run testssl.sh, adapt findings |
| `expect header: Strict-Transport-Security` | run Nuclei/ZAP baseline, accept tool finding |
| own YAML request/matcher DSL | Nuclei templates (write *templates*, not an engine) |
| own HTTP/SSH/DB runner | external tools + adapters |
| own severity model | tool severity + cross-tool confidence |
| "regex said something" | `NO-TOOL: skipped` |

Layout (inside the audit subtree, liftable with it):

```text
audit/security/
  profiles/          # run manifests: baseline-web, tls, supply-chain, dotnet-config
  nuclei-templates/  # own *templates* for the external engine, if any
  adapters/          # zap_to_sarif, testssl_to_sarif, dotnet_vuln_to_sarif
  tools/             # run_security_profile entrypoint
  docs/
```

Tool versions are pinned and printed in the report header, findings are
reproducible per commit — same as the rest of the fleet.

## Open questions

- **Where does v0.2 code live?** `OwnAudit.DotNetConfig` as a .NET project vs. a
  Python typed-parser module in the aggregation layer. The .NET route gets MSBuild
  APIs for free; the Python route keeps the audit subtree dependency-free. Decide
  at v0.2 start, not before.
- **Nuclei template curation.** Which subset of community templates is
  non-intrusive enough for the default profile, and who reviews additions.
- **Target declaration.** Format for the scan allowlist (`targets/*.txt` vs. a
  section in the profile) and how CI proves the target is a lab/staging host, not
  production, before running network tools.
- **Licensing hygiene.** All fleet tools are consumed as external executables
  (Nuclei MIT, Trivy Apache-2.0, testssl.sh GPLv2, ZAP Apache-2.0) — GPL tools are
  invoked, never linked, matching how GPL analyzers are already handled.
- **Consolidation timing.** Whether v0.1 lands in `OwnAudit` first (current live
  audit repo) and rides the deferred consolidation back into `audit/`, or waits
  for consolidation. Default: follow wherever the static-layer fleet lives at
  implementation time.
