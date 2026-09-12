#!/usr/bin/env python3
"""#263-A calibration — step 6, the training preregistration and its scope combiner.

Step 6 fixes the protocol of a training collection that has not happened. It
contains no clock, no observation, no fitted constant and no selected N.

    training-scope-purity        the combiner is pure and holds no value
    training-scope-admissible    Q_p is READ OFF the frozen selector, not recomputed
    training-scope-intersection  smallest common rung, or NO_COMMON_N with no number
    training-scope-refusals      a missing rung or stratum stops rather than shrinks
    training-prereg-shape        the artifact is protocol, never a result
    training-prereg-bindings     all three digests equal the live ones
    training-prereg-universe     the declared universe is the instrument's own
    training-no-incidental-measurement  no workflow can reach a clock while step 7 is shut

`training-scope-admissible` is the load-bearing one. The margin `(1 + G)` must be
applied exactly once, inside the frozen `select_n`, so the control perturbs the
`limit` the frozen function reported and requires the combiner's answer to move.
A combiner that recomputed the margin itself would ignore that and pass.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_training_prereg.py
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "calibration"))
sys.path.insert(0, str(ROOT / "scripts" / "training"))
sys.path.insert(0, str(ROOT / "tests"))

import perf_baseline as pb  # noqa: E402
import policy as pol  # noqa: E402
import scope as sc  # noqa: E402
from test_calibration_freeze import implementation_digest  # noqa: E402

PREREG = ROOT / "docs" / "evidence" / "calibration" / "p022-263a-training-preregistration.json"
FREEZE = ROOT / "docs" / "evidence" / "calibration" / "p022-263a-policy-freeze.json"
CONSTANTS = ROOT / "docs" / "evidence" / "calibration" / "p022-263a-design-constants.json"
SCOPE_SOURCE = ROOT / "scripts" / "training" / "scope.py"
SCOPE_ROOT = "scripts/training/"
# A committed pre-step-6 report, used ONLY as a witness of which cells the frozen
# instrument emits. It is excluded from U as training data and is not read as one.
UNIVERSE_WITNESS = (ROOT / "docs" / "evidence" / "historical"
                    / "p022-263a-calibration-run-a.linux.json")

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


def _constants() -> pol.DesignConstants:
    c = json.loads(CONSTANTS.read_text(encoding="utf-8"))["constants"]
    return pol.DesignConstants.from_committed(
        q=tuple(c["q"]), m=tuple(c["M"]), r_runs=c["R_runs"],
        n_ladder=c["N_ladder"], g=tuple(c["G"]))


def _selection(widths: dict[int, int], constants: pol.DesignConstants) -> dict[str, object]:
    """A real frozen-selector result: one cell of unit duration, envelope a_abs = width."""
    envelopes = {n: pol.Envelope(n=n, a_abs=Fraction(w), r_rel=Fraction(0))
                 for n, w in widths.items()}
    reference = {n: [Fraction(1)] for n in widths}
    return pol.select_n(envelopes, reference, constants)


def control_purity() -> None:
    tree = ast.parse(SCOPE_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in list(node.args.defaults) + [d for d in node.args.kw_defaults if d]:
                if isinstance(default, ast.Constant) and isinstance(default.value, (int, float)):
                    problems.append(f"{node.name} carries the numeric default {default.value!r}")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                mutable = isinstance(node.value, (ast.List, ast.Dict, ast.Set))
                if isinstance(target, ast.Name) and mutable:
                    problems.append(f"module-level mutable {target.id}")
    allowed = {"__future__", "collections.abc", "fractions", "policy"}
    if imported - allowed:
        problems.append(f"imports outside the permitted set: {sorted(imported - allowed)}")
    if problems:
        fail("training-scope-purity", "; ".join(problems))
    else:
        ok("training-scope-purity",
           f"imports are {sorted(imported)} and nothing else; no numeric default and no "
           "module-level mutable state; no clock, no filesystem, no randomness")


def control_admissible(c: pol.DesignConstants) -> None:
    problems: list[str] = []
    sel = _selection({5: 100, 15: 10, 45: 10}, c)
    q = sc.admissible_rungs(sel, c, stratum="t")
    if q != (15, 45):
        problems.append(f"Q is {q}, expected (15, 45) for widths 100/10/10 at G=1/10")
    if sel["selected_n"] not in q:
        problems.append("the stratum's own frozen pick is not in its own admissible set")

    # The margin must be applied ONCE, inside the frozen selector. Perturb the limit
    # the frozen function reported: a combiner that recomputed (1 + G) itself would
    # ignore this and answer the same.
    tightened = dict(sel)
    tightened["limit"] = pol.as_pair(Fraction(10))          # exactly the best width
    q_tight = sc.admissible_rungs(tightened, c, stratum="t")
    if q_tight != (15, 45):
        problems.append(f"tightening the limit to the best width gave {q_tight}")
    loosened = dict(sel)
    loosened["limit"] = pol.as_pair(Fraction(1000))
    if sc.admissible_rungs(loosened, c, stratum="t") != (5, 15, 45):
        problems.append("loosening the reported limit did not widen the admissible set, so "
                        "the combiner is not reading the frozen limit at all")

    zero_g = pol.DesignConstants.from_committed(q=(19, 20), m=(2, 1), r_runs=5,
                                                n_ladder=[5, 15, 45], g=(0, 1))
    tight = _selection({5: 100, 15: 10, 45: 20}, zero_g)
    if sc.admissible_rungs(tight, zero_g, stratum="t") != (15,):
        problems.append("at G = 0 the admissible set is not exactly the argmin")

    if problems:
        fail("training-scope-admissible", "; ".join(problems))
    else:
        ok("training-scope-admissible",
           "Q is read off the frozen selector's own widths and limit: perturbing that "
           "limit moves the answer, G = 0 gives exactly the argmin, and each stratum's "
           "own frozen pick is always inside its own set")


def control_intersection(c: pol.DesignConstants) -> None:
    problems: list[str] = []
    lin = _selection({5: 100, 15: 10, 45: 10}, c)        # Q = (15, 45)
    win = _selection({5: 100, 15: 50, 45: 10}, c)        # Q = (45,)
    r = sc.combine({"linux": lin, "windows": win}, c, strata=("linux", "windows"))
    if r["outcome"] != sc.OUTCOME_SELECTED or r.get("selected_n") != 45:
        problems.append(f"expected SELECTED n=45, got {r['outcome']} {r.get('selected_n')}")
    if r["q_common"] != (45,):
        problems.append(f"q_common is {r['q_common']}")

    # Disjoint: max of the per-stratum picks would name a rung admissible on neither.
    a = _selection({5: 10, 15: 100, 45: 60}, c)          # Q = (5,)
    b = _selection({5: 60, 15: 100, 45: 10}, c)          # Q = (45,)
    r2 = sc.combine({"linux": a, "windows": b}, c, strata=("linux", "windows"))
    if r2["outcome"] != sc.OUTCOME_NO_COMMON_N:
        problems.append(f"disjoint strata gave {r2['outcome']}")
    if "selected_n" in r2:
        problems.append("NO_COMMON_N carries a selected_n key, so a caller reading it "
                        "blindly proceeds on a number the rule did not select")
    worst = max(int(str(a["selected_n"])), int(str(b["selected_n"])))
    qa, qb = sc.admissible_rungs(a, c, stratum="a"), sc.admissible_rungs(b, c, stratum="b")
    if worst in qa and worst in qb:
        problems.append("the max-of-picks counterexample no longer demonstrates anything")

    # Order: the smallest common rung, never the stratum's own pick.
    both = _selection({5: 10, 15: 10, 45: 10}, c)        # Q = (5, 15, 45)
    r3 = sc.combine({"linux": both, "windows": both}, c, strata=("linux", "windows"))
    if r3.get("selected_n") != 5:
        problems.append("with every rung common the smallest was not chosen: "
                        f"{r3.get('selected_n')}")

    if problems:
        fail("training-scope-intersection", "; ".join(problems))
    else:
        ok("training-scope-intersection",
           "the smallest rung admissible on both strata wins; disjoint sets stop at "
           f"NO_COMMON_N with no selected_n key, where max-of-picks would have named "
           f"n={worst}, which is admissible on neither")


def control_refusals(c: pol.DesignConstants) -> None:
    good = _selection({5: 100, 15: 10, 45: 10}, c)
    missing = dict(good)
    missing["widths"] = {5: pol.as_pair(Fraction(100)), 15: pol.as_pair(Fraction(10))}
    cases = [
        ("one stratum only", lambda: sc.combine({"linux": good}, c, strata=("linux",))),
        ("a stratum named twice",
         lambda: sc.combine({"linux": good}, c, strata=("linux", "linux"))),
        ("selections and strata disagree",
         lambda: sc.combine({"linux": good}, c, strata=("linux", "windows"))),
        ("a rung missing from a stratum", lambda: sc.admissible_rungs(missing, c, stratum="t")),
        ("no widths mapping", lambda: sc.admissible_rungs(
            {"limit": pol.as_pair(Fraction(1))}, c, stratum="t")),
        ("a float width", lambda: sc.admissible_rungs(
            {"widths": {5: 1.0, 15: 1.0, 45: 1.0}, "limit": pol.as_pair(Fraction(1))},
            c, stratum="t")),
        ("a width that is not a reduced pair", lambda: sc.admissible_rungs(
            {"widths": {5: (2, 4), 15: (1, 1), 45: (1, 1)}, "limit": pol.as_pair(Fraction(1))},
            c, stratum="t")),
    ]
    problems = []
    for name, call in cases:
        verdict = _refusal(call)
        if verdict:
            problems.append(f"{name}: {verdict}")
    if problems:
        fail("training-scope-refusals", "; ".join(problems))
    else:
        ok("training-scope-refusals",
           f"all {len(cases)} malformed scopes refused BY NAME, including a float width "
           "and a rung that was never measured")


def _refusal(call: object) -> str:
    """Empty when the call refused by name. Anything else is the defect.

    An earlier draft caught bare `Exception` and scored that as a refusal, so a
    `KeyError` from a guard that had been deleted read exactly like the guard
    working. That is the defect this PR has now recorded seven times: a control
    that cannot tell a traceback from a finding. A crash is reported here, never
    counted as a refusal.
    """
    try:
        call()  # type: ignore[operator]
    except (sc.ScopeRefused, pol.PolicyRefused):
        return ""
    except Exception as exc:                      # reported, never swallowed
        return f"crashed with {type(exc).__name__} instead of refusing by name: {exc}"
    return "accepted rather than refused"


def control_prereg_shape(art: dict[str, object]) -> None:
    permitted = {"artifact", "anchor_commit", "bindings", "design_constants", "stratification",
                 "universe", "collection_protocol", "order", "run_identity_required_fields",
                 "identity_drift_rule", "abort_semantics", "exactly_one_collection",
                 "future_procedure", "holdout", "forbidden_in_step_6", "ratified_by",
                 "step_7_collection", "admissibility_of_observations"}
    problems: list[str] = []
    if set(art) != permitted:
        problems.append(f"keys are {sorted(set(art) ^ permitted)} away from the permitted set")

    forbidden_keys = {"A_abs", "R_rel", "a_abs", "r_rel", "selected_n", "selected_N",
                      "envelope", "envelopes", "widths", "measurements", "median_ns",
                      "elapsed_ns", "fitted"}

    def keys(node: object) -> list[str]:
        if isinstance(node, dict):
            return list(node) + [k for v in node.values() for k in keys(v)]
        if isinstance(node, list):
            return [k for item in node for k in keys(item)]
        return []

    def floats(node: object) -> list[object]:
        if isinstance(node, dict):
            return [f for v in node.values() for f in floats(v)]
        if isinstance(node, list):
            return [f for item in node for f in floats(item)]
        return [node] if isinstance(node, float) else []

    present = sorted(set(keys(art)) & forbidden_keys)
    if present:
        problems.append(f"keys naming a fitted or measured quantity: {present}; step 6 "
                        "preregisters a protocol and produces no result of it")
    if floats(art):
        problems.append(f"floating-point values: {floats(art)}")
    if art.get("ratified_by") != "owner":
        problems.append("ratified_by is not 'owner'")
    if problems:
        fail("training-prereg-shape", "; ".join(problems))
    else:
        ok("training-prereg-shape",
           f"{len(permitted)} permitted top-level keys, no key naming a fitted or measured "
           "quantity anywhere, and no float")


def control_prereg_bindings(art: dict[str, object]) -> None:
    problems: list[str] = []
    b = art.get("bindings")
    if not isinstance(b, dict):
        fail("training-prereg-bindings", "bindings is not an object")
        return
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    constants = json.loads(CONSTANTS.read_text(encoding="utf-8"))

    if b.get("policy_implementation_digest") != freeze.get("policy_implementation_digest"):
        problems.append("the bound policy digest is not the one step 4 froze")
    live = pb.harness_digest()
    if b.get("measurement_harness_digest") != live:
        problems.append(f"the bound harness digest is not the live {live[:12]}")
    if art.get("design_constants") != constants.get("constants"):
        problems.append("the echoed design constants are not the step 5 artifact's")

    rc, out = _git("ls-tree", "-r", "--long", "-z", "HEAD", "--", SCOPE_ROOT)
    if rc != 0:
        problems.append("git could not list the training scope root at HEAD")
    else:
        entries = []
        for record in out.decode("utf-8").split("\0"):
            if not record.strip():
                continue
            meta, path = record.split("\t", 1)
            _mode, _kind, sha, _size = meta.split()
            if path.endswith(".py"):
                entries.append((path, _git("cat-file", "blob", sha)[1]))
        if not entries:
            problems.append(f"{SCOPE_ROOT} contains no committed *.py at HEAD")
        else:
            # The step 4 framing, imported rather than restated: a second copy of
            # the byte layout would only ever prove the two copies agree.
            recomputed = implementation_digest(entries)
            if b.get("training_scope_implementation_digest") != recomputed:
                problems.append(f"the bound scope digest is not the {recomputed[:12]} that "
                                f"{len(entries)} committed file(s) hash to under that "
                                "framing")
    if problems:
        fail("training-prereg-bindings", "; ".join(problems))
    else:
        ok("training-prereg-bindings",
           "all three digests bind: policy to what step 4 froze, harness to the live "
           "instrument, and the scope combiner to its own committed bytes")


def _git(*args: str) -> tuple[int, bytes]:
    proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    return proc.returncode, proc.stdout


def control_prereg_universe(art: dict[str, object]) -> None:
    """The declared universe must be the instrument's own, not a number I typed."""
    u = art.get("universe")
    if not isinstance(u, dict):
        fail("training-prereg-universe", "universe is not an object")
        return
    problems: list[str] = []
    manifest = pb.load_manifest()
    workloads = manifest[0] if isinstance(manifest, tuple) else manifest
    calibration = sorted(w.id for w in workloads if not w.decisive)
    if sorted(u.get("calibration_workloads", [])) != calibration:
        problems.append(f"declared workloads are not the manifest's {calibration}")
    if list(u.get("rungs", [])) != [r.id for r in pb.RUNGS]:
        problems.append(f"declared rungs are not the instrument's {[r.id for r in pb.RUNGS]}")
    if tuple(u.get("regimes", [])) != pb.D7_REGIMES:
        problems.append(f"declared regimes are not {list(pb.D7_REGIMES)}")

    witness = json.loads(UNIVERSE_WITNESS.read_text(encoding="utf-8"))
    cells = witness.get("cells")
    if not isinstance(cells, list):
        problems.append("the universe witness carries no cells")
    else:
        if u.get("expected_cells_per_stratum") != len(cells):
            problems.append(f"declared {u.get('expected_cells_per_stratum')} cells per stratum "
                            f"but the instrument emits {len(cells)}")
        seen_workloads = sorted({str(c["workload"]) for c in cells})
        if seen_workloads != calibration:
            problems.append(f"the witness covers {seen_workloads}, not the declared universe")
        identity = sorted({tuple(sorted(set(c) & {"rung", "engine", "workload", "regime"}))
                           for c in cells})
        if identity != [("engine", "regime", "rung", "workload")]:
            problems.append("the emitted cells do not carry the four-part identity")
    if problems:
        fail("training-prereg-universe", "; ".join(problems))
    else:
        ok("training-prereg-universe",
           f"{u.get('expected_cells_per_stratum')} cells per stratum, over the manifest's "
           f"{len(calibration)} calibration workloads, the instrument's {len(pb.RUNGS)} rungs "
           "and both regimes, each carrying the frozen four-part identity")


