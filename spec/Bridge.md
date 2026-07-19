# OwnIR Bridge Specification

> **Status: normative, descriptive.** This document specifies the **verdict-
> determining behavior of the OwnIR bridge** (`ownlang/ownir.py`) *as it is
> today* — everything between "a facts document was loaded" and "a list of
> `Finding`s left the bridge" that the JSON schema alone does not pin. It is the
> migration contract for the Rust `own-bridge` crate (P-022 step 6, #258/#259):
> a port conforms when it satisfies every rule here, byte-for-byte where a rule
> names an output surface. Constituent contracts it composes, never duplicates:
> [OwnIR.md](OwnIR.md) (the fact **data** contract, rules IR1–IR6),
> [Inference.md](Inference.md) (the MOS layer, rules INF-*),
> [OwnCore.md](OwnCore.md)/[Lifetimes.md](Lifetimes.md)/[Diagnostics.md](Diagnostics.md)
> (the analyses and codes). Forward-looking design lives in
> `docs/proposals/P-022-rust-core-migration.md` and
> `docs/notes/interprocedural-roadmap.md`, never here. Open decisions are
> tracked as issues (§9), never as silent TODOs.

## 0. What the bridge is, and the ownership boundary

The bridge is **not deserialization**. It owns, end to end:

1. **Validation** of a facts document (§1) — the strict door.
2. **Lowering** facts to the core `Module` AST: routing each owned-resource
   record, minting handles, lowering flow bodies, hoisting cross-branch locals,
   applying MOS contracts at call sites (§2).
3. **MOS inference orchestration** — building skeletons, running the solver,
   degrading observably ([Inference.md](Inference.md); §3).
4. **Analysis input preparation** — constructing the inputs of the DI, effect,
   and protocol analyses from their optional fact blocks (§4).
5. **Verdict mapping** — running the core over the lowered module, mapping every
   core diagnostic back to a fact handle, synthesizing the human message,
   grading severity, attaching evidence, deduplicating and ordering (§5).

**BR-B1 (bridge/analysis boundary).** The bridge *prepares* analysis inputs and
*maps* analysis outputs; it must never duplicate a solver or dataflow algorithm
the core owns. Concretely: ownership/borrow/lifetime verdicts come from
`check_module` (the composed core driver in `ownlang/__main__.py`); DI verdicts
from `ownlang/di.py`'s five finders; effect verdicts from
`ownlang/effects.py`; protocol verdicts from `ownlang/obligations.py`; the MOS
fixpoint from `ownlang/ownership.py:solve`. The bridge does **not**
independently solve for violations after routing: its only authority to
*admit, suppress, or redirect* sites is the **closed** routing behavior of
BR-L1 (plus the lowering-time admission rules BR-L6–L9) and the advisory side
paths of BR-V1; over the inputs it admits, the analyses own every verdict.
Beyond that, the bridge's own logic is identity and the synthesis of
*presentation* (messages, severity tiers, evidence slices).

**BR-B2 (no verdict repair).** The bridge must not repair a wrong analysis
verdict by replacing its code or its primary anchor. It may *skip* a closed list
of bridge-artifact diagnostics (BR-V2) and *re-anchor* only where this spec says
so explicitly (OWN025 at the view site, DI004/DI005 at their call/store sites —
BR-V5, §4).

## 1. Validation — the two doors

**BR-D1 (the strict door).** `load(path)` is the validation gate for external
input. It performs, **in this order** (the order is observable through which
error fires first): JSON parse → root-is-object → **version gate** (IR1; absent
`ownir_version` = current; `bool` rejected — the `bool`-is-`int` trap) →
`components[]` shape → each record's `resource` kind (absent defaults to
`"subscription"`; present-but-unknown rejected, IR4) → the optional per-record
strings `type`, `source_type`, `source_provenance`, `ignore_reason` (present ⇒
must be strings) → `services[]` (lifetime enum, non-empty `name`, `deps`/
`weak_deps`/`root_resolves` string arrays, `file` string, `line` int-not-bool,
`ctor_file`/`ctor_line`/`ctor_type`, `root_resolve_sites` and
`scope_cache_sites` as `{type,file,line}` object arrays, `scope_cached` string
array) → `effects[]` (`deps` strings, `io` bool, `line` int, `bindings`
`{name,init,refs,line}`) → `functions[]` (`sig` present ⇒ string; each param:
non-empty `name`, `line` int, `effect` ∈ `_PARAM_EFFECTS` when present) →
`protocols[]` via the shared obligation parser (fail-loud; **duplicate protocol
names rejected** — the name is the identity verdicts map back by) →
`protocol_functions[]` via the shared method parser. Every violation raises
`OwnIRError` with an actionable message, never a bare traceback.

