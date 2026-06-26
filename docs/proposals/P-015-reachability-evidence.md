# P-015 -- Reachability-slice evidence: explain the path, not just the point

Status: **accepted, in progress** (model + SARIF builder landed; OwnIR wiring is the next patch)

## Why

Two academic works were proposed as inputs to Own.NET's design: **ReachHover**
(a data-flow reachability UI; ICSME '23 + a 72-developer survey) and the
**Optional Checker** (modular cooperating qualifier checkers via partial
rely-guarantee; ASE '24). A review of that research landed on a sharper framing
than the original "Rust-style borrow checker compiling to C#" pitch:

> Optional Checker  -> how to build modular, checkable *contracts*
> ReachHover        -> how to *explain* multi-file diagnostics
> Own.NET           -> applies both to C#/WPF resources, lifetimes, XAML, DI

The single most important realisation is that the "fact-based frontends -> one
core -> explainable diagnostics" architecture the review recommends **already
exists** in this repo (`ownir.py` facts, one core checker, several analyses).
So the recommendation collapses to one concrete, high-leverage gap rather than a
rewrite.

## The gap (precise)

A finding answers *that* something is wrong. The reachability question a
developer actually asks is *why is this held, and through what?* Today:

- `ownlang/ownir.py` `Finding` already carries `related` and emits SARIF
  **`relatedLocations`** -- good, unordered secondary anchors (e.g. a DI
  captive's consuming constructor).
- But there are **no `codeFlows`** anywhere: the *ordered* retention path
  (`singleton -> transient -> scoped`) that the DI checker already computes
  (`CaptiveDependency.path` and friends) is dropped into the message **string**
  instead of being emitted as a structured slice a SARIF/IDE consumer can walk.
- The core `Diagnostic` (the `.own` path) had no structured secondary locations
  at all -- only a primary line + caret, plus textual
  `[consumed by ... at file:line]` riders.

That ordered slice *is* the ReachHover idea. It is the highest-value, smallest
change in the whole synthesis: the data is already computed; only the
presentation is missing.

## What this change adds

1. **`ownlang/evidence.py`** -- a pure, dependency-free transform from an ordered
   chain of `(file, line, label)` steps to the two SARIF constructs:
   `related_locations(steps)` -> `relatedLocations`, `code_flow(steps)` ->
   `codeFlows`, and `di_path_steps(path, loc_by_name, end_label)` which turns a
   DI dependency path (service names) into ordered steps anchored at each
   service's registration site. One vocabulary for every producer.
2. **`ownlang/diagnostics.py`** -- `Diagnostic` gains a structured `evidence`
   slice (`Evidence(line, label, file, role)`), the typed successor to the
   textual riders, rendered as `note:` lines in both `render` and
   `render_pretty`. Additive and backward compatible: an empty slice (the common
   case) leaves existing output byte-for-byte unchanged.

## The remaining wiring (next patch)

The DI findings in `ownir.py` should pass the ordered slice through:

- add `flow: tuple[tuple[str, int, str], ...] = ()` to `ownir.Finding`;
- in `_sarif_result`, after the existing `relatedLocations`, splice
  `result["codeFlows"] = evidence.code_flow(f.flow)` when non-empty;
- in `_di_findings`, build `loc_by_name = {s.name: (s.file, s.line) ...}` once and
  pass `flow=evidence.di_path_steps(c.path, loc_by_name, end_label)` per family
  ("captures scoped service" for DI001, "leaked transient IDisposable" for DI004,
  etc.).

This is a ~10-line edit, intentionally kept out of this commit because
`ownir.py` is large and must be edited where it can be run against its test
suite (`build_sarif` has golden-file tests) rather than rewritten wholesale.

## Staged plan (the review's priorities, mapped to this repo)

- **P0 (this proposal)** -- reachability evidence for existing WPF/Event/Dispose/DI
  findings: structured `relatedLocations` (done) + `codeFlows` slice (builder
  done; OwnIR wiring next).
- **P1** -- resource-protocol contracts as first-class declarations
  (`resource Subscription { acquire: ev += h; release: ev -= h }`), building on
  the existing `extern fn` per-parameter effects (`borrow`/`borrow_mut`/`consume`).
- **P2** -- XAML -> .g.cs -> OwnIR join (`xaml_facts.py` already emits an
  OwnIR-parallel envelope; the join is where the evidence slice spans XAML, the
  generated `Connect()`, the code-behind handler and the view-model).
- **P3** -- ArrayPool/Span borrow-like resource views (storage policies in
  `buffers.py` already exist).
- **P4** -- a real borrow/lifetime checker for OwnLang as a separate experimental
  branch -- explicitly *not* the near-term roadmap.

## Non-goals / honest scope

- Not a "Rust borrow checker compiling to C#". The killer cases are C#/WPF
  resource and lifetime audit (event leaks, `DispatcherTimer`, `IDisposable`
  ownership, DI lifetime mismatch, pools), not memory safety.
- Soundness is stated as: **sound for supported patterns, conservative when
  facts are missing, runtime-correlated when static proof is insufficient** --
  not whole-language soundness. The runtime-correlation arm already exists in
  the audit subtree.
