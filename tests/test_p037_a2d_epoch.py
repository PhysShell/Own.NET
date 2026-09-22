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
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
EPOCH = ROOT / "docs" / "evidence" / "p037-a2d-epoch.json"
NOTE = ROOT / "docs" / "notes" / "p037-formal-kernel.md"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA7 = re.compile(r"^[0-9a-f]{7,40}$")

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
    bad = [k for k, v in shas.items() if not (isinstance(v, str) and SHA7.match(v))]
    check("predecessors-are-commits", not bad, f"{bad}")
    missing = [k for k, v in shas.items() if not commit_exists(str(v))]
    check("predecessors-present-in-this-checkout", not missing, f"{missing}")
    full = [k for k in ("population_T", "baseline_R", "a2_treatment_head", "a2_2_s_orchestrator",
                        "integration_head") if not SHA40.match(str(shas.get(k, "")))]
    check("load-bearing-predecessors-are-full-shas", not full, f"{full}")
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

    # The ORDER, enforced by git: the doors may not move before R_D names T_D.
    later: dict[str, Any] = doc["named_later"]
    integration = str(shas["integration_head"])
    if later.get("T_D") is None:
        moved = paths_differ(integration, "HEAD", t_paths) if commit_exists(integration) else False
        check("doors-untouched-until-T-D-is-named", not moved,
              "a treatment path moved on this branch before T_D and R_D exist")
        check("nothing-named-before-its-turn",
              all(v is None for v in later.values()), f"{later}")
    else:
        t_d = str(later["T_D"])
        check("T-D-present-and-descends-from-integration",
              SHA40.match(t_d) is not None and commit_exists(t_d) and is_ancestor(integration, t_d),
              t_d)
        check("T-D-doors-equal-integration-doors",
              commit_exists(t_d) and not paths_differ(integration, t_d, t_paths),
              "T_D must carry the doors of 6f9c373 unchanged")
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

    if _failures:
        print(f"RESULT: {len(_failures)} a2d-epoch check(s) failed")
        return 1
    print(f"RESULT: a2d epoch frozen consistently: {len(shas)} predecessor(s), "
          f"{len(t_paths)} treatment path(s), {len(roots)} instrument root(s), "
          f"T_D {'named' if later.get('T_D') else 'not yet named'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
