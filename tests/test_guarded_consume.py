#!/usr/bin/env python3
"""#380 — a guarded release is not a call-site handoff (INF-S2), on the real extractor.

The Roslyn call-site handoff (`ConsumeReleaseArgs` -> `ConsumesParam` -> `DisposesLocal`)
lowers a first-party consumer's release as a `release` of the caller's argument: an
unconditional `must`. INF-S2 allows that only for a DEFINITE release. Before #380 a callee
that disposed its parameter only under a guard (`if (dispose) s.Dispose();`) was treated
as a consumer too, which fabricated a release at callers that keep the resource
(`MaybeClose(s, false)`): false OWN002/OWN003/OWN009 there, and a false `must` summary on
a wrapper forwarding its own parameter that way. Reproduced on pinned dotnet/runtime code;
see the issue for the evidence.

The fixture (frontend/roslyn/samples/GuardedConsumeSample.cs) pins three families:

  (a) partial release — guard false, guarded early return, guarded transitive forward:
      the call is NOT lowered as a release and the caller that keeps, uses and disposes
      the stream is never charged a fabricated release (OWN002/OWN003/OWN009);
  (b) guard true, caller relies on the callee: nothing beyond sound inference — no
      fabricated release AND no fabricated leak (OWN001);
  (c) definite consumers — plain dispose and dispose in a finally every return runs
      through: still a handoff, so a later use is still OWN002. This is the regression
      anchor that keeps the fix from disabling the consume contract wholesale.

P-037-X STAGE 1 RE-RECORD (research/p037-max-v1, EXPLORATORY; carrier commit 702d25b,
bridge tolerance 2d2ba15). On main the extractor decides every one of these sites itself:
a definite consumer becomes a call-site `release`, a guarded one is folded into a `use`, and
the core never sees the call. Under the Stage 1 carrier a statement-form invocation of a
first-party callee that carries a record is ONE canonical OwnIR `call` op, and the core
decides from the callee's summary:

  * definite consumers: INF-S2 on the callee gives `must`, A1 lowers the call to `$consume`,
    so the later use is still OWN002 — the SAME verdict, derived instead of fabricated
    (frozen protocol rows XB-5/XB-6: "OWN002 unchanged through the canonical call");
  * guarded consumers: the callee summarizes `may` (no guard value is read at this stage),
    A5a makes the top-level call a kill site with an OWN051 advisory — "OWN051 only",
    never a fabricated release, never a fabricated leak (rows XB-1..XB-4). Main's silence
    was the fold; on this branch silence would mean the canonical call no longer reaches
    the core, and is a failure;
  * the wrapper forwarding its parameter with the guard false summarizes `may` (INF-S3: a
    single straight-line forward to a `may` callee) where the fold gave an accidental `no`
    (row XB-7); a guarded summary reading the `false` cell is what would make it `no` again.

And the PINNED KNOWN LIMITATION: `ForwardDynamic` forwards its own parameter AND the guard.
On main the forward is folded into a `use`, so the summary is `no`, and the pin says: "if a
canonical first-party call fact ever carries this forward to the core, the pin turns red and
should be re-recorded, and #304's reopen condition 1 is due for a re-check". That is exactly
what Stage 1 does, so the pin is re-recorded to `may` HERE, on the research branch only.
Whether #304 reopen condition 1 is met is the owner's decision and is NOT claimed by this
record. A move to `must` would mean the fabricated consume is back.

Line numbers are read off the fixture's text, not hard-coded, so an edit to the comments
cannot silently shift what is being checked.

REQUIRED VS SKIPPED — the tests/test_extractor_columns.py convention: required exactly
when OWN_TIERB_REQUIRED=1, a clean printed skip otherwise.

Run:  OWN_TIERB_REQUIRED=1 python3 tests/test_guarded_consume.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.Extractor")
_SAMPLE_REL = os.path.join("frontend", "roslyn", "samples", "GuardedConsumeSample.cs")
_SAMPLE = os.path.join(_REPO, _SAMPLE_REL)

# (call text in the fixture, the callee, the tracked argument) — partial (guarded)
# consumers: never a call-site release; under the Stage 1 carrier ONE canonical `call`.
_PARTIAL = [
    ("MaybeClose(keptStream, false);", "MaybeClose", "keptStream"),
    ("CloseUnlessKept(earlyKept, true);", "CloseUnlessKept", "earlyKept"),
    ("MaybeForward(forwardKept, false);", "MaybeForward", "forwardKept"),
    ("MaybeClose(handedStream, true);", "MaybeClose", "handedStream"),
]
# (call text, callee, argument) — definite consumers: the handoff anchor. On main these ARE
# call-site releases; under the Stage 1 carrier the same handoff is a canonical `call` that
# the core derives as `must` (INF-S2 on the callee), so the later use is still OWN002.
_DEFINITE = [
    ("Close(handoffStream);", "Close", "handoffStream"),
    ("CloseInFinally(finallyStream);", "CloseInFinally", "finallyStream"),
]
# The kept streams: exactly the OWN051 advisory (an honest `may` at a top-level kill site).
_ADVISORY_ONLY = ["keptStream", "earlyKept", "forwardKept", "handedStream"]
# The handed-off streams: OWN002, and NOT OWN051 — a definite consumer is verified, not `may`.
_USE_AFTER_HANDOFF = ["handoffStream", "finallyStream"]

_CODE = re.compile(r"\[(OWN\d{3})\]")


def _line_of(text: str) -> int:
    hits = [i for i, ln in enumerate(open(_SAMPLE, encoding="utf-8"), 1) if text in ln]
    if len(hits) != 1:
        raise AssertionError(f"fixture must contain {text!r} exactly once, found {len(hits)}")
    return hits[0]


def _walk(body: list, out: list) -> None:
    for op in body or []:
        out.append(op)
        for key in ("then", "else", "body"):
            if key in op:
                _walk(op[key], out)


def _ops(facts: dict) -> list[dict]:
    out: list[dict] = []
    for fn in facts.get("functions", []):
        _walk(fn.get("body"), out)
    return out


def _calls(facts: dict[str, Any]) -> set[tuple[str, str, int]]:
    """(callee simple name, argument, line) for every argument of every canonical `call`."""
    out: set[tuple[str, str, int]] = set()
    for op in _ops(facts):
        if op.get("op") != "call":
            continue
        callee = str(op.get("callee", "")).rsplit(".", 1)[-1]
        for arg in op.get("args") or []:
            out.add((callee, str(arg), int(op.get("line", -1))))
    return out


def _core(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "ownlang", *argv], cwd=_REPO,
                          capture_output=True, text=True,
                          env={**os.environ, "PYTHONPATH": _REPO})


def run() -> int:
    if not shutil.which("dotnet"):
        if os.environ.get("OWN_TIERB_REQUIRED") == "1":
            print("guarded consume: FAIL - dotnet is REQUIRED here "
                  "(OWN_TIERB_REQUIRED=1) and is not on PATH")
            return 1
        print("guarded consume: SKIP - dotnet not on PATH")
        return 0

    fails: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        facts_path = os.path.join(tmp, "facts.json")
        try:
            subprocess.run(["dotnet", "run", "--project", _EXT, "--", "--flow-locals",
                            _SAMPLE_REL, "-o", facts_path],
                           cwd=_REPO, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            print(f"guarded consume: FAIL - the extractor exited {exc.returncode}\n"
                  f"{exc.stdout}\n{exc.stderr}")
            return 1
        with open(facts_path, encoding="utf-8") as fh:
            facts = json.load(fh)
        verdict = _core(["ownir", facts_path, "--severity", "warning"])
        summaries = _core(["summaries", facts_path])

    releases = {(op.get("var"), op.get("line")) for op in _ops(facts) if op.get("op") == "release"}
    calls = _calls(facts)
    for text, callee, var in _PARTIAL:
        line = _line_of(text)
        if (var, line) in releases:
            fails.append(f"{text!r}: a partial (guarded) release was lowered as a call-site "
                         "release — the fabricated `must` of #380")
        if (callee, var, line) not in calls:
            fails.append(f"{text!r}: no canonical `call` op carries {var} to {callee} — the "
                         "P-037-X Stage 1 carrier regressed to the extractor-side fold")
    for text, callee, var in _DEFINITE:
        line = _line_of(text)
        if (var, line) in releases:
            fails.append(f"{text!r}: a definite consumer is again a call-site release — the "
                         "handoff is fabricated in the extractor instead of derived by the "
                         "core from the canonical call (P-037-X Stage 1 record)")
        if (callee, var, line) not in calls:
            fails.append(f"{text!r}: no canonical `call` op carries {var} to {callee} — the "
                         "consume contract has no carrier at all")

    if verdict.returncode >= 2:
        fails.append(f"ownir hard error (rc={verdict.returncode}): {verdict.stderr.strip()}")
    report = verdict.stdout + verdict.stderr

    def codes_for(var: str) -> set[str]:
        return {m.group(1) for ln in report.splitlines() if f"'{var}'" in ln
                for m in _CODE.finditer(ln)}

    for var in _ADVISORY_ONLY:
        codes = codes_for(var)
        if codes != {"OWN051"}:
            why = ("silence: the canonical call no longer reaches the core (main's fold is back)"
                   if not codes else
                   "a fabricated release (OWN002/OWN003/OWN009) or leak (OWN001) is back")
            fails.append(f"{var}: expected exactly the OWN051 advisory (an honest `may` at a "
                         f"top-level kill site), got {sorted(codes)} — {why}")
    for var in _USE_AFTER_HANDOFF:
        codes = codes_for(var)
        if "OWN002" not in codes:
            fails.append(f"{var}: expected OWN002 (use after a definite handoff), got "
                         f"{sorted(codes)} — the consume contract regressed")
        if "OWN051" in codes:
            fails.append(f"{var}: a definite consumer was lowered as an UNVERIFIED transfer "
                         "(OWN051) — INF-S2 no longer derives `must` through the canonical call")

    try:
        docs = json.loads(summaries.stdout)["summaries"]
    except (ValueError, KeyError, TypeError):
        docs = []
        fails.append(f"summaries dump unreadable (rc={summaries.returncode})")
    # P-037-X Stage 1 (research/p037-max-v1, EXPLORATORY; re-recorded at 702d25b): the
    # forward reaches the MOS as a canonical `call`, so INF-S3 derives `may` (a single
    # straight-line forward to a `may` callee) where the folded `use` gave an accidental
    # `no`. Honest but coarser; the frozen protocol (paper-eval/prereg/p037-max-v1.json,
    # row XB-7) predicts `no` again only once a guarded summary reads the `false` cell.
    wrapper_name = "GuardedConsumeSample.BorrowingWrapper"
    wrapper = [p for d in docs if d.get("method", "").endswith(wrapper_name)
               for p in d.get("params", []) if p.get("name") == "borrowed"]
    if [p.get("transfer") for p in wrapper] != ["may"]:
        fails.append(f"BorrowingWrapper.borrowed: expected transfer 'may' (P-037-X Stage 1 "
                     f"record), got {[p.get('transfer') for p in wrapper]}")

    # KNOWN LIMITATION pin (see the module docstring). On main the pin is `no`. P-037-X
    # Stage 1 (research/p037-max-v1, EXPLORATORY; re-recorded at 702d25b) is exactly the
    # pin's `may` branch: the canonical `call` reached the core and INF-S3 derived `may`.
    # Re-recorded here on the research branch only. Whether #304 reopen condition 1 is met
    # by this carrier is the owner's decision and is NOT claimed by this record.
    dynamic_name = "GuardedConsumeSample.ForwardDynamic"
    dynamic = [p.get("transfer") for d in docs if d.get("method", "").endswith(dynamic_name)
               for p in d.get("params", []) if p.get("name") == "forwarded"]
    if dynamic != ["may"]:
        if dynamic == ["must"]:
            why = "the fabricated consume is back (#380 regressed)"
        elif dynamic == ["no"]:
            why = ("the canonical call no longer reaches the core (the P-037-X Stage 1 carrier "
                   "regressed)")
        else:
            why = "the representation moved; classify it before re-recording this pin"
        fails.append(f"KNOWN-LIMITATION PIN MOVED: ForwardDynamic.forwarded is {dynamic}, "
                     f"pinned ['may'] on research/p037-max-v1 — {why}")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"guarded consume: {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
