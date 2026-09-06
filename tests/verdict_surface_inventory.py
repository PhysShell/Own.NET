#!/usr/bin/env python3
"""The Layer 3 **surface** inventory (P-022 #259 checkpoint 5.0).

`tests/verdict_census.py` counts the frozen ledger — how many goldens, how many
findings, how many are replayed. This module asks the question checkpoint 5
actually needs answered: *which* of the surfaces cp5 must prove do those
goldens already exercise, and which are not reached at all.

Three ledgers, each a list of branches read off `ownlang/ownir.py` (the
reference), each branch matched against the committed goldens so the coverage
column is **computed from the tree**, never typed:

* **BR-V4 — message synthesis.** Every wording branch of the matrix in
  `check_facts`, plus the messages the bridge does *not* synthesize: the DI and
  effect verdicts carry `di.py`/`effects.py`'s own `message` property, and two
  flow-local fallbacks interpolate the **core diagnostic's** message. Each
  branch declares its `source`, which is the answer to "who owns this string" —
  the question that decides whether cp5 ports a bridge wording, an analysis
  wording, or a core-diagnostic message.
* **BR-V5 — evidence slices.** Every `related`/`flow` family, by field, code and
  step count, plus the two degradation rules (a step with `line < 1` is
  omitted; a slice shorter than two steps is dropped) as their own rows.
* **BR-V9 — rendered surfaces.** The `render_finding`/`build_sarif` branches.
  Coverage is the join of the row ledger below with the `pins` each case of the
  `tests/fixtures/verdict_renders/` family declares (read through
  `verdict_render_census`). The two halves are deliberately apart: a row nobody
  pins is reported here, and a case pinning a row this ledger does not know is
  a problem rather than a silent extra.

Self-policing, in the same spirit as the census: every golden finding must
match **exactly one** BR-V4 branch and every non-empty slice exactly one BR-V5
family. Zero matches means the ledger has a hole; two means two branches are
indistinguishable on the surface — both are `problems`, and both fail the gate
rather than quietly rounding the inventory down.

Pure: no `ownlang` import and no side effects — it reads what is committed.
Held to `mypy --strict` (see `files` in pyproject.toml).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from verdict_census import FIXDIR, GOLDEN_SUFFIX, Plan, plan
from verdict_render_census import pinned_rows
from verdict_render_census import plan as render_plan

HERE = os.path.dirname(os.path.abspath(__file__))

# --- message sources ------------------------------------------------------
# Who owns the string. The distinction is the whole point of the cp5.0
# inventory: a bridge wording is ported into `own-bridge`, an analysis wording
# belongs to `own-analysis` (the finder that already owns the verdict), and a
# core-diagnostic message is the one thing this core does not have at all
# (it carries each code's TITLE where the reference carries a sentence).
BRIDGE = "bridge"
CORE_ANALYSIS = "core-analysis"
CORE_DIAGNOSTIC = "core-diagnostic"
PROTOCOL = "bridge-protocol"
SOURCES = (BRIDGE, CORE_ANALYSIS, CORE_DIAGNOSTIC, PROTOCOL)

# The inline-lambda note, appended verbatim wherever the record's `lambda` is
# true (BR-V4). Declared once: three branches share it.
LAMBDA_NOTE = (" — and being an inline lambda it has no '-=' handle, so it "
               "could never be detached")
# A quoted identifier interpolated into a wording. Non-greedy: every template
# below anchors it with a literal tail, so the shortest match is the right one.
N = "(?:.*?)"


@dataclass(frozen=True)
class Branch:
    """One declared wording branch, and how a golden finding is recognised as
    having taken it.

    Recognition is by `(code, kind, message)` — everything a serialized
    `Finding` carries about its wording. Two branches of the matrix are
    therefore ONE row here, and deliberately so: the flow-local "never
    returned" wording and the `pool` token wording are the same sentence on the
    same `kind`, and the reference emits `handler=""` for both, so nothing in
    the Layer 3 document separates them. That is a property of the surface, not
    a shortcut — a port that reached the sentence by the other branch would
    produce a byte-identical golden — and it is recorded on the row rather than
    papered over with a discriminator that does not exist. `handler_empty`
    stays available for a branch that genuinely needs it; none does today.
    """

    id: str
    rule: str
    source: str
    what: str
    pattern: str
    codes: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    handler_empty: bool | None = None
    #: why this row is expected to read zero. A row at zero WITHOUT one is a
    #: missing control; a row at zero WITH one is a recorded disposition, and
    #: the note has to name what pins the branch instead.
    note: str = ""

    def matches(self, f: dict[str, object]) -> bool:
        code, kind = f.get("code"), f.get("kind")
        handler, message = f.get("handler"), f.get("message")
        if self.codes and code not in self.codes:
            return False
        if self.kinds and kind not in self.kinds:
            return False
        if self.handler_empty is not None and (handler == "") != self.handler_empty:
            return False
        return isinstance(message, str) and re.fullmatch(self.pattern, message,
                                                         re.DOTALL) is not None


#: Dispositions for the rows a facts document cannot reach — see `Branch.note`.
UNREACHABLE_DI_PHRASE = (
    "unreachable from any facts document: `transient` is the shortest region, so no "
    "subscriber it could outlive exists, and an unrecognised lifetime never reaches "
    "`di_source_life` (the DI life map admits only the three). Pinned by "
    "`verdict::tests::every_di_lifetime_phrase_is_pinned_including_the_unreachable_two`, "
    "whose expected text is not written in the test: it is read from the recorded "
    "probe `tests/fixtures/unreachable_branches.json`"
)
UNREACHABLE_CAPTURE_PHRASE = (
    "unreachable from any facts document: routing R3 mints a handle only for a source "
    "with a declared capture region, and `static` is the only entry in that table. Pinned "
    "by the `verdict::tests` control named for it, whose expected text is not written in "
    "the test: it is read from the recorded probe "
    "`tests/fixtures/unreachable_branches.json`"
)
#: The disposition of the two fallback rows: see `Branch.note`.
UNIT_PINNED = (
    "unreachable from any facts document (the nine-op flow vocabulary raises only codes "
    "that HAVE a wording); pinned by a `verdict::tests` control driven through "
    "`map_core`, whose expected text is read from the recorded probe "
    "`tests/fixtures/unreachable_branches.json`. The core message it "
    "interpolates is checkpoint 5.2's"
)


def _flow_local(bid: str, code: str, kind: str, what: str, tail: str,
                source: str = BRIDGE, note: str = "") -> Branch:
    noun = "pooled buffer" if kind == "pooled buffer" else "IDisposable local"
    return Branch(bid, "BR-V4", source, what,
                  rf"{re.escape(noun)} '{N}'{tail}", (code,), (kind,), note=note)


# --- BR-V4: the message matrix -------------------------------------------
MESSAGE_BRANCHES: tuple[Branch, ...] = (
    # flow-local OWN001, split on `ever_released` and on `pool`.
    _flow_local("flowlocal_own001_never", "OWN001", "disposable",
                "flow-local OWN001, never released", r" is never disposed \(leak\)"),
    _flow_local("flowlocal_own001_partial", "OWN001", "disposable",
                "flow-local OWN001, released on some path",
                r" may not be disposed on every path \(leak\)"),
    _flow_local("flowlocal_own001_pool_partial", "OWN001", "pooled buffer",
                "flow-local OWN001 on a pooled buffer, returned on some path",
                r" may not be returned to the pool on every path \(leak\)"),
    # flow-local use/release codes, per pool split.
    _flow_local("flowlocal_own002", "OWN002", "disposable", "flow-local use-after-dispose",
                r" is used after it is disposed"),
    _flow_local("flowlocal_own003", "OWN003", "disposable", "flow-local double dispose",
                r" is disposed more than once"),
    _flow_local("flowlocal_own009", "OWN009", "disposable",
                "flow-local maybe-use-after-dispose",
                r" may be used after disposal on some path"),
    _flow_local("flowlocal_own002_pool", "OWN002", "pooled buffer",
                "flow-local use-after-return", r" is used after it is returned to the pool"),
    _flow_local("flowlocal_own003_pool", "OWN003", "pooled buffer",
                "flow-local double return", r" is returned to the pool more than once"),
    _flow_local("flowlocal_own009_pool", "OWN009", "pooled buffer",
                "flow-local maybe-use-after-return",
                r" may be used after being returned on some path"),
    # the two fallbacks: a flow-local code with no wording of its own keeps the
    # CORE diagnostic's message verbatim after a colon.
    _flow_local("flowlocal_fallback", "", "disposable",
                "flow-local fallback: the core message, verbatim", r": .*",
                CORE_DIAGNOSTIC, UNIT_PINNED),
    _flow_local("flowlocal_fallback_pool", "", "pooled buffer",
                "flow-local pooled fallback: the core message, verbatim",
                r": .*", CORE_DIAGNOSTIC, UNIT_PINNED),
    Branch("own025_view", "BR-V4", BRIDGE, "OWN025 pooled-view wording",
           rf"pooled buffer '{N}' is viewed at its full length, past the logical "
           rf"length it was rented for \(over-read / over-clear\)",
           ("OWN025",), ("pooled buffer",)),
    # OWN014, DI-sourced: the `nice` lifetime phrase, and the lambda note.
    *(Branch(f"own014_di_{life}", "BR-V4", BRIDGE,
             f"OWN014 captive, source registered {label}",
             rf"event '{N}' is subscribed \(handler '{N}'\) to '{N}' — {re.escape(nice)} "
             rf"that outlives '{N}'; the strong subscription promotes '{N}' to the "
             rf"source's lifetime, so it can never be collected — a captive/region "
             rf"escape \(leak, no release path\)",
             (), ("subscription token",), note=note)
      for life, label, nice, note in (
          ("singleton", "singleton", "a DI singleton (application-lifetime) service", ""),
          ("scoped", "scoped", "a DI scoped service", ""),
          ("transient", "transient", "a DI transient service", UNREACHABLE_DI_PHRASE))),
    Branch("own014_di_unknown_life", "BR-V4", BRIDGE,
           "OWN014 captive, source lifetime outside the three known ones",
           rf"event '{N}' is subscribed \(handler '{N}'\) to '{N}' — a DI (?!singleton "
           rf"\(application-lifetime\) |scoped |transient ){N} service that outlives "
           rf"'{N}'; the strong subscription promotes '{N}' to the source's lifetime, so "
           rf"it can never be collected — a captive/region escape \(leak, no release path\)",
           (), ("subscription token",), note=UNREACHABLE_DI_PHRASE),
    Branch("own014_di_lambda", "BR-V4", BRIDGE,
           "OWN014 captive on an inline lambda handler (the no-'-=' note)",
           rf"event '{N}' is subscribed \(handler '{N}'\) to '{N}' — a DI {N} that "
           rf"outlives '{N}'; the strong subscription promotes '{N}' to the source's "
           rf"lifetime, so it can never be collected — a captive/region escape "
           rf"\(leak, no release path{re.escape(LAMBDA_NOTE)}\)",
           (), ("subscription token",)),
    # OWN014, capture routing: the static vs named-source origin, and the note.
    Branch("own014_capture_static", "BR-V4", BRIDGE, "OWN014 capture of a static source",
           rf"event '{N}' is subscribed \(handler '{N}'\) to a static \(process-lived\) "
           rf"event source that outlives '{N}'; the strong subscription promotes '{N}' to "
           rf"the source's lifetime, so it can never be collected — a region escape "
           rf"\(leak, no release path\)", (), ("subscription token",)),
    Branch("own014_capture_named", "BR-V4", BRIDGE,
           "OWN014 capture of a named longer-lived source",
           rf"event '{N}' is subscribed \(handler '{N}'\) to a longer-lived source "
           rf"\('{N}'\) that outlives '{N}'; the strong subscription promotes '{N}' to the "
           rf"source's lifetime, so it can never be collected — a region escape "
           rf"\(leak, no release path\)", (), ("subscription token",),
           note=UNREACHABLE_CAPTURE_PHRASE),
    Branch("own014_capture_lambda", "BR-V4", BRIDGE,
           "OWN014 capture on an inline lambda handler (the no-'-=' note)",
           rf"event '{N}' is subscribed \(handler '{N}'\) to (?:a static \(process-lived\) "
           rf"event source|a longer-lived source \('{N}'\)) that outlives '{N}'; the strong "
           rf"subscription promotes '{N}' to the source's lifetime, so it can never be "
           rf"collected — a region escape \(leak, no release path"
           rf"{re.escape(LAMBDA_NOTE)}\)", (), ("subscription token",)),
    # the token kinds.
    Branch("token_timer", "BR-V4", BRIDGE, "timer wording",
           rf"timer '{N}' \(handler '{N}'\) is started but never stopped or detached — "
           rf"the running timer keeps '{N}' alive \(leak\)", (), ("timer",)),
    Branch("token_disposable_typed", "BR-V4", BRIDGE, "disposable field, `type` present",
           rf"IDisposable field '{N}' \(type '{N}'\) is never disposed — its owner "
           rf"'{N}' leaks it \(leak\)", (), ("disposable field",)),
    Branch("token_disposable_untyped", "BR-V4", BRIDGE, "disposable field, no `type`",
           rf"IDisposable field '{N}' is never disposed — its owner '{N}' leaks it "
           rf"\(leak\)", (), ("disposable field",)),
    Branch("token_local_disposable_typed", "BR-V4", BRIDGE,
           "local disposable, `type` present",
           rf"local IDisposable '{N}' \(type '{N}'\) is created but never disposed "
           rf"\(leak\)", (), ("disposable",)),
    Branch("token_local_disposable_untyped", "BR-V4", BRIDGE, "local disposable, no `type`",
           rf"local IDisposable '{N}' is created but never disposed \(leak\)",
           (), ("disposable",)),
    Branch("token_subscribe_injected", "BR-V4", BRIDGE,
           "ignored Subscribe() result, injected source",
           rf"the result of '{N}' is ignored — its IDisposable subscription is never "
           rf"disposed; the source is an injected dependency whose lifetime is unknown, "
           rf"so it may outlive and keep '{N}' alive \(possible leak\)",
           (), ("subscription token",)),
    Branch("token_subscribe_other", "BR-V4", BRIDGE,
           "ignored Subscribe() result, any other source",
           rf"the result of '{N}' is ignored — the IDisposable subscription is never "
           rf"disposed, leaking '{N}' \(leak\)", (), ("subscription token",)),
    Branch("pooled_never_returned", "BR-V4", BRIDGE,
           "pooled buffer never returned — the `pool` token wording AND the "
           "flow-local never-returned wording, one sentence (see `Branch`)",
           rf"pooled buffer '{N}' is rented but never returned to the pool \(leak\)",
           ("OWN001",), ("pooled buffer",)),
    Branch("token_subscription_injected", "BR-V4", BRIDGE,
           "plain `+=` subscription, injected source",
           rf"event '{N}' is subscribed \(handler '{N}'\) but never unsubscribed; its "
           rf"source is an injected dependency whose lifetime is unknown, so it may "
           rf"outlive and keep '{N}' alive \(possible leak\)", (), ("subscription token",)),
    Branch("token_subscription_injected_lambda", "BR-V4", BRIDGE,
           "plain `+=` subscription, injected source, inline lambda",
           rf"event '{N}' is subscribed \(handler '{N}'\) but never unsubscribed; its "
           rf"source is an injected dependency whose lifetime is unknown, so it may "
           rf"outlive and keep '{N}' alive \(possible leak{re.escape(LAMBDA_NOTE)}\)",
           (), ("subscription token",)),
    Branch("token_subscription_other", "BR-V4", BRIDGE,
           "plain `+=` subscription, any other source",
           rf"event '{N}' is subscribed \(handler '{N}'\) but never unsubscribed — the "
           rf"source keeps '{N}' alive \(leak\)", (), ("subscription token",)),
    Branch("token_subscription_other_lambda", "BR-V4", BRIDGE,
           "plain `+=` subscription, any other source, inline lambda",
           rf"event '{N}' is subscribed \(handler '{N}'\) but never unsubscribed — the "
           rf"source keeps '{N}' alive \(leak{re.escape(LAMBDA_NOTE)}\)",
           (), ("subscription token",)),
    # the advisory side paths.
    Branch("advisory_own050", "BR-V4", BRIDGE, "OWN050 unresolved-reference note",
           rf"cannot verify '{N}' — its declaring type is an unresolved reference "
           rf"\(build the project or pass references\); leakage analysis skipped",
           ("OWN050",)),
    Branch("advisory_own051", "BR-V4", BRIDGE, "OWN051 unverified-transfer note",
           rf"cannot verify whether '{N}' takes ownership of '{N}' \(inferred contract: "
           rf"{N}\); optimistically assuming it does — '{N}' is not checked past this call",
           ("OWN051",)),
    Branch("advisory_own052", "BR-V4", BRIDGE, "OWN052 degraded-inference note",
           rf"interprocedural summary inference failed \({N}\); method summaries "
           rf"skipped — cross-method ownership transfer was not checked this run",
           ("OWN052",)),
    # the messages the bridge does NOT synthesize: the DI and effect finders'
    # own `message` property (ownlang/di.py, ownlang/effects.py).
    Branch("di001_message", "BR-V4", CORE_ANALYSIS, "DI001 captive message (di.py)",
           rf"singleton '{N}' captures scoped service '{N}' \(captive dependency: {N}\)"
           rf"(?: \[consumed by {N} at {N}\])?", ("DI001",)),
    Branch("di002_message", "BR-V4", CORE_ANALYSIS, "DI002 weak-captive message (di.py)",
           rf"singleton '{N}' weakly captures scoped service '{N}' \(WeakReference\): .*"
           rf"(?: \[consumed by {N} at {N}\])?", ("DI002",)),
    Branch("di003_message", "BR-V4", CORE_ANALYSIS,
           "DI003 captured-transient message (di.py)",
           rf"singleton '{N}' captures transient IDisposable '{N}': .*"
           rf"(?: \[consumed by {N} at {N}\])?", ("DI003",)),
    Branch("di004_message", "BR-V4", CORE_ANALYSIS, "DI004 root-resolution message (di.py)",
           rf"singleton '{N}' resolves transient IDisposable '{N}' by hand from its "
           rf"injected root IServiceProvider .*", ("DI004",)),
    Branch("di005_message", "BR-V4", CORE_ANALYSIS, "DI005 scope-cache message (di.py)",
           rf"singleton '{N}' caches scoped service '{N}', resolved from a scope it "
           rf"creates, into a field: .*", ("DI005",)),
    Branch("eff001_message", "BR-V4", CORE_ANALYSIS, "EFF001 storm message (effects.py)",
           rf"effect re-runs on every render: dependency '{N}'.*", ("EFF001",)),
    # the protocol family (BR-P3). Bridge-synthesized like the matrix above,
    # but from a violation rather than a handle record, so it is its own
    # source: the analysis owns the verdict, the bridge owns the sentence.
    # Deliberately line-free — OwnAudit fingerprints on (path, rule, message).
    Branch("obl001_barrier_definite", "BR-V4", PROTOCOL,
           "OBL001: a barrier fires while the obligation is open on every path",
           rf"obligation '{N}' is still open when barrier '{N}' fires in '{N}' — "
           rf"'{N}' must happen first", ("OBL001",)),
    Branch("obl002_barrier_maybe", "BR-V4", PROTOCOL,
           "OBL002: a barrier fires while it is open on some path",
           rf"obligation '{N}' may still be open \(open on some path\) when barrier "
           rf"'{N}' fires in '{N}' — '{N}' must happen first", ("OBL002",)),
    Branch("obl003_exit_definite", "BR-V4", PROTOCOL,
           "OBL003: the method leaves while the obligation is open on every path",
           rf"obligation '{N}' is not closed when {N} — the object is published in its "
           rf"in-between state; close with '{N}' on every path \(a finally block covers "
           rf"the throw paths\)", ("OBL003",)),
    Branch("obl004_exit_maybe", "BR-V4", PROTOCOL,
           "OBL004: the method leaves while it is open on some path",
           rf"obligation '{N}' may not be closed \(open on some path\) when {N} — the "
           rf"object is published in its in-between state; close with '{N}' on every "
           rf"path \(a finally block covers the throw paths\)", ("OBL004",)),
    Branch("obl005_dead_rule", "BR-V4", PROTOCOL,
           "OBL005: a scoped protocol matched no reported method (advisory)",
           rf"protocol '{N}' is scoped to \[.*\] but no reported method matches — "
           rf"the rule is dead \(typo in scope\.methods\?\)", ("OBL005",)),
)

# The `_consumed_suffix` / `[singleton registered at …]` tails ride inside the
# analysis messages above; they are counted separately because each is its own
# degradation rule (an unknown ctor location drops the tail entirely).
MESSAGE_TAILS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("tail_consumed_typed", "` [consumed by the '<impl>' constructor at f:l]`",
     ("DI001", "DI002", "DI003"), r".* \[consumed by the '.*?' constructor at .*?:\d+\]"),
    ("tail_consumed_bare", "` [consumed by the constructor at f:l]` (impl type unknown)",
     ("DI001", "DI002", "DI003"), r".* \[consumed by the constructor at .*?:\d+\]"),
    ("tail_consumed_absent", "no consuming-constructor tail (location unknown)",
     ("DI001", "DI002", "DI003"), r"(?!.*\[consumed by ).*"),
    ("tail_registered", "` [singleton registered at f:l]` on DI004/DI005",
     ("DI004", "DI005"), r".* \[singleton registered at .*?:\d+\]"),
    ("tail_registered_absent", "no registration tail (the primary IS the registration)",
     ("DI004", "DI005"), r"(?!.*\[singleton registered at ).*"),
    ("tail_obl_exit_falls_off", "`the method falls off the end` — a leak off the end "
     "has no exit site to name", ("OBL003", "OBL004"),
     r".* when the method falls off the end — .*"),
    ("tail_obl_exit_via", "`'<method>' exits via return|throw` — the exit site is named",
     ("OBL003", "OBL004"), r".* when '.*?' exits via (?:return|throw) — .*"),
)


# --- BR-V5: the evidence slices ------------------------------------------
@dataclass(frozen=True)
class SliceFamily:
    """One `related`/`flow` shape: which field, which codes, how many steps, and
    the label each step must carry. A slice matching no family (or two) is a
    ledger problem, exactly as an unmatched message is."""

    id: str
    what: str
    field: str
    codes: tuple[str, ...]
    labels: tuple[str, ...]
    # `True` when `labels` is (first, repeated-middle, last) rather than an
    # exact per-step list — the DI path slices, whose middle hops repeat.
    variadic: bool = False
    #: see `Branch.note`.
    note: str = ""

    def matches(self, code: str, steps: list[list[object]]) -> bool:
        if self.codes and code not in self.codes:
            return False
        labels = [s[2] if len(s) == 3 else None for s in steps]
        if not all(isinstance(x, str) for x in labels):
            return False
        want: list[str]
        if self.variadic:
            first, middle, last = self.labels
            if len(labels) < 3:
                return False
            want = [first, *([middle] * (len(labels) - 2)), last]
        else:
            want = list(self.labels)
            if len(labels) != len(want):
                return False
        return all(re.fullmatch(w, str(g), re.DOTALL)
                   for w, g in zip(want, labels, strict=True))


DI_CODES = ("DI001", "DI002", "DI003", "DI004", "DI005")
OBL_CODES = ("OBL001", "OBL002", "OBL003", "OBL004", "OBL005")
# The four protocol step labels (BR-P3). Written out rather than matched with
# `.*`, because which STEP a slice carries is the thing the family distinguishes
# — a two-step slice built from the wrong pair would otherwise count as covered.
_OBL_OPENED = rf"obligation '{N}' opens here \({N}\)"
_OBL_BARRIER = rf"barrier '{N}' fires while it is open"
_OBL_EXIT = rf"the method exits here via {N} while it is open"
_OBL_LATE_CLOSE = r"closed here — after the barrier has already fired"
_CAPTOR = rf"singleton '{N}' \(captor\)"
_VIA = rf"via '{N}'"
_END = r"(?:captures scoped service|weakly captures scoped service|captures transient "
_END += rf"IDisposable|leaks transient IDisposable|caches scoped service) '{N}'"

SLICE_FAMILIES: tuple[SliceFamily, ...] = (
    SliceFamily("di_path_1", "DI retention path, one resolvable hop (the rest dropped)",
                "flow", DI_CODES, (_END,)),
    SliceFamily("di_path_2", "DI retention path, captor → captured", "flow", DI_CODES,
                (_CAPTOR, _END)),
    SliceFamily("di_path_3plus", "DI retention path with `via` hops", "flow", DI_CODES,
                (_CAPTOR, _VIA, _END), variadic=True),
    SliceFamily("di_consumer_related_typed", "DI consuming constructor, impl type known",
                "related", ("DI001", "DI002", "DI003"),
                (rf"consuming constructor of '{N}'",)),
    SliceFamily("di_consumer_related_bare", "DI consuming constructor, impl type unknown",
                "related", ("DI001", "DI002", "DI003"), (r"consuming constructor",)),
    SliceFamily("di004_registration_related", "DI004 registration beside the call site",
                "related", ("DI004",), (rf"registration of singleton '{N}'",)),
    SliceFamily("di005_registration_related", "DI005 registration beside the store site",
                "related", ("DI005",), (rf"registration of singleton '{N}'",)),
    SliceFamily("capture_escape_flow", "OWN014 subscribe site → source registration site",
                "flow", ("OWN014",),
                (rf"'{N}' subscribes '{N}' to '{N}' here",
                 rf"source '{N}' \({N}\) registered here — outlives '{N}'")),
    SliceFamily("effect_flow", "EFF001 re-run site → identity-mint site", "flow",
                ("EFF001",),
                (rf"effect re-runs here on '{N}'",
                 rf"'{N}' gets a fresh identity here — stabilise with useMemo")),
    *(SliceFamily(f"flowlocal_flow_{code.lower()}{'_pool' if pool else ''}",
                  f"flow-local {code} origin → violation"
                  f"{' (pooled)' if pool else ''}", "flow", (code,),
                  (rf"{'rented' if pool else 'acquired'} '{N}' here", re.escape(viol)))
      for pool in (False, True)
      for code, viol in (
          ("OWN002", "used here after it was released/returned"),
          ("OWN003", "released/returned here a second time"),
          ("OWN009", "may be used here after release on some path"),
          ("OWN025", "viewed here at full length, past what it was rented for"))
      if not (code == "OWN025" and not pool)),
    SliceFamily("protocol_flow_3", "OBL opened → barrier → late close", "flow",
                OBL_CODES, (_OBL_OPENED, _OBL_BARRIER, _OBL_LATE_CLOSE)),
    SliceFamily("protocol_flow_open_barrier",
                "OBL opened → barrier, no close after it", "flow", OBL_CODES,
                (_OBL_OPENED, _OBL_BARRIER)),
    SliceFamily("protocol_flow_open_exit", "OBL opened → the exit it leaked through",
                "flow", OBL_CODES, (_OBL_OPENED, _OBL_EXIT)),
    SliceFamily("protocol_flow_open_only",
                "OBL opened, and nothing else: a leak off the END anchors AT the open, "
                "so its second step would repeat the first", "flow", OBL_CODES,
                (_OBL_OPENED,)),
    SliceFamily("protocol_flow_exit_only",
                "OBL exit alone: the open carries no line (< 1) and its step is dropped",
                "flow", OBL_CODES, (_OBL_EXIT,)),
)

# The degradations BR-V5 names in prose. Counted as their own rows because a
# rule that only ever fires as "the slice is present" is a rule with no
# negative control.
@dataclass(frozen=True)
class Degradation:
    id: str
    what: str
    field: str
    codes: tuple[str, ...]
    kinds: tuple[str, ...] = ()
    handler_empty: bool | None = None
    #: matched against the finding's message when the code alone does not say
    #: which branch minted it — an OWN014 builds an escape slice only on the
    #: DI-sourced branch, and only the wording tells the two apart here.
    message: str | None = None


DEGRADATIONS: tuple[Degradation, ...] = (
    Degradation("di_consumer_related_dropped",
                "DI001/2/3 with no consuming-constructor related (line < 1)",
                "related", ("DI001", "DI002", "DI003")),
    Degradation("di004_related_dropped",
                "DI004 with no registration related (the primary IS the registration)",
                "related", ("DI004",)),
    Degradation("di005_related_dropped",
                "DI005 with no registration related (the primary IS the registration)",
                "related", ("DI005",)),
    Degradation("capture_escape_flow_dropped",
                "DI-sourced OWN014 with no escape slice (source registration unknown "
                "→ < 2 steps)", "flow", ("OWN014",), message=rf".* to '{N}' — a DI .*"),
    Degradation("capture_flow_absent",
                "OWN014 from the capture route: no escape slice by design "
                "(only the DI-sourced branch builds one)", "flow", ("OWN014",),
                message=r".* to (?:a static \(process-lived\) event source"
                        r"|a longer-lived source) .*"),
    Degradation("effect_flow_dropped",
                "EFF001 with no slice (a re-run or mint line < 1)", "flow", ("EFF001",)),
    Degradation("flowlocal_flow_absent",
                "OWN001 on a local/pooled record: a single-point finding, no slice "
                "by design", "flow", ("OWN001",), ("disposable", "pooled buffer")),
    Degradation("protocol_flow_absent",
                "an OBL finding with no slice at all: the anchorless OBL005 by design, "
                "and a leak whose only step has an unknown line", "flow", OBL_CODES),
)


# --- BR-V9: the rendered surfaces ----------------------------------------
@dataclass(frozen=True)
class RenderBranch:
    """One rendered-surface rule. `probe` names what a cp5.3 golden must
    contain for the row to count as covered; until that family exists every
    row reads uncovered, which is the honest state of BR-V9 at cp5.0."""

    id: str
    surface: str
    what: str


RENDER_BRANCHES: tuple[RenderBranch, ...] = (
    RenderBranch("human_line", "render", "`file:line: sev: [code] msg [resource: kind]`"),
    RenderBranch("human_severity", "render", "host severity in the human line"),
    RenderBranch("github_line", "github", "`::sev file=…,line=…,title=CODE::msg`"),
    RenderBranch("github_severity", "github", "host severity as the annotation level"),
    RenderBranch("github_esc_percent", "github", "`%` → `%25` in the message data"),
    RenderBranch("github_esc_cr", "github", "CR → `%0D` in the message data"),
    RenderBranch("github_esc_lf", "github", "LF → `%0A` in the message data"),
    RenderBranch("github_esc_prop_colon", "github", "`:` → `%3A` in a property value"),
    RenderBranch("github_esc_prop_comma", "github", "`,` → `%2C` in a property value"),
    RenderBranch("msbuild_line", "msbuild", "`file(line): sev CODE: msg [resource: kind]`"),
    RenderBranch("msbuild_severity", "msbuild", "host severity in the msbuild line"),
    RenderBranch("fallback_human", "render", "an unknown format falls back to the human line"),
    RenderBranch("sarif_envelope", "sarif", "`$schema` + `version` + one `run`"),
    RenderBranch("sarif_driver", "sarif", "`tool.driver.name` = Owen + `informationUri`"),
    RenderBranch("sarif_rules", "sarif", "rule catalogue: sorted, deduplicated + `TITLES`"),
    RenderBranch("sarif_result_order", "sarif",
                 "results keep the bridge's own order (BR-V8), never the catalogue's"),
    RenderBranch("sarif_schema_version", "sarif", "the `ownirSchemaVersion` driver property"),
    RenderBranch("sarif_level_note", "sarif", "an advisory renders as `note`"),
    RenderBranch("sarif_level_warning", "sarif", "an intrinsic warning renders as `warning`"),
    RenderBranch("sarif_level_error", "sarif", "a provable leak renders as `error`"),
    RenderBranch("sarif_level_host_warning", "sarif",
                 "`severity=warning` downgrades an error, never an advisory"),
    RenderBranch("sarif_region", "sarif", "`region.startLine` for a line ≥ 1"),
    RenderBranch("sarif_region_omitted", "sarif", "`region` omitted entirely for line < 1"),
    RenderBranch("sarif_start_column", "sarif", "`region.startColumn` only beside a line"),
    RenderBranch("sarif_uri_backslash", "sarif", "backslashes normalised in the artifact URI"),
    RenderBranch("sarif_properties", "sarif",
                 "`resourceKind` always; component/event/handler only when non-empty"),
    RenderBranch("sarif_related", "sarif", "`relatedLocations` from `related`"),
    RenderBranch("sarif_code_flows", "sarif", "`codeFlows` from the ordered `flow`"),
    RenderBranch("sarif_suppressions", "sarif",
                 "`suppressions` (`inSource` + justification) for a suppressed finding"),
    RenderBranch("sarif_empty", "sarif", "an empty finding list is a valid, empty run"),
    RenderBranch("refusal_error", "surface", "a bridge refusal projects as `{\"error\": …}`"),
)


#: The disposition every BR-V9 row carries while its family does not exist.
RENDER_FAMILY_PENDING = (
    "no fixture family yet — checkpoint 5.3 builds `tests/fixtures/verdict_renders/`; "
    "once it exists an uncovered row here is a missing control")
#: A rendered case pins a ROW, not a golden's own count, so its `all goldens`
#: and `replayed` columns are the same number: the family has no excluded set.


class InventoryError(Exception):
    """The tree is not in a state an inventory may be taken over."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Coverage:
    """One ledger row's measured coverage: findings (or slices) over all
    goldens, over the replayed set, and the cases that reach it."""

    id: str
    what: str
    detail: str
    total: int
    replayed: int
    cases: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class SurfaceInventory:
    messages: tuple[Coverage, ...]
    tails: tuple[Coverage, ...]
    slices: tuple[Coverage, ...]
    degradations: tuple[Coverage, ...]
    renders: tuple[Coverage, ...]
    render_family_exists: bool


