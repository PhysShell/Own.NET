# P-032 — Own.Arch facts & intent model

- **Status:** draft. Imported from a design discussion and normalized into the
  proposal series (the pasted original self-titled itself P-027; renumbered here).
- **Extends:** [P-023 — Architecture guard](P-023-architecture-guard.md) — this
  proposal deepens P-023's intent-model/drift design into a fact-extraction core.

## Summary

Introduce `Own.Arch` as the Own.NET-side architecture analysis core: a deterministic extractor and evaluator for architecture facts, intent models, and rule packs.

This proposal is intentionally scoped to Own.NET. Own.NET should not become the full audit dashboard, PR gate, or agent runner. Its job is to produce reliable architecture facts and deterministic findings that other projects can consume.

Own.NET owns:

- project graph extraction;
- package/reference extraction;
- later Roslyn/type-level dependency extraction;
- architecture intent model schema;
- deterministic rule evaluation;
- stable finding fingerprints;
- generated architecture artifacts such as graph JSON and optional diagrams.

OwnAudit consumes these outputs for reporting, baseline, drift, SARIF, and dashboards.

007 consumes these outputs indirectly through typed refactoring tasks and gates.

## Existing groundwork

This builds directly on the existing "P-023 — Architecture guard (Own.Arch)" proposal. P-023 already defines the key architecture: hand-written intent model, extracted actual dependency graph, and drift as "actual - allowed"; it also explicitly says PRs should fail only on new architectural dependency violations, while existing debt is baselined and ratcheted.

P-023 already scopes the MVP to project-level dependency checks over `.sln`, `.csproj`, `ProjectReference`, `PackageReference`, and `packages.config`, with rules such as forbidden project edges, forbidden packages per layer, unmapped projects, and unused allowed edges.

P-023 also already sketches Phase 2 as type-level facts using IL/Roslyn to catch type dependencies, forbidden APIs, and namespace-level cycles.

Related proposals:

- [Agentic coding discipline proposal](../agentic-coding-discipline-proposal.md)
  introduces disciplined agentic coding ideas for Own.NET/OwnAudit/007, including task contracts, diff policy gates, agent-readable invariants, and analyzer rule catalogs.

- [P-031 — Project resource model files](P-031-resource-model-files.md)
  proposes declarative per-project resource model files (`own.models.yaml`) for acquire/release/capture conventions. It is not an architecture model, but it is useful prior art for project-local declarative models resolved through the semantic layer.

## Problem

Own.NET already has strong ambitions around ownership, resources, WPF lifetime diagnostics, Roslyn extraction, and analyzer rules. The missing architecture piece is not “draw a diagram”. The missing piece is a stable fact model that can answer:

- which projects belong to which architectural layer;
- which references cross forbidden boundaries;
- which packages are forbidden in a layer;
- which namespaces/types depend on presentation, persistence, SQL, DevExpress, or other sensitive APIs;
- which intended dependencies are unused and probably stale;
- which violations are new versus old debt.

Without a deterministic architecture fact layer, any high-level architecture review becomes subjective prose. That is useless as a gate. A gate needs facts, fingerprints, and evidence.

## Non-goals

Own.NET should not own:

- PR dashboards;
- long-term trend history;
- SARIF publishing to GitHub;
- AI-generated refactoring patches;
- 007 run records;
- runtime heap correlation;
- hand-maintained C4 diagrams as source of truth.

Own.NET may generate diagrams from the intent model and graph, but diagrams must be artifacts, not the canonical architecture model.

## Proposed design

Introduce a small `Own.Arch` subsystem:

```text
.sln/.csproj/packages.config
        ↓
project/package extractor
        ↓
arch-facts.json

architecture.intent.json
        ↓
rule evaluator
        ↓
arch-findings.json
        ↓
optional generated artifacts:
  - arch-report.md
  - architecture.mmd
  - structurizr.dsl
```

Phase 2 adds:

```text
compiled solution / Roslyn workspace / IL
        ↓
type dependency extractor
        ↓
type-level arch-facts.json
```

## Architecture intent model

Use JSON for the MVP, because OwnAudit already uses stdlib-only Python and existing "arch/rules.json" is JSON. YAML can be added later as an authoring format if needed.

Example:

```json
{
  "schema": "own.arch.intent/v1",
  "architecture": {
    "name": "STS Broker",
    "style": ["layered", "modular-monolith", "hexagonal-boundaries"]
  },
  "layers": [
    {
      "name": "Presentation",
      "matches": ["*.UI.*", "*.Wpf.*", "*.ViewModels.*"],
      "mayDependOn": ["Application", "DomainAbstractions"]
    },
    {
      "name": "Application",
      "matches": ["*.Application.*", "*.Services.*"],
      "mayDependOn": ["Domain", "DomainAbstractions"]
    },
    {
      "name": "Domain",
      "matches": ["*.Domain.*", "*.Core.*"],
      "mayDependOn": ["DomainAbstractions"],
      "forbiddenApis": ["System.Windows.*", "System.Data.*", "DevExpress.*"]
    },
    {
      "name": "Infrastructure",
      "matches": ["*.Infrastructure.*", "*.DataAccess.*"],
      "mayDependOn": ["Domain", "DomainAbstractions"]
    }
  ],
  "forbiddenPackages": {
    "Domain": [
      "System.Data.SqlClient",
      "Microsoft.Data.SqlClient",
      "DevExpress*",
      "PresentationFramework"
    ],
    "Application": [
      "DevExpress*",
      "PresentationFramework"
    ]
  }
}
```

