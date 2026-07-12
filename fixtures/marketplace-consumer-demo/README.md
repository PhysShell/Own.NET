# Marketplace consumer-simulation fixture

This directory stands in for "a repo that installs the Owen GitHub
Action" (public display name "Owen lifetime/resource check" — public
facade rebrand, `docs/notes/owen-public-facade.md` / PR #246) —
deliberately small, deliberately *not* part of `frontend/roslyn/samples`
(Own.NET's own extractor precision-test corpus, which mixes many
deliberate positive/negative cases and is not representative of an
ordinary consumer's code).

Used by `.github/workflows/action-marketplace-readiness.yml`'s
`consumer-simulation` job, via `uses: ./` (GitHub Actions does not evaluate
expressions in `steps.uses`, so a dynamic `uses: PhysShell/Own.NET@<this
commit>` isn't achievable — see `docs/notes/action-marketplace-readiness.md`
for the full account). The meaningful difference from `ci.yml`'s own
`uses: ./` dog-food job is this fixture: small and consumer-shaped, not
Own.NET's own precision-test corpus.

- `Leaky.cs` — one intentional, unambiguous leak (`OWN001`): a
  `MemoryStream` local that is never disposed. Exists to prove the action
  actually finds something and annotates it, not just that it runs and
  exits cleanly.
- `Clean.cs` — the same shape, disposed correctly. Exists to prove the
  action does *not* fail a normal, correct file (no false alarm on the
  negative control).

This is an honest approximation, not a full substitute for a genuinely
separate consumer repository — a real external repo would additionally
prove the action resolves for a checkout with an entirely different git
remote/identity. That was not created here without explicit authorization
(creating a second public repository is a visible, user-facing action);
see `docs/notes/action-marketplace-readiness.md` for the tradeoff this
records.
