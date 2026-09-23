#!/usr/bin/env python3
"""P-037 A2.2-D: the door-registration epoch is frozen before it is implemented.

Runs no tool; asks git. docs/evidence/p037-a2d-epoch.json is the machine-readable
form of formal note 10.6.14: which epoch it closes and by what, which commits are
historical predecessors (present, in the recorded order, never a baseline), what
the a2d treatment is and which paths it may move, what the instrument closure of
the epoch is (roots minus the carved-out doors, the extractor frozen inside it),
the environment the epoch is measured in, the order of the steps, and the claims
preregistered for the after-measurement. This test holds the record, the note and
the tree to each other, and it holds the ORDER: until the R_D manifest names T_D,
no door may move on this branch (the treatment cannot start before its baseline
exists); once named, T_D's doors must equal the integration head's.

The freeze tightening (owner ruling after the freeze) is held here too: every
predecessor is a full 40-character SHA, the fact expectation is a closed machine
field (`measurement_policy.fact_diff`) and never prose, and the D production diff
inside the wide treatment units is bounded by `production_diff_gate`, whose
non-registration fields this test pins and whose tool (scripts/p037_door_diff_gate.py)
this test runs: its synthetic controls, and the gate itself on this branch.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EPOCH = ROOT / "docs" / "evidence" / "p037-a2d-epoch.json"
NOTE = ROOT / "docs" / "notes" / "p037-formal-kernel.md"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
GATE = ROOT / "scripts" / "p037_door_diff_gate.py"
FACT_DIFF_POLICIES = {"unchanged", "allowed_surfaces"}

# 10.6.14a (post-freeze adjudication): the gate above is scoped to the wide
# treatment units only (its own docstring says so), so a WITHIN_ALLOWLIST
# verdict backs nothing about the rest of the tree. It cannot by itself stand
# behind the wider claims_preregistered sentence "only the treatment paths
# and tests move". Three things outside t_paths/tests are legitimate against
# T_D: the record and the note this module's own docstring already treats as
# a pair of governance artifacts distinct from the measured tree (the epoch
# record's named_later and registration fields are how it is meant to be
# edited, already governed by the checks above; the formal note is where an
# adjudication like this one itself is written down) and exactly two
# deterministic docs/generated/ projections, whose own freshness
# tests/test_checkpoint_status.py mechanically enforces — so extending the
# tests/ ledger forces them to move too, a consequence the freeze's boundary
# text did not name. Logged as discovered after the freeze, not as evidence
# the exception was preregistered.
EPOCH_RECORD_PATH = "docs/evidence/p037-a2d-epoch.json"
FORMAL_NOTE_PATH = "docs/notes/p037-formal-kernel.md"
DOCS_GENERATED_ADJUDICATED = (
    "docs/generated/p022-cp1-census.md",
    "docs/generated/p022-coord-census.md",
)

# 10.7a (Phase B entry gate, discovered the same way 10.6.14a was: after the
# fact, not preregistered). `19af74c` opened a second epoch past A2.2-D's own
# closing head, on the same branch this test also runs on, and added its own
# top-level governance record (docs/evidence/p037-b-epoch.json is not
# EPOCH_RECORD_PATH -- that constant names A2.2-D's record specifically) plus
# a non-`tests/`-prefixed audit script. Both are outside every allowlist this
# test knew about, so `only-treatment-paths-tests-record-and-adjudicated-
# docs-move` has been silently red since `19af74c` itself, independent of any
# later Phase B commit -- confirmed by running this file's own check against
# T_D..19af74c alone. `formal/p037-kernel/` gets a full prefix exception, not
# a per-file list: like `tests/`, it is a non-production verification tree
# (its own README: "not wired to anything"), and Phase B is the first work
# ever touching its source rather than only reading it -- the same reasoning
# `tests/` already had, now extended to the other verification-only tree.
#
# B1 adds three more non-`tests/`-prefixed scripts (the Phase-B measurement
# instrument this tuple's own docstring above already anticipated the shape
# of): a production-diff gate, a provenance/population contract, and a
# difference classifier. Same reasoning as `p037_proof_boundary.py`'s own
# entry -- audit/measurement tooling, not `ownlang`/`rust/crates/own-ir`/
# `spec` treatment, landing in the same commit that defines it.
PHASE_B_GOVERNANCE_FILES = (
    "docs/evidence/p037-b-epoch.json",
    "docs/evidence/p037-b-ledger-assumptions.json",
    "docs/evidence/p037-b-ledger-harnesses.json",
    "scripts/p037_proof_boundary.py",
    "scripts/p037_b_production_diff_gate.py",
    "scripts/p037_evidence_b.py",
    "scripts/p037_b_classifier.py",
)
PHASE_B_PREFIXES = ("formal/p037-kernel/",)

# 10.6.14b: order step 6 (D after) lands its evidence as exactly these six
# files under docs/evidence/, and nothing about them is inferred or
# regenerated -- each is pinned to the exact sha256 the accepted external
# evidence run at treatment 4ba49c14d8777dc94554e5ec4208a9607fb89908
# already produced and the owner already reviewed. A path landing here with
# any other content is not this evidence; it stays a boundary violation, not
# a silent exception. This is the foreseen admission the order always named
# (unlike 10.6.14a, discovered only after the fact) -- it exists before any
# of the six paths does, not after.
D_AFTER_EVIDENCE_MANIFEST_PATH = "docs/evidence/p037-a2d-manifest.md"
D_AFTER_EVIDENCE_PINS = {
    "docs/evidence/p037-a2d-after-mos-repo.json":
        "4f084383f40a69891b3327499e88d145750681f558833fbb2d7ee2f9fe3f5bce",
    "docs/evidence/p037-a2d-after-mos-corpus.json":
        "e5a3d185dc85f52b5769eb3c5a44777806f27cec33836ac7ef00d924ba43b6e9",
    "docs/evidence/p037-a2d-after-verdict-python.json":
        "a4601b11cbf9398042b59be53f91751fa9ca1f6187c9628db1ae9d24f5a77ad7",
    "docs/evidence/p037-a2d-after-verdict-rust.json":
        "e6150987bcde281527452229bbd1615fc41a007d84143b93684a9556bbb8f0aa",
    "docs/evidence/p037-a2d-cumulative.json":
        "5aeaf5e149f26a5467f52896256cff2e16e3e5e5c4c9f11e2d85bd8aaa29cd0b",
    D_AFTER_EVIDENCE_MANIFEST_PATH:
        "18912d32707f66b704c78eabdd02e26cdbef9e046a3240ab48c4af9b42e13e7b",
}

_failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"ok[{name}]")
    else:
        _failures.append(name)
        print(f"FAIL[{name}]: {detail}")


def git(*args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout.strip()


def commit_exists(rev: str) -> bool:
    return git("cat-file", "-e", f"{rev}^{{commit}}")[0] == 0


def is_ancestor(older: str, newer: str) -> bool:
    return git("merge-base", "--is-ancestor", older, newer)[0] == 0


def paths_differ(a: str, b: str, paths: list[str]) -> bool:
    return git("diff", "--quiet", a, b, "--", *paths)[0] != 0


def git_blob_bytes(rev: str, path: str) -> bytes | None:
    """The exact committed bytes of `path` at `rev`, or None if absent there.

    Binary, not `git()`'s `text=True`: a content hash must see the bytes git
    actually stored, never a universal-newlines transcription of them."""
    proc = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT,
                          capture_output=True, check=False)
    return proc.stdout if proc.returncode == 0 else None


def gate_verdict(reference: str, head: str) -> tuple[int, str]:
    """Run the production-diff gate; (exit code, RESULT line). The record is read from `head`."""
    proc = subprocess.run([sys.executable, str(GATE), "check", "--reference", reference,
                           "--head", head, "--require", "allowlist"],
                          cwd=ROOT, capture_output=True, text=True, check=False)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(("RESULT:", "REFUSED:"))]
    return proc.returncode, lines[-1] if lines else proc.stdout.strip()[-200:]


def later_is_null(doc: dict[str, Any]) -> bool:
    return doc["named_later"].get("T_D") is None


def section_10_6_14(note: str) -> str:
    start = note.find("#### 10.6.14")
    return note[start:] if start >= 0 else ""


def run() -> int:
    doc: dict[str, Any] = json.loads(EPOCH.read_text(encoding="utf-8"))
    note = NOTE.read_text(encoding="utf-8")
    section = section_10_6_14(note)

    check("epoch-record-schema", doc.get("schema") == "p037-epoch/1" and doc.get("epoch") == "a2d",
          f"{doc.get('schema')} {doc.get('epoch')}")
    check("note-carries-10-6-14", bool(section) and "A2.2-D" in section[:200],
          "formal note lacks section 10.6.14")

    pred: dict[str, Any] = doc["predecessors"]
    shas = {k: v for k, v in pred.items() if k not in ("role", "environment")}
    bad = [k for k, v in shas.items() if not (isinstance(v, str) and SHA40.match(v))]
    check("predecessors-are-full-40-char-shas", not bad,
          f"{bad}: a short SHA is for people and stops being unique whenever git decides")
    missing = [k for k, v in shas.items() if not commit_exists(str(v))]
    check("predecessors-present-in-this-checkout", not missing, f"{missing}")
    if not missing:
        chain = [("population_T", "baseline_R"), ("baseline_R", "a2_treatment_head"),
                 ("a2_treatment_head", "a2_2_s_evidence"), ("a2_2_s_evidence", "a2_2_s_docs"),
                 ("a2_2_s_docs", "integration_head"), ("a2_2_s_orchestrator", "integration_head"),
                 ("a2_1_treatment_A_prime", "a2_1_after_S_prime"),
                 ("a2_1_after_S_prime", "main_merge_of_a2_1"),
                 ("main_merge_of_a2_1", "a2_treatment_head")]
        broken = [f"{a}->{b}" for a, b in chain if not is_ancestor(str(shas[a]), str(shas[b]))]
        check("predecessors-in-recorded-order", not broken, f"{broken}")
        check("this-branch-descends-from-the-integration-head",
              is_ancestor(str(shas["integration_head"]), "HEAD"),
              "HEAD does not descend from the integration head that closed a2")
    check("predecessors-are-history-not-baselines",
          "not a baseline" in str(pred.get("role", ""))
          and "M1" in str(pred.get("environment", "")),
          "the record must say what the predecessors are not")

    treatment: dict[str, Any] = doc["treatment"]
    instrument: dict[str, Any] = doc["instrument"]
    t_paths = [str(p) for p in treatment["paths"]]
    roots = [str(p) for p in instrument["roots"]]
    carved = [str(p) for p in instrument["carved_out"]]
    absent = [p for p in t_paths + roots if not (ROOT / p.rstrip("/")).exists()]
    check("closure-paths-exist", not absent, f"{absent}")
    covered = [p for p in carved if any(p == r or p.startswith(r) for r in roots)]
    check("carve-outs-lie-under-instrument-roots",
          covered == carved and set(carved) <= set(t_paths),
          f"carved {carved}, treatment {t_paths}")
    check("extractor-is-instrument-not-treatment",
          "frontend/roslyn/OwnSharp.Extractor/" in roots
          and not any(p.startswith("frontend/") for p in t_paths),
          "the sidecar's producer is frozen in a2d")
    check("spec-is-treatment", "spec/" in t_paths, "the vocabulary text moves with the doors")
    check("both-doors-are-treatment",
          "ownlang/ownir.py" in t_paths and "rust/crates/own-ir/" in t_paths, f"{t_paths}")
    # Every path the a2 instrument closure measured is still measured in a2d, as instrument or
    # as treatment: nothing falls out of the closure at the epoch boundary.
    a2_instrument = ["ownlang/", "rust/", "scripts/own-check.sh", "scripts/p037_evidence.py",
                     "scripts/p037_mos_snapshot.py", "scripts/p037_verdict_snapshot.py",
                     "scripts/shadow_compare.py"]
    dropped = [p for p in a2_instrument if p not in roots]
    check("a2-instrument-closure-not-dropped", not dropped, f"{dropped}")
    check("orchestrator-outside-the-closure",
          instrument.get("orchestrator", {}).get("path") == "scripts/p037_cumulative_evidence.py"
          and "outside" in str(instrument.get("orchestrator", {}).get("rule", ""))
          and "scripts/p037_cumulative_evidence.py" not in roots,
          "the orchestrator is pinned per run, not frozen in the closure")

    env: dict[str, Any] = doc["environment"]
    check("environment-id-named", env.get("id") == "P037_A2D_MEASUREMENT_M2"
          and env.get("id") in section, f"{env.get('id')} (must be in 10.6.14 too)")
    rules = " ".join(str(x) for x in env.get("qualification", []))
    check("environment-qualified-before-use",
          "profile" in rules and "recipe" in rules and "one measured workspace" in rules
          and "environment id recorded on every record" in rules,
          "qualification must name the profile, the recipe, one workspace root and the id")
    check("m1-is-not-a-control", "not a control" in str(env.get("m1_rule", ""))
          and "not retaken" in str(env.get("m1_rule", "")), f"{env.get('m1_rule')}")

    order = [str(s) for s in doc["order"]]
    heads = [s.split(":")[0].split(" ")[0] for s in order]
    check("order-freeze-tooling-TD-RD-treatment-after",
          heads == ["freeze", "tooling", "T_D", "R_D", "D", "D"] and "after" in order[-1][:8],
          f"{heads}")
    claims: dict[str, Any] = doc["claims_preregistered"]
    check("claims-preregistered-facts-unchanged",
          str(claims.get("facts", "")).startswith("UNCHANGED")
          and str(claims.get("mos", "")).startswith("UNCHANGED")
          and str(claims.get("verdicts", "")).startswith("UNCHANGED")
          and "refuse" in str(claims.get("fail_loud", "")),
          "a2d preregisters UNCHANGED facts, MOS and verdicts plus fail-loud doors")
    check("cross-epoch-comparison-forbidden",
          any("no a2d record is compared with an a2 record" in str(r)
              for r in doc.get("comparison_rules", [])),
          "the record must forbid comparing across the instrument boundary")

    # The fact expectation is a closed machine field, never a sentence to be parsed.
    policy = doc.get("measurement_policy")
    check("measurement-policy-is-a-closed-field",
          isinstance(policy, dict) and policy.get("fact_diff") in FACT_DIFF_POLICIES,
          f"{policy}")
    check("a2d-preregisters-fact-diff-unchanged",
          isinstance(policy, dict) and policy.get("fact_diff") == "unchanged",
          "the a2d claim is UNCHANGED facts: the extractor is instrument now")
    check("measurement-policy-value-is-not-the-prose",
          isinstance(policy, dict) and policy.get("fact_diff") != claims.get("facts"),
          "the driver must read the enum, not the claim sentence")

    # The production-diff gate: its non-registration fields are pinned here, so a D head
    # can extend the registrations by name but cannot widen the allowlist.
    gate: dict[str, Any] = doc.get("production_diff_gate", {})
    py_gate = gate.get("python", {})
    rs_gate = gate.get("rust", {})
    sp_gate = gate.get("spec", {})
    check("gate-tool-named-and-present",
          gate.get("tool") == "scripts/p037_door_diff_gate.py" and GATE.exists(),
          f"{gate.get('tool')}")
    check("gate-python-only-load-is-mutable",
          py_gate.get("unit") == "ownlang/ownir.py" and py_gate.get("mutable_top_level") == ["load"]
          and isinstance(py_gate.get("registered_helpers"), list),
          f"{py_gate}")
    check("gate-rust-strict-and-the-two-models",
          rs_gate.get("unit") == "rust/crates/own-ir/"
          and rs_gate.get("mutable_files") == ["src/strict.rs"]
          and rs_gate.get("mutable_items") == {"src/lib.rs": ["struct Function", "struct OwnIr"]}
          and set(rs_gate.get("registered_new_items", {})) <= {"src/lib.rs"}
          and rs_gate.get("frozen_files") == ["Cargo.toml", "src/protocol.rs", "src/pyrepr.rs",
                                              "src/span.rs"]
          and rs_gate.get("controls") == ["tests/"],
          f"{rs_gate}")
    check("gate-spec-only-the-live-contracts",
          sp_gate.get("unit") == "spec/"
          and sp_gate.get("mutable_files") == ["OwnIR.md", "ownir.schema.json"],
          f"{sp_gate}")
    crate = "rust/crates/own-ir/"
    production = [f[len(crate):] for f in git("ls-files", "--", crate)[1].splitlines()
                  if not f[len(crate):].startswith("tests/")]
    covered = (set(rs_gate.get("mutable_files", [])) | set(rs_gate.get("mutable_items", {}))
               | set(rs_gate.get("frozen_files", [])))
    check("gate-covers-every-production-file-of-the-crate",
          set(production) == covered, f"tracked {sorted(production)} vs policy {sorted(covered)}")
    new_items = rs_gate.get("registered_new_items", {}).values()
    registrations_empty = (py_gate.get("registered_helpers") == []
                           and all(v == [] for v in new_items))
    check("gate-registrations-are-empty-until-D-registers",
          registrations_empty or not later_is_null(doc),
          "nothing is registered before the treatment exists")
    selftest = subprocess.run([sys.executable, str(GATE), "selftest"], cwd=ROOT,
                              capture_output=True, text=True, check=False)
    check("gate-selftest-controls-behave", selftest.returncode == 0,
          "\n".join(ln for ln in selftest.stdout.splitlines() if ln.startswith("FAIL")))

    # The ORDER, enforced by git: the doors may not move before R_D names T_D.
    later: dict[str, Any] = doc["named_later"]
    integration = str(shas["integration_head"])
    if later.get("T_D") is None:
        moved = paths_differ(integration, "HEAD", t_paths) if commit_exists(integration) else False
        check("doors-untouched-until-T-D-is-named", not moved,
              "a treatment path moved on this branch before T_D and R_D exist")
        check("nothing-named-before-its-turn",
              all(v is None for v in later.values()), f"{later}")
        rc, line = gate_verdict(integration, "HEAD")
        check("gate-finds-this-head-identical-to-integration",
              rc == 0 and " IDENTICAL " in line, line)
    else:
        t_d = str(later["T_D"])
        check("T-D-present-and-descends-from-integration",
              SHA40.match(t_d) is not None and commit_exists(t_d) and is_ancestor(integration, t_d),
              t_d)
        check("T-D-doors-equal-integration-doors",
              commit_exists(t_d) and not paths_differ(integration, t_d, t_paths),
              "T_D must carry the doors of 6f9c373 unchanged")
        if commit_exists(t_d):
            rc, line = gate_verdict(integration, t_d)
            check("gate-finds-T-D-identical-to-integration",
                  rc == 0 and " IDENTICAL " in line, line)
            rc, line = gate_verdict(t_d, "HEAD")
            check("gate-holds-this-head-within-the-allowlist-of-T-D", rc == 0, line)

            changed = [f for f in git("diff", "--name-only", t_d, "HEAD")[1].splitlines() if f]
            allowed_prefixes = (*tuple(t_paths), "tests/", *PHASE_B_PREFIXES)
            governance = (EPOCH_RECORD_PATH, FORMAL_NOTE_PATH, *PHASE_B_GOVERNANCE_FILES)
            # R_D (order step 4) sits between T_D and the D treatment on this
            # branch and is a separately governed, already-accepted
            # evidence-only commit; "only the treatment paths and tests move"
            # describes step 5, not step 4. Identified by the commit that
            # added its own manifest rather than hardcoded, so this stays
            # correct without independently tracking R_D's SHA.
            r_d_files: set[str] = set()
            r_d_manifest = later.get("R_D_manifest")
            if isinstance(r_d_manifest, str):
                added = git("log", "--diff-filter=A", "--format=%H", "--", r_d_manifest)[1]
                added_shas = added.splitlines()
                if added_shas:
                    r_d_files = {f for f in git("diff", "--name-only", t_d, added_shas[0])[1]
                                .splitlines() if f}
            check("R-D-diff-is-evidence-only",
                  all(f.startswith("docs/evidence/") for f in r_d_files) if r_d_files else True,
                  f"{sorted(f for f in r_d_files if not f.startswith('docs/evidence/'))}")

            # 10.6.14b: a changed path pinned in D_AFTER_EVIDENCE_PINS is
            # excepted only when its committed bytes hash to the pinned
            # value -- landing anything else at that path is still a
            # violation, not a silent pass.
            d_after_changed = {f for f in changed if f in D_AFTER_EVIDENCE_PINS}
            d_after_mismatched = sorted(
                f for f in d_after_changed
                if hashlib.sha256(git_blob_bytes("HEAD", f) or b"").hexdigest()
                != D_AFTER_EVIDENCE_PINS[f])
            check("D-after-evidence-pins-match-exactly",
                  not d_after_mismatched, f"{d_after_mismatched}")
            d_after_ok = d_after_changed - set(d_after_mismatched)

            outside = [f for f in changed if f not in governance
                      and not f.startswith(allowed_prefixes)
                      and f not in DOCS_GENERATED_ADJUDICATED
                      and f not in r_d_files
                      and f not in d_after_ok]
            check("only-treatment-paths-tests-record-and-adjudicated-docs-move",
                  not outside, f"{outside}")

            d_after_evidence = later.get("D_after_evidence")
            if d_after_evidence is not None:
                check("D-after-evidence-named-correctly",
                      d_after_evidence == D_AFTER_EVIDENCE_MANIFEST_PATH
                      and (ROOT / D_AFTER_EVIDENCE_MANIFEST_PATH).exists(),
                      f"{d_after_evidence}")
            moved_docs = [f for f in DOCS_GENERATED_ADJUDICATED if f in changed]
            if moved_docs:
                render_check = subprocess.run(
                    [sys.executable, "scripts/render_checkpoint_status.py", "--check"],
                    cwd=ROOT, capture_output=True, text=True, check=False)
                check("adjudicated-docs-projections-are-not-stale",
                      render_check.returncode == 0,
                      "\n".join(render_check.stdout.splitlines()[-10:]))
                check("adjudicated-docs-projections-track-a-tests-only-source",
                      paths_differ(t_d, "HEAD", ["tests/fixtures/ownir_validation.json"]),
                      "the two admitted docs/generated files moved without their "
                      "tests/ ledger source moving")
        manifest = later.get("R_D_manifest")
        check("R-D-manifest-named-with-T-D",
              isinstance(manifest, str) and (ROOT / manifest).exists()
              and t_d in (ROOT / manifest).read_text(encoding="utf-8"),
              f"{manifest}")

    named = [k for k in ("population_T", "baseline_R", "a2_treatment_head", "a2_2_s_evidence",
                         "integration_head") if str(shas[k])[:7] not in section]
    check("note-names-the-predecessors", not named, f"10.6.14 lacks {named}")
    unnamed_paths = [p for p in t_paths if p not in section]
    check("note-names-the-treatment-paths", not unnamed_paths, f"10.6.14 lacks {unnamed_paths}")
    check("note-names-the-gate-and-the-policy-field",
          "production_diff_gate" in section and "measurement_policy" in section
          and "p037_door_diff_gate.py" in section,
          "10.6.14 must carry the tightening: the gate and the closed policy field")

    if _failures:
        print(f"RESULT: {len(_failures)} a2d-epoch check(s) failed")
        return 1
    print(f"RESULT: a2d epoch frozen consistently: {len(shas)} predecessor(s), "
          f"{len(t_paths)} treatment path(s), {len(roots)} instrument root(s), "
          f"T_D {'named' if later.get('T_D') else 'not yet named'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