**BR-D2 (the tolerant door).** `check_facts(facts)` (and `to_module`/`to_own`)
accept a dict directly, without `load()` — the path tests and embedders use.
On this door the bridge re-validates with **three distinct tolerances**, none
of them a blanket rule: (1) a **malformed optional-block entry is skipped as a
whole**, never patched into shape (`_effect_findings` and `_protocol_findings`
drop a malformed entry — a `deps: "a"` must not become `("a",)` and mint a
spurious verdict); (2) an **accepted** entry's fields go through the existing
**field-specific coercions** (`_di_findings` `str()`-coerces identity/location
fields and admits `disposable` only as the JSON boolean `true`); (3) `line`
**degrades to `0`** via `_as_int` on the paths that use the tolerant helper
(not all paths do — OD-3). A **duplicate protocol name resolves first-wins**
(deterministically) instead of raising. The two doors are deliberate: strict
for external input, tolerant for already-shaped input — but their
*divergences* are part of this contract and enumerated in §9 (OD-1, OD-2,
OD-3). A port must implement the strict door exactly; whether it exposes the
tolerant door at all is #259's decision recorded against OD-1.

**BR-D3 (`sig` asymmetry — normative, not a bug).** A present-but-non-string
`sig` on a `functions[]` **record** is rejected at the strict door; a malformed
`sig` on a **flow `call` op** is read as absent (`_call_sig`), degrading to the
name-merged summary — never a wrong overload ([OwnIR.md §5.1](OwnIR.md)).

**BR-D4 (deterministic input ordering).** The bridge imposes no ordering on
input: document order is semantic. Handle identity (BR-L2), component naming
fallbacks (BR-L3), and finding evidence all derive from the order records
appear in the document. Determinism of the *outputs* is achieved by the output
contracts (BR-V8, INF-R1), not by sorting inputs.

## 2. Fact lowering

### 2.1 The routing table

**BR-L1 (one routing table, two renderers).** `to_module` (production: facts →
core AST) and `to_own` (the human-readable `.own` sketch) implement the **same**
routing decision procedure; any divergence between them is a spec violation.
For each `components[].subscriptions[]` record, **in this exact order**:

