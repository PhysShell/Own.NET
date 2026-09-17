#!/usr/bin/env python3
"""P-022 — controls on the wiring that makes the merge gate a status check.

    ci-not-applicable       a tree without the frozen T0 passes, and says why
    ci-applies-in-full      a tree with it is judged by every predicate
    ci-refusal-survives     a refusal from the gate is still a refusal here
    ci-co-change-refused    the gate may not change in the merge that brings the contract
    ci-gate-repair-allowed  repairing the gate on its own is ordinary work
    ci-no-base-is-stated    without a base the co-change rule says it did not run
    ci-misuse-is-two        a commit that does not exist is misuse, not a verdict
    ci-gate-files-exist     every file the co-change rule watches is really there
    ci-workflow-names       the workflow names the contexts a ruleset must require
    ci-workflow-derives-t0  the workflow hard-codes no path the tools already own
    control-inventory       this list and the executed set are the same set

The applicability rule is the one that makes a required check possible at all:
without it the gate refuses every pull request in the repository, including the
one that adds it. The co-change rule is the one that makes it worth requiring:
a pull request runs its own copy of the workflow, so a branch could otherwise
carry the freeze and a weakened gate together and be judged by the gate it
brought with it.

Run:  python tests/test_step7_mergegate_ci.py
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "step7"))
sys.path.insert(0, str(ROOT / "tests"))

import mergegate_ci as ci  # noqa: E402
import test_step7_mergegate as mgt  # noqa: E402

WORKFLOW = ROOT / ".github/workflows/p022-merge-gate.yml"
CONTEXTS = ("P-022 merge gate controls", "P-022 merge gate")

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


def guarded(check: str, control: Callable[[], None]) -> None:
    try:
        control()
    except Exception as exc:
        fail(check, f"the control raised {type(exc).__name__}: {exc}")


def run(*args: str) -> tuple[int, str]:
    """The wrapper's exit code and everything it said, captured. A green run that
    prints REFUSED teaches readers to skim past refusals."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = ci.main(list(args))
    return rc, out.getvalue()


def wired(tmp: Path, name: str, **kwargs: object) -> tuple[Path, str, str]:
    """A repository, the commit that carries T0, and the commit before it.

    `world()` builds its tree in two commits: the first carries the instrument
    and the tools, the second adds T0 and the bindings. That first commit is
    exactly the shape of a base branch that does not yet carry the contract.
    """
    repo, head = mgt.world(tmp, name=name, **kwargs)
    return repo, head, head + "^"


def control_not_applicable() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, _, before = wired(Path(raw), "na")
        rc, said = run("--repo", str(repo), "--commit", before)
        if rc != 0:
            fail("ci-not-applicable", f"a tree with no frozen contract was refused: {said[:160]}")
            return
        if "not applicable" not in said:
            fail("ci-not-applicable", f"it passed without saying why: {said[:160]}")
            return
    ok("ci-not-applicable",
       "with no T0 in the tree no merge can make the frozen contract reachable, so the check "
       "passes and names the reason — otherwise it would refuse every pull request in the repo")


def control_applies_in_full() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, head, before = wired(Path(raw), "full")
        rc, said = run("--repo", str(repo), "--commit", head, "--base", before)
        if rc != 0:
            fail("ci-applies-in-full", f"a satisfying tree was refused: {said[:200]}")
            return
        missing = [c for c in ("t0_frozen_and_authorized", "instrument_matches_t0",
                               "steps_4_5_6_rebound", "step7_machinery_enforces")
                   if c not in said]
        if missing:
            fail("ci-applies-in-full", f"the wrapper did not report {missing}")
            return
    ok("ci-applies-in-full",
       "the moment a tree carries T0 every predicate runs and is reported by name")


def control_refusal_survives() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, head, before = wired(Path(raw), "stale", rebound=False)
        rc, said = run("--repo", str(repo), "--commit", head, "--base", before)
        if rc != 1 or "REFUSED" not in said:
            fail("ci-refusal-survives",
                 f"a stale binding came back as rc={rc}: {said[:200]}")
            return
    ok("ci-refusal-survives",
       "the wrapper adds rules, it does not soften the ones underneath: a stale binding is "
       "still exit 1")


def control_co_change_refused() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, head, before = wired(Path(raw), "cochange")
        # the branch brings the contract and its own copy of the gate at once
        attacked = mgt.commit_tree(repo, {
            ci.GATE_FILES[0]: "# a gate that says yes\n",
            ci.GATE_FILES[2]: "name: P-022 merge gate\n"})
        rc, said = run("--repo", str(repo), "--commit", attacked, "--base", before)
        if rc != 1:
            fail("ci-co-change-refused",
                 "a merge carrying both the freeze and a rewritten gate was allowed")
            return
        if ci.GATE_FILES[0] not in said:
            fail("ci-co-change-refused", f"refused without naming the changed file: {said[:200]}")
            return
        _ = head
    ok("ci-co-change-refused",
       "a guard that arrives together with what it guards is not a guard; the refusal names "
       "every gate file the merge rewrites")


