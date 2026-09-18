#!/usr/bin/env python3
"""The three #262 Stage-3 cutover hygiene tails, at the OwnIR input boundary.

`ownlang` is the P-022 REFERENCE. Three of its input-boundary behaviours were
recorded by #262 as defects owed before the public Rust-default cutover, and
they are closed Python-first — the migration's standing rule, because a
divergence repaired by changing the port would freeze the reference's accident
into the contract instead of removing it.

invalid UTF-8
    before: `UnicodeDecodeError` escaped `load()` uncaught -> rc **70**
    after:  `OwnIRError` -> rc **2**

V1, the constants `NaN` / `Infinity` / `-Infinity`
    before: accepted by CPython's `json`, then refused downstream by the
            VERSION door as a float the source text never contained
    after:  refused at the **JSON door**, where the port refuses them

V2, the literal top-level `-0`
    before: read as the integer 0 and **ACCEPTED as v0** — the document was
            analysed
    after:  refused at the OwnIR input boundary

The Rust replay (`rust/crates/own-cli/tests/replay.rs`) proves the port agrees
on all three through the production executable. This module is the other half:
it proves the REFERENCE does what the ruling says, and — the part a byte
comparison cannot express — that each repair stayed inside its ruling's scope.

Scope is most of the work here, so it is asserted rather than described:

* V2 is scoped by #262 to the **top-level scalar** `ownir_version`. A `-0`
  nested in a wrong-type container, or on any other field, is explicitly NOT
  this exception and must keep behaving exactly as before. `#261`'s Version
  census pinned `{"ownir_version": [-0]}` as byte parity with the port, so
  widening the repair would break a parity claim rather than improve one.
* V2 is scoped to the literal `-0`, not to "a negative zero". `-0.0` and
  `-0e0` are floats to both implementations, already agree, and must not be
  swept in.
* V3 — an integral version beyond `i64`/`u64` — was already repaired to byte
  parity at #261 and is NOT reopened. It shares the `parse_int` path the V2
  repair installs, so it is re-asserted here: a hook that quietly turned a
  bignum into something else would break a closed parity claim.

Run:  python tests/test_ownir_input_boundary.py
      python tests/run_tests.py            (in the suite)
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from ownlang.ownir import OwnIRError, load  # noqa: E402

# The exit codes the ruling names. 2 is "ordinary refused input"; 70 is the
# analyzer accusing itself of a bug, which is what every tail below used to do
# about a file the caller supplied.
RC_REFUSED = 2
RC_INTERNAL_ERROR = 70


def _fail(msg: str, *, check: str) -> int:
    print(f"FAIL[{check}]: {msg}")
    return 1


def _load_bytes(blob: bytes) -> tuple[str, object]:
    """Run `load()` over exactly these bytes. Returns ("ok", document) or
    ("refused", message)."""
    fd, path = tempfile.mkstemp(suffix=".facts.json")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        try:
            return "ok", load(path)
        except OwnIRError as e:
            # The message carries the temp path; strip it so the assertions
            # below are about the CONTRACT and not about mkstemp.
            return "refused", str(e).replace(path, "<facts>")
    finally:
        os.unlink(path)


def _run_cli(blob: bytes) -> tuple[int, str]:
    """Run the same bytes through the PRODUCTION reference path — the module
    entry point a launcher invokes — because a repair that only holds inside
    `load()` is not a repair of anything a user can reach."""
    fd, path = tempfile.mkstemp(suffix=".facts.json")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        env = dict(os.environ, PYTHONPATH=_ROOT)
        proc = subprocess.run(
            [sys.executable, "-m", "ownlang", "ownir", path],
            capture_output=True, text=True, env=env, cwd=_ROOT)
        return proc.returncode, proc.stderr.replace(path, "<facts>")
    finally:
        os.unlink(path)


def _refusal_case(blob: bytes, *, check: str, must_contain: str) -> int:
    """A document that must be REFUSED as input, both through `load()` and
    through the production CLI path, at rc 2 and never at rc 70."""
    failures = 0
    outcome, detail = _load_bytes(blob)
    if outcome != "refused":
        return _fail(f"load() ACCEPTED {blob!r}; it must raise OwnIRError",
                     check=check)
    if must_contain not in str(detail):
        failures += _fail(
            f"load() refused {blob!r} but the message does not carry "
            f"{must_contain!r}: {detail!r}", check=check)
    rc, stderr = _run_cli(blob)
    if rc != RC_REFUSED:
        failures += _fail(
            f"the production path answered {blob!r} with rc {rc}, not "
            f"{RC_REFUSED}"
            + (" — that is the analyzer calling its own input a bug"
               if rc == RC_INTERNAL_ERROR else "")
            + f". stderr: {stderr!r}", check=check)
    if must_contain not in stderr:
        failures += _fail(
            f"the production path refused {blob!r} without carrying "
            f"{must_contain!r}: {stderr!r}", check=check)
    return failures


def run() -> int:
    failures = 0

    # --- tail 1: invalid UTF-8 -------------------------------------------
    #
    # The message is stated in terms of the FILE — the first offending byte and
    # its offset — rather than in the decoder's voice, which is what lets the
    # port report it identically. Both halves are asserted, because an offset
    # that silently became a character index would still "contain 0xff".
    invalid_utf8 = b'{"ownir_version": 0, "components": [{"name": "\xff\xfe"}]}'
    assert invalid_utf8.index(b"\xff") == 46
    failures += _refusal_case(
        invalid_utf8, check="invalid-utf8",
        must_contain="is not valid UTF-8: byte 0xff at offset 46")

    # A truncated multi-byte sequence at the very end: the offset must be the
    # START of the incomplete sequence, and the byte must still be reportable.
    # This is the case an implementation that indexed past the valid prefix
    # would crash on.
    failures += _refusal_case(
        b'{"ownir_version": 0}\xc3', check="invalid-utf8",
        must_contain="is not valid UTF-8: byte 0xc3 at offset 20")

    # SCOPE: valid UTF-8 that is invalid JSON must still reach the JSON door,
    # not the new one. A BOM is the case that distinguishes them — it decodes
    # cleanly and then fails to parse.
    failures += _refusal_case(
        b"\xef\xbb\xbf{}", check="invalid-utf8-scope",
        must_contain="is not valid JSON")
    outcome, detail = _load_bytes(b"\xef\xbb\xbf{}")
    if outcome == "refused" and "not valid UTF-8" in str(detail):
        failures += _fail(
            "a UTF-8 BOM decodes cleanly and must be refused by the JSON "
            f"door, not the UTF-8 door: {detail!r}", check="invalid-utf8-scope")

    # --- tail 2, V1: the non-standard constants --------------------------
    #
    # Each of the three enumerated, not inferred from one of them: they take
    # different routes through CPython's scanner (`-Infinity` in particular is
    # reached by the number scanner, not the constant scanner).
    for token in (b"NaN", b"Infinity", b"-Infinity"):
        failures += _refusal_case(
            b'{"ownir_version": ' + token + b"}", check="v1-non-standard-constant",
            must_contain=(
                f"is not valid JSON: {token.decode()} is not a JSON value"))
        # And it must be the JSON door, never the Version door it used to
        # reach after CPython had already accepted the token as a float.
        outcome, detail = _load_bytes(b'{"ownir_version": ' + token + b"}")
        if outcome == "refused" and "must be an integer" in str(detail):
            failures += _fail(
                f"{token.decode()} still reaches the VERSION door: {detail!r} "
                "— V1 requires the refusal at the JSON door",
                check="v1-non-standard-constant")

    # V1 anywhere else in the document is the same refusal: the constants are
    # refused by the PARSER, so the position cannot matter.
    failures += _refusal_case(
        b'{"ownir_version": 0, "components": [{"line": NaN}]}',
        check="v1-non-standard-constant",
        must_contain="is not valid JSON: NaN is not a JSON value")

    # --- tail 3, V2: the literal top-level `-0` ---------------------------
    failures += _refusal_case(
        b'{"ownir_version": -0}', check="v2-top-level-negative-zero",
        must_contain="must be an integer, got -0:")

    # SCOPE 1 — nested. #261's Version census pinned this as BYTE PARITY with
    # the port, so the exact rendering is asserted, not merely the refusal.
    outcome, detail = _load_bytes(b'{"ownir_version": [-0]}')
    want = "OwnIR 'ownir_version' must be an integer, got [0]"
    if outcome != "refused" or str(detail) != want:
        failures += _fail(
            f"a -0 BELOW the top level must render exactly {want!r} (#261 "
            f"Version census, byte parity with the port), got "
            f"{outcome}/{detail!r}", check="v2-scope-nested")

    # SCOPE 2 — a `-0` on any other field is not V2 at all and must not even
    # be refused: it is an ordinary zero, and the document still analyses.
    ok_doc = (b'{"ownir_version": 0, "components": [{"name": "C", '
              b'"file": "a.cs", "line": -0}]}')
    outcome, _ = _load_bytes(ok_doc)
    if outcome != "ok":
        failures += _fail(
            "a -0 on an ordinary coordinate field must be an ordinary 0 and "
            f"the document must still load, got {outcome}",
            check="v2-scope-other-fields")

    # SCOPE 3 — the ruling names the LITERAL `-0`, not "a negative zero".
    # These are floats to both implementations, already agree, and must keep
    # the float rendering rather than being swept into V2.
    for blob in (b'{"ownir_version": -0.0}', b'{"ownir_version": -0e0}'):
        outcome, detail = _load_bytes(blob)
        want = "OwnIR 'ownir_version' must be an integer, got -0.0"
        if outcome != "refused" or str(detail) != want:
            failures += _fail(
                f"{blob!r} is a FLOAT negative zero, not V2's literal -0; it "
                f"must render exactly {want!r}, got {outcome}/{detail!r}",
                check="v2-scope-float")

    # --- V3 is NOT reopened ----------------------------------------------
    #
    # It rides the same `parse_int` hook the V2 repair installs, so a hook that
    # lost arbitrary precision would silently undo #261's repair-2. Both signs,
    # because that repair was measured over both.
    for sign in ("", "-"):
        big = f"{sign}99999999999999999999999999"
        outcome, detail = _load_bytes(
            b'{"ownir_version": ' + big.encode() + b"}")
        want = f"OwnIR facts are schema v{big}, but this core understands v0"
        if outcome != "refused" or not str(detail).startswith(want):
            failures += _fail(
                f"an oversized integral version must keep taking the Version "
                f"MISMATCH branch with its full precision ({want!r}), got "
                f"{outcome}/{detail!r}", check="v3-not-reopened")

    # --- the ordinary path still works ------------------------------------
    #
    # Two hooks now sit in the decode path. The cheapest way for them to be
    # wrong is for them to be wrong about everything, so an ordinary document
    # with ordinary integers is checked to still load and still carry them as
    # plain values.
    outcome, doc = _load_bytes(
        b'{"ownir_version": 0, "components": [{"name": "C", "file": "a.cs", '
        b'"line": 12, "column": 3}]}')
    if outcome != "ok":
        failures += _fail(f"an ordinary document must load, got {outcome}: "
                          f"{doc!r}", check="ordinary-document")
    else:
        line = doc["components"][0]["line"]  # type: ignore[index,call-overload]
        if line != 12 or type(line) is not int:
            failures += _fail(
                f"an ordinary integer must decode as a plain int, got "
                f"{line!r} ({type(line).__name__})", check="ordinary-document")

    if failures:
        return 1
    print(
        "ownir input boundary OK: the three #262 cutover hygiene tails are "
        "closed on the PRODUCTION reference path (invalid UTF-8 -> rc 2 with "
        "the offending byte and offset; NaN/Infinity/-Infinity refused at the "
        "JSON door; the literal top-level -0 refused), each held inside its "
        "ruling's scope (nested -0 byte-parity, -0 elsewhere still an ordinary "
        "zero, -0.0/-0e0 still floats, a BOM still a JSON refusal), with V3 "
        "re-asserted at both signs and the ordinary path unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
