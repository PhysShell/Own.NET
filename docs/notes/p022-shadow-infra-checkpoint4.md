# P-022 step 7a (#260/#269) — checkpoint 4: first-divergence reduction

> Status: **infrastructure for shadow mode**, the last checkpoint of the row-7a
> slice. Still not shadow mode and still not a parity claim: this reducer
> **refuses** the verdict layer, because comparing final diagnostics is #260's
> *acceptance* and is blocked by #259 (cp5 and 4b). Numbers are generated:
> [`docs/generated/p022-shadow-census.md`](../generated/p022-shadow-census.md).

Checkpoints 1–3 built the pair and made it walkable. This one walks it —
over the `lowered` and `summaries` layers only — and names the **first** place
two engines part company: the layer, the step address, and the *minimal*
difference inside that step.

## What landed

- **`reduce_traces`** on both sides, independent readings of the same rules.
  A comparison is the last thing you want to have only one implementation of,
  and having two paid for itself twice in this checkpoint alone (below).
- **`tests/fixtures/repro/<case>.reduction.json`** — the reduction per case,
  committed and replayed byte-for-byte by the port.
- **The census's divergence counters are now computed**, not gate-implied.
  Until this checkpoint they were "0 because a green build cannot represent
  anything else"; now a reducer produces them over a declared scope and the
  generator reads them off.

Over the 9 committed reductions: **left-only 0 / right-only 0 / changed 0 /
ordering-only 0 / unexplained 0**, with **2** `status` observations — both
boundaries the port declares in its own error text (the unported
obligation-protocol analysis; the typed door).

## The decisions this checkpoint took, and why

- **The scope is a contract, and `verdicts` is refused rather than skipped.**
  Infrastructure that would compare final diagnostics on request is
  infrastructure that becomes an unearned shadow-mode claim the first time
  somebody widens a constant. So the layer is refused, the refusal is carried
  in every reduction's `out_of_scope`, and a test asserts it is there:
  *"not compared" must never be readable as "compared and agreed"*.
- **`status` and `projection` are counted apart from the four content
  classes.** Neither is a difference in what an engine *computed*: one says the
  engines disagree about whether a layer produced at all, the other that their
  surfaces are not comparable member-for-member. Folding either into "changed"
  would inflate a divergence count with declared boundaries.
- **When both engines refused a layer, the reducer compares *that* they
  refused, never how they phrased it.** A refusal's text is each engine's own —
  the port's map-or-raise wording is not the reference's — and diffing the
  wordings would manufacture a divergence out of a known difference in message
  vocabulary.
- **The difference is minimal.** Reporting a whole statement as "changed" makes
  the reader diff it by hand, which is how a real difference gets waved through
  as formatting. The reducer walks into the value and names the field —
  `.line`, `[3].handle`, `[len]`, `[keys]`.
- **Object key order is significant.** The Layer 2 and Layer 3 surfaces fix
  their field order as part of a byte-exact contract, so a port emitting the
  right fields in the wrong order is a real defect. A key-order-only difference
  reports path `[keys]` with the two key lists, rather than dumping two
  identical-looking objects on the reader.

## Two findings, both from having two implementations

**1. The capture carried the MOS document in the wrong key order.** The
reference embedded `dump_summaries`' dict in *insertion* order; the port read
the same surface back from its rendered form, which is
`json.dumps(..., sort_keys=True)` — the form `tests/fixtures/summaries/` pins
byte-for-byte. So the two engines' MOS documents differed in key order alone,
and the first reduction reported a `changed` step for a difference **neither
surface has**.

Resolved at the capture, not at the comparison: each layer document is now
carried in the key order **its own surface fixes**. The dict's insertion order
was an implementation detail of `dump_summaries`, never part of the contract.

**2. The two reducers disagreed about what "the same" means.** Python's `dict`
compares order-insensitively and `True == 1`; the port's value type
distinguishes both. An order-insensitive reference reducer would have quietly
disagreed with the port about every key-order difference. The reference now has
an explicit `_same` that treats key order as significant and `bool` as distinct
from `int`, matching the port.

Neither would have surfaced with one implementation. The first would have been
a permanent phantom divergence; the second, a silent disagreement about the
comparison's own semantics.

## The reducer is shown to work, not assumed to

A reducer that has never reported is a reducer nobody has seen work; one that
reports on unchanged data is worse than none. Both sides run six controls on a
real Layer 2 output, each introducing **one** controlled change into a copy:

| control | expected |
|---|---|
| unchanged data | `identical`, and `first` is null |
| one changed field, deep in a step's value | `changed`, naming the step and path `.line` |
| a step only the reference addresses | `left-only`, naming the step |
| a step only the port addresses | `right-only`, naming the step |
| the same steps in a different sequence | `ordering-only` |
| the same fields in a different key order | `changed`, path `[keys]` |
| both engines refused, differently worded and differently projected | `identical` |

The changed-field control moved case twice before it tested the right thing.
`di` is DI-only and its last lowered step (`externs[$borrow_mut]`) carries no
`line`, so the reference's control *added* a key while the port's replaced one
that was not there — the reference passed on the wrong thing and the port
correctly stayed silent. The two halves disagreeing is what surfaced it; the
control now picks a step that actually carries the field, on
`canonical_key_order`.

## Mutation campaign

Definition and recorded result: `docs/evidence/p022-shadow-cp4.json` and its `.result.json`.
**Round 1 — 11 mutations, 8 caught, 3 survivors.**

- **M57 / M62** (both sides): removing the "both refused ⇒ no comparison"
  short-circuit changed nothing, because no committed case reaches a state
  where it matters (both refusals there carry the same projection). The rule
  was real and untested. A synthetic control now drives two refused layers with
  different error texts *and* different projections through both reducers.
- **M59**: key-order sensitivity had no control left — finding 1 above had
  removed the only case in the corpus that exercised it. A synthetic control
  now reorders one step's fields and requires `changed` with path `[keys]`.

**Round 2 — 11 mutations, 11 caught, 0 survivors**, control clean.

## Where the row-7a slice stands

All five things the P-022 status row listed as "sliceable now" are built:
same-input capture with a canonical hash; the reproduction-artifact format; the
engine protocol; the `AnalysisTrace` schema with stable-ID normalization; and
first-divergence reduction over the lowered and MOS layers.

What remains for #260 is exactly what was blocked when the slice started, and
is blocked still: **comparing end diagnostics as an acceptance surface**, which
needs #259's cp5 (messages, evidence, rendered surfaces) and 4b (the
obligation-protocol analysis). The infrastructure is deliberately shaped so
that crossing that line is a contract decision — the reduction scope, the
engine vocabulary and the layer vocabulary are all frozen constants with tests
that fail when they move.

The wording, one last time: what this slice proved is "two engines can be
given the same named input, made to report their layer outputs in one format,
normalized into one walkable shape, and walked to a first difference over two
of three layers" — never "shadow mode", and never "parity".
