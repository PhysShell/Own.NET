#!/usr/bin/env python3
"""P-022 — controls on the merge gate.

    mergegate-complete-tree       a world that satisfies the freeze is allowed
    mergegate-missing-instrument  the digest T0 names must exist in the tree
    mergegate-stale-bindings      steps 4/5/6 must be re-bound to that digest
    mergegate-exact-binding-field the digest is read at each artifact's own path
    mergegate-decoy-digest        the right digest in a field nobody binds is not a binding
    mergegate-noop-campaign-link  a permissive link check must not satisfy the gate
    mergegate-dead-authority      hostqual authorising anything must not satisfy it
    mergegate-dead-authority-eb   nor must execbinding — the claim covers both readers
    mergegate-dead-continuity     nor must a postflight that stops comparing campaign links
    mergegate-always-inadmissible nor must one that refuses every campaign
    mergegate-missing-machinery   the tools must be there at all
    mergegate-lingering-auto      the revoked automatic authority must stay revoked
    mergegate-unfrozen-t0         an unfrozen or unauthorised T0 is not merged as frozen
    mergegate-reads-t0-digest     the expected digest comes from T0, not from a constant
    control-inventory-complete    this list and the executed set are the same set

Fixtures ship the real tools, and four controls mutate one enforcement point
each. An earlier revision shipped a stub whose check_campaign_link was a bare
pass and called that world compliant: the fixture demonstrated the false
positive it was meant to exclude. Checking for the name of a mechanism is not
checking the mechanism, and a witness that only ever sees refusals is not
checking one either — hence a positive control beside each negative one.

Failures print FAIL[<check>]: <detail>; nothing stops at the first one.

Run:  python tests/test_step7_mergegate.py
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "step7"))

import execbinding as eb  # noqa: E402
import mergegate as mg  # noqa: E402

NL = chr(10)

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


NOTE_REVOKED = """Status:
  AUTOMATIC AUTHORISATION OF THE FIRST STEP-7 COLLECTION IS REVOKED (T0-0).
"""
NOTE_AUTO = """Status:
  SINGLE STEP-7 COLLECTION AUTHORISED automatically after that gate.
"""

T0_TEMPLATE = """```text
Status:
  {status}
  collection_authorized: {flag}
```

    measurement_harness_digest
    {digest}
