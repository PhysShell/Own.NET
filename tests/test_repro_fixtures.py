#!/usr/bin/env python3
"""Shadow-mode infrastructure, layer 0 (P-022 step 7a, #260/#269): the
same-input capture and the reproduction artifact.

**Infrastructure for shadow mode, not shadow mode.** Nothing here compares two
engines' end diagnostics; that comparison is #260's acceptance and is blocked
on #259 (cp5 and 4b). What this family proves is the two things a comparison
would otherwise have to assume: that both engines can *name the same input*,
and that a reproduction has *one format*.

Two committed surfaces, one ledger:

* **`tests/fixtures/repro/digests.json`** — the canonical hash of **every**
  facts document in the shared corpora (`tests/fixtures/{ownir,lowered,
  summaries,verdicts}`) plus the canonical-form controls beside the manifest.
  This is the same-input capture surface: the Rust `own-shadow` recomputes
  every digest from the same documents with zero Python
  (`rust/crates/own-shadow/tests/repro.rs`), so "both engines saw the same
  input" is a checked fact. The array is sorted by case name and each record
  depends on nothing but its own case — the insertion-stability rule (P-022
  discipline §4) is asserted here on **both** its lines, `churn == 0` and
  `delta == 1`.
* **`tests/fixtures/repro/<case>.repro.json`** — full reproduction artifacts
  for a curated set of cases, listed exhaustively in the manifest with what
  each one pins. The artifact set is deliberately *not* the whole corpus:
  every artifact embeds its input plus three layer documents that already
  live in the tree, so committing 81 of them would triple the corpus to prove
  nothing the curated set does not. The **properties** (determinism,
  byte-exact round-trip, self-verification, tamper refusal) run over all 81
  swept cases; the **goldens** pin the format on the curated set, and the
  Rust side replays those byte-for-byte.

What each check is evidence for:

* `render_repro` twice, byte-identical — determinism of the capture.
* `json.loads(golden)` re-rendered == the golden bytes — the artifact
  round-trips byte-for-byte through parse/serialize, which is what makes it a
  *format* rather than one program's output.
* `verify_repro(golden) == []` — the artifact describes itself: the digest and
  byte length are recomputed from the embedded document.
* one changed character in the embedded document — the digest changes and
  `verify_repro` refuses, naming the mismatch. Run over every swept case, not
  a sample.

Python is authoritative: `python tests/test_repro_fixtures.py --write`
regenerates `digests.json` and every artifact.

Run:  python tests/test_repro_fixtures.py            (verify)
      python tests/test_repro_fixtures.py --write    (regenerate)
      python tests/run_tests.py                      (runs it in the suite)
"""

from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ownlang.repro import (
    CANONICAL_ALGORITHM,
    REPRO_VERSION,
    ReproError,
    canonical_hash,
    load_document,
    project_repro,
    render_repro,
    verify_repro,
)

HERE = os.path.dirname(os.path.abspath(__file__))
FIXDIR = os.path.join(HERE, "fixtures", "repro")
MANIFEST = os.path.join(FIXDIR, "manifest.json")
DIGESTS = os.path.join(FIXDIR, "digests.json")

# The shared facts corpora, swept automatically in a fixed order. `repro` is
# this family's own directory: the canonical-form controls the other corpora
# have no reason to carry.
CORPORA: tuple[tuple[str, str], ...] = (
    ("ownir", os.path.join(HERE, "fixtures", "ownir")),
    ("lowered", os.path.join(HERE, "fixtures", "lowered")),
    ("summaries", os.path.join(HERE, "fixtures", "summaries")),
    ("verdicts", os.path.join(HERE, "fixtures", "verdicts")),
    ("repro", FIXDIR),
)


