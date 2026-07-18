# Bridge Behavior Matrix

> **Status: normative completeness ledger** for [Bridge.md](Bridge.md) (#258).
> Every verdict-determining behavior of `ownlang/ownir.py` is mapped to: the
> normative rule that owns it, its Python source, the `tests/test_ownir.py`
> checks that pin it (line numbers of the `checks += 1` blocks at the commit
> this ledger was generated on — they drift with edits; the *family names* are
> the stable identity), and the parity-fixture **layer** (§6 of Bridge.md:
> L1 = validation, L2 = normalized lowered representation, L3 = normalized
> diagnostics, S = the `summaries` dump) the Rust port must replay it at.
> **No family may be silently omitted here**; a new `test_ownir.py` family
> without a row (or vice-versa) is a red build in spirit — reviewers enforce
> it until a generated cross-check exists (see OD-7).
>
> Suites beyond `test_ownir.py` that also exercise the bridge:
> `test_ownership.py` (INF-L/F solver unit layer), `test_diag_sarif.py`
> (SARIF projection), `test_diag_fixtures.py`/`test_cfg_fixtures.py` (the
> corpus-wide parity fixtures), `test_di_eff_fact_parity.py`,
> `test_obligations.py` (§8 protocol vocabularies), `test_effects.py`,
> `test_verify_delta.py`/`test_certify.py`/`test_fix_candidates.py`
> (fix-pipeline consumers of `check_facts` output).

## (a) Validation — the strict door

| Behavior | Source | Rule | Pinned by (test_ownir.py) | Layer |
|---|---|---|---|---|
| version gate: mismatch raises; absent = current; producers stamp one literal | `load` | IR1/IR2, BR-D1 | L349, L354, L360, L412 | L1 |
| unknown `resource` kind rejected; absent defaults `subscription` | `load` | IR4, BR-D1 | L384, L390 | L1 |
| unknown flow op raises (via lowering guard) | `_lower_flow` | IR4, BR-L10 | L369, L508 | L1 |
| optional per-record strings must be strings (`source_provenance`, `ignore_reason`) | `load` | BR-D1 | L246, L304 | L1 |
| `services[]` shape: lifetime enum, name, line int-not-bool, dep/site arrays, ctor fields | `load` | BR-D1 | L1185–L1236 (9 checks) | L1 |
| function `sig` present-but-non-string rejected (record side) | `load` | BR-D3 | L2306 | L1 |
| schema↔code enum binding: `ownir_version`, `resourceKind`, `diLifetime`, `paramEffect`, `flowOp` (no gaps/dupes) | `ownir.schema.json` + authority sets | IR3/IR4 | L434–L480 (6 checks) | L1 |
| every declared flow op actually lowers (no coverage gap) | `_FLOW_OPS` ↔ `_lower_flow` | BR-L10 | L485 | L2 |

## (b) Fact lowering

| Behavior | Source | Rule | Pinned by | Layer |
|---|---|---|---|---|
| lowered facts parse as valid `.own` (textual twin) | `to_own` | BR-L1 | L112, L236, L1250, L1291, L1364 | L2 |
| unresolved-subscription never lowers to an acquire (no phantom OWN001) | routing R1 | BR-L1 | L1256 | L2 |
| capture lowers to `subscribe self` under region, not a token | routing R3 | BR-L1 | L1300 | L2 |
| released capture skipped (mitigated → silent) | routing R3 | BR-L1 | L1330 | L2/L3 |
| deferred-projection escape does not mask a flow leak | `_lower_flow` | BR-L6 | L637 | L2/L3 |
| unknown callee dropped: no `Call`, no OWN040 crash | call lowering (b) | BR-L9b | L2472 | L2 |
| kill-on-rebind: overwritten owned local leaks the original | `_lower_flow` result/alias pop | BR-L6 | L2677, L2980 | L3 |
| fresh mint inside nested branch (mos threaded through recursion) | `_lower_flow` | BR-L9d | L2691 | L3 |
| cross-branch hoist: release-after-merge clean; use-only still leaks; factory-result variant | `_hoisted_branch_locals` | BR-L7 | L2746, L2761, L2774 | L3 |
| hoist limitations stay loud: nested depth ≥ 1, while-body, early-return unsafe; safe single-branch hoists | `_branch_hoist_safe` | BR-L7 | L2795, L2815, L2834, L2851 | L3 |
| hoisted pool rent keeps its kind | `_hoisted_branch_locals` | BR-L7 | L2868 | L3 |
| `alias_join` RID semantics: either-release discharges; both-drop = one leak; both-release = OWN003; use-after = OWN002; untracked src = no claim; wrapper-return escapes | `_lower_flow` alias_join + core RID | BR-L6, INF-A3 | L2890–L2980 (7 checks) | L3 |
| `overspan` → OWN025 at the view line; field-pass pool flow shape | `_lower_flow`, `check_facts` | BR-V5 | L2994, L3021 | L3 |

## (c) Interprocedural MOS (bridge side; solver unit layer in `test_ownership.py`)

| Behavior | Source | Rule | Pinned by | Layer |
|---|---|---|---|---|
| compositional handoff: consume silent / use-after OWN002 / borrow leak OWN001; explicit effect wins | `_lower_fn_params`, `lower_call` | INF-A1, BR-L5 | L1436–L1518 (6), L1530 | L3 |
| transitive consume/borrow through forwards; two-hop; conditional = `may` | skeletons + solver | INF-S3, INF-F5 | L1554–L1632 (5) | L3/S |
| TZ D1 definite-release ladder (partial/while/early-return vs all-paths) | `_definite_release` | INF-S2 | L1654–L1733 (5) | L3/S |
| optimistic untrack + OWN051 gating; kill-site pre/post split | `_unverified_transfer_calls`, `_kill_sites_for_unverified` | INF-A5a/b, BR-L8 | L1753–L1812 (4), L1830 | L3 |
| observable degradation: OWN052 exactly once; healthy solve clean | `to_module` try/except | INF-F6/P3, BR-M1 | L1853, L1878 | L3 |
| summaries dump: content, byte-determinism, degraded shape, stage-2 key vocab | `dump_summaries` | INF-R1/R2, BR-M3 | L1898, L1913, L1922, L2286, L2297 | S |
| overload merge + channel routing (agree/disagree, direct call, fresh merge, `global::`) | `_merge_skeletons`, BR-L9a | INF-M1–M3 | L1945–L2050 (6) | L3 |
| stage-2 `sig` resolution: precise overload, fallback, unmatched, `global::`, forward edges, mixed producers, dup name+sig merge | `_mos_lookup`, `_sig_key` | OwnIR §5.1, BR-D3 | L2083–L2266 (11) | L3/S |
| sink-extern channels `$consume`/`$borrow`/`$borrow_mut` (+ transitive) | `_OWNERSHIP_SINK_EXTERNS` | INF-S6 | L2318–L2388 (7) | L3 |
| T1 fresh results: leak/dispose/use-after; factory-of-factory; param-return not fresh; mixed-origin and null-path degrade | `_infer_return_skeleton`, `_callee_returns_fresh` | INF-R3/R4, INF-A2 | L2409–L2455 (5), L2706, L2724 | L3 |
| Tier B BCL table: IO/Xml/Json/crypto factories, namespace matching precision, exclusions, Tier A override (incl. dropped overloads, `global::`, wrapper recall) | `_BCL_FRESH_BY_NS`, `_is_bcl_fresh_factory` | INF-A4 | L2490–L2656 (16) | L3 |

## (d) Analysis input preparation

| Behavior | Source | Rule | Pinned by | Layer |
|---|---|---|---|---|
| DI graph finders' verdict sets + messages + anchor metadata (DI001/002/003/004/005 unit layer) | `ownlang/di.py` (not the bridge) | BR-B1, BR-P1 | L805–L1048 (18) | (core suite) |
| advisory codes OWN051/OWN052 registered in `TITLES` (spec↔code drift guard) | `diagnostics.TITLES` | INF-P2/P3 | L1937 | — |
| effects re-validation skip-not-coerce; protocol first-wins on tolerant door | `_effect_findings`, `_protocol_findings` | BR-D2, BR-P2/P3 | (pinned in `test_effects.py` / `test_obligations.py`) | L3 |

## (e) Verdict mapping

| Behavior | Source | Rule | Pinned by | Layer |
|---|---|---|---|---|
| the golden path: one finding, exact file:line/code/message/tag; released silent; empty facts clean | `check_facts` | BR-V1/V4/V5 | L121–L141 (4) | L3 |
| source tiering: injected = warning tier, static = error tier, lambda note | BR-V4/V6 | severity matrix | L157–L177 (3) | L3 |
| publisher provenance: `returned_fresh` silent; unknown value keeps warning; beats DI hop | routing R4 | BR-L1 | L208–L230 (4) | L3 |
| suppression: non-empty reason suppresses (still minted); empty does not; SARIF `suppressions` | BR-V6 | — | L271–L293 (4) | L3 |
| subscribe tiering (self/injected/static) | routing R2 + BR-V4 | — | L328–L341 (3) | L3 |
| per-kind findings: timer / disposable field / ignored subscribe / pool / local-disposable (location, wording, tag, released-twin silence) | BR-V4 | message matrix | L523–L617 (11) | L3 |
| flow-local OWN001 wording split (`ever_released`), component naming, kind tags | BR-V4 | — | L643–L671 (6) | L3 |
| exception-edge dedup (one OWN001 per acquire across exits); nested-throw recall; finally+switch; pool labelling; while fixpoint verdicts | BR-V7 + core lowering | — | L691–L774 (5) | L3 |
| DI bridge findings: severity, anchors (DI004 call site / DI005 store site + registration `related`), flows, not-double-reported | BR-P1, BR-V5 | — | L855–L1180 (17) | L3 |
| OWN050 advisory: location/message/kind; coexists with real OWN001 | `_unresolved_findings` | BR-V1/V6 | L1262–L1275 (3) | L3 |
| OWN014 captures: static source, released silent, injected conservative, lambda note; DI-sourced escalation + proven-safe transient + additive fallback; escape flow slice | routing R3/R5, BR-V4/V5 | — | L1306–L1408 (8) | L3 |
| flow evidence slices: handoff OWN002 2-step; consume-param OWN001 maps (no "cannot map back"); timer with incidental source keeps its path; OWN025 Rent→view flow | BR-V3/V5 | — | L1455–L1482 (3), L3004 | L3 |
| SARIF projection: envelope, driver, rules, results, levels, `--severity warning`, empty run, oracle round-trip | `build_sarif` | BR-V9 | L3081–L3139 (11) | L3 |

## (f) Rendering / CLI surfaces

| Behavior | Source | Rule | Pinned by | Layer |
|---|---|---|---|---|
| `github` / `msbuild` / fallback-human renders; escaping; severity pass-through; msbuild default stays `error` | `render_finding` | BR-V9 | L3038–L3074 (8) | L3 |

## Open decisions cross-reference

OD-1…OD-6 are defined in [Bridge.md §9](Bridge.md); additionally:

- **OD-7 (#296 — matrix drift).** This ledger is hand-generated; a `checks += 1`
  family added to `test_ownir.py` without a row here is invisible until
  review. A generated cross-check (family-count assertion or extraction
  script) is a candidate follow-up for #259's fixture tooling.

## Rust fixture requirement summary

Every row above marked **L1/L2/L3/S** requires a same-layer Rust parity
fixture in #259; rows marked *(core suite)* are `own-analysis`/`own-di`
territory (the bridge only routes them — BR-B1) and are covered by those
crates' own parity suites. Layer 2 (the normalized lowered representation)
has **no Python emitter yet** — building it is #259's first deliverable
([Bridge.md §6](Bridge.md)); until then the (b)-section rows are pinned only
end-to-end (L3), which is exactly the visibility gap layer 2 exists to close.
