# Coordinate-surface inventory (#259 cp4 RED)

Measured, not read. Every claim below is a run against the reference or a grep
over the tree at the commit this note lands on.

The question this answers is **not** "where does `u32` appear". It is: *which
different contracts are currently represented by one `u32`, and which of them
actually have to become signed 64-bit?* Those have different answers, and
replacing the type wherever the compiler complains first would merge them again.

## Why this exists

#326 made signed-64 source coordinates part of the `OwnIR` contract
(`spec/OwnIR.md` §4.2), and cp1 proved both doors agree on it. `check_facts`
then carries those values, verbatim, onto the verdict surface — measured across
`i64::MIN`, `-1`, `0`, `1`, `u32::MAX`, `u32::MAX + 1`, `i64::MAX`, on the
**validated** `services[].line` path as well as the unvalidated
`subscriptions[].line` one. No clamp, no normalisation, no rejection.

The Rust side cannot represent that: `own_diagnostics::Diagnostic.line`,
`own_analysis::di::Service.line` and `own_syntax::ast` all carry `u32`. So the
port's public verdict representation is narrower than the language its own
strict door accepts. That is a parity boundary, not an implementation detail.

## The four use classes

### 1. Carrier — the value itself

| where | type |
|---|---|
| `own_ir` (`services[].line`, `ctor_line`, site/effect/binding/param/event) | `i64` / `Option<i64>` |
| `own_lowered` (`Param.line`, `Stmt` lines) | `i64` / `Option<i64>` |
| `own_syntax::ast` (8+ node kinds) | `u32` |
| `own_cfg` (`ir`, `builder`, `buffers`) | `u32` |
| `own_analysis` (`di::Service.line`, `effect`, `ownership`, `lifetime`) | `u32` |
| `own_diagnostics::Diagnostic.line` | `u32` |

The seam is exactly at `own_lowered → own_syntax/own_cfg`.

#### Secondary and identity carriers

The first revision of this inventory stopped at `Diagnostic.line` and said
"coordinate surfaces" as though that were all of them. It was not — review
found a second family in the same crate, and the omission mattered because two
of its members are *identity* carriers, where widening a type is not a
representation change but a comparison-key change.

| where | type | class |
|---|---|---|
| `own_diagnostics::Evidence.line` (+ `Evidence::new`) | `u32` | secondary carrier |
| `own_diagnostics::DiagKey.line` (+ `DiagKey::new`) | `u32` | **identity** |
| `own_diagnostics::EvidenceIdentity.line` | `u32` | **identity** |
| `own_diagnostics::DiagIdentity.line` | `u32` | **identity** |
| `own_diagnostics::LocatedDiagnostic::line()` | `-> u32` | accessor |
| `own_diagnostics::sarif::Step.line` | `u32` | projection |
| `own_diagnostics::sarif::Region.start_line` | `u32` | projection |
| `own_diagnostics::sarif::phys(file, line)` | `u32` | projection |

`Step` and `Region` belong to §4, not here: they are the SARIF shape, and their
admissible domain is the format's.

#### Measured: what a secondary coordinate actually carries

Run against the reference, varying the **validated** `ctor_line`
(spec/OwnIR.md §4.2) on a DI captive, which surfaces as a `related` location,
and varying `services[].line`, which surfaces as a `flow` hop:

```
ctor_line     related
i64::MIN      ()                                       <- location ABSENT
-1            ()                                       <- location ABSENT
0             ()                                       <- location ABSENT
1             (('Sing.cs', 1, 'consuming constructor…'),)
u32::MAX+1    (('Sing.cs', 4294967296, …),)
i64::MAX      (('Sing.cs', 9223372036854775807, …),)

services[].line   flow[0]
i64::MIN          ('S.cs', 2, 'captures scoped service…')   <- captor hop DROPPED
0                 ('S.cs', 2, 'captures scoped service…')   <- captor hop DROPPED
i64::MAX          ('S.cs', 9223372036854775807, 'singleton … (captor)')
```

So secondary coordinates behave **differently from the primary one**, and the
difference is the useful part:

* upward they are unbounded exactly like the primary — `i64::MAX` survives into
  `related` and into a `flow` hop verbatim, well past `u32::MAX`;
* downward they are **admission-gated**: a non-positive coordinate makes the
  whole location *disappear* rather than appear at line 0. `i64::MIN` drops the
  hop, so the gate is `>= 1` and not a truthiness test — the two agree only at
  zero.

That is the §3 sentinel again, one level down. A secondary carrier therefore
needs a wider **upper** bound and is never handed a non-positive value by its
producer, while the primary `Diagnostic.line` must represent the full signed
band including `0` and negatives.

#### Deliberately out of scope: `column`

