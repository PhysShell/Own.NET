"""P-037 B0: the proof-boundary audit and its falsifiers, on every run.

`--check` must be PASS on the tree, and `--selftest` must show every cheap
falsifier firing (docs/notes/p037-phase-b-proof-boundary.md §C). The kernel
mutants (`--mutants`, F5) need cargo and run in the `formal-p037` CI job
instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import p037_proof_boundary as pb


def run() -> int:
    rc_check = pb.main(["--check"])
    rc_self = pb.main(["--selftest"])
    ok = rc_check == 0 and rc_self == 0
    print(f"p037 proof boundary: {'PASS' if ok else 'FAIL'} "
          f"(check rc={rc_check}, selftest rc={rc_self})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
