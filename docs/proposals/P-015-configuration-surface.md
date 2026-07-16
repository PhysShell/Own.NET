# P-015 — Configuration surface: check selection & per-category severity

- **Status:** draft — but a **first minimal slice has shipped** (via P-035, PR #284):
  an **explicit `own-check --config own.toml`** (no auto-discovery) that reads **only**
  the `[weak-subscription].subscribe` table, in **TOML** (`ownlang/config.py`,
  `tomllib`; a malformed config is a hard error). Everything else below —
  auto-discovery, per-category enable/severity, per-path overrides, env — remains
  **deferred**. The format question is therefore **settled: TOML.**
- **Origin:** [P-014](P-014-semantic-resolution.md) Open Question 2. P-014 ships a
  single `--event-leaks` gate as *instance #1* of the need this proposal generalises.
- **Depends on / reconciles with:**
  - [P-013](P-013-distribution-surface.md) — the existing surface (`--format`,
    `--severity`) and the **"one checker"** discipline: the Python core is the
    single source of truth, wrappers stay thin, exactly one place decides what a
    finding says (P-013:19-21, 45-46). Config must not become a second decider.
  - [P-004](P-004-wpf-lifetime-profile.md) — `[OwnIgnore("reason")]` (P-004:60-61):
    inline, per-site suppression. This proposal is its project-wide counterpart;
    the two must compose, not collide.
  - `spec/CLI.md` (the CLI contract), `ownlang/ownir.py` (renderer + the
    `Severity` model, diagnostics.py:28-30).

## Motivation

A flag per check does not scale. P-014 already needs `--event-leaks`; the
disposable/pool/local-disposable detectors will each want the same on/off and
severity control; a real codebase wants *"treat subscriptions as warnings, keep
disposables as errors, skip pool checks in tests/"*. Every linter solved this with
a **config file** (`.eslintrc`, `ruff.toml`, `.editorconfig`, `rustfmt.toml`), not
a growing flag list. Own.NET should follow the convention rather than accreting
one `--no-X` flag per check.

The honest-skip philosophy (ROADMAP.md:49-51) makes this load-bearing, not
cosmetic: until a check is trustworthy (cf. P-014's event rule before Tier A), the
*right* state is "off" — and that state should be expressible per-project, in one
place, under version control, not buried in CI invocation strings.

## Scope (draft)

A discovered config file — working name `.ownrc` / `own.toml` (format TBD, see
Open questions) — that controls, per **check category**:

- **enabled / disabled** (the generalised `--event-leaks` gate);
- **severity** (`error` / `warning` / `off`), per category, overriding the global
  `--severity` default;
- optionally **per-path overrides** (globs, e.g. relax a category under `tests/`),
  à la `.editorconfig` / ruff `[per-file-ignores]`.

Check categories map to the resource kinds the extractor already emits —
`subscription` / `subscribe` / `timer` / `disposable` / `local-disposable` /
`pool` — plus, later, the core OWN0NN families. The category vocabulary should be a
small, documented, stable set.

Discovery: nearest config walking up from the scanned path (the
`.editorconfig`/ruff model), with CLI flags overriding the file.

## Where it is enforced (the "one checker" constraint)

Per P-013, the verdict authority is the **core**. So config that changes a verdict
(severity, on/off) is consumed in the core (`ownlang`), in one place — *not* split
across the wrappers, and *not* a second checker. Precedence (draft):

```
CLI flag  >  inline [OwnIgnore]  >  config file  >  built-in default
```

The extractor *may* skip emitting facts for a disabled category as an optimisation,
but the authoritative selection is core-side so there is one place that decides.

This collides with one known plumbing fact (from P-014): `check_facts()` drops
every diagnostic whose `severity != Severity.ERROR` (ownir.py:326-329), and the
`Severity` enum is only `ERROR`/`WARNING` (diagnostics.py:28-30). So:

- `off` → don't emit the finding;
- `warning` → emit but advisory — needs the filter-bypassing path P-014 already
  introduces for OWN050 (`_di_findings`-style, ownir.py:377), or a widening of the
  `check_facts` filter;
- `error` → the existing path.

Whether to widen the filter or route everything advisory through the bypass path
is the central implementation question.

## Non-goals (draft)

- **Per-rule fine-grained config** beyond the category level (initially). Start
  with categories; finer granularity is bug-driven later.
- **A query/policy language.** It is a settings file, not a DSL.
- **Editor integration / live config** — that is [P-011](P-011-editor-tooling.md).
- **Changing the OwnIR fact contract.** Config is a driver/presentation concern;
  it adds no fact and needs no `ownir_version` bump.

## Relationship to the spec & docs (anti-drift)

- **Normative `spec/` core is untouched** — config selects/relabels findings, it
  does not change the ownership semantics or the OwnIR vocabulary. The one doc that
  grows is `spec/CLI.md` (the CLI/driver contract), plus a new section or doc
  describing the config schema *when built* (spec follows code).
- The `Severity` model may gain an explicit `off`/advisory handling; if a third
  severity tier is ever introduced it lands in `diagnostics.py` + `spec/Diagnostics.md`
  — but the draft above avoids that by treating `off` as non-emission and `warning`
  via the existing bypass path.

## Open questions

1. **File format — RESOLVED: TOML.** Shipped as `own.toml` (`tomllib`) in the P-035
   slice; not reopening INI/JSON.
2. **Discovery & precedence.** The shipped slice is **explicit `--config PATH` only**
   (no discovery), so nearest-file-up walking and CLI/`[OwnIgnore]` precedence remain
   open for when a broader surface lands.
3. **Enforcement point.** Core-side only (clean "one checker") vs extractor-side
   skip for disabled categories (cheaper) — likely both, with the core
   authoritative.
4. **Severity plumbing.** Widen the `check_facts` `ERROR`-only filter, or route all
   advisory findings through the OWN050/`_di_findings` bypass path? (Shared
   question with P-014.)
5. **Category vocabulary.** Lock the stable category names (resource kinds today;
   how do core OWN0NN families map in?).
6. **Overlap with P-013.** `--severity` is a *global* presentation default;
   per-category severity here supersedes it. Confirm the two compose cleanly and
   document the single precedence story.
