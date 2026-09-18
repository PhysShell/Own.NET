#!/usr/bin/env python3
"""#262 Stage 3 — the decision packet cannot quietly say something untrue.

A decision packet is a form, and a form invites being filled in from memory at
the end of the work. #262 asks for named fields; this module makes the packet a
DERIVED artifact instead, and then holds the ledger it is derived from to the
rules that make the derivation worth anything.

The rules, and the misreading each one exists to stop:

    deferred-stays-deferred   a performance field acquires a number, or softer
                              wording, and a deferral is read as a pass
    no-performance-claim      performance language leaks into a field that is
                              not a performance field
    windows-not-inferred      a row measured on Linux is presented as covering
                              Windows, or an OWED Windows row quietly acquires
                              a Linux-shaped answer
    closure-is-not-a-difference  a bug closed by this change is listed as a
                              standing known difference, which would make the
                              packet describe a defect the tree no longer has
    required-differences      a difference #262 already ratified goes missing
    stage-4-not-now           `Python-removal timing` says anything other than
                              Stage 4 / later
    packet-is-generated       the committed packet drifts from what the ledger
                              and the tree currently produce

Run:  python tests/test_stage3_packet.py
      python tests/run_tests.py            (in the suite)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

LEDGER = os.path.join(ROOT, "docs", "evidence", "p022-stage3-cutover.json")
GENERATED = os.path.join(ROOT, "docs", "generated", "p022-stage3-packet.md")

# The exact deferral wording the owner ruling requires. Anything else -- a
# number, "n/a", "not applicable", "no regression" -- is a different claim.
DEFERRAL = "DEFERRED BY OWNER — NOT MEASURED"

# The three fields #262 names and the ruling defers. They must all be present:
# deleting one is how a deferral stops being visible.
DEFERRED_FIELDS = ("startup_delta", "end_to_end_delta", "peak_memory_delta")

# Differences #262 ratified. A packet that lost one would be a packet that
# stopped disclosing something the owner already decided must be disclosed.
REQUIRED_DIFFERENCES = ("WIN-ABC", "CLI-B1", "V4")

# Words that turn a measurement into a performance claim. Checked OUTSIDE the
# deferred fields, where the whole point is that no such claim is made.
PERFORMANCE_WORDS = re.compile(
    r"\b(faster|slower|speedup|speed-up|throughput|latency|benchmark(?:ed)?|"
    r"ms\b|milliseconds?|regressi\w* in (?:time|speed)|performance (?:is|was|budget))",
    re.I)


def _fail(msg: str, *, check: str) -> int:
    print(f"FAIL[{check}]: {msg}")
    return 1


def run() -> int:
    failures = 0
    if not os.path.isfile(LEDGER):
        return _fail(f"{os.path.relpath(LEDGER, ROOT)} is missing — the packet is derived from "
                     f"it and there is nothing to check", check="ledger-exists")
    led = json.load(open(LEDGER, encoding="utf-8"))

    # --- deferred stays deferred -----------------------------------------
    for field in DEFERRED_FIELDS:
        got = led.get("deferred_fields", {}).get(field)
        if got is None:
            failures += _fail(
                f"the deferred field {field!r} is missing entirely. #262 asked for it and #263 "
                f"still owes it; a packet without the line is a packet nobody can notice is "
                f"missing it", check="deferred-stays-deferred")
        elif got != DEFERRAL:
            failures += _fail(
                f"{field} reads {got!r}, not {DEFERRAL!r}. A deferral is not a measurement and "
                f"must never be rendered as one — including as 'n/a', 'no change', or a number",
                check="deferred-stays-deferred")

    if "deferred by owner" not in led.get("owner_ruling_performance", "").lower():
        failures += _fail("the owner's performance ruling is not recorded verbatim on the "
                          "decision surface", check="deferred-stays-deferred")

    # --- no performance claim anywhere else -------------------------------
    for m in led.get("measurements", []):
        hit = PERFORMANCE_WORDS.search(m.get("result", ""))
        if hit:
            failures += _fail(
                f"measurement {m['id']!r} uses performance language ({hit.group(0)!r}). "
                f"Performance is deferred for this decision; a timing encountered incidentally "
                f"must not be promoted into a claim", check="no-performance-claim")

    # --- Windows is never inferred from Linux -----------------------------
    seen_platforms = set()
    for m in led.get("measurements", []):
        seen_platforms.add(m.get("platform"))
        owed = m.get("result", "").startswith("OWED")
        if owed and m.get("label") != "DEFERRED EVIDENCE":
            failures += _fail(
                f"{m['id']!r} is OWED but is not labelled DEFERRED EVIDENCE — an unlabelled "
                f"gap reads as a result", check="windows-not-inferred")
        if m.get("label") == "DEFERRED EVIDENCE" and not owed:
            failures += _fail(
                f"{m['id']!r} is labelled DEFERRED EVIDENCE but carries a result. Either it was "
                f"measured, in which case say where, or it was not",
                check="windows-not-inferred")
    if "windows" not in seen_platforms:
        failures += _fail(
            "no measurement names the windows platform at all, so the packet cannot be said to "
            "cover it either way", check="windows-not-inferred")

    # --- a closure is not a standing difference ---------------------------
    closed = {c["id"] for c in led.get("closed_in_this_change", [])}
    diffs = {d["id"] for d in led.get("known_differences", [])}
    both = closed & diffs
    if both:
        failures += _fail(
            f"{sorted(both)} appear as BOTH closed and as standing known differences. #262 says "
            f"not to list a closed bug as a known difference merely because it used to exist",
            check="closure-is-not-a-difference")
    for wanted in REQUIRED_DIFFERENCES:
        if wanted not in diffs:
            failures += _fail(
                f"the ratified difference {wanted!r} is not carried forward into the packet",
                check="required-differences")
    if not closed:
        failures += _fail("nothing is recorded as CLOSED, although this change closes three "
                          "#262 hygiene tails — closures must be recorded separately from "
                          "differences", check="closure-is-not-a-difference")

    # --- Stage 4 is not now ----------------------------------------------
    from stage3_packet import packet  # scripts/ is on sys.path (set above)
    text = packet()
    m = re.search(r"^Python-removal timing:\s*(.+)$", text, re.M)
    if not m:
        failures += _fail("the packet has no `Python-removal timing:` line",
                          check="stage-4-not-now")
    elif ("Stage 4" not in m.group(1)
          or re.search(r"\bnow\b(?!\.)", m.group(1).replace("NOT now", ""))):
        failures += _fail(
            f"`Python-removal timing:` reads {m.group(1)!r}; it must say Stage 4 / a separate PR "
            f"/ after the observation policy, and must not say now", check="stage-4-not-now")

    # --- the packet is generated, not typed -------------------------------
    if not os.path.isfile(GENERATED):
        failures += _fail(f"{os.path.relpath(GENERATED, ROOT)} has not been generated "
                          f"(`python scripts/stage3_packet.py --write`)",
                          check="packet-is-generated")
    else:
        committed = open(GENERATED, encoding="utf-8").read()
        # The candidate SHA and the dirty marker move with the tree, so they are
        # normalised out: what must not drift is everything else.
        norm = re.compile(r"^Stage-3 candidate SHA:.*$", re.M)
        if norm.sub("", committed).strip() != norm.sub("", text).strip():
            failures += _fail(
                "the committed packet differs from what the ledger and the tree produce now — "
                "regenerate it with `python scripts/stage3_packet.py --write` rather than "
                "editing it", check="packet-is-generated")

    # --- the candidate SHA is this tree -----------------------------------
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True, check=False).stdout.strip()
    if head and led.get("candidate_sha") and led["candidate_sha"] != head:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", led["candidate_sha"], "HEAD"],
            cwd=ROOT, capture_output=True, check=False).returncode == 0
        if not ancestor:
            failures += _fail(
                f"the ledger's candidate_sha {led['candidate_sha'][:12]} is not this tree and "
                f"not an ancestor of it — the packet describes a tree nobody has",
                check="candidate-sha-is-this-tree")

    if failures:
        return 1
    print(
        f"stage-3 packet OK: {len(led['measurements'])} measurements, "
        f"{len(led['known_differences'])} known differences, {len(closed)} recorded closures; "
        f"all three performance fields present and reading exactly {DEFERRAL!r}; no performance "
        f"language outside them; every OWED row labelled DEFERRED EVIDENCE and none of them "
        f"filled in from another platform; Python removal says Stage 4; the committed packet "
        f"matches what the ledger produces")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
