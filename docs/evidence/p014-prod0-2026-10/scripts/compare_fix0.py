"""P-014 FIX0: compare the FIX0 run's sidecars and controls with the f84943d run
(03-fix0-preregistration §2.3).

Per unit, everything must be identical except reasons, and the only added reasons allowed are
`preprocessor-conditional`, `unreadable-source` and `p2p-unit-*`. Every reason present at f84943d
must still be present. A unit status may only move from COMPLETE to SOURCE_SET_INCOMPLETE.

usage: python -I compare_fix0.py <f84943d res dir> <fix0 res dir>
"""

import json
import os
import sys

ALLOWED = ("preprocessor-conditional", "unreadable-source", "p2p-unit-")
FILES = [
    "P4.cost.1.sidecar.json",
    "P5.cost.1.sidecar.json",
    "K8a.sidecar.json",
    "K8b.sidecar.json",
    "K8c.sidecar.json",
    "G0.sidecar.json",
    "K9-net8.0.sidecar.json",
    "K9-net10.0.sidecar.json",
    "K9-notfm.sidecar.json",
    "K10-with.sidecar.json",
    "K10-without.sidecar.json",
    "samples.flag.sidecar.json",
]


def main() -> int:
    old_dir, new_dir = sys.argv[1], sys.argv[2]
    bad = []
    for f in FILES:
        with open(os.path.join(old_dir, f), encoding="utf-8") as fh:
            old = json.load(fh)["units"]
        with open(os.path.join(new_dir, f), encoding="utf-8") as fh:
            new = json.load(fh)["units"]
        if len(old) != len(new):
            bad.append(f"{f}: unit count {len(old)} -> {len(new)}")
            continue
        for a, b in zip(old, new, strict=True):
            name = f"{f}:{a.get('project')}"
            for k in sorted(set(a) | set(b)):
                if k in ("reasons", "unit_status", "source_set_status"):
                    continue
                if a.get(k) != b.get(k):
                    bad.append(f"{name}: field '{k}' differs")
            ra, rb = a["reasons"], b["reasons"]
            for axis in ("reference", "unsupported"):
                if ra[axis] != rb[axis]:
                    bad.append(f"{name}: reasons.{axis} differs")
            removed = set(ra["source_set"]) - set(rb["source_set"])
            added = set(rb["source_set"]) - set(ra["source_set"])
            if removed:
                bad.append(f"{name}: source_set reasons removed {sorted(removed)}")
            if any(not r.startswith(ALLOWED) for r in added):
                bad.append(f"{name}: unexpected source_set reasons {sorted(added)}")
            moved = (a["unit_status"], b["unit_status"])
            if moved[0] != moved[1] and moved != ("COMPLETE", "SOURCE_SET_INCOMPLETE"):
                bad.append(f"{name}: status {moved[0]} -> {moved[1]}")
            print(f"{name}: {moved[0]} -> {moved[1]}; added {sorted(added)}")
    with open(os.path.join(old_dir, "controls.json"), encoding="utf-8") as fh:
        c_old = json.load(fh)["results"]
    with open(os.path.join(new_dir, "controls.json"), encoding="utf-8") as fh:
        c_new = json.load(fh)["results"]
    if c_old != c_new:
        bad.append("controls.json differs")
    print("controls identical:", c_old == c_new)
    for b in bad:
        print("FAIL:", b)
    print("RESULT:", "PASS" if not bad else "FAIL")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
