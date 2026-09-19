# `OwnSharp.Oracle` — the P-037 A2.2-4 completeness oracle

**Evidence infrastructure, not production.** The oracle never writes OwnIR,
shares no source with `OwnSharp.Extractor`, and nothing it computes leaks into
`facts.json`. It exists to check one frozen sentence
(`docs/notes/p037-formal-kernel.md` §10.6.1,
`corpus/p037-relevance/registry.json`):

> Completeness means every candidate occurrence at a call-related syntax site
> is either represented by the raw guarded-call vocabulary or assigned exactly
> one named exclusion. Occurrence alone does not establish ownership flow to
> the enclosing callee.

    dotnet run --project frontend/roslyn/OwnSharp.Oracle -- <inputs> --facts facts.json -o oracle.json

The driver `scripts/p037_completeness_oracle.py` builds both projects once,
runs the extractor and the oracle over every census input, and holds the
result to the findings ledger, the relevance probe and the hostile census.

## What it does

1. **Inventory.** For every member body in every type declaration (class,
   struct, record, interface; methods, constructors with their `: this` /
   `: base` initializer, a call-like site of its own since R5, operators,
   accessors, expression bodies included),
   every reference to a local or parameter of that member is inventoried by
   **Roslyn symbol**, never by spelling. References inside lambdas and local
   functions are inventoried too, flagged `nested_function`.
2. **Universe.** A symbol is a *candidate* — the frozen "disposable candidate
   local or owned parameter" — by one of five declared rules on symbols:
   `owned_parameter` (by-value, type implements `System.IDisposable`, not an
   optional-dispose type), `created_local` (a non-`using` local initialized by
   an object creation of such a type), `first_party_factory_local` (initialized
   by a call to a method declared in the compilation returning such a type),
   `bcl_file_factory_local` (`System.IO.File.OpenRead/OpenWrite/Open/Create/
   OpenText/CreateText/AppendText`) and `pool_rental_local`
   (`ArrayPool<T>.Rent`, `MemoryPool<T>.Rent`). The legacy pass's wider factory
   vocabulary (crypto, Xml, Json, ADO.NET) is deliberately not re-implemented:
   a fact on such a local is reported `outside_universe` with its initializer,
   counted, and never RED unless the member also declares a universe candidate
   of the same spelling.
3. **Path classification.** Each occurrence is walked *upward* from the
   identifier: through transparent wrappers (parentheses, `!`, a cast or `as`
   whose semantic conversion is identity / reference), may-value forms (`?:`,
   `??`, switch expression, `as` that may fail), member accesses, conditional
   accesses, closures, until the first call-related slot (an argument of an
   invocation / object creation / delegate invocation, or a call receiver) or a
   non-call context. At every edge the conversion is asked of Roslyn
   (`SemanticModel.GetConversion`, `IConversionOperation.GetConversion`), and
   the ordinal of a slot comes from Roslyn's own `IArgumentOperation.Parameter`
   (reduced extension receivers are ordinal 0, expanded params elements bind to
   the params ordinal), so nothing here is the extractor's downward
   `Classify`/`EmitCall` walked twice.
4. **Verdict per universe occurrence**, exactly one of:
   - `captured` — with the site kind (`invocation`, `object_creation`,
     `delegate_invocation`, `constructor_initializer`), the declared ordinal
     and the representation the
     vocabulary owes (`var` / `param` / `opaque`: may-value, `ref`/`out`,
     params, and an unstable parameter are `opaque`);
   - `excluded` — by exactly one of the fourteen frozen names (eleven at the
     freeze, `predicate_result` / `interpolation_hole` / `indexer_argument`
     named by the A2.2-4R4 ruling), attributed to the
     slot it sits under; every call whose argument *contains* the explained
     site is listed as an enclosing `nested_call_result`, so `Use(Wrap(r))`
     reads inner-captured / outer-excluded side by side;
   - `not_call_related` — a named non-call context from a closed table
     (`return`, `local_declarator`, `tested_operand`, `foreach_source`,
     `query_clause`, `local_function_declaration`, …). A context outside the
     table, or a derived value under an argument that no frozen name covers, is
     RED, never a bin.
5. **Two-sided join.** Every `var`/`param` fact of both carriers must join an
   inventoried occurrence of the *same symbol* at its site and ordinal with the
   expected representation (`negated` included); every call fact must sit on a
   site the member owns, carry the site's `call_kind`, and be made relevant by
   some handle-shaped occurrence; every captured universe occurrence must find
   its fact. Records bind to members by file and name, overloads by the call or
   guard sites the record carries.

## RED kinds

| kind | meaning |
|---|---|
| `occurrence_not_captured` | a universe occurrence at a call slot has no fact (no record, no call fact at the site, or no slot at the ordinal) |
| `representation_mismatch` | the fact's slot kind is not the one the vocabulary owes (`var` where `opaque` is expected, or the reverse) |
| `fact_binds_other_symbol` | a `var` (or opaque-over-local) fact names a symbol by spelling while a candidate of the same spelling exists in the member: the symbol at the slot is not the candidate |
| `fact_captures_excluded_occurrence:<name>` | a fact represents an occurrence the taxonomy excludes by `<name>` |
| `fact_without_occurrence` / `param_fact_misbound` | a fact names a local or parameter no reference at the slot resolves to |
| `fact_without_relevant_occurrence` | a call fact made relevant by nothing the oracle can see |
| `fact_site_not_found` / `fact_in_nested_function` / `call_kind_mismatch` / `record_unbound` / `member_in_both_carriers` | site identity and carrier integrity |
| `unclassified_argument_shape:<shape>` | a candidate occurrence under an argument that no frozen exclusion names (none over the current inputs after R4 and R5; anything new) |
| `unclassified_conversion:<edge>` / `unclassified_context:<kind>` | a conversion edge or a syntax the oracle has no rule for |

Exit 0 = no RED, 1 = RED, 2 = usage / unreadable input. The report
(`oracle.json`, schema `p037-completeness-oracle/1`) carries the universe
counts, the per-occurrence verdicts with their paths, the per-fact slot
checks, the closed context table's counts, every RED with member, symbol,
site and ordinal, and the compilation's error count (a census must be valid
C#; the samples are not, on purpose, and say so).

## What it is not

- Not a second copy of the production classifier: it walks up over syntax
  where production walks down over operations, it asks Roslyn for conversions
  and ordinals where production computes positions, and it is held to a
  *designed* classification (`corpus/p037-hostile/expected.json`, written from
  the taxonomy, never recorded from a run) so the two cannot agree on nonsense.
- Not the specification of flow: it over-approximates and demands
  explanations; it cannot make the checker braver than P-037.
- Not a consumer of `mentions`, pseudo-ordinals or any production metadata
  that the freeze forbids; its own metadata stays in its own report.
