# CLI

> **Status: normative, descriptive.** Source of truth: `ownlang/__main__.py`.
> Run as `python -m ownlang <command> <file.own>`.

| Command | Does | Exit |
|---|---|---|
| `check` | runs the full checker (policies + lifetimes + per-fn loans/permissions), prints rustc-style diagnostics | non-zero if any **error** |
| `emit`  | prints the generated C# (or an honest `CodegenError` if unsupported, see [CodegenContract §C2](CodegenContract.md)) | non-zero on error |
| `cfg`   | prints the control-flow graph (blocks + instructions) for inspection | — |
| `report`| prints the compile-time buffer report and writes `*.ownreport.json` | — |

Notes:
- `check`'s non-zero exit on errors is what makes it usable as a CI gate.
- Diagnostics are sorted by `(line, code)`; rendering is rustc-style
  (`file:line:col`, source line, caret) with a `[resource: <kind>]` suffix when
  the finding is about a kind-tagged resource.
- A parse/lex failure surfaces as a single **OWN020** at the offending line.