def _facts_cases(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(n[: -len(".facts.json")] for n in os.listdir(directory)
                  if n.endswith(".facts.json"))


def _manifest() -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                         list[dict[str, Any]], list[str]]:
    """(synthetic case entries, domain-refusal entries, artifact entries,
    ledger problems)."""
    problems: list[str] = []
    if not os.path.exists(MANIFEST):
        return [], [], [], [f"manifest missing: {MANIFEST}"]
    with open(MANIFEST, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("repro_version") != REPRO_VERSION:
        problems.append(
            f"manifest repro_version {data.get('repro_version')!r} != "
            f"emitter REPRO_VERSION {REPRO_VERSION}")
    synthetic = data.get("synthetic_cases", [])
    refusals = data.get("domain_refusals", [])
    artifacts = data.get("artifacts", [])
    for label, entries in (("synthetic_cases", synthetic), ("artifacts", artifacts)):
        if not isinstance(entries, list) or not entries:
            problems.append(f"manifest '{label}' must be a non-empty array")
            continue
        names: list[str] = []
        for e in entries:
            name, pins = e.get("name"), e.get("pins")
            if not (isinstance(name, str) and name):
                problems.append(f"{label}: entry without a name: {e!r}")
                continue
            names.append(name)
            if not (isinstance(pins, list) and pins
                    and all(isinstance(p, str) and p for p in pins)):
                problems.append(f"{label} '{name}': 'pins' must be a non-empty "
                                f"array of non-empty strings saying what the case "
                                f"is evidence FOR")
        if len(set(names)) != len(names):
            problems.append(f"{label} contains duplicate names")
    # The refusal ledger has its own shape: a reason, and the substring each
    # engine's refusal must carry (null on the Rust side where the two
    # parsers refuse for different reasons — see the entry's note).
    seen: list[str] = []
    if not isinstance(refusals, list) or not refusals:
        problems.append("manifest 'domain_refusals' must be a non-empty array")
    else:
        for e in refusals:
            name, reason = e.get("name"), e.get("reason")
            if not (isinstance(name, str) and name):
                problems.append(f"domain_refusals: entry without a name: {e!r}")
                continue
            seen.append(name)
            if not (isinstance(reason, str) and reason):
                problems.append(f"domain_refusals '{name}': 'reason' must say WHY the "
                                f"two engines cannot agree on this document")
            needle = e.get("python_error_contains")
            if not (isinstance(needle, str) and needle):
                problems.append(f"domain_refusals '{name}': 'python_error_contains' "
                                f"must be a non-empty substring of the refusal text")
        if len(set(seen)) != len(seen):
            problems.append("domain_refusals contains duplicate names")
    return list(synthetic), list(refusals), list(artifacts), problems


def _plan() -> tuple[dict[str, tuple[str, str]], dict[str, dict[str, Any]],
                     list[str], list[str]]:
    """The plan: capturable cases (name -> corpus label, facts path), the
    domain-refusal controls (name -> ledger entry), the curated artifact names,
    and the ledger problems. Names must be unique across every corpus — one
    digest ledger and one golden tree serve them all. A refusal control is
    deliberately NOT a capturable case: it has no digest, because the whole
    point is that neither engine can name it."""
    synthetic, refusals, artifacts, problems = _manifest()
    plan: dict[str, tuple[str, str]] = {}
    for label, directory in CORPORA:
        for name in _facts_cases(directory):
            if name in plan:
                problems.append(
                    f"case name '{name}' exists in BOTH the {plan[name][0]} and "
                    f"{label} corpora — names must be unique across the sweep")
                continue
            plan[name] = (label, os.path.join(directory, f"{name}.facts.json"))
    refusal_names = {e["name"] for e in refusals if isinstance(e.get("name"), str)}
    listed = sorted(e["name"] for e in synthetic if isinstance(e.get("name"), str))
    on_disk = [n for n in _facts_cases(FIXDIR) if n not in refusal_names]
    for missing in sorted(set(listed) - set(on_disk)):
        problems.append(f"manifest synthetic case '{missing}' has no "
                        f"{missing}.facts.json under fixtures/repro")
    for unlisted in sorted(set(on_disk) - set(listed)):
        problems.append(f"'{unlisted}.facts.json' is not in manifest.json — add "
                        f"the case to synthetic_cases (name, pins)")
    refusal_entries: dict[str, dict[str, Any]] = {}
    for e in refusals:
        name = e.get("name")
        if not isinstance(name, str):
            continue
        refusal_entries[name] = e
        path = os.path.join(FIXDIR, f"{name}.facts.json")
        if not os.path.exists(path):
            problems.append(f"domain_refusals '{name}' has no {name}.facts.json "
                            f"under fixtures/repro")
        # A refusal control must not also be a capturable case: `plan` swept
        # the directory, so remove it and say so if it was never there.
        plan.pop(name, None)
    artifact_names = [e["name"] for e in artifacts if isinstance(e.get("name"), str)]
    for phantom in sorted(set(artifact_names) - set(plan)):
        problems.append(f"manifest artifacts names '{phantom}', which is not a "
                        f"planned case")
    return plan, refusal_entries, sorted(artifact_names), problems


def _load(path: str) -> Any:
    """Read one facts document through the canonical loader — the domain is
    enforced on the LITERALS, which is the only place the reference can still
    tell `-0` from `0`."""
    with open(path, encoding="utf-8") as f:
        return load_document(f.read())


def _tamper(document: Any) -> Any:
    """A deep copy of `document` with exactly one changed character (or, when
    it holds no string, one changed integer) at the first leaf a depth-first
    walk reaches. Deterministic, so the refusal it provokes is reproducible.
    Returns `None` when the document has no mutable leaf at all."""
    changed = False

    def walk(value: Any) -> Any:
        nonlocal changed
        if changed:
            return value
        if isinstance(value, str) and value:
            changed = True
            head = "a" if value[0] != "a" else "b"
            return head + value[1:]
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            changed = True
            return value - 1 if value > 0 else value + 1
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value

    out = walk(copy.deepcopy(document))
    return out if changed else None


def _digest_records(plan: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    """The digest ledger's records, sorted by case name. Each record is a pure
    function of its own case — no ordinal, no neighbour — so inserting a case
    churns nothing (P-022 discipline §4)."""
    records: list[dict[str, Any]] = []
    for case in sorted(plan):
        corpus, path = plan[case]
        digest = canonical_hash(_load(path))
        records.append({
            "case": case,
            "corpus": corpus,
            "digest": digest["digest"],
            "bytes": digest["bytes"],
        })
    return records


def _render_digests(plan: dict[str, tuple[str, str]]) -> str:
    return json.dumps({
        "comment": (
            "The canonical hash of every shared facts document (P-022 step 7a, "
            "#260/#269). Generated: python tests/test_repro_fixtures.py --write. "
            "The Rust own-shadow recomputes every digest from the same documents "
            "with zero Python, which is what makes 'both engines saw the same "
            "input' a checked fact rather than an assumption. Records are sorted "
            "by case and depend on nothing but their own case, so inserting a "
            "case churns no existing record."),
        "repro_version": REPRO_VERSION,
        "algorithm": CANONICAL_ALGORITHM,
        "documents": _digest_records(plan),
    }, indent=2, ensure_ascii=False) + "\n"


# The negative controls, counted so the summary reports what actually ran
# rather than what the reader assumes did. Public because
# `scripts/render_checkpoint_status.py` derives the census from them rather
# than from a number somebody typed into a document.
STRUCTURAL_CONTROL_COUNT = 12
DOMAIN_BACKSTOP_COUNT = 5


def _forge(artifact: dict[str, Any], mutate: Any) -> Any:
    """A deep copy of `artifact` with one structural rule broken."""
    forged = copy.deepcopy(artifact)
    mutate(forged)
    return forged


def _structural_controls(artifact: dict[str, Any]) -> list[str]:
    """Negative controls for `verify_repro`: every structural rule it states
    must have a document that breaks exactly that rule and is refused for it.
    Without these, `verify_repro` could degrade to "recompute the digest" and
    every positive check would still pass — the shape P-022 discipline 2 is
    about (a rule with no control is a rule nothing tests)."""
    fails: list[str] = []

    def expect(label: str, needle: str, mutate: Any) -> None:
        problems = verify_repro(_forge(artifact, mutate))
        if not any(needle in p for p in problems):
            fails.append(f"verify_repro accepts {label} (expected a problem "
                         f"naming {needle!r}, got {problems})")

    def set_version(a: dict[str, Any]) -> None:
        a["repro_version"] = REPRO_VERSION + 1

    def add_member(a: dict[str, Any]) -> None:
        a["extra_member"] = 1

    def drop_layer(a: dict[str, Any]) -> None:
        del a["engines"][0]["layers"][1]

    def reorder_layers(a: dict[str, Any]) -> None:
        a["engines"][0]["layers"].reverse()

    def unknown_engine(a: dict[str, Any]) -> None:
        a["engines"][0]["id"] = "some-other-engine"

    def duplicate_engine(a: dict[str, Any]) -> None:
        a["engines"].append(copy.deepcopy(a["engines"][0]))

    def engines_out_of_order(a: dict[str, Any]) -> None:
        rust = copy.deepcopy(a["engines"][0])
        rust["id"] = "rust-own-bridge"
        a["engines"].insert(0, rust)

    def produced_with_error(a: dict[str, Any]) -> None:
        a["engines"][0]["layers"][0]["error"] = "an error beside a document"

    def refused_without_error(a: dict[str, Any]) -> None:
        layer = a["engines"][0]["layers"][0]
        layer["status"] = "refused"
        layer.pop("document", None)

    def drop_surface_version(a: dict[str, Any]) -> None:
        del a["engines"][0]["layers"][0]["surface_version"]

    def unknown_status(a: dict[str, Any]) -> None:
        a["engines"][0]["layers"][0]["status"] = "maybe"

    def drop_canonical(a: dict[str, Any]) -> None:
        del a["input"]["canonical"]

    expect("a wrong format version", "repro_version", set_version)
    expect("an unknown artifact member", "unknown artifact member", add_member)
    expect("a missing layer", "frozen layers", drop_layer)
    expect("layers out of the frozen order", "frozen layers", reorder_layers)
    expect("an unknown engine id", "frozen engine vocabulary", unknown_engine)
    expect("a repeated engine", "appears twice", duplicate_engine)
    expect("engines out of the frozen order", "out of the frozen order",
           engines_out_of_order)
    expect("a produced layer carrying an error", "carries an error",
           produced_with_error)
    expect("a refused layer without an error", "non-empty error text",
           refused_without_error)
    expect("a layer without surface_version", "surface_version is missing",
           drop_surface_version)
    expect("an unknown layer status", "is neither", unknown_status)
    expect("a missing canonical block", "input.canonical is missing",
           drop_canonical)
    return fails


def _domain_backstop_controls() -> list[str]:
    """`canonical_bytes` keeps a VALUE-level domain check behind
    `load_document`'s literal-level one, for a document that arrives already
    parsed (the observer API takes a dict). It needs its own control, or the
    backstop is untested code that a mutation would walk straight through."""
    fails: list[str] = []
    for label, value in (
        ("a float", {"x": 1.5}),
        ("an integer above the domain", {"x": 2**63}),
        ("an integer below the domain", {"x": -(2**63) - 1}),
        ("a non-string object key", {1: "x"}),
        ("a value of an unsupported type", {"x": {1, 2}}),
    ):
        try:
            canonical_hash(value)
        except ReproError:
            continue
        fails.append(f"canonical_hash accepts {label} — the value-level domain "
                     f"backstop is not enforcing the closed domain")
    return fails


def _artifact_goldens() -> set[str]:
    if not os.path.isdir(FIXDIR):
        return set()
    return {n[: -len(".repro.json")] for n in os.listdir(FIXDIR)
            if n.endswith(".repro.json")}


def _check_insertion_stability(plan: dict[str, tuple[str, str]],
                               records: list[dict[str, Any]]) -> list[str]:
    """P-022 discipline §4, both normative lines: inserting one synthetic
    member must churn **zero** existing records and add **exactly one**.
    Enforced here on the generator itself, in memory — the ledger this family
    commits is derived from a vocabulary (the swept corpora), which is exactly
    the shape the rule exists for."""
    probe = "zzz_insertion_probe_not_a_committed_case"
    if probe in plan:
        return [f"the insertion probe name '{probe}' collides with a real case"]
    widened = dict(plan)
    widened[probe] = ("repro", os.path.join(FIXDIR, "canonical_minimal.facts.json"))
    after = _digest_records(widened)
    before_by_case = {r["case"]: r for r in records}
    after_by_case = {r["case"]: r for r in after}
    churn = [c for c, r in before_by_case.items() if after_by_case.get(c) != r]
    delta = sorted(set(after_by_case) - set(before_by_case))
    problems: list[str] = []
    if churn:
        problems.append(f"insertion churn == {len(churn)}, must be 0 "
                        f"(first: {churn[:3]})")
    if delta != [probe]:
        problems.append(f"insertion delta == {delta}, must be exactly ['{probe}']")
    return problems


def run() -> int:
    plan, refusals, artifact_names, ledger_problems = _plan()
    # (check tag, detail) — the tag is what a mutation campaign attributes a
    # catch to; the detail is what a human needs to fix it.
    fails: list[tuple[str, str]] = [("ledger", m) for m in ledger_problems]
    if not plan and not fails:
        fails.append(("plan", "no cases planned (no *.facts.json under the swept corpora)"))

    # 1. Determinism of the capture, and of the canonical hash, over EVERY case.
    n_refused_layers = 0
    for case in sorted(plan):
        _corpus, path = plan[case]
        facts = _load(path)
        try:
            first = render_repro(facts)
        except ReproError as e:
            fails.append(("capture", f"{case}: not capturable: {e}"))
            continue
        if render_repro(_load(path)) != first:
            fails.append((
                "capture-determinism",
                f"{case}: the reproduction artifact is non-deterministic"
            ))
            continue
        if canonical_hash(facts) != canonical_hash(_load(path)):
            fails.append(("hash-determinism", f"{case}: the canonical hash is non-deterministic"))
            continue
        problems = verify_repro(json.loads(first))
        if problems:
            fails.append((
                "capture-verify",
                f"{case}: the freshly built artifact does not verify: {problems}"
            ))
            continue
        # 2. A changed character in the input is a REFUSAL, not a different
        #    reproduction — over every case, not a sample.
        tampered = _tamper(facts)
        if tampered is None:
            fails.append((
                "tamper-control",
                f"{case}: has no leaf to tamper — the tamper control cannot run, so this case "
                f"proves nothing about it"
            ))
            continue
        if canonical_hash(tampered)["digest"] == canonical_hash(facts)["digest"]:
            fails.append((
                "tamper-digest",
                f"{case}: a changed character did not change the digest"
            ))
            continue
        forged = json.loads(first)
        forged["input"]["document"] = tampered
        if not verify_repro(forged):
            fails.append((
                "tamper-refusal",
                f"{case}: an artifact whose embedded document was changed still verifies — the "
                f"digest is not a gate"
            ))
        n_refused_layers += sum(
            1 for e in json.loads(first)["engines"] for lyr in e["layers"]
            if lyr["status"] == "refused")

    # 3. The domain-refusal controls: documents NEITHER engine may name. The
    #    ledger is executable — the day this reference starts accepting one,
    #    the suite goes red demanding a decision rather than quietly widening
    #    the domain.
    for case in sorted(refusals):
        entry = refusals[case]
        path = os.path.join(FIXDIR, f"{case}.facts.json")
        if not os.path.exists(path):
            continue  # already reported by the ledger check
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            load_document(text)
        except ReproError as e:
            needle = entry.get("python_error_contains")
            if isinstance(needle, str) and needle not in str(e):
                fails.append((
                    "domain-refusal-reason",
                    f"{case}: refused, but not for the declared reason: expected {needle!r} in {e}"
                ))
        except json.JSONDecodeError as e:
            fails.append((
                "domain-refusal-kind",
                f"{case}: refused as malformed JSON ({e}) rather than as a domain violation — the "
                f"control no longer tests the domain rule it was written for"
            ))
        else:
            fails.append((
                "domain-refusal",
                f"{case}: the canonical loader ACCEPTS a document the ledger declares unnameable "
                f"({entry.get('reason')}); the control has rotted — promote it or record the "
                f"decision"
            ))

    # 4. The digest ledger is complete, in sync, and insertion-stable.
    records = _digest_records(plan) if plan else []
    if not os.path.exists(DIGESTS):
        fails.append((
            "digest-ledger",
            "digests.json missing; regenerate with 'python tests/test_repro_fixtures.py --write'"
        ))
    else:
        with open(DIGESTS, encoding="utf-8") as f:
            committed = f.read()
        if committed != _render_digests(plan):
            fails.append((
                "digest-ledger",
                "digests.json is stale (a corpus document changed, or a case was added/removed); "
                "regenerate with 'python tests/test_repro_fixtures.py --write' and re-run the Rust "
                "side (cd rust && cargo test)"
            ))
    fails += [("insertion-stability", m) for m in _check_insertion_stability(plan, records)]

    # 5. The curated artifacts: golden in sync, byte-exact round-trip, verified.
    for case in artifact_names:
        golden_path = os.path.join(FIXDIR, f"{case}.repro.json")
        if case not in plan:
            continue  # already reported by the ledger check
        expected = render_repro(_load(plan[case][1]))
        if not os.path.exists(golden_path):
            fails.append((
                "artifact-golden",
                f"{case}: artifact golden missing; regenerate with 'python "
                f"tests/test_repro_fixtures.py --write'"
            ))
            continue
        with open(golden_path, encoding="utf-8") as f:
            actual = f.read()
        if actual != expected:
            fails.append((
                "artifact-golden",
                f"{case}: artifact golden is stale (a layer output or the format changed); "
                f"regenerate with 'python tests/test_repro_fixtures.py --write' and re-run the "
                f"Rust side (cd rust && cargo test)"
            ))
            continue
        parsed = json.loads(actual)
        if json.dumps(parsed, indent=2, ensure_ascii=False) + "\n" != actual:
            fails.append((
                "artifact-roundtrip",
                f"{case}: the artifact does not round-trip byte-for-byte through parse/serialize"
            ))
        problems = verify_repro(parsed)
        if problems:
            fails.append((
                "artifact-verify",
                f"{case}: committed artifact does not verify: {problems}"
            ))
    for orphan in sorted(_artifact_goldens() - set(artifact_names)):
        fails.append((
            "artifact-orphan",
            f"{orphan}: orphaned artifact golden (not in the manifest's 'artifacts' ledger); "
            f"remove it or list the case"
        ))

    # 6. Negative controls for the two gates the positive checks cannot reach.
    n_structural = 0
    if artifact_names and artifact_names[0] in plan:
        reference = project_repro(_load(plan[artifact_names[0]][1]))
        controls = _structural_controls(reference)
        n_structural = STRUCTURAL_CONTROL_COUNT
        fails += [("structural-control", f"{artifact_names[0]}: {f_}") for f_ in controls]
    else:
        fails.append((
            "structural-control",
            "no artifact case available to drive the structural controls"
        ))
    fails += [("domain-backstop", m) for m in _domain_backstop_controls()]

    if fails:
        for check, detail in fails:
            print(f"FAIL[{check}]: repro fixture {detail}")
        return 1
    print(f"repro (shadow-mode infrastructure, layer 0) fixtures OK: "
          f"{len(plan)} documents captured and digest-pinned, "
          f"{len(artifact_names)} artifacts round-tripped and verified, "
          f"{n_refused_layers} refused layer envelope(s) across all captures, "
          f"{len(plan)} tamper controls refused, "
          f"{len(refusals)} domain-refusal controls held, "
          f"{n_structural} structural + {DOMAIN_BACKSTOP_COUNT} domain-backstop "
          f"controls refused")
    return 0


def write() -> int:
    plan, _refusals, artifact_names, problems = _plan()
    if problems:
        for p in problems:
            print(f"ERROR: {p}")
        return 1
    with open(DIGESTS, "w", encoding="utf-8") as f:
        f.write(_render_digests(plan))
    print(f"wrote {DIGESTS} ({len(plan)} documents)")
    for case in artifact_names:
        out = os.path.join(FIXDIR, f"{case}.repro.json")
        artifact = project_repro(_load(plan[case][1]))
        remaining = verify_repro(artifact)
        if remaining:
            print(f"ERROR: {case}: refusing to write an artifact that does not "
                  f"verify: {remaining}")
            return 1
        with open(out, "w", encoding="utf-8") as f:
            f.write(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {out}")
    for orphan in sorted(_artifact_goldens() - set(artifact_names)):
        path = os.path.join(FIXDIR, f"{orphan}.repro.json")
        os.remove(path)
        print(f"removed orphaned {path}")
    return 0


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        raise SystemExit(write())
    raise SystemExit(run())
