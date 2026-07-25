# WPF002 twin: a Stop() in the ELSE of the canonical `if (disposing)` (soundness FN, #305 attack B)

The timer twin of `subscription-disposing-else-branch-release` — `.Stop()`
rides the same teardown/guard predicate as the `-=`, so the else-branch hole
applied verbatim: a Stop() that executes only via `~Finalizer ->
Dispose(false)` was credited as a teardown release, while the finalizer itself
is a declared non-context.

Fixed together with the subscription case: the canonical positive-`disposing`
exemption now covers only a site on the POSITIVE side of the guard
(`SiteOnNegativeBranch`) — a release in the `else` demotes like any parameter
guard. The `if (disposing)` THEN-branch pattern (`after.cs`,
`timer-stop-param-guarded`-family shapes) stays credited unchanged. Full
attack record: `docs/notes/teardown-predicate-adversarial-audit.md`.
