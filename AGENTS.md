# AGENTS.md

This file provides guidance to agents when working with code in this repository.

- Use the repository root for core commands: `python -m ownlang check|emit|cfg|report <file.own>`; `emit` deliberately refuses to generate C# when any diagnostic exists.
- Full zero-dependency regression is `python tests/run_tests.py`; single tests are standalone scripts such as `python tests/test_ownir.py`, not pytest tests.
- `tests/run_tests.py` imports the other test files and runs the codegen fuzzer with `(iterations=3000, seed=1234)`; run `python tests/test_codegen_props.py <iterations> <seed>` when changing codegen invariants.
- Lint gate is exactly `ruff check .` plus `mypy`; mypy is strict only for `ownlang`, while tests/fuzzers stay dynamic and are covered by ruff.
- Ruff intentionally omits SIM because branch-collapsing fights the commented checker/control-flow structure; do not simplify those branches just for style.
- The core pipeline is parser -> CFG resolver/lowering -> ownership/lifetime/effect/DI analyses -> diagnostics; Roslyn and OwnTS frontends emit facts only, and the Python core owns all verdicts.
- Unknown OwnLang calls are hard errors: add local/`extern fn` signatures with ownership effects instead of letting calls tunnel through opaque host code.
- Adding AST/CFG variants normally requires updating `assert_never` dispatch sites in `ownlang/cfg.py`, `ownlang/analysis.py`, and `ownlang/codegen.py`.
- Codegen has two intentional modes: straight-line, laminar lifetimes get try/finally hoisting; branchy/transferring code emits releases inline. Do not add runtime “released?” flags to paper over static mistakes.
- OwnIR schema is versioned in `ownlang/ownir.py`; additive optional fields like resource/type metadata are tolerated, incompatible vocabulary changes must fail loudly.
- For C# repo scans, `scripts/own-check.sh` is the Action/bash surface and defaults to `--flow-locals`; on Windows use `scripts\own-check.ps1` rather than requiring bash.
- The Roslyn extractor auto-adds built `bin/` refs for `.csproj`/`.sln` inputs unless `--no-project-refs`; unresolved external events become advisory OWN050, not guessed leaks.
- `audit/` must stay decoupled from `ownlang` and consumes `own-check` only through its CLI/SARIF; `audit/README.md` says active audit development currently lives in the separate OwnAudit repo.
- Existing Cursor guidance: if CodeGraph MCP tools are available, prefer them for structural symbol/caller/impact questions; use text search for literal strings and comments.