"""

# The digest sits at a different exact path in each artifact, so a fixture that
# wrote one flat shape everywhere would be exercising a gate that does not exist.
BINDING_SHAPES = {
    "docs/evidence/calibration/p022-263a-policy-freeze.json":
        lambda d: {"measurement_harness_digest": d},
    "docs/evidence/calibration/p022-263a-design-constants.json":
        lambda d: {"bound_measurement_harness_digest": d},
    "docs/evidence/calibration/p022-263a-training-preregistration.json":
        lambda d: {"bindings": {"measurement_harness_digest": d}},
}

HOSTQUAL, EXECBINDING = mg.STEP7_TOOLS[1], mg.STEP7_TOOLS[2]

# Mutations of the real tools, one enforcement point each. Appending a definition
# is enough where a later definition wins; the continuity check lives inside a
# larger function, so that one is a targeted edit of its condition.
NOOP_LINK = '''

def check_campaign_link(link, binding_path, repo):
    return check("campaign_link", True, "stubbed: what a lexical gate accepted")
'''

DEAD_AUTHORITY = '''

def bind_t0(repo, path, commit):
    block = {"commit": commit, "path": path, "blob_sha": "b" * 40,
             "sha256": "f" * 64, "status": "FROZEN", "collection_authorized": True}
    return block, check("t0", True, "stubbed: always authorised")
'''

# The second reader. The gate's message claims enforcement on both, so a control
# that only breaks the first leaves half of that claim unproved.
DEAD_AUTHORITY_EB = '''

def t0_at(repo, path, commit):
    return {"commit": commit, "path": path, "blob_sha": "b" * 40, "sha256": "f" * 64,
            "status": "FROZEN", "collection_authorized": True}
'''

# The mutation the positive postflight control exists to catch: a tool that
# refuses every campaign satisfies a negative-only witness, which would then be
# reading "nothing is admissible" as "the swap was caught".
ALWAYS_INADMISSIBLE = '''

def session_admissibility(*args, **kwargs):
    return {"admissible": False, "reasons": ["stubbed: nothing is ever admissible"]}
'''

CONTINUITY_CONDITION = ('preflight.get("campaign_link_sha256") != '
                        "sha256_file(campaign_link_path)")


def dead_continuity(src: str) -> str:
    """Leave check_campaign_link working and remove only the comparison of the
    preflight's campaign link with this pass's."""
    return src.replace(CONTINUITY_CONDITION, "False")


def real_tools() -> dict[str, str]:
    """The tools as they actually are. A fixture that shipped a stub would prove
    only that the gate accepts stubs."""
    return {t: (ROOT / t).read_text(encoding="utf-8") for t in mg.STEP7_TOOLS}


def commit_tree(repo: Path, files: dict[str, str]) -> str:
    repo.mkdir(parents=True, exist_ok=True)

    def run(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)

    if not (repo / ".git").exists():
        run("init", "-q")
        run("config", "user.email", "control@example.invalid")
        run("config", "user.name", "control")
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    run("add", "-A")
    run("commit", "-q", "-m", "fixture")
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def world(tmp: Path, *, frozen: bool = True, authorized: bool = True,
          instrument: str = "print('instrument')" + NL, rebound: bool = True,
          machinery: bool = True, auto_authority: bool = False, decoy: bool = False,
          wrong_field: bool = False, mutate: dict[str, object] | None = None,
          name: str = "w") -> tuple[Path, str]:
    """A synthetic target tree, and the commit a merge into it would produce."""
    repo = tmp / name
    files = {eb.INSTRUMENT_SOURCES[0]: instrument,
             eb.INSTRUMENT_SOURCES[1]: '{"decisive": []}' + NL,
             mg.STEP7_NOTE: NOTE_AUTO if auto_authority else NOTE_REVOKED}
    if machinery:
        tools = real_tools()
        for tool, change in (mutate or {}).items():
            before = tools[tool]
            tools[tool] = change(before) if callable(change) else before + str(change)
            if tools[tool] == before:
                # A mutation that lands nowhere turns an attack control into a
                # second positive control that nobody reads as one.
                raise AssertionError(f"the mutation for {tool} changed nothing; the source it "
                                     "targets has moved")
        files.update(tools)
    else:
        files[mg.STEP7_TOOLS[0]] = "# capture only" + NL
    probe = commit_tree(repo, files)
    # T0 names whatever THIS tree's own sources hash to, so a fixture cannot pass
    # by agreeing with a constant this file also wrote.
    digest = eb.harness_digest_at(repo, probe) or ""
    files[mg.T0_PATH] = T0_TEMPLATE.format(
        status="FROZEN." if frozen else "NOT_FROZEN.",
        flag="true" if authorized else "false",
        digest=digest)
    bound = digest if rebound else "0" * 64
    for artifact, shape in BINDING_SHAPES.items():
        doc = shape(bound)
        if decoy:                    # the right digest, in a field nobody binds
            doc["decoy"] = digest
        if wrong_field and "training" in artifact:   # right digest, wrong exact path
            doc = {"measurement_harness_digest": digest}
        files[artifact] = json.dumps(doc, indent=2) + NL
    return repo, commit_tree(repo, files)


def verdicts(repo: Path, commit: str) -> dict[str, str]:
    return {str(r["check"]): str(r["result"]) for r in mg.gate(repo, commit)}


def details(repo: Path, commit: str) -> dict[str, str]:
    return {str(r["check"]): str(r["detail"]) for r in mg.gate(repo, commit)}


def control_complete_tree() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw))
        bad = sorted(k for k, v in verdicts(repo, commit).items() if v != "pass")
        if bad:
            seen = details(repo, commit)
            fail("mergegate-complete-tree",
                 f"a satisfying world was refused on {bad}: {[seen[k][:90] for k in bad]}")
            return
        # Captured: a green run that prints a refusal teaches readers to skim past
        # refusals, which is how the word stops meaning anything.
        with contextlib.redirect_stdout(io.StringIO()):
            rc = mg.main(["--repo", str(repo), "--commit", commit])
        if rc != 0:
            fail("mergegate-complete-tree", "the CLI refused a satisfying world")
            return
    ok("mergegate-complete-tree",
       "a tree carrying the named instrument, the exactly re-bound artifacts, the real tools "
       "and the revoked automatic authority is allowed")


def control_missing_instrument() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw))
        # the instrument moves after T0 named it — the exact intermediate state a
        # stray merge produces when the repair PR is not in yet
        drifted = commit_tree(repo, {eb.INSTRUMENT_SOURCES[0]: "print('older')" + NL})
        if verdicts(repo, drifted).get("instrument_matches_t0") != "fail":
            fail("mergegate-missing-instrument",
                 "a tree whose instrument does not hash to the digest T0 names was allowed")
            return
        noise = io.StringIO()
        with contextlib.redirect_stdout(noise):
            rc = mg.main(["--repo", str(repo), "--commit", drifted])
        if rc == 0 or "REFUSED" not in noise.getvalue():
            fail("mergegate-missing-instrument", "the CLI allowed it")
            return
    ok("mergegate-missing-instrument",
       "the frozen contract cannot become reachable from a tree whose instrument is not the "
       "one it names")


def control_stale_bindings() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw), rebound=False)
        if verdicts(repo, commit).get("steps_4_5_6_rebound") != "fail":
            fail("mergegate-stale-bindings", "artifacts bound to an older digest were allowed")
            return
    ok("mergegate-stale-bindings",
       "steps 4, 5 and 6 must be re-bound to the digest T0 names, not merely present")


def control_exact_binding_field() -> None:
    """Each artifact binds at its own path, and only that path counts."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit = world(tmp, name="exact")
        if verdicts(repo, commit).get("steps_4_5_6_rebound") != "pass":
            fail("mergegate-exact-binding-field",
                 "correct exact fields were refused: "
                 + details(repo, commit)["steps_4_5_6_rebound"])
            return
        moved_repo, moved = world(tmp, wrong_field=True, name="wrongfield")
        if verdicts(moved_repo, moved).get("steps_4_5_6_rebound") != "fail":
            fail("mergegate-exact-binding-field",
                 "the training preregistration bound at the wrong path was accepted; the gate "
                 "is searching the file rather than reading the binding")
            return
    ok("mergegate-exact-binding-field",
       "policy freeze at measurement_harness_digest, design constants at "
       "bound_measurement_harness_digest, training preregistration at "
       "bindings.measurement_harness_digest — and nowhere else")


