#!/usr/bin/env python3
"""The mutation harness's own controls: bytes, and a catcher's identity.

One rule, and it earned a test the hard way. `scripts/mutate_campaign.py` reads
each mutation target, rewrites it, and puts it back; it then refuses to record a
result if the tree changed. Reading and writing through Python's text mode makes
those two steps disagree on any checkout whose working copy uses CRLF: every
campaign rewrote its targets' line endings and then correctly refused its own
run. The tree HAD changed — what changed it was the harness — so no campaign
could be recorded on that platform at all, which is exactly the kind of silence
this discipline exists to break.

The control drives `read_source` / `write_source` directly, with both endings,
because the property is about bytes on disk and nothing above them can observe
it: the harness's own "was it restored?" check compares TEXT, and passed
throughout.

Run:  python tests/test_mutate_campaign.py
      python tests/run_tests.py           (auto-discovered with every other test_*.py)
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "scripts"))

from mutate_campaign import CRLF, LF, parse_test_output, read_source, write_source


def run() -> int:
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as work:
        for name, ending in (("lf", LF), ("crlf", CRLF)):
            path = os.path.join(work, f"target_{name}.py")
            body = ("A = 1" + ending + "B = 2" + ending).encode("utf-8")
            with open(path, "wb") as f:
                f.write(body)

            text, seen = read_source(path)
            if seen != ending:
                fails.append(f"{name}: read_source saw {seen!r}, the file uses "
                             f"{ending!r}")
            if text != "A = 1\nB = 2\n":
                fails.append(f"{name}: the text a pattern is matched against is "
                             f"{text!r}; a campaign's patterns are written with "
                             f"LF, so it must be normalized")

            # RESTORE: byte-for-byte, or the harness is what made the tree dirty.
            write_source(path, text, seen)
            with open(path, "rb") as f:
                restored = f.read()
            if restored != body:
                fails.append(f"{name}: restoring rewrote the file "
                             f"({restored!r} != {body!r}) — a campaign that does "
                             f"this refuses its own result, and the tree it "
                             f"blames is one it changed itself")

            # A MUTATION keeps the file's own ending too: a mutated target that
            # differs from the original in more than the mutation is a mutation
            # nobody can attribute.
            write_source(path, text.replace("A = 1", "A = 9"), seen)
            with open(path, "rb") as f:
                mutated = f.read()
            want = ("A = 9" + ending + "B = 2" + ending).encode("utf-8")
            if mutated != want:
                fails.append(f"{name}: a mutated write produced {mutated!r}, "
                             f"expected {want!r}")

        # The default is LF, so a caller that forgets the ending cannot silently
        # convert a file rather than leave it alone.
        path = os.path.join(work, "default.py")
        write_source(path, "A = 1\n")
        with open(path, "rb") as f:
            if f.read() != b"A = 1\n":
                fails.append("write_source's default ending is not LF")

    # A CATCHER NAME IS AN IDENTITY, and it may not depend on the platform
    # that produced it. cargo prints its target with the host separator, so on
    # Windows the same failing test was recorded as `own-shadow/tests\\repro.rs
    # ::…` while every definition and every committed result says
    # `own-shadow/tests/repro.rs::…`. Five acc-1 mutations reported "expected
    # catchers MISSED" while naming exactly the test that had been expected.
    windows = (
        "     Running tests\\repro.rs (target\\debug\\deps\\repro-1.exe)\n"
        "test verify_refuses_each_structural_violation ... FAILED\n")
    posix = (
        "     Running tests/repro.rs (target/debug/deps/repro-1)\n"
        "test verify_refuses_each_structural_violation ... FAILED\n")
    want = ["own-shadow/tests/repro.rs::verify_refuses_each_structural_violation"]
    for label, out in (("windows", windows), ("posix", posix)):
        found, _ = parse_test_output("own-shadow", out)
        if found != want:
            fails.append(f"{label}: cargo output names catcher(s) {found}, "
                         f"expected {want} — a catcher whose spelling "
                         f"depends on the host makes expected_catchers "
                         f"unmatchable there")

    if fails:
        for f in fails:
            print(f"FAIL[campaign-harness]: {f}")
        return 1
    print("campaign harness OK: 11 controls held (a source is read with its own "
          "ending and matched as LF; restoring and mutating both reproduce that "
          "ending byte-for-byte; the default is LF; a cargo catcher has one "
          "identity on both hosts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