## Finding codes

MVP deterministic rules:

```text
ARCH001: ProjectReference crosses a forbidden layer boundary.
ARCH002: Forbidden package is referenced from a layer.
ARCH003: Project matches zero or multiple layers.
ARCH004: Forbidden direct framework/API reference at project level.
ARCH030: Allowed dependency is declared but unused.
```

Phase 2 rules:

```text
ARCH010: Type-level dependency crosses a forbidden layer boundary.
ARCH011: Forbidden API is used in a layer.
ARCH012: Namespace-level dependency cycle.
ARCH013: Type-level dependency on forbidden framework namespace.
```

Phase 3 heuristic/report-only rules:

```text
ARCH020: Type has excessive fan-out.
ARCH021: Type mixes APIs from unrelated layers.
ARCH022: Interface has too many members.
ARCH023: Component behaves as unstable hub.
```

Important: deterministic findings may gate. Heuristic findings are report-only until proven reliable on the project corpus.

## Fingerprint policy

Every deterministic architecture finding must have a stable fingerprint:

```text
sha256(rule_id | normalized_from_symbol | normalized_to_symbol | normalized_target_kind)
```

Do not include file path or line number in the primary fingerprint. File paths and line numbers are evidence, not identity.

This prevents baseline churn during refactors while still catching newly introduced architectural edges.

## CLI sketch

```bash
own-arch extract-projects \
  --solution Broker.sln \
  --out arch-facts.project.json

own-arch evaluate \
  --facts arch-facts.project.json \
  --intent architecture.intent.json \
  --out arch-findings.json \
  --report arch-report.md

own-arch render \
  --intent architecture.intent.json \
  --facts arch-facts.project.json \
  --format mermaid \
  --out architecture.mmd
```

Phase 2:

```bash
own-arch extract-types \
  --solution Broker.sln \
  --configuration Release \
  --out arch-facts.types.json
```

## Output contracts

"arch-facts.project.json":

```json
{
  "schema": "own.arch.facts.project/v1",
  "projects": [
    {
      "name": "Broker.Presentation",
      "path": "src/Broker.Presentation/Broker.Presentation.csproj",
      "targetFrameworks": ["net472"],
      "projectReferences": ["Broker.Application"],
      "packageReferences": ["DevExpress.Xpf"],
      "layer": "Presentation"
    }
  ],
  "edges": [
    {
      "from": "Broker.Presentation",
      "to": "Broker.Application",
      "kind": "ProjectReference"
    }
  ]
}
```

"arch-findings.json":

```json
{
  "schema": "own.findings/v1",
  "tool": "own-arch",
  "findings": [
    {
      "rule": "ARCH001",
      "severity": "error",
      "category": "architecture",
      "resource": "Broker.Presentation",
      "message": "Presentation depends on Infrastructure directly",
      "fingerprint": "sha256:...",
      "evidence": [
        {
          "kind": "ProjectReference",
          "from": "Broker.Presentation",
          "to": "Broker.Infrastructure",
          "path": "src/Broker.Presentation/Broker.Presentation.csproj"
        }
      ]
    }
  ]
}
```

## Integration with OwnAudit

Own.NET produces:

- "arch-facts.project.json";
- "arch-facts.types.json";
- "arch-findings.json";
- optional generated diagrams/reports.

OwnAudit consumes these artifacts for:

- SARIF export;
- baseline/diff;
- PR drift report;
- dashboards;
- health scoring.

Own.NET should not duplicate OwnAudit’s baseline/diff/reporting layer.

## Integration with 007

007 should consume Own.Arch through task specs, not through direct architecture logic.

Example 007 task target:

```yaml
task_id: ownarch.fix.arch001.ui-sql
target_repo: Own.NET
input:
  findings: artifacts/arch-findings.json
  selector:
    rule: ARCH001
    rank: 1
constraints:
  max_files_changed: 5
  require_tests: true
  require_reaudit: true
  forbid_baseline_update_without_reason: true
gates:
  required:
    - own-arch-evaluate
    - no-new-arch-findings
```

## Acceptance criteria

MVP is accepted when:

1. "own-arch extract-projects" can read a solution/project set and emit "arch-facts.project.json".
2. "own-arch evaluate" can detect forbidden project edges, forbidden packages, and unmapped projects.
3. Findings use stable fingerprints.
4. Existing violations can be consumed by OwnAudit baseline/diff without schema translation hacks.
5. Generated markdown report includes evidence for every finding.
6. A simple Mermaid or Structurizr artifact can be generated from the intent model, but is not source of truth.
7. Tests cover:
   - valid layered graph;
   - forbidden Presentation → Infrastructure edge;
   - Domain package pollution;
   - unmapped project;
   - multi-mapped project;
   - unused allowed dependency.

## Risks

### Risk: Own.Arch becomes a second NDepend clone

Mitigation: keep scope narrow. Own.Arch detects architecture dependency facts, not every possible code smell.

### Risk: false confidence from inferred architecture style

Mitigation: style inference must be report-only. Gates rely on deterministic facts.

### Risk: duplicate rule languages

Mitigation: one intent schema. Generated ArchUnitNET, NetArchTest, C4, Mermaid, or Structurizr outputs are optional render targets, not alternative sources of truth.

## First implementation slice

Implement only:

```text
architecture.intent.json
project graph extraction
ARCH001
ARCH002
ARCH003
arch-findings.json
arch-report.md
tests
```

Everything else waits. The first slice should be boring, deterministic, and hard to misinterpret.