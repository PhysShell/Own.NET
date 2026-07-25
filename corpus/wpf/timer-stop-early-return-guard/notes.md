# WPF002 twin: a Stop() behind an early-return parameter guard (soundness FN, #305 attack A)

The timer twin of `subscription-teardown-early-return-guard` — `.Stop()` rides
the same teardown/guard predicate as the `-=` ("one predicate, one context
model"), so the early-return hole applied verbatim: `if (keepTicking) return;
_timer.Stop();` was credited while `if (!keepTicking) { _timer.Stop(); }` was
demoted (`timer-stop-param-guarded`).

Fixed together with the subscription case by `IsParamGuardedByEarlyReturn`
(shared predicate — both release kinds inherit the rule): a `return` lexically
preceding the release site, guarded by a parameter of the enclosing callable,
demotes; the canonical inverted disposing exit (`if (!disposing) return;`)
stays credited. Full attack record:
`docs/notes/teardown-predicate-adversarial-audit.md`.
