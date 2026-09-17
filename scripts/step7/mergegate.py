#!/usr/bin/env python3
"""P-022 — the merge gate: does the world a freeze enters satisfy its references?

The frozen T0 names things that live outside itself: an accepted harness
identity, the step-7 machinery that enforces the campaign join, the T0-0
amendment that revoked automatic collection authority. On the branch where T0
was frozen, some of those referents arrive through *other* pull requests. That
is fine while the merge order holds — and merge order held by agreement is one
stray click away from becoming an archaeological artifact, with a document
saying FROZEN in a tree where its referent does not exist yet.

So the order is checked rather than promised, and it is checked against the
**target tree**, never against pull-request numbers. A PR number proves that
someone pressed a button; it proves nothing about what the merged tree contains.

Run it on the commit a merge would produce:

    python scripts/step7/mergegate.py --repo . --commit <sha>

Exit 0 only when every predicate holds. Any failure means the frozen contract
would become reachable from a tree that cannot satisfy it, and the merge is
refused however mergeable the forge believes it to be.

The digest is not hard-coded here: it is read out of the frozen T0 and then
RECOMPUTED from the instrument sources in the target tree, by the frozen
formula, without importing the instrument. A gate that trusted a constant in
its own source would be checking itself.
"""

from __future__ import annotations

import argparse

import json
import re
import subprocess
import sys
from pathlib import Path

import execbinding as eb  # the single implementation of the harness-digest formula

T0_PATH = "docs/notes/p022-263-t0-protocol-freeze.md"
STEP7_NOTE = "docs/notes/p022-263a-step7-environment-capture.md"
BINDING_ARTIFACTS = (
    "docs/evidence/calibration/p022-263a-policy-freeze.json",
    "docs/evidence/calibration/p022-263a-design-constants.json",
    "docs/evidence/calibration/p022-263a-training-preregistration.json",
)
STEP7_TOOLS = ("scripts/step7/envcapture.py", "scripts/step7/hostqual.py",
               "scripts/step7/execbinding.py")
DIGEST_RE = re.compile(r"measurement_harness_digest\s*\n?\s*([0-9a-f]{64})")


def blob(repo: Path, commit: str, path: str) -> bytes | None:
    proc = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{path}"],
                          capture_output=True, check=False)
    return proc.stdout if proc.returncode == 0 else None


def check(name: str, ok: bool, detail: str) -> dict[str, object]:
    return {"check": name, "result": "pass" if ok else "fail", "detail": detail}


def gate(repo: Path, commit: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []

    raw_t0 = blob(repo, commit, T0_PATH)
    if raw_t0 is None:
        return [check("t0_present", False, f"{T0_PATH} does not exist at {commit}")]
    text = raw_t0.decode("utf-8", "replace")
    frozen = re.search(r"^\s*(NOT_FROZEN|FROZEN)\.?\s*$", text, re.MULTILINE)
    flag = re.search(r"^\s*collection_authorized:\s*(true|false)\s*$", text, re.MULTILINE)
    declared = frozen.group(1) if frozen else "<no status line>"
    authorized = (flag.group(1) == "true") if flag else None
    results.append(check(
        "t0_frozen_and_authorized", declared == "FROZEN" and authorized is True,
        f"T0 declares {declared}, collection_authorized={json.dumps(authorized)}"))

    named = DIGEST_RE.search(text)
    results.append(check("t0_names_a_digest", named is not None,
                         f"T0 names {named.group(1)[:12] if named else '<none>'} as the accepted "
                         "harness identity"))
    if named is None:
        return results
    expected = named.group(1)

    # Recomputed from the target tree's own sources, by the frozen formula.
    live = eb.harness_digest_at(repo, commit)
    results.append(check(
        "instrument_matches_t0", live == expected,
        f"the instrument at {commit[:12]} hashes to {live[:12] if live else '<unreadable>'}; "
        f"T0 names {expected[:12]}. The frozen contract would otherwise point at an identity "
        "this tree does not contain"))

    rebound = []
    for path in BINDING_ARTIFACTS:
        raw = blob(repo, commit, path)
        if raw is None:
            rebound.append(f"{Path(path).name}: absent")
        elif expected not in raw.decode("utf-8", "replace"):
            rebound.append(f"{Path(path).name}: still bound to an older digest")
    results.append(check(
        "steps_4_5_6_rebound", not rebound,
        "; ".join(rebound) if rebound else
        f"the policy freeze, the design constants and the training preregistration all bind "
        f"{expected[:12]}"))

    missing_tools = [t for t in STEP7_TOOLS if blob(repo, commit, t) is None]
    hostqual = (blob(repo, commit, "scripts/step7/hostqual.py") or b"").decode("utf-8", "replace")
    enforces_link = "CAMPAIGN_LINK_SCHEMA" in hostqual and "check_campaign_link" in hostqual
    enforces_authority = "collection_authorized is" in hostqual or (
        "authorized is not True" in hostqual)
    results.append(check(
        "step7_machinery_present", not missing_tools and enforces_link and enforces_authority,
        "; ".join(filter(None, [
            f"missing: {missing_tools}" if missing_tools else "",
            "" if enforces_link else "hostqual does not enforce the campaign link",
            "" if enforces_authority else "hostqual does not enforce the authority state",
        ])) or "capture, qualification and binding tools are present, and the campaign link and "
               "authority state are enforced"))

    note = (blob(repo, commit, STEP7_NOTE) or b"").decode("utf-8", "replace")
    revoked = "AUTOMATIC AUTHORISATION OF THE FIRST STEP-7 COLLECTION IS REVOKED" in note
    lingering = "SINGLE STEP-7 COLLECTION AUTHORISED automatically" in note
    results.append(check(
        "t0_zero_prerequisite", revoked and not lingering,
        "the step-7 status block revokes the automatic collection authority"
        if revoked and not lingering else
        "the step-7 note still authorises the first collection automatically, so hosts plus a "
        "binding would again be enough to start a clock"))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    results = gate(args.repo, args.commit)
    failed = [r for r in results if r["result"] != "pass"]
    if args.json:
        print(json.dumps({"commit": args.commit, "checks": results,
                          "merge_allowed": not failed}, indent=2))
    else:
        for r in results:
            print(f"{'ok  ' if r['result'] == 'pass' else 'FAIL'} [{r['check']}] {r['detail']}")
        print()
        print("merge gate: allowed" if not failed else
              f"merge gate: REFUSED, {len(failed)} predicate(s) unsatisfied — the frozen "
              "contract must not become reachable from this tree")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