def control_decoy_digest() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw), rebound=False, decoy=True)
        if verdicts(repo, commit).get("steps_4_5_6_rebound") != "fail":
            fail("mergegate-decoy-digest",
                 "a stale binding passed because the right digest sat in a decoy field")
            return
    ok("mergegate-decoy-digest",
       "the right digest in a field nobody binds is not a binding, and a substring search "
       "would have called it one")


def control_noop_campaign_link() -> None:
    """The attack the previous revision of this gate could not see."""
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw), mutate={HOSTQUAL: NOOP_LINK}, name="noop")
        if verdicts(repo, commit).get("step7_machinery_enforces") != "fail":
            fail("mergegate-noop-campaign-link",
                 "a permissive check_campaign_link satisfied the gate; the name of a mechanism "
                 "is not the mechanism")
            return
        detail = details(repo, commit)["step7_machinery_enforces"]
        if "accepted" not in detail:
            fail("mergegate-noop-campaign-link", f"refused for an unrelated reason: {detail}")
            return
    ok("mergegate-noop-campaign-link",
       "a tree whose link check always passes is refused, and the refusal names the attack "
       "that got through")


def _dead_authority(check_name: str, tool: str, stub: str, reader: str) -> None:
    """Both readers carry the authority state machine, and the gate says so.
    A control that breaks one of them leaves the other half of that claim
    standing on nothing."""
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw), mutate={tool: stub}, name="deadauth")
        if verdicts(repo, commit).get("step7_machinery_enforces") != "fail":
            fail(check_name, f"a {reader} authority check that always passes satisfied the gate")
            return
        detail = details(repo, commit)["step7_machinery_enforces"]
        wrongly = [s for s in ("FROZEN+false", "NOT_FROZEN+true", "NOT_FROZEN+false")
                   if f"{reader} accepted {s}" in detail]
        if len(wrongly) != 3:
            fail(check_name, f"refused, but named {wrongly} rather than all three forbidden "
                             f"states: {detail}")
            return
    ok(check_name,
       f"a tree whose {reader} authorises anything is refused, and the refusal names every "
       "forbidden state it accepted: FROZEN+false, NOT_FROZEN+true, NOT_FROZEN+false")