| # | Condition | Action |
|---|---|---|
| R1 | `resource == "unresolved-subscription"` | skip (surfaced later as advisory OWN050, §5) |
| R2 | `resource == "subscribe"` and `source == "self"` | skip silently (GC-collectible self-cycle) |
| R3 | `resource == "capture"` | region := `_CAPTURE_SOURCE_REGIONS[source]` (today: only `"static"` → `Process`). If no region **or** `released` → skip silently (conservative / mitigated). Else mint `cap_<gid>`: a function **param** typed `EventSource` with the source's region + a `Subscribe(handle)` body node; the function takes the subscriber's region (BR-L4) |
| R4 | `resource == "subscription"`, `source == "injected"`, `source_provenance == "returned_fresh"` | skip silently (#146; the **instance-level** provenance beats the type-level DI hop R5) |
| R5 | `resource == "subscription"`, `source == "injected"`, not `released`, and `source_type` resolves in the DI life map | mint `cap_<gid>` as in R3 with the source's **DI region** (`singleton→Process`, `scoped`, `transient`); the handle record carries `di_source_life` (drives the captive wording, BR-V5) |
| R6 | otherwise | mint `sub_<gid>`: `Let(handle, Acquire(<R>))` where `<R>` = `_RESOURCES[resource]` (absent kind defaults to `subscription`); plus `Release(handle)` iff `released` |

The prelude resources (`Subscription`/`Timer`/`Disposable`/`PooledBuffer`) and
the capture lifetime order (`Process` > `scoped` > `transient`;
`Subscriber < Process`) are fixed declarations; the lifetime declarations are
emitted **only when at least one capture was minted** (a capture-free document
lowers byte-identically to the pre-capture era).

**BR-L2 (handle identity).** Handles are minted from **global counters in
document order**: `sub_<n>`/`cap_<n>` share one counter across all components;
`parg_<n>`/`loc_<n>` share a second counter across all functions (params first
within each function, then hoisted lets, then body order). Every handle maps to
`{**record, component, file}` (plus `di_source_life` for R5, plus
`{resource: "flow-local", ever_released, pool}` for flow locals). The handle is
the **only** identity a verdict maps back through (BR-V3); nothing may scrape a
human message for identity.

**BR-L3 (identity fallbacks).** A component without `name` is named
`Component<gid>` with the counter's **current** value; a function without
`name` is `Fn<loc>`; files default to `"?"`. (Quirk recorded as OD-4.)

**BR-L4 (subscriber region).** The subscriber's own region is its DI-registered
lifetime's region when its component name is registered in `services[]`, else
the un-registered `Subscriber` region (`Subscriber < Process`).

### 2.2 Flow bodies

**BR-L5 (per-function lowering order).** For each `functions[]` record:
contract **params first** (`_lower_fn_params` — they seed the local map), then
**hoisted lets** (BR-L7, sorted by name), then the **body** via `_lower_flow`.
The synthesized return type is `Disposable` iff the body contains a
`return` op carrying a `var` on some path, else none — this is what makes
`return s` a valid escape; the type-mismatch artifacts it can produce are
skipped in BR-V2.

**BR-L6 (the local map and kill-on-rebind).** `localmap: C#-name → handle`
resolves every later reference. `use`/`overspan`/`release` on an **unmapped**
name lower to *nothing* (silent — the untracked/optimistic residue);
`return <unmapped>` lowers to a bare `Return`. Overwriting a tracked local — a
re-bound `call` result or `alias_join` target — **pops the stale mapping
first**, even when the new binding makes no claim (an untracked `alias_join`
src, a non-fresh call result): the old obligation must leak rather than be
discharged through a dead handle. A **hoisted** local is never re-bound (it
keeps its single outer-scope handle).

**BR-L7 (cross-branch hoisting).** A name acquired *inside* an `if`/`while`
branch but referenced after the merge is declared **once at function scope**
(the in-branch acquire is then skipped). A name is hoisted iff **all four**
hold: (1) acquired (plain `acquire`, or `fresh`-returning call result) at
depth ≥ 1; (2) its **shallowest** non-acquire reference is at depth 0; (3) it
is not acquired anywhere inside a `while` body (loop acquires are cumulative —
hoisting would hide a per-iteration leak); (4) the definite-assignment safety
walk holds — no path can early-`return` (without returning the name) before
the post-merge reference/discharge on a path that did not acquire it (an `if` establishes
acquisition only when **both** arms do; a `while` body never does). The hoisted
`Let` carries the **first** branch-acquire line and preserves the pool kind.
An **untracked** name (BR-L8) is never hoisted.

**BR-L8 (optimistic untrack and kill sites).** Implements INF-A5 exactly:
locals handed to a `may`/`unknown`-contract position **inside a branch/loop**
are whole-body untracked (their acquires / fresh mints / alias mints are not
emitted; OWN051 carries the note); a local whose unverified handoff is a
**top-level** call is tracked up to that call, discharged **at** it by a
`$consume` on its handle (keyed by op identity — the specific call node), and
unmapped after it. OWN051 advisories are minted **during lowering**, gated on
the arg being *owned here* (an acquired local or a fresh-factory result).

**BR-L9 (call lowering).** For a `call` op, in order: (a) **channel routing** —
when the callee (canonical, `global::`-stripped) is overloaded **or** its
resolved summary has any `may`/`unknown` param, no direct `Call` is emitted;
instead each argument with a resolved `must`/`no` transfer is routed through
the fixed sink externs (`$consume`/`$borrow`), skipping untracked args; the
contract applied is the **sig-resolved** overload summary when the call carries
a matching `sig`, else the name-merge; (b) otherwise a **direct `Call`** is
emitted only when the callee has a summary or is a sink extern — an
unresolvable callee (BCL/extension method) is dropped: no effect, no claim,
never a crash; (c) the **kill-site** `$consume` (BR-L8); (d) the **fresh
result** mint (INF-A2) — after popping a stale binding (BR-L6) — only when the
result is not hoisted/untracked and `_callee_returns_fresh` holds (Tier A
overrides Tier B for every first-party name, INF-A4).

**BR-L10 (vocabulary enforcement in the lowerer).** An op in `_FLOW_OPS`
without a lowering branch raises "internal core inconsistency"; an op outside
`_FLOW_OPS` raises the vocabulary-skew error naming `OWNIR_VERSION`
([OwnIR.md §2](OwnIR.md)). Both are `OwnIRError`, both name file:line.

**BR-L11 (source locations).** Every lowered node carries the fact's `line`
through `_as_int` (non-int → 0). The bridge never invents lines; the anchor
policy for *findings* is BR-V5's.

## 3. Interprocedural MOS

Normatively specified in [Inference.md](Inference.md) (INF-L/S/R/M/F/A/P +
serialization). The bridge-side obligations beyond it:

**BR-M1 (orchestration).** `to_module` builds skeletons and runs `solve` once
per document, **before** lowering any function; a solver exception degrades the
whole layer to the empty MOS and records the reason for OWN052 (INF-F6) — the
checker never crashes on inference.

**BR-M2 (first-party / overload sets).** `first_party` = canonical names of
all `functions[]` records; `overloaded` = canonical names occurring more than
once. Both are keyed on the **bare** canonical name regardless of `sig`
(INV4); they gate Tier B (INF-A4) and channel routing (BR-L9a).

**BR-M3 (the summaries dump).** `dump_summaries` is the stage-1 parity
surface: byte-identical under `functions[]` permutation, per INF-R1/R2.

Function-to-rule map (for the port): `_build_skeletons`→INF-S1–S6,
`_infer_return_skeleton`→INF-R1–R5, `_merge_skeletons`/`_merge_returns`→
INF-M1–M3, `solve`/`solve_with_log`→INF-F1–F7, `_mos_lookup`/`_sig_key`/
`_call_sig`→OwnIR §5.1, `_callee_returns_fresh`/`_is_bcl_fresh_factory`→
INF-A2/A4 (Tier B table `_BCL_FRESH_BY_NS`), `_definite_release`/
`_walk_release`/`_param_signals`→INF-S2/S4, `_forward_targets`/
`_early_return_before_forward`/`_forward_path_action`→INF-S3/S6,
`_infer_param_effect`→INF-A1, `_unverified_transfer_calls`/
`_kill_sites_for_unverified`→INF-A5a/A5b.

## 4. Analysis input preparation

**BR-P1 (DI).** `services[]` records construct `di.Service` values with:
string coercion on identity/location fields, `_as_int` on lines, `disposable`
**only** for the JSON boolean `true`, tuples for the dep/site arrays. The five
finders (`find_captive_dependencies`, `find_captured_transient_disposables`,
`find_weak_captive_dependencies`, `find_explicit_root_resolutions`,
`find_scope_cached_captives`) own the verdicts. The bridge also derives
`loc_by_name` (registration sites, `line ≥ 1` only) for evidence slices, and
the DI **life map** (`name → lifetime`) that feeds R5/BR-L4.

**BR-P2 (effects).** Each `effects[]` entry is re-validated on the tolerant
door (skip-not-coerce, BR-D2) and constructs an `effects.Effect` with its
binding table; `find_effect_storms` owns the verdict; the bridge attaches the
two-step evidence slice (re-run site → identity-mint site, both lines ≥ 1).

**BR-P3 (protocols).** Protocol rules and method event trees parse through the
**shared** obligation parser (the single shape authority for both doors);
`check_protocols` and `unmatched_scopes` own the verdicts. The bridge maps
`(kind, definite)` → OBL001/002/003/004, synthesizes the deliberately
**line-free** messages (fingerprint stability for baseline/FP-judge overlays),
derives `component` as the second-to-last dotted segment of the method name,
and builds the opened→barrier(→late-close) evidence slice (lines ≥ 1 only).
OBL005 (dead rule) is advisory and anchorless.

## 5. Verdict mapping

**BR-V1 (the pipeline).** `check_facts` = `to_module` → `check_module(mod)` →
map **ERROR-severity core diagnostics only** (sub-error core diagnostics are
not mapped) → append, in order: DI findings, effect findings, protocol
findings, OWN050 advisories, OWN051 notes (minted during lowering), OWN052
notes (one per solve-failure reason; anchorless: `file="?"`, `line=0`) →
dedup (BR-V7) → sort (BR-V8).

**BR-V2 (the skip list — closed).** Exactly `OWN033`, `OWN034`, `OWN035`,
`OWN040`, `OWN041` are dropped before mapping: they report inconsistencies in
shapes the bridge itself synthesized (return types BR-L5, uninferrable
parameter effects, calls to unlowered callees) — bridge-modeling artifacts,
never real C# findings, and they carry no subject. Growing or shrinking this
list is a contract change.

**BR-V3 (map-or-raise, IR5).** Every mapped diagnostic must resolve, through
its structured `subject` (`name#line` → handle prefix), to a known handle;
otherwise the bridge raises `OwnIRError` ("the lowering has drifted") rather
than dropping a verdict. Identity is never recovered from message text.

**BR-V4 (message synthesis is a parity surface).** The human message for every
mapped finding is synthesized by the bridge from the handle record, per the
matrix in `ownir.py` (`check_facts`): flow-local wordings split on
`ever_released` ("never disposed/returned" vs "may not … on every path") and
on `pool` ("pooled buffer" vs "IDisposable local"); OWN025 has its own view
wording; capture and DI-sourced OWN014 have their region/captive wordings with
the `nice` lifetime phrases; token kinds (`timer`, `disposable` (+`type`),
`local-disposable` (+`type`), `subscribe`, `pool`, default subscription) each
have fixed sentences; the inline-lambda "no `-=` handle" note is appended
exactly where the record's `lambda` is true. **The exact strings are
normative** — OwnAudit fingerprints and the parity fixtures depend on them; a
wording change is a contract change.

**BR-V5 (anchors).** The primary anchor is the record's `line` — the acquire/
subscribe site — with the specified exceptions: OWN025 anchors at the **view**
site (the core diagnostic's line); DI004 at the resolve **call site** and
DI005 at the **cache/store site** (registration as the related location,
falling back to registration when the site is unknown); OWN052/OBL005 are
anchorless. Related locations and ordered `flow` slices are attached exactly
where §4/§5 say (DI consumer ctor; DI paths via `di_path_steps`; the capture
escape slice subscribe-site → registration-site; flow-local origin→violation
2-step; effect re-run→mint; protocol opened→barrier). Steps with unknown lines
(`< 1`) are omitted; a slice shorter than 2 steps is dropped.

**BR-V6 (severity and suppression).** `advisory` findings (OWN050/051/052,
OBL005) render as warnings, SARIF `note`, and are excluded from the exit code.
An intrinsic `severity="warning"` (injected-source subscription/subscribe,
DI002/003/004/005) is still a verdict (counts toward the exit code); display
level = host severity for `severity=None`. A non-empty `ignore_reason` on the
record marks the finding **suppressed**: still minted and counted, carried in
SARIF `suppressions` (`inSource` + justification), excluded from the exit code
and the human stream; an empty string never suppresses. Flow-local records
never carry a reason.

**BR-V7 (dedup).** Findings deduplicate on the full tuple
`(file, line, code, component, event, handler, message, kind, advisory,
severity, ignore_reason)` — **excluding** `related`/`flow` — first occurrence
wins. Rationale: a resource leaking on several lowered exits yields one core
OWN001 per exit that all remap to the same acquire anchor. (Evidence-only
divergence collapsing is OD-5.)

**BR-V8 (ordering).** The final list is stably sorted by
`(file, line, code)`; ties keep pre-sort insertion order (core → DI → effects
→ protocols → OWN050 → OWN051 → OWN052, each in its own construction order).

**BR-V9 (rendering).** `render`/`render_github`/`render_msbuild`/`build_sarif`
are pure functions of the finding list (plus the host severity choice):
formats, escaping (`%`/CR/LF, plus `:`/`,` in workflow-command properties),
SARIF rule catalogue (sorted codes + `TITLES`), `ownirSchemaVersion` stamp,
level mapping (BR-V6), backslash-normalized URIs, `region` omitted for
`line < 1`. Byte-exact per fixture layer 3 (§6).

## 6. Parity fixture plan (three layers)

The implementation issue (#259) is gated on three fixture layers, each with a
committed regeneration path and a zero-Python steady state:

- **Layer 1 — validation.** Acceptance/rejection pairs for every BR-D1 check
  (one fixture per rejection message class, plus the acceptance twins).
  Python is authoritative at generation time; steady state: the Rust
  `own-bridge` replays them without Python present. Existing seeds:
  `tests/fixtures/ownir/*.facts.json` + the raise-tests in `test_ownir.py`.
- **Layer 2 — normalized lowered representation.** A canonical JSON projection
  of the lowered `Module` (functions, params with regions, statement kinds
  with handles and lines, prelude/lifetime presence) per facts fixture — the
  seam where a lowering bug is visible *before* it hides behind a verdict.
  **Built and Rust-implemented** (#259 slices 1–3): `ownlang/lowered.py` is
  the authoritative Python emitter (#299 — its docstring freezes the
  normalization decisions; `LOWERED_VERSION` keys the surface),
  `tests/fixtures/lowered/<case>.facts.json` + `<case>.golden.json` are the
  committed pairs under the frozen `manifest.json` ledger, and
  `tests/test_lowered_fixtures.py` is the verify/`--write` harness
  (manifest == facts == goldens exactly; stale, missing, orphaned,
  pair-deleted, and unlisted fixtures are each a red build). On the Rust
  side, `own-lowered` (#300) is the typed data surface + canonical emitter
  that round-trips every shared golden byte-exactly (presence-aware
  missing/null/value handle metadata; per-document `LOWERED_VERSION`
  enforcement), and `own-bridge` (#301) **constructs** the Layer 2 document
  from the facts themselves — `facts → own-ir parse → lower → canonical
  emit` reproduces all 26 `rust_replay: true` goldens byte-for-byte with
  the golden used only as expected output. A `rust_replay: false` case
  (today exactly `tolerant_unknown_kind`) is a Python-only snapshot pinning
  an open decision (OD-2/#294) and takes no side on it: the Rust bridge
  fails loud on a present-but-unknown resource kind instead of adopting the
  tolerant fallback. Layer 1, Layer 3, analysis wiring, and #259 as a whole
  remain open.
- **Layer 3 — final normalized diagnostics.** The findings list (and its
  SARIF/github/msbuild renderings) per facts fixture, byte-exact — the outer
  contract. Existing seeds: the end-to-end expectations in `test_ownir.py`
  and the SARIF projections in `test_diag_sarif.py`; the `summaries` dump
  (INF-R1) covers the MOS sub-surface.

Regeneration: each layer gets a `--write` mode mirroring
`tests/test_cfg_fixtures.py`; a stale committed fixture is a red build; the
Rust side replays the same files (`rust/crates/own-*/tests/parity.rs`
precedent). No fixture family from `tests/test_ownir.py` may be silently
omitted — the behavior matrix ([BridgeBehaviorMatrix.md](BridgeBehaviorMatrix.md))
is the completeness ledger.

## 7. Rules index

- **BR-B1–B2** — boundary: prepare-and-map only; no verdict repair.
- **BR-D1–D4** — the strict door's ordered checklist; the tolerant door's
  skip-not-coerce; the `sig` asymmetry; document order is semantic.
- **BR-L1–L11** — routing table + twin rule; handle identity; identity
  fallbacks; subscriber region; per-function order + return synthesis; local
  map + kill-on-rebind; hoisting (4 conditions); untrack/kill-sites; call
  lowering; vocabulary enforcement; source locations.
- **BR-M1–M3** — MOS orchestration, first-party/overload sets, summaries dump.
- **BR-P1–P3** — DI/effect/protocol input preparation.
- **BR-V1–V9** — pipeline; skip list; map-or-raise; message matrix; anchors;
  severity/suppression; dedup; ordering; rendering.

## 8. Conformance

Pinned by [`tests/test_ownir.py`](../tests/test_ownir.py) (the bridge suite)
plus [`tests/test_ownership.py`](../tests/test_ownership.py) (the solver) and
[`tests/test_diag_sarif.py`](../tests/test_diag_sarif.py) (rendering). The
complete family-by-family mapping — every test family → the BR/IR/INF rule it
pins, its Python location, and whether a Rust fixture is required — lives in
[BridgeBehaviorMatrix.md](BridgeBehaviorMatrix.md); **no family may be
silently omitted** there. A change to this spec without a matching change
under those suites (or vice-versa) is a red build.

## 9. Open decisions (tracked as issues, not TODOs)

Ambiguities found during the inventory. Per #258's charter, none is resolved
here by fiat: each is either documented above as the migration contract, or —
where current Python behavior looks accidental — opened as a **Python-first**
issue to be settled *before* the port relies on it.

- **OD-1 (#294 — the tolerant door's scope).** Should Rust `own-bridge` expose the
  tolerant door (BR-D2) at all, or is strict-only + a Python-side test shim
  the porting contract?
- **OD-2 (#294 — unknown kind on the tolerant door).** `to_module`/`to_own` silently
  route a present-but-unknown `resource` kind as `subscription` when `load()`
  is bypassed — the tolerant door contradicts IR4 here. Fail-loud in the
  lowerer too, or spec the fallback?
- **OD-3 (#294 — line coercion inconsistency).** Finding construction uses strict
  `int(...)` on some paths (token/capture anchors) and `_as_int` on others —
  a non-int `line` on the tolerant door crashes one path and degrades the
  other.
- **OD-4 (#295 — positional identity fallbacks).** `Component<gid>`/`Fn<loc>`
  defaults couple a nameless record's identity to the running counter
  (document position), so an unrelated earlier record shifts it.
- **OD-5 (#295 — dedup blind to evidence).** BR-V7's key excludes `related`/`flow`;
  two findings differing only in evidence collapse to the first.
- **OD-6 (#295 — anchorless SARIF).** OWN052/OBL005 emit `file="?"`, `line=0` —
  SARIF gets a literal `?` artifact URI (region correctly omitted).
