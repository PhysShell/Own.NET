# Marketplace consumer-simulation fixture

This directory stands in for "a repo that installs the Own.NET GitHub
Action" — deliberately small, deliberately *not* part of
`frontend/roslyn/samples` (Own.NET's own extractor precision-test corpus,
which mixes many deliberate positive/negative cases and is not
representative of an ordinary consumer's code).

Used by `.github/workflows/action-marketplace-readiness.yml`'s
`consumer-simulation` job, which references the action the way a real
external repository would — `uses: PhysShell/Own.NET@<ref>` (resolved by
the Actions runner's own action-fetch mechanism, not `uses: ./`) — against
a sparse checkout containing *only* this directory, so the job's own
workspace does not have the rest of Own.NET's source on disk either.

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