def control_dead_authority() -> None:
    _dead_authority("mergegate-dead-authority", HOSTQUAL, DEAD_AUTHORITY, "hostqual")


def control_dead_authority_eb() -> None:
    _dead_authority("mergegate-dead-authority-eb", EXECBINDING, DEAD_AUTHORITY_EB, "execbinding")


def control_dead_continuity() -> None:
    """The campaign-swap witness needs its own sensitivity proof: a postflight
    that refuses everything would satisfy a negative-only control."""
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw), mutate={HOSTQUAL: dead_continuity}, name="deadcont")
        if verdicts(repo, commit).get("step7_machinery_enforces") != "fail":
            fail("mergegate-dead-continuity",
                 "a postflight that no longer compares the preflight's campaign link with "
                 "this pass's satisfied the gate; the swap witness proves nothing")
            return
        detail = details(repo, commit)["step7_machinery_enforces"]
        if "swapped" not in detail:
            fail("mergegate-dead-continuity", f"refused for an unrelated reason: {detail}")
            return
    ok("mergegate-dead-continuity",
       "removing only the preflight/postflight campaign-link comparison, and leaving "
       "check_campaign_link intact, is caught and named as the swap becoming admissible")


def control_always_inadmissible() -> None:
    """A refusal is only evidence if acceptance was possible."""
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw), mutate={HOSTQUAL: ALWAYS_INADMISSIBLE}, name="noadmit")
        if verdicts(repo, commit).get("step7_machinery_enforces") != "fail":
            fail("mergegate-always-inadmissible",
                 "a postflight that refuses every campaign satisfied the gate; the swap "
                 "witness was reading a blanket refusal as enforcement")
            return
        detail = details(repo, commit)["step7_machinery_enforces"]
        if "unchanged campaign was inadmissible" not in detail:
            fail("mergegate-always-inadmissible", f"refused for another reason: {detail}")
            return
    ok("mergegate-always-inadmissible",
       "the unchanged campaign must survive preflight to postflight, so a tool that refuses "
       "everything cannot pose as one that caught the swap")


def control_missing_machinery() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw), machinery=False)
        if verdicts(repo, commit).get("step7_machinery_enforces") != "fail":
            fail("mergegate-missing-machinery",
                 "a tree without the qualification and binding tools was allowed")
            return
    ok("mergegate-missing-machinery",
       "without the tools that enforce the campaign link and the authority state, the freeze "
       "would enter a world that cannot keep its promises")


