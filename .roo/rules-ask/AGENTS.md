# Project Documentation Rules (Non-Obvious Only)

- The current OwnLang grammar lives in the `ownlang/parser.py` docstring; `spec/` is normative for behavior examples, while `docs/proposals/` is forward-looking.
- `frontend/roslyn/OwnSharp.Extractor` is only the C# fact extractor; the user-facing check command is `scripts/own-check.*`, and explanations live in `python -m ownlang explain`.
- `frontend/ownts` is a heuristic React spike, not a TypeScript analyzer; EFF001 is decided by the core lattice in `ownlang/effects.py`.
- `case.own` files in corpus folders are often hand reductions; paired `before.cs`/`after.cs` files are the real C# scenarios used by extractor/benchmark jobs.
- `audit/` is a liftable, older base; its README points current audit work to the separate OwnAudit repo, so avoid presenting it as the live source of truth.
- For structural code questions, existing Cursor rules prefer CodeGraph MCP if available; do not re-grep symbol/caller questions when the index can answer them.
