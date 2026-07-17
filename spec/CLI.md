# CLI

> **Status: normative, descriptive.** Source of truth: `ownlang/__main__.py`.
> Run as `python -m ownlang <command> <file.own>`.

| Command | Does | Exit |
|---|---|---|
| `check` | runs the full checker (policies + lifetimes + per-fn loans/permissions), prints rustc-style diagnostics | non-zero if any **error** |
| `emit`  | prints the generated C# (or an honest `CodegenError` if unsupported, see [CodegenContract §C2](CodegenContract.md)) | non-zero on error |
| `cfg`   | prints the control-flow graph (blocks + instructions) for inspection | — |
| `report`| prints the compile-time buffer report and writes `*.ownreport.json` | — |
| `config`| reads an explicit `own.toml` and prints the declared P-035 `[weak-subscription].subscribe` names, one per line (the minimal P-015 config carrier). `python -m ownlang config <own.toml>` | non-zero on a **malformed** config (hard error) |
| `own-fix subscriptions candidates`| S0 (analysis-only): reads a `--fix-candidates` facts file and, for one **exact** `--class <FQN>`, emits a deterministic `candidates.json` — a selection-request safety envelope plus a candidate bundle per leaky subscription (line-independent `finding_id`, pinned `target_api`, `allowed_actions` = `convert_acquire` for a proven INotifyPropertyChanged contract else `manual_review`, per-file SHA-256). `python -m ownlang own-fix subscriptions candidates <facts.json> --config <own.toml> --class <FQN> [--finding-id <ID>]... --output <candidates.json> [--root <dir>]` | non-zero on a partial/nested/generated/unknown class, an unknown finding-id, an unpinnable target, or an unreadable source |
| `own-fix subscriptions verify-delta`| S2 step 10 (analyzer-semantic gate): binds the mandatory step 9 `gate-result.json`, then re-runs Own.NET's real core analyzer — from a **snapshotted** `ownlang` package in a fresh isolated `python -S -B -E` subprocess, the extractor from a snapshotted deployment on the pinned runtime — over the pristine preimage and the accepted step 8 postimage, and proves the OWN001 delta matches the plan (converted candidates gone, manual-review preserved, no new OWN001 of any resource lane, no new OWN050), publishing a byte-deterministic `delta-result.json`. OWN001-only (an OWN014 candidate is `ANALYSIS_SCOPE`); no `--config`. `python -m ownlang own-fix subscriptions verify-delta --bundle <step8-bundle> --plan <validated-plan.json> --candidates <candidates.json> --root <pristine-source-root> --gate <step9-gate-result.json> --extractor-dll <OwnSharp.Extractor.dll> --out <delta-evidence-dir> [--ref-dir <dir>]...` | non-zero (exit 2) on any refusal (stable category: `INPUT_LAYOUT`/`AUTHORITY_BINDING`/`GATE_BINDING`/`TOOLCHAIN_BINDING`/`ANALYSIS_SCOPE`/`BASELINE_ANALYSIS`/`POSTIMAGE_ANALYSIS`/`ANALYSIS_IDENTITY`/`DELTA_MISMATCH`/`NEW_OWN001`/`NEW_OWN050`/`IDEMPOTENCE`/`ISOLATION`/`PUBLICATION`/`INFRASTRUCTURE`), no partial output |
| `own-fix subscriptions verify-target`| S2 step 11 (fake-target gate): binds the mandatory step 10 `delta-result.json` and the step 8 bundle, then proves the wrapper the accepted postimage actually calls is a genuine non-retaining subscription — a fixed Roslyn `bind` (SemanticModel over the pristine preimage + accepted postimage; per-finding callsite bijection; the `plan.target_api.subscribe` shape resolved inside the selected reference-slot wrapper) followed by a fixed runtime `probe` (three fresh isolated children that load the derived wrapper from its exact materialized slot via a dedicated AssemblyLoadContext, run a runtime-compatibility preflight, then a frozen GC harness) proving the subscriber becomes GC-collectable after a subscribe-then-drop. A wrapper that retains the subscriber is a fake target (`TARGET_RETAINS`). A converted plan needs `--probe-dll`/`--wrapper-ordinal`; a manual-only plan forbids them (the six probe checks publish `not_applicable`). Publishes a byte-deterministic `target-result.json`. `python -m ownlang own-fix subscriptions verify-target --bundle <step8-bundle> --root <pristine-source-root> --plan <validated-plan.json> --candidates <candidates.json> --delta <step10-delta-result.json> --out <target-evidence-dir> [--probe-dll <OwnSharp.WeakTargetProbe.dll> --wrapper-ordinal <N>] [--ref-dir <dir>]...` | non-zero (exit 2) on any refusal (stable category: `INPUT_LAYOUT`/`AUTHORITY_BINDING`/`DELTA_BINDING`/`REFERENCE_BINDING`/`TOOLCHAIN_BINDING`/`CALLSITE_BINDING`/`WRAPPER_BINDING`/`WRAPPER_RUNTIME_UNSUPPORTED`/`HARNESS_INVALID`/`TARGET_BEHAVIOR`/`TARGET_RETAINS`/`HARNESS_NONDETERMINISM`/`ISOLATION`/`PUBLICATION`/`INFRASTRUCTURE`), no partial output |

Notes:
- `check`'s non-zero exit on errors is what makes it usable as a CI gate.
- **`own-check --config <own.toml>`** (the shell/Action wrapper, `scripts/own-check.sh`)
  reads the same file via `config` and forwards the declared weak-subscribe wrapper
  names to the Roslyn extractor (`--weak-subscribe "SimpleType.Method"`, internal
  transport), so a matching call is treated as an already-released subscription
  (P-035). The composite Action exposes it as the optional `config:` input. A malformed
  config is a hard error at every layer, never a silent skip.
- Diagnostics are sorted by `(line, code)`; rendering is rustc-style
  (`file:line:col`, source line, caret) with a `[resource: <kind>]` suffix when
  the finding is about a kind-tagged resource.
- A parse/lex failure surfaces as a single **OWN020** at the offending line.
