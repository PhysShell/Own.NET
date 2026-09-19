# `corpus/p037-relevance` — the relevance taxonomy census for P-037 A2.2

Frozen at A2.2-0 (docs/notes/p037-formal-kernel.md §10.6). This directory is
the machine-readable half of that ruling.

> **Completeness means every candidate occurrence at a call-related syntax
> site is either represented by the raw guarded-call vocabulary or assigned
> exactly one named exclusion. Occurrence alone does not establish ownership
> flow to the enclosing callee.**

## Why this exists

The A2.1 guarded-fact sidecar (corrected treatment A', `5a0de070`) captures two
argument shapes out of the twenty-eight in `probe/case.cs` correctly (the bare
identifier and the parenthesized one) and two falsely (a boxed struct handle,
recorded as a `param` fact although the callee receives a copy, and a delegate
invocation recorded as a plain call of the delegate's `Invoke`). The tempting repair — "a handle occurs somewhere below the
argument, therefore the call is relevant" — is exactly the wrong one: for
`Use(Wrap(r))` the value reaching `Use` is `Wrap`'s result, for
`Use3(new Stream[] { r })` it is an array, for `Run(() => Use(r))` it is a
closure, and for `TakeBox(r)` it is a `Box` made by a hidden user-defined
conversion. A completeness checker built on occurrence would confidently prove
nonsense. So the taxonomy separates **relevance** (a deliberately small,
syntactic value-flow recognizer) from **representability** (the frozen
vocabulary), and demands that every occurrence the broad oracle finds is either
captured or matches exactly one **named** exclusion.

## Layout

    registry.json          the frozen classes, transparent wrappers, may-value
                           forms, call-like forms and named exclusions
    probe/case.cs          one method per shape; method names are the keys
    probe/expected.json    each method's class (and exclusion) and its conversion
                           edge, plus what the A2.1 extractor observably emitted
                           for it at A' (5a0de070, the treatment main carries)
                           and, since A2.2-4, the completeness oracle's reading
                           of the row (`a2_2_4_oracle`)
    oracle_findings.json   every RED the completeness oracle is expected to raise,
                           tied to a finding classified by §10.1

`tests/test_p037_relevance_freeze.py` keeps the registry, the probe, and §10.6
consistent: every probe method classified, every class and exclusion frozen,
every wrapper / form / exclusion exercised by at least one probe, and every
name mentioned in the prose. It runs nothing: the extractor observations in
`expected.json` are recorded facts. A2.2-4 turned each row into a checked
assertion: `scripts/p037_completeness_oracle.py check` runs the completeness
oracle (`frontend/roslyn/OwnSharp.Oracle`) over the probe and demands that
every row reads `captured:<site kind>` for a relevant class and
`excluded:<named exclusion>` for an indirect one (the nested-call row reads
inner-captured plus the outer `nested_call_result`), and the freeze test pins
the recorded column against the class.

## What moves this census

A2.2-1 landed: the transparent and may-value rows read `sidecar_call` in
`a2_2_1_observed`, measured with the walker; the boxing row lost its false
capture; every other row reads as at A'. A2.2-1a closed the conversion
vocabulary (`reference_checked`, `boxing`) with no production change. A2.2-2
landed: the object_creation row reads `sidecar_call:object_creation` in
`a2_2_2_observed`; A2.2-2b re-shaped the delegate_invocation row with a record
to `sidecar_call:delegate_invocation` (A' had captured it as a plain invocation
of the delegate's `Invoke`, which the coarse vocabulary could not see), and the
local-handle delegate row stays `no_record` at every step. A2.2-3P landed: the
orphan carrier `guarded_functions[]` delivers the facts of the methods the legacy
pass never admitted; `a2_2_3p_observed` reads `orphan_call` for PlainSame and the
inner call of Nested, `orphan_call:delegate_invocation` for the local-handle
delegate row, and stays `no_record` only where the sole occurrence is a named
exclusion (Tuple, Closure, UserConversion, Indexer): no fact exists to carry.

A2.2-4 landed: the oracle reads all 28 rows as their frozen class
(`a2_2_4_oracle`), and its one RED on this file, the expression-bodied
`Box.op_Implicit` helper whose owned parameter flows into a constructor with no
record in either carrier, is finding F-MEMBER in `oracle_findings.json`. The
generated hostile census lives in `corpus/p037-hostile`.

A2.2-4R landed: R4 added the three exclusion rows PredicateResult,
InterpolationHole and IndexerArgument, R5 the constructor row CtorInit
(`orphan_call:constructor_initializer`; the freeze test's `constructor_rows`),
and R6 repaired F-MEMBER, so `Box.op_Implicit` now carries its fact as an
orphan. The probe has 32 rows, `a2_2_4r6_observed` moves none of them against
`a2_2_4r5_observed`, and the oracle reads the file RED-free.

Only an A2.2 step, deliberately, one row at a time: a transparent wrapper
becomes `captured` in A2.2-1, a call-like form in A2.2-2, an orphan record
appears in A2.2-3. A row that moves without a step meaning to move it is a
regression, exactly as in `corpus/p037-shapes`.
