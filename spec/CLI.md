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