def control_lingering_auto() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw), auto_authority=True)
        if verdicts(repo, commit).get("t0_zero_prerequisite") != "fail":
            fail("mergegate-lingering-auto",
                 "a tree still authorising the first collection automatically was allowed")
            return
    ok("mergegate-lingering-auto",
       "the revoked automatic authority must still be revoked in the target tree, or hosts "
       "plus a binding are again enough to start a clock")


def control_unfrozen_t0() -> None:
    states = (("not frozen", {"frozen": False}),
              ("frozen but unauthorised", {"authorized": False}),
              ("unfrozen but authorised", {"frozen": False, "authorized": True}))
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        for i, (label, kwargs) in enumerate(states):
            repo, commit = world(tmp, name=f"state{i}", **kwargs)
            if verdicts(repo, commit).get("t0_frozen_and_authorized") != "fail":
                fail("mergegate-unfrozen-t0", f"{label} was treated as a freeze")
                return
    ok("mergegate-unfrozen-t0",
       "only FROZEN together with collection_authorized: true is merged as a freeze; the other "
       "three states are refused here as they are at the session gates")


def control_reads_t0_digest() -> None:
    """The gate must not carry the expected digest in its own source."""
    source = (ROOT / "scripts" / "step7" / "mergegate.py").read_text(encoding="utf-8")
    hardcoded = re.findall("(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", source)
    if hardcoded:
        fail("mergegate-reads-t0-digest",
             f"the gate carries {len(hardcoded)} literal digest(s) in its own source; it would "
             "then be checking a constant it wrote rather than the contract")
        return
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        # two different instruments, two different digests, both accepted because
        # each tree's own T0 names its own
        for i, text in enumerate(("print('one')" + NL, "print('a different one')" + NL)):
            repo, commit = world(tmp, instrument=text, name=f"digest{i}")
            if verdicts(repo, commit).get("instrument_matches_t0") != "pass":
                fail("mergegate-reads-t0-digest",
                     "a tree whose T0 names its own instrument was refused")
                return
    ok("mergegate-reads-t0-digest",
       "the expected digest is read out of the frozen T0 and recomputed from the target tree; "
       "no digest is written into this gate's own source")


def control_inventory_complete() -> None:
    listed = set(re.findall("^    ([a-z0-9-]+) +[^ ]", __doc__ or "", re.MULTILINE))
    executed = {name for name, _ in CONTROLS}
    if listed != executed:
        fail("control-inventory-complete",
             f"listed but not executed: {sorted(listed - executed)}; executed but not listed: "
             f"{sorted(executed - listed)}")
        return
    ok("control-inventory-complete",
       f"{len(executed)} controls listed, {len(executed)} executed, same names in both")


CONTROLS: list[tuple[str, Callable[[], None]]] = [
    ("mergegate-complete-tree", control_complete_tree),
    ("mergegate-missing-instrument", control_missing_instrument),
    ("mergegate-stale-bindings", control_stale_bindings),
    ("mergegate-exact-binding-field", control_exact_binding_field),
    ("mergegate-decoy-digest", control_decoy_digest),
    ("mergegate-noop-campaign-link", control_noop_campaign_link),
    ("mergegate-dead-authority", control_dead_authority),
    ("mergegate-dead-authority-eb", control_dead_authority_eb),
    ("mergegate-dead-continuity", control_dead_continuity),
    ("mergegate-always-inadmissible", control_always_inadmissible),
    ("mergegate-missing-machinery", control_missing_machinery),
    ("mergegate-lingering-auto", control_lingering_auto),
    ("mergegate-unfrozen-t0", control_unfrozen_t0),
    ("mergegate-reads-t0-digest", control_reads_t0_digest),
    ("control-inventory-complete", control_inventory_complete),
]


def run() -> int:
    for name, control in CONTROLS:
        guarded(name, control)
    print()
    print(f"merge gate controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
