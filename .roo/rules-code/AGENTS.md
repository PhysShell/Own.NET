# Project Coding Rules (Non-Obvious Only)

- Keep the “one checker” boundary: Roslyn/OwnTS extract facts; Python core modules decide OWN/WPF/DI/EFF findings.
- OwnLang tests need explicit local/`extern fn` signatures for every call, because unknown calls intentionally raise OWN040.
- When adding AST/CFG instruction shapes, update the `assert_never` exhaustiveness sites in `ownlang/cfg.py`, `ownlang/analysis.py`, and `ownlang/codegen.py`.
- Preserve the RID/handle split in `analysis.State`: loans are keyed by resource id so aliases see the same borrow/release obligation.
- Codegen’s try/finally hoist is only for straight-line, laminar lifetimes with top-level releases; branchy or ownership-transfer cases must remain faithful inline cleanup.
- Buffer cleanup follows original backing variables across moves; reports intentionally skip malformed buffer modes and let checker diagnostics stand.
- OwnIR version bumps are for incompatible fact vocabulary changes only; additive metadata fields should remain backward-tolerant.
- Do not import `ownlang` from `audit/`; that subtree is designed to lift out and may reuse only CLI/SARIF seams.
