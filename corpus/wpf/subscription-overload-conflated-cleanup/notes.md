# Subscription whose only `-=` is in an uncalled overload of a teardown helper (soundness FN)

**Pattern (#278 follow-up, blocker 3).** `Dispose()` calls `Cleanup()` — the
no-argument overload, which detaches nothing. The matching `-=` lives only in
`Cleanup(bool)`, which no teardown path (and nothing else in the class) calls.

**The bug.** The first #278 slice keyed its intra-class teardown closure by
SIMPLE METHOD NAME: "Dispose calls *Cleanup*" marked every method named
`Cleanup` as a teardown context, so the `-=` inside the uncalled `Cleanup(bool)`
was silently credited as released — overload conflation as a silent-exemption
path.

**The fix.** The closure is SYMBOL-based (`IMethodSymbol` +
`SymbolEqualityComparer`): an invocation extends the teardown set only with the
specific method it RESOLVES to. `Dispose() => Cleanup();` credits exactly
`Cleanup()`; `Cleanup(bool)` stays outside the set and its `-=` grounds
nothing. An invocation that fails to resolve extends nothing — the worst case
stays "keeps today's honest warning". `before.cs` is OWN001; `after.cs` moves
the `-=` into the overload Dispose actually calls and is silent.

(The method-GROUP name fallback used for wiring handlers to an unresolved
lifecycle event — see `subscription-xaml-name-only-release/notes.md` — is
distinct by construction: a method group carries no argument list, so its name
denotes the whole overload set; an invocation selects exactly one target and
must be resolved to it.)

**What the checker says (`.own` reduction).** The scope acquires the token and
the called teardown path performs no release => **OWN001** with the
subscription-token resource tag.

**Regression guard.** `scripts/benchmark.py`: `before.cs` must be **caught**,
`after.cs` must be **silent**.
