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
      the stream stays silent;
  (b) guard true, caller relies on the callee: nothing beyond sound inference — no
      fabricated release AND no fabricated leak;
  (c) definite consumers — plain dispose and dispose in a finally every return runs
      through: still a handoff, so a later use is still OWN002. This is the regression
      anchor that keeps the fix from disabling the consume contract wholesale.

plus the wrapper case: a parameter forwarded with the guard false summarizes as `no`.

Line numbers are read off the fixture's text, not hard-coded, so an edit to the comments
cannot silently shift what is being checked.

REQUIRED VS SKIPPED — the tests/test_extractor_columns.py convention: required exactly
when OWN_TIERB_REQUIRED=1, a clean printed skip otherwise.

Run:  OWN_TIERB_REQUIRED=1 python3 tests/test_guarded_consume.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXT = os.path.join(_REPO, "frontend", "roslyn", "OwnSharp.Extractor")
_SAMPLE_REL = os.path.join("frontend", "roslyn", "samples", "GuardedConsumeSample.cs")
_SAMPLE = os.path.join(_REPO, _SAMPLE_REL)

# (call text in the fixture, the tracked argument) — the call must NOT be a release.
_PARTIAL = [
    ("MaybeClose(keptStream, false);", "keptStream"),
    ("CloseUnlessKept(earlyKept, true);", "earlyKept"),
    ("MaybeForward(forwardKept, false);", "forwardKept"),
    ("MaybeClose(handedStream, true);", "handedStream"),
]
# (call text, argument) — definite consumers: the call IS a release (the handoff anchor).
_DEFINITE = [
    ("Close(handoffStream);", "handoffStream"),
    ("CloseInFinally(finallyStream);", "finallyStream"),
]
_SILENT = ["keptStream", "earlyKept", "forwardKept", "handedStream"]
_USE_AFTER_HANDOFF = ["handoffStream", "finallyStream"]


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
    for text, var in _PARTIAL:
        if (var, _line_of(text)) in releases:
            fails.append(f"{text!r}: a partial (guarded) release was lowered as a call-site "
                         "release — the fabricated `must` of #380")
    for text, var in _DEFINITE:
        if (var, _line_of(text)) not in releases:
            fails.append(f"{text!r}: a definite consumer is no longer a call-site release — "
                         "the consume contract regressed")

    if verdict.returncode >= 2:
        fails.append(f"ownir hard error (rc={verdict.returncode}): {verdict.stderr.strip()}")
    report = verdict.stdout + verdict.stderr
    for var in _SILENT:
        if f"'{var}'" in report:
            fails.append(f"{var}: expected silence (no fabricated release, no fabricated leak), "
                         f"got a finding")
    for var in _USE_AFTER_HANDOFF:
        if not any("[OWN002]" in ln and f"'{var}'" in ln for ln in report.splitlines()):
            fails.append(f"{var}: expected OWN002 (use after a definite handoff)")

    try:
        docs = json.loads(summaries.stdout)["summaries"]
    except (ValueError, KeyError, TypeError):
        docs = []
        fails.append(f"summaries dump unreadable (rc={summaries.returncode})")
    wrapper_name = "GuardedConsumeSample.BorrowingWrapper"
    wrapper = [p for d in docs if d.get("method", "").endswith(wrapper_name)
               for p in d.get("params", []) if p.get("name") == "borrowed"]
    if [p.get("transfer") for p in wrapper] != ["no"]:
        fails.append(f"BorrowingWrapper.borrowed: expected transfer 'no', got "
                     f"{[p.get('transfer') for p in wrapper]}")

    for f in fails:
        print(f"FAIL: {f}")
    print(f"guarded consume: {len(fails)} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
