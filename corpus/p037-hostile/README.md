# `corpus/p037-hostile` — the generated hostile census for the completeness oracle

P-037 A2.2-4. Every file under `cases/` and the whole of `expected.json` are
written by `scripts/p037_hostile_census.py generate`; do not edit them by hand
(`tests/test_p037_hostile_census.py` fails when the committed files differ
from a regeneration). The oracle is `frontend/roslyn/OwnSharp.Oracle`; the
driver that runs the extractor and the oracle over this census and holds the
result to `expected.json` is `scripts/p037_completeness_oracle.py check`.

## What a case is

One self-contained program (`static class H_<case>`) with one method `M`
(or, for the member-kind cases, the member named by `member_override`) and
the helpers it needs. `expected.json` records for every case its **designed**
classification, derived from the frozen taxonomy
(`corpus/p037-relevance/registry.json`, `docs/notes/p037-formal-kernel.md`
§10.6), never from a run:

- `occurrences` — the universe occurrences of the method in source order, each
  with the verdict the taxonomy assigns: `captured` (site kind, declared
  ordinal, representation `var` / `param` / `opaque`, enclosing
  `nested_call_result` calls) or `excluded` (by exactly one of the frozen
  names), or, for a vocabulary edge, the RED the sentence's letter demands;
- `carrier` — where production must deliver the member's record:
  `functions`, `guarded_functions` (the orphan carrier) or `none` (nothing
  admitted and no fact to carry);
- `red` and `finding` — for a case that witnesses a classified finding, the
  exact RED kinds and counts the oracle must raise and the finding's id in
  `corpus/p037-relevance/oracle_findings.json`. An unexpected RED fails; so
  does an expected RED that stops appearing.

## Coverage

Four factors, covered **pairwise** under C#'s feasibility constraints (every
value of each factor meets every value of every other at least once; the
greedy covering is deterministic):

| factor | values |
|---|---|
| site form | `inv` static invocation · `ext` reduced extension receiver · `ctor` object creation · `del` delegate invocation |
| value-flow | the 22 argument shapes of the relevance probe: bare, parenthesized, `!`, identity / upcast / checked cast, `as` upcast, `as` may-fail, `?:`, `??`, switch expression, implicit and explicit user conversion, boxing, nested call, tuple, array, collection, closure, method group, `nameof`, member access |
| binding | positional · named and reordered · expanded `params` element · `ref` · omitted optional argument |
| carrier admission | `record_local` (a tracked local admits) · `record_param` (an owned parameter admits) · `orphan_local` (every candidate escapes through a field store) · `unmodelled_local` / `unmodelled_param` (`lock`, the legacy pass's unmodelled construct) |

plus the named cases:

- the compositions the A2.2-4 GO asked for by name (`comp-*`): parentheses
  around a user conversion, a may-value arm through a user conversion, a named
  argument under a transparent wrapper, a constructor with `params`, a
  delegate with named arguments, an orphan method with a direct flow, a nested
  call with a transparent inner argument;
- the shadowing witnesses (`shadow-*`): the same spelling in sibling scopes
  (both orders), a lambda-local creation beside an unrelated local of the same
  spelling, and the GO's literal `Stream r = …; { Stream r2 = …; Sink(r2); }`;
- the member kinds the legacy pass never visits (`member-*`): an
  expression-bodied method, a struct method, a record method, a property
  accessor, and a declared local function (the known, counted gap);
- two receiver forms (`ext-*`): a reduced extension through `?.`, and a
  struct handle boxed into an `object` receiver;
- three constructor-initializer sites (`ctorinit-*`, `vocab-constructor-initializer`):
  a direct forwarding, named and reordered arguments under a reference
  upcast, and a nested call whose result the initializer receives;
- the argument shapes the frozen vocabulary had no name for (`vocab-*`): a
  tested operand, an interpolation hole and an indexer argument, named by the
  A2.2-4R4 ruling (`predicate_result`, `interpolation_hole`,
  `indexer_argument`), and a constructor-initializer argument, a call-like
  fact shape since A2.2-4R5 (`call_kind: constructor_initializer`).

The findings these witness are classified in
`corpus/p037-relevance/oracle_findings.json`; each stays RED, by name, until a
ruling or a separately classified change closes it.
