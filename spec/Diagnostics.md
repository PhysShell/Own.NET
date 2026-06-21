# OwnLang Diagnostics

> **Status: normative, descriptive.** The single source of truth is
> `ownlang/diagnostics.py` (`TITLES`); this document groups the codes and links
> them to the rule that raises them. All are `error` severity unless noted.

The split between **definite** (holds on every path) and **maybe** (holds on some
path) codes is deliberate: a fault that holds everywhere is a sharper message
than one behind a branch. It falls out of the set-of-states lattice
([OwnCore §3](OwnCore.md#3-ownership-states)).

## Flow-sensitive ownership / loans / permissions

| Code | Title | Rule |
|------|-------|------|
| OWN001 | owned resource not released on all paths (possible leak) | [R1](OwnCore.md#6-rules-normative) |
| OWN002 | use after release | R2 (definite) |
| OWN003 | double release | R3 |
| OWN004 | borrow escapes its scope | R10 |
| OWN005 | use after move | R4 (definite) |
| OWN006 | mutable borrow while a shared borrow is live | R8 |
| OWN007 | move while borrowed | R5 |
| OWN008 | release while borrowed | R6 |
| OWN009 | use after possible release (released on some path) | R2 (maybe) |
| OWN010 | use after possible move (moved on some path) | R4 (maybe) |
| OWN011 | mutable borrow while another mutable borrow is live | R8 |
| OWN012 | shared borrow while a mutable borrow is live | R9 |
| OWN013 | owner accessed while it is mutably borrowed | R7 |
| OWN014 | value escapes to a longer-lived region (lifetime promotion) | [Lifetimes §L3](Lifetimes.md) |

## Buffer storage policies

See [BufferPolicies.md](BufferPolicies.md).

| Code | Title |
|------|-------|
| OWN015 | stack-backed buffer cannot escape the current function |
| OWN016 | stack-backed buffer moved to a longer-lived owner |
| OWN017 | movable buffer escape is not supported by codegen (PoC limitation) |
| OWN018 | buffer size must be an integer |
| OWN019 | inline capacity too large for a stack-backed policy |
| OWN021 | stack allocation requires a statically known bound |
| OWN023 | scratch fallback forbidden but the size may exceed the inline limit |
| OWN024 | sensitive buffer is not cleared on release |
| OWN025 | full-length view of a pooled buffer reaches past its logical length |

## Unsupported

| Code | Title |
|------|-------|
| OWN020 | unsupported construct (loops / async — out of scope for the MVP) |

## Name resolution & structural

| Code | Title |
|------|-------|
| OWN030 | undefined name (incl. undefined resource / lifetime) |
| OWN031 | name already defined in this scope (incl. redefined lifetime) |
| OWN032 | owned resource copied without 'move' |
| OWN033 | function must return a value on all paths |
| OWN034 | operation requires an owned resource |
| OWN035 | return type mismatch |
| OWN036 | cyclic lifetime ordering |

## Extern / call boundary

| Code | Title |
|------|-------|
| OWN040 | call to an undeclared function (unknown calls are forbidden) |
| OWN041 | call argument mismatch (arity / effect / plain-vs-resource) |

## C# front-end resolution coverage (P-014)

Advisory only — a *coverage note*, never a verdict (this is the "noted" exception
to the `error`-by-default rule above). Emitted by the OwnIR bridge (not the core
lattice) when the type-aware C# extractor ([P-014](../docs/proposals/P-014-semantic-resolution.md))
sees a `+=` that looks like an event subscription but cannot bind its left side to
an event — its declaring type is an unreferenced external assembly. We do not
guess a leak; we report, honestly, that it was not checked. Rendered as a
`warning` regardless of `--severity` and excluded from the exit code.

| Code | Title |
|------|-------|
| OWN050 | declaring type unresolved — leakage analysis skipped |

## Rendering

The CLI renders rustc-style: `file:line:col`, the source line, and a caret under
the named identifier (the first single-quoted name in the message). A finding
about a kind-tagged resource carries a `[resource: <kind>]` suffix
([Lifetimes §L4](Lifetimes.md)).
