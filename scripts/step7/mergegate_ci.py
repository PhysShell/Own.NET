#!/usr/bin/env python3
"""P-022 — the merge gate as a status check.

`mergegate.py` answers one question: may the frozen contract become reachable
from this tree? It answers it about a tree that *has* a frozen contract. A
required status check runs on every pull request in the repository, including
the ones that have nothing to do with P-022, so two rules have to be settled
before that gate can be wired to a branch protection rule.

**Applicability.** If the frozen T0 does not exist at the merge commit, no merge
can make it reachable and there is nothing to protect. The check passes and says
so. This is not a way around the gate: the moment a tree carries T0, every
predicate applies in full.

**Co-change.** A required check that a pull request can rewrite is decoration.
The workflow that runs on a pull request is the one *on that pull request*, so a
branch may carry both the freeze and a weakened gate and be judged by the gate
it brought with it. So: **the gate's own files may not change in the same merge
that introduces or changes the frozen contract.** Repairing the gate is still
ordinary work; doing it in the same breath as the freeze is not.

Neither rule is enforcement isolation. A repository administrator can turn the
protection off, and this script cannot see that. What it removes is the quiet
path — a weakened gate arriving as part of the change it was meant to judge.

Exit codes: 0 the merge may proceed (or the gate does not apply), 1 it is
refused, 2 the question could not be asked.

    python scripts/step7/mergegate_ci.py --repo . --commit <merge sha> \
        --base <base sha>

`--base` is what the co-change rule compares against. Without it the rule cannot
run, and the output says that rather than implying it passed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mergegate as mg

# The gate's own surface: the predicates, this wrapper, and the workflow that
# runs them. A change to any of these changes what "the gate passed" means.
GATE_FILES = ("scripts/step7/mergegate.py",
              "scripts/step7/mergegate_ci.py",
              ".github/workflows/p022-merge-gate.yml")


def blob_sha(repo: Path, commit: str, path: str) -> str | None:
    """The blob a path resolves to, or None when the path is not there."""
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{commit}:{path}"],
                          capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def applies(repo: Path, commit: str) -> bool:
    return blob_sha(repo, commit, mg.T0_PATH) is not None


def is_commit(repo: Path, rev: str) -> bool:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", f"{rev}^{{commit}}"],
                          capture_output=True, check=False).returncode == 0


def co_change(repo: Path, commit: str, base: str) -> list[str]:
    """Which gate files this merge changes, if it also touches the contract.

    Empty when the contract is untouched: repairing the gate is ordinary work.
    """
    t0_now, t0_base = blob_sha(repo, commit, mg.T0_PATH), blob_sha(repo, base, mg.T0_PATH)
    if t0_now == t0_base:
        return []
    return [path for path in GATE_FILES
            if blob_sha(repo, commit, path) != blob_sha(repo, base, path)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--commit", required=True,
                        help="the commit a merge would produce, not the branch head")
    parser.add_argument("--base", help="the base commit the co-change rule compares against")
    args = parser.parse_args(argv)

    if not is_commit(args.repo, args.commit):
        print(f"merge gate: MISUSE — {args.commit} is not a commit in {args.repo}")
        return 2
    # A base that is not in the clone would make every gate file look changed,
    # and the co-change rule would refuse for a reason that is about the checkout
    # rather than about the merge. A question that cannot be asked is not a no.
    if args.base is not None and not is_commit(args.repo, args.base):
        print(f"merge gate: MISUSE — the base {args.base} is not a commit in {args.repo}; "
              "the co-change rule cannot be evaluated, and a shallow checkout must not be "
              "reported as a rewritten gate")
        return 2

    if not applies(args.repo, args.commit):
        print(f"merge gate: not applicable — {mg.T0_PATH} does not exist at {args.commit[:12]}, "
              "so no merge here can make the frozen contract reachable. Every predicate "
              "applies the moment a tree carries it.")
        return 0

    if args.base is None:
        print("merge gate: the co-change rule did not run — no --base was given, so this pass "
              "cannot say whether the gate itself changed alongside the contract")
    else:
        changed = co_change(args.repo, args.commit, args.base)
        if changed:
            print("merge gate: REFUSED — this merge changes the frozen contract and the gate "
                  f"that judges it in one act: {', '.join(changed)}. Repair the gate in its own "
                  "merge; a guard that arrives with what it guards is not a guard.")
            return 1
        print("ok   [gate_unchanged] the contract moves and the gate does not; this merge is "
              "judged by the gate already on the base")

    results = mg.gate(args.repo, args.commit)
    for row in results:
        mark = "ok  " if row["result"] == "pass" else "FAIL"
        print(f"{mark} [{row['check']}] {row['detail']}")
    bad = [r for r in results if r["result"] != "pass"]
    print()
    if bad:
        print(f"merge gate: REFUSED, {len(bad)} predicate(s) unsatisfied — the frozen contract "
              "must not become reachable from this tree")
        return 1
    print("merge gate: allowed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