WORKFLOWS = ROOT / ".github" / "workflows"
# Each guarded entrypoint, and the file that must still define its flag. Without the
# second half a rename would make this control pass by finding nothing, which is the
# proxy-instead-of-the-thing failure it exists to avoid.
MEASUREMENT_ENTRYPOINTS = (
    ("perf_baseline.py", "--calibrate", ROOT / "scripts" / "perf_baseline.py"),
    ("runner.py", "--measure", ROOT / "scripts" / "round7" / "runner.py"),
)


def _shell_lines(text: str) -> list[str]:
    """Workflow lines that could execute. A comment cannot, so it is not an invocation."""
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def control_no_incidental_measurement(art: dict[str, object]) -> None:
    """While step 7 is shut, no workflow may hold a path to a measurement entrypoint.

    Step 6 preregisters a protocol and takes no observation. That claim was false on
    the commit that first made it: the legacy calibration pair still ran in CI, timing
    forty cells per platform on every push and uploading them. A preregistration that
    fixes "exactly one collection" while CI gathers numbers on a timer has an epistemic
    side channel whatever anyone means to do with the output. This is the mechanical
    version of the rule, so the next person to add a convenient diagnostic finds the
    suite red rather than a reviewer's memory.
    """
    problems: list[str] = []
    if str(art.get("step_7_collection", "")).upper() != "NOT AUTHORISED":
        ok("training-no-incidental-measurement",
           "step 7 is recorded as authorised, so this control no longer constrains the "
           "workflows and the collection protocol governs instead")
        return

    for _name, flag, source in MEASUREMENT_ENTRYPOINTS:
        if not source.exists():
            problems.append(f"{source.name} is gone, so guarding {flag} proves nothing")
        elif f'"{flag}"' not in source.read_text(encoding="utf-8"):
            problems.append(f"{source.name} no longer defines {flag}; this guard would pass "
                            "by finding a flag that has been renamed")

    if not WORKFLOWS.is_dir():
        problems.append(f"{WORKFLOWS} is not a directory, so no workflow could be read")
    else:
        scanned = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
        if not scanned:
            problems.append("no workflow files were found, so this scanned nothing")
        for workflow in scanned:
            for line in _shell_lines(workflow.read_text(encoding="utf-8")):
                for name, flag, _source in MEASUREMENT_ENTRYPOINTS:
                    if name in line and flag in line:
                        problems.append(f"{workflow.name} can reach {name} {flag}: {line.strip()}")
    if problems:
        fail("training-no-incidental-measurement", "; ".join(problems))
    else:
        ok("training-no-incidental-measurement",
           f"step 7 is shut and no executable line of any workflow reaches "
           f"{', '.join(f'{n} {f}' for n, f, _ in MEASUREMENT_ENTRYPOINTS)}; both flags still "
           "exist, so the guard is not passing on a rename")


def run() -> int:
    constants = _constants()
    control_purity()
    control_admissible(constants)
    control_intersection(constants)
    control_refusals(constants)
    if not PREREG.exists():
        fail("training-prereg-shape", f"{PREREG.name} does not exist")
    else:
        art = json.loads(PREREG.read_text(encoding="utf-8"))
        control_prereg_shape(art)
        control_prereg_bindings(art)
        control_prereg_universe(art)
        control_no_incidental_measurement(art)
    print()
    print(f"training preregistration controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