`LocatedDiagnostic.column` is `Option<NonZeroU32>`, and its doc says why: it is
the type-level mirror of `_check_column`'s 1-based contract. That contract is
real and column-specific — `line` has no 1-based rule, which is exactly what
cp1's `accept-zero-line` / `accept-negative-line` controls pin. Widening
`column` alongside `line` because both are "coordinates" would re-glue the two
axes three censuses were spent separating. It is not part of this change.

### 2. Conversion

There is **no** coordinate-narrowing conversion in the tree today — no `as
u32`, no `u32::try_from` on a line. The narrowing does not exist yet because
the two halves have never been connected; cp4 is what would connect them. The
inventory records this so the absence is a measured fact rather than an
assumption: the first `try_from` written during the wiring would be the whole
defect, and there is nothing to find *now* precisely because the wiring is not
written.

`own_syntax::token` does `self.line.saturating_add(1)` — the lexer counting
newlines. Parser-native, unrelated to facts (see §"Two producers" below).

### 3. Semantics — `>= 1` as a sentinel

`line >= 1` is used to mean **"a known site"**, and it is a real contract, not
a range check:

| surface | guard | meaning |
|---|---|---|
| `own_analysis::di` :141 | `Some((_, file, line)) if *line >= 1` | use the call/store site; otherwise fall back to the registration site |
| `ownlang/ownir.py::_di004_primary` | `if getattr(c, "resolved_line", 0) >= 1` | same |
| `ownlang/ownir.py::_di005_primary` | `if getattr(c, "cached_line", 0) >= 1` | same |

Both implementations already spell it `>= 1`. **This predicate needs no
semantic change when the carrier widens** — `>= 1` means the same thing over
signed values, and a negative line correctly takes the fallback. It is only
*equivalent* to `!= 0` today because `u32` cannot be negative; widening the
carrier makes the written form the operative one, which is the form that is
already correct.

### 4. Projection — `>= 1` as a format domain

SARIF `region.startLine` is 1-based **by the format**, independently of what a
verdict may carry:

| surface | guard |
|---|---|
| `own_diagnostics::sarif` :230 | `region: (line >= 1).then_some(Region { start_line: line })` |
| `own_diagnostics::sarif` :241 | `step.line >= 1 && !step.file.is_empty()` |
| `ownlang/ownir.py::_sarif_result` | `if f.line >= 1: phys["region"] = {"startLine": f.line}` |

`Region.start_line` and `Step.line` are `u32` today, and the measurement below
shows the reference emitting `startLine` well past `u32::MAX`. So the format's
narrower **admission** domain (`>= 1`) is being conflated with a narrower
**numeric carrier**, which the format does not ask for. SARIF keeps the gate
and loses the ceiling.

Measured on the reference, over the same band:

```
line          SARIF physicalLocation.region
i64::MIN      <no region>
-1            <no region>
0             <no region>
1             {'startLine': 1}
u32::MAX+1    {'startLine': 4294967296}
i64::MAX      {'startLine': 9223372036854775807}
```

So the projection domain is genuinely narrower than the verdict domain, and
that is **correct rather than a bug**: a non-positive line means "no region",
not "a broken verdict". The two must not be merged again. Note the third row of
the measurement: above `u32::MAX` the reference still emits `startLine`
verbatim, so the projection is narrower only at the bottom.

## Two producers, one AST type

The finding the inventory was for.

`own_syntax::ast` node lines come from the lexer, which counts newlines in a
`.own` file — bounded by file size, never signed, and `u32` is honest there.
The same type would also be the target of the OwnIR → `Module` projection cp4
needs, where the line comes from an extractor and is signed-64 by contract.

One type, two producers, two different admissible domains. The type currently
states the parser's domain and would silently impose it on the facts producer.
That — not "`Diagnostic` is `u32`" — is the actual defect, and it is why the
answer is not obviously "widen everything".

## What this does NOT decide

The representation. The candidates the inventory leaves open:

* widen the AST and everything downstream to signed 64;
* keep the parser-native AST narrow and give the programmatic construction path
  its own coordinate type;
* introduce one source-coordinate primitive both producers construct through.

Each has a different blast radius through §3 and §4, and the choice belongs to
the next change with this inventory in front of it. What the inventory settles
is smaller and more useful:

* every `>= 1` predicate — the DI sentinel, the SARIF gate, and the secondary
  admission gate measured above — is **already correct** and must survive
  verbatim. The work is a *width* change, not a semantics change, and a patch
  that touches any of those predicates while widening a carrier has done
  something the reference does not do.
* the primary verdict line must represent the full signed band, `0` and
  negatives included; secondary carriers need only the raised ceiling, because
  their producers gate them at `>= 1` before construction.
* three of the newly-found carriers are **identity** (`DiagKey`,
  `EvidenceIdentity`, `DiagIdentity`). Widening those is a comparison-key
  change, so whatever is chosen has to keep the #255 non-collapsing key
  non-collapsing — that is a property to re-prove, not to assume.
* `column` is out of scope, and stays `NonZeroU32`.