def _load(p: Plan, fixdir: str) -> tuple[dict[str, list[dict[str, object]]], list[str]]:
    """case -> its golden's findings (a refused case contributes none)."""
    out: dict[str, list[dict[str, object]]] = {}
    problems: list[str] = []
    for name in sorted(p.cases):
        path = os.path.join(fixdir, f"{name}{GOLDEN_SUFFIX}")
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError) as e:
            problems.append(f"{name}: unreadable golden: {e}")
            continue
        if not isinstance(doc, dict):
            problems.append(f"{name}: golden is not a JSON object")
            continue
        findings = doc.get("findings")
        if findings is None:
            out[name] = []
            continue
        if not isinstance(findings, list) or not all(isinstance(x, dict) for x in findings):
            problems.append(f"{name}: golden findings must be an array of objects")
            continue
        out[name] = list(findings)
    return out, problems


def _tally(hits: dict[str, list[str]], excluded: set[str], ledger_id: str,
           what: str, detail: str, note: str = "") -> Coverage:
    cases = hits.get(ledger_id, [])
    return Coverage(ledger_id, what, detail, len(cases),
                    sum(1 for c in cases if c not in excluded),
                    tuple(sorted(set(cases))), note)


def compute_surface_inventory(p: Plan | None = None,
                              fixdir: str = FIXDIR) -> SurfaceInventory:
    """Match every committed golden against the three ledgers. Raises
    `InventoryError` on a plan problem, an unreadable golden, or a finding /
    slice the ledger cannot place — an inventory over a tree the ledger does
    not describe is exactly the stale number this module exists to prevent."""
    if p is None:
        p = plan(fixdir=fixdir)
    problems = list(p.problems)
    goldens, load_problems = _load(p, fixdir)
    problems.extend(load_problems)
    if problems:
        raise InventoryError(problems)
    excluded = set(p.excluded)

    msg_hits: dict[str, list[str]] = {}
    tail_hits: dict[str, list[str]] = {}
    slice_hits: dict[str, list[str]] = {}
    degradation_hits: dict[str, list[str]] = {}
    for case, findings in goldens.items():
        for f in findings:
            matched = [b.id for b in MESSAGE_BRANCHES if b.matches(f)]
            if len(matched) != 1:
                problems.append(
                    f"{case}: message matches {len(matched)} BR-V4 branches "
                    f"({', '.join(matched) or 'none'}): {f.get('message')!r}")
            for bid in matched:
                msg_hits.setdefault(bid, []).append(case)
            code = str(f.get("code", ""))
            message = str(f.get("message", ""))
            for tid, _what, codes, pattern in MESSAGE_TAILS:
                if code in codes and re.fullmatch(pattern, message, re.DOTALL):
                    tail_hits.setdefault(tid, []).append(case)
            for field in ("related", "flow"):
                steps = f.get(field)
                if not isinstance(steps, list):
                    problems.append(f"{case}: {field} is not an array")
                    continue
                if not steps:
                    for d in DEGRADATIONS:
                        if d.field != field or (d.codes and code not in d.codes):
                            continue
                        if d.kinds and f.get("kind") not in d.kinds:
                            continue
                        if d.handler_empty is not None and \
                                (f.get("handler") == "") != d.handler_empty:
                            continue
                        if d.message is not None and not re.fullmatch(
                                d.message, message, re.DOTALL):
                            continue
                        degradation_hits.setdefault(d.id, []).append(case)
                    continue
                typed = [s for s in steps if isinstance(s, list)]
                hit = [fam.id for fam in SLICE_FAMILIES
                       if fam.field == field and fam.matches(code, typed)]
                if len(hit) != 1:
                    problems.append(
                        f"{case}: a {code} {field} slice matches {len(hit)} BR-V5 "
                        f"families ({', '.join(hit) or 'none'}): {typed!r}")
                for fid in hit:
                    slice_hits.setdefault(fid, []).append(case)
    if problems:
        raise InventoryError(problems)

    rp = render_plan()
    problems.extend(f"rendered-surface ledger: {p_}" for p_ in rp.problems)
    render_exists = bool(rp.cases)
    render_hits: dict[str, list[str]] = {
        row: list(cases) for row, cases in pinned_rows(rp).items()
    }
    known_rows = {r.id for r in RENDER_BRANCHES}
    for unknown in sorted(set(render_hits) - known_rows):
        problems.append(f"rendered-surface case(s) {render_hits[unknown]} pin "
                        f"'{unknown}', which is not a BR-V9 ledger row")
    if problems:
        raise InventoryError(problems)

    return SurfaceInventory(
        messages=tuple(_tally(msg_hits, excluded, b.id, b.what, b.source, b.note)
                       for b in MESSAGE_BRANCHES),
        tails=tuple(_tally(tail_hits, excluded, tid, what, "wording tail")
                    for tid, what, _c, _p in MESSAGE_TAILS),
        slices=tuple(_tally(slice_hits, excluded, fam.id, fam.what, fam.field, fam.note)
                     for fam in SLICE_FAMILIES),
        degradations=tuple(_tally(degradation_hits, excluded, d.id, d.what, d.field)
                           for d in DEGRADATIONS),
        # Until cp5.3 builds the family there is nothing to match against, so
        # every row carries that as its disposition. The moment the family
        # exists the note goes away and an uncovered row reads as the missing
        # control it would then be.
        renders=tuple(_tally(render_hits, excluded, r.id, r.what, r.surface,
                             "" if render_exists else RENDER_FAMILY_PENDING)
                      for r in RENDER_BRANCHES),
        render_family_exists=render_exists,
    )