def control_gate_repair_allowed() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, head, _ = wired(Path(raw), "repair")
        # the contract is already in the base and does not move; only the gate does
        repaired = mgt.commit_tree(repo, {ci.GATE_FILES[0]: "# a repaired gate\n"})
        rc, said = run("--repo", str(repo), "--commit", repaired, "--base", head)
        if rc != 0:
            fail("ci-gate-repair-allowed",
                 f"an ordinary repair of the gate was refused: {said[:200]}")
            return
        if "gate_unchanged" not in said:
            fail("ci-gate-repair-allowed", f"it passed without saying so: {said[:200]}")
            return
    ok("ci-gate-repair-allowed",
       "when the contract does not move, changing the gate is ordinary work and stays "
       "possible — the rule is about co-change, not about freezing the gate forever")


def control_no_base_is_stated() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, head, _ = wired(Path(raw), "nobase")
        rc, said = run("--repo", str(repo), "--commit", head)
        if rc != 0:
            fail("ci-no-base-is-stated", f"a satisfying tree was refused: {said[:200]}")
            return
        if "did not run" not in said:
            fail("ci-no-base-is-stated",
                 f"a pass with no base did not say the co-change rule was skipped: {said[:200]}")
            return
    ok("ci-no-base-is-stated",
       "a manual run cannot pose as a full one: without a base the wrapper says the co-change "
       "rule did not run rather than implying it held")


def control_misuse_is_two() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, _, _ = wired(Path(raw), "misuse")
        rc, said = run("--repo", str(repo), "--commit", "f" * 40)
        if rc != 2:
            fail("ci-misuse-is-two", f"a commit that does not exist returned {rc}: {said[:160]}")
            return
    ok("ci-misuse-is-two",
       "a question that could not be asked is exit 2, never a verdict — the same three codes "
       "the step-7 tools already use")


def control_gate_files_exist() -> None:
    missing = [p for p in ci.GATE_FILES if not (ROOT / p).exists()]
    if missing:
        fail("ci-gate-files-exist",
             f"the co-change rule watches {missing}, which are not in this repository; a "
             "renamed file would be watched by nobody")
        return
    ok("ci-gate-files-exist",
       f"all {len(ci.GATE_FILES)} watched files exist: {', '.join(ci.GATE_FILES)}")


def control_workflow_names() -> None:
    if not WORKFLOW.exists():
        fail("ci-workflow-names", f"{WORKFLOW.name} does not exist")
        return
    text = WORKFLOW.read_text(encoding="utf-8")
    absent = [c for c in CONTEXTS if f"name: {c}" not in text]
    if absent:
        fail("ci-workflow-names",
             f"the workflow declares no job named {absent}; a ruleset requiring that context "
             "would wait forever on a check nothing reports")
        return
    if "mergegate_ci.py" not in text:
        fail("ci-workflow-names", "the workflow does not run the wrapper")
        return
    ok("ci-workflow-names",
       f"the workflow declares exactly the contexts a ruleset must require: {', '.join(CONTEXTS)}")


def control_workflow_derives_t0() -> None:
    """The workflow must not carry a second copy of a path the tools own."""
    import mergegate as mg
    text = WORKFLOW.read_text(encoding="utf-8")
    if mg.T0_PATH in text:
        fail("ci-workflow-derives-t0",
             f"the workflow hard-codes {mg.T0_PATH}; applicability would then be decided in two "
             "places that can drift apart")
        return
    ok("ci-workflow-derives-t0",
       "applicability is decided once, in the tool that owns T0_PATH; the workflow only runs it")


def control_inventory() -> None:
    import re
    listed = set(re.findall("^    (ci-[a-z0-9-]+|control-inventory) +[^ ]", __doc__ or "",
                            re.MULTILINE))
    executed = {name for name, _ in CONTROLS}
    if listed != executed:
        fail("control-inventory",
             f"listed but not executed: {sorted(listed - executed)}; executed but not listed: "
             f"{sorted(executed - listed)}")
        return
    ok("control-inventory", f"{len(executed)} controls listed, {len(executed)} executed")


CONTROLS: list[tuple[str, Callable[[], None]]] = [
    ("ci-not-applicable", control_not_applicable),
    ("ci-applies-in-full", control_applies_in_full),
    ("ci-refusal-survives", control_refusal_survives),
    ("ci-co-change-refused", control_co_change_refused),
    ("ci-gate-repair-allowed", control_gate_repair_allowed),
    ("ci-no-base-is-stated", control_no_base_is_stated),
    ("ci-misuse-is-two", control_misuse_is_two),
    ("ci-gate-files-exist", control_gate_files_exist),
    ("ci-workflow-names", control_workflow_names),
    ("ci-workflow-derives-t0", control_workflow_derives_t0),
    ("control-inventory", control_inventory),
]


def main() -> int:
    for name, control in CONTROLS:
        guarded(name, control)
    print()
    print(f"merge gate wiring controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
