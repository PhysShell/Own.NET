# `corpus/p037-relevance` — the relevance taxonomy census for P-037 A2.2

Frozen at A2.2-0 (docs/notes/p037-formal-kernel.md §10.6). This directory is
the machine-readable half of that ruling.

> **Completeness means every candidate occurrence at a call-related syntax
> site is either represented by the raw guarded-call vocabulary or assigned
> exactly one named exclusion. Occurrence alone does not establish ownership
> flow to the enclosing callee.**

## Why this exists

The A2.1 guarded-fact sidecar (corrected treatment A', `5a0de070`) captures two
argument shapes out of the twenty-five in `probe/case.cs` (the bare identifier and
the parenthesized one). The tempting repair — "a handle occurs somewhere below the
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

`tests/test_p037_relevance_freeze.py` keeps the registry, the probe, and §10.6
consistent: every probe method classified, every class and exclusion frozen,
every wrapper / form / exclusion exercised by at least one probe, and every
name mentioned in the prose. It runs nothing: the extractor observations in
`expected.json` are recorded facts, and A2.2-4 is the step that turns each
row into a checked `captured` / `excluded_by_rule:<name>` assertion.

## What moves this census

Only an A2.2 step, deliberately, one row at a time: a transparent wrapper
becomes `captured` in A2.2-1, a call-like form in A2.2-2, an orphan record
appears in A2.2-3. A row that moves without a step meaning to move it is a
regression, exactly as in `corpus/p037-shapes`.
