# Project Debug Rules (Non-Obvious Only)

- `python -m ownlang cfg <file.own>` is the fastest way to inspect resolver/lowering output before debugging dataflow.
- `python -m ownlang report <file.own>` writes `<file>.ownreport.json` beside the source and can still surface checker diagnostics on stderr.
- OwnIR bad facts are usage/contract errors: `python -m ownlang ownir facts.json` exits 2 with a one-line message instead of a traceback.
- For machine formats (`github`, `msbuild`, `sarif`), OwnIR diagnostics go to stdout and summaries go to stderr; do not mix those streams in parsers.
- Use `--verbosity verbose` on `python -m ownlang ownir` to get per-code counts; `quiet` hides advisory OWN050 notes.
- In `own-check.sh`, dotnet build/run chatter is redirected to stderr so stdout remains host-parseable findings.
- `own-check.sh --stats` requires the default flow-local path (`--legacy` makes the stats meaningless and is rejected by the extractor).
- If Roslyn reports OWN050 for external events, check whether `.csproj`/`.sln` `bin/` refs exist or pass `--ref-dir`; `--no-project-refs` disables the auto-ref path.
