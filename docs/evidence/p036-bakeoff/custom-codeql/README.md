# Bakeoff-written CodeQL queries (expressiveness probe — NOT stock CodeQL)

Two queries written during the P-036 bakeoff (2026-09-17) to answer "what would
a CodeQL user have to write to get the subscription-leak class at all?":

- `SubscriptionNeverRemoved.ql` — the naive, pre-#278 Owen rule: a `+=` on
  another object's event with no matching `-=` anywhere in the class.
- `SubscriptionNotReleasedInTeardown.ql` — a bounded port of the landed
  #293/#305 extractor predicate (teardown roots by name, handlers wired to the
  class's own lifecycle events, intra-class transitive calls, parameter-guard
  demotion with the canonical `if (disposing)` exemption and the early-return
  refinement). Deliberately no argument-value reasoning, no enrollment, no
  exceptional-path reasoning — exactly the ceiling of the current predicate.

Results from these queries are scored `DETECTED_CUSTOM_QUERY` /
`FALSE_POSITIVE_CUSTOM_QUERY` and never as stock detections
(`docs/notes/p036-bakeoff.md` §0.5). Run with
`scripts/p036_bakeoff.py --custom-queries docs/evidence/p036-bakeoff/custom-codeql`
after the main pass has built the CodeQL 2.27 databases.
