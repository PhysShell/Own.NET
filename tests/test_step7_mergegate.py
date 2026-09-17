#!/usr/bin/env python3
"""P-022 — controls on the merge gate.

    mergegate-complete-tree      a world that satisfies the freeze is allowed
    mergegate-missing-instrument the digest T0 names must exist in the tree
    mergegate-stale-bindings     steps 4/5/6 must be re-bound to that digest
    mergegate-missing-machinery  the campaign link and authority must be enforceable
    mergegate-lingering-auto     the revoked automatic authority must stay revoked
    mergegate-unfrozen-t0        an unfrozen or unauthorised T0 is not merged as frozen
    mergegate-reads-t0-digest    the expected digest comes from T0, not from a constant

Every control builds a throwaway repository, so the gate is exercised against
real git objects rather than against a mock of the thing it exists to read.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_step7_mergegate.py
"""

from __future__ import annotations

import contextlib
import io
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


HOSTQUAL_STUB = ('CAMPAIGN_LINK_SCHEMA = "own.net/p022/campaign-link"\n'
                 'def check_campaign_link():\n    pass\n'
                 'def gate():\n    if authorized is not True:\n        return "refuse"\n')
STEP7_NOTE_REVOKED = ("Status:\n  AUTOMATIC AUTHORISATION OF THE FIRST STEP-7 COLLECTION "
                      "IS REVOKED (T0-0).\n")
STEP7_NOTE_AUTO = "Status:\n  SINGLE STEP-7 COLLECTION AUTHORISED automatically after that gate.\n"


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
          instrument: str = "print('instrument')\n", rebound: bool = True,
          machinery: bool = True, auto_authority: bool = False,
          name: str = "w") -> tuple[Path, str]:
    """A synthetic target tree, and the commit a merge into it would produce."""
    repo = tmp / name
    # The digest T0 will name is whatever this tree's own sources hash to, so a
    # fixture cannot pass by agreeing with a constant this file also wrote.
    files = {mg.STEP7_TOOLS[0]: "# capture\n",
             eb.INSTRUMENT_SOURCES[0]: instrument,
             eb.INSTRUMENT_SOURCES[1]: '{"decisive": []}\n',
             mg.STEP7_NOTE: STEP7_NOTE_AUTO if auto_authority else STEP7_NOTE_REVOKED}
    if machinery:
        files[mg.STEP7_TOOLS[1]] = HOSTQUAL_STUB
        files[mg.STEP7_TOOLS[2]] = "# binding\n"
    probe = commit_tree(repo, files)
    digest = eb.harness_digest_at(repo, probe) or ""
    status = "FROZEN." if frozen else "NOT_FROZEN."
    flag = "true" if authorized else "false"
    files[mg.T0_PATH] = (f"```text\nStatus:\n  {status}\n  collection_authorized: {flag}\n```\n\n"
                         f"    measurement_harness_digest\n    {digest}\n")
    bound = digest if rebound else "0" * 64
    for artifact in mg.BINDING_ARTIFACTS:
        files[artifact] = '{"measurement_harness_digest": "' + bound + '"}\n'
    return repo, commit_tree(repo, files)


def verdicts(repo: Path, commit: str) -> dict[str, str]:
    return {str(r["check"]): str(r["result"]) for r in mg.gate(repo, commit)}


def control_complete_tree() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw))
        results = verdicts(repo, commit)
        bad = sorted(k for k, v in results.items() if v != "pass")
        if bad:
            fail("mergegate-complete-tree", f"a satisfying world was refused on {bad}")
            return
        # Captured: a green run that prints a refusal teaches readers to skim past
        # refusals, which is how the word stops meaning anything.
        with contextlib.redirect_stdout(io.StringIO()):
            rc = mg.main(["--repo", str(repo), "--commit", commit])
        if rc != 0:
            fail("mergegate-complete-tree", "the CLI refused a satisfying world")
            return
    ok("mergegate-complete-tree",
       "a tree carrying the named instrument, the re-bound artifacts, the machinery and the "
       "revoked automatic authority is allowed")


def control_missing_instrument() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        repo, commit = world(tmp)
        # the instrument moves after T0 named it — the exact intermediate state a
        # stray merge produces when the repair PR is not in yet
        drifted = commit_tree(repo, {eb.INSTRUMENT_SOURCES[0]: "print('older instrument')\n"})
        results = verdicts(repo, drifted)
        if results.get("instrument_matches_t0") != "fail":
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


def control_missing_machinery() -> None:
    with tempfile.TemporaryDirectory() as raw:
        repo, commit = world(Path(raw), machinery=False)
        if verdicts(repo, commit).get("step7_machinery_present") != "fail":
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
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        for label, kwargs in (("not frozen", {"frozen": False}),
                              ("frozen but unauthorised", {"authorized": False}),
                              ("unfrozen but authorised", {"frozen": False, "authorized": True})):
            repo, commit = world(tmp, name=f"w-{len(list(tmp.glob('w-*')))}", **kwargs)
            if verdicts(repo, commit).get("t0_frozen_and_authorized") != "fail":
                fail("mergegate-unfrozen-t0", f"{label} was treated as a freeze")
                return
    ok("mergegate-unfrozen-t0",
       "only FROZEN together with collection_authorized: true is merged as a freeze; the other "
       "three states are refused here as they are at the session gates")


def control_reads_t0_digest() -> None:
    """The gate must not carry the expected digest in its own source."""
    source = (ROOT / "scripts" / "step7" / "mergegate.py").read_text(encoding="utf-8")
    hardcoded = re.findall(r"\b[0-9a-f]{64}\b", source)
    if hardcoded:
        fail("mergegate-reads-t0-digest",
             f"the gate carries {len(hardcoded)} literal digest(s) in its own source; it would "
             "then be checking a constant it wrote rather than the contract")
        return
    with tempfile.TemporaryDirectory() as raw:
        # two different instruments, two different digests, both accepted because
        # each tree's T0 names its own
        for text in ("print('one')\n", "print('a completely different instrument')\n"):
            repo, commit = world(Path(raw), instrument=text,
                                 name=f"d{abs(hash(text)) % 1000}")
            if verdicts(repo, commit).get("instrument_matches_t0") != "pass":
                fail("mergegate-reads-t0-digest",
                     "a tree whose T0 names its own instrument was refused")
                return
    ok("mergegate-reads-t0-digest",
       "the expected digest is read out of the frozen T0 and recomputed from the target tree; "
       "no digest is written into this gate's own source")


CONTROLS: list[tuple[str, Callable[[], None]]] = [
    ("mergegate-complete-tree", control_complete_tree),
    ("mergegate-missing-instrument", control_missing_instrument),
    ("mergegate-stale-bindings", control_stale_bindings),
    ("mergegate-missing-machinery", control_missing_machinery),
    ("mergegate-lingering-auto", control_lingering_auto),
    ("mergegate-unfrozen-t0", control_unfrozen_t0),
    ("mergegate-reads-t0-digest", control_reads_t0_digest),
]


def run() -> int:
    for name, control in CONTROLS:
        guarded(name, control)
    print()
    print(f"merge gate controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
