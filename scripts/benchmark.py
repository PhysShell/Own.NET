#!/usr/bin/env python3
"""
Corpus benchmark — score the checker against the labeled real-world corpus.

Each ``corpus/<area>/<case>/`` holds a real bug: ``before.cs`` (buggy),
``after.cs`` (fixed), ``expected-diagnostics.txt`` (the codes), ``case.own`` (a
reduction) and ``notes.md``. ``tests/test_corpus.py`` checks the ``.own``
*reduction*; this harness runs the **actual C#** through the extractor + core
(``own-check.sh``) and measures the two things the ``.own`` check cannot:

  - **recall** — the bug is *caught* in the real ``before.cs`` (>= 1 verdict);
  - **specificity** — the real ``after.cs`` (the fix) is *silent* (0 verdicts, i.e.
    no false alarm on correct code).

The aggregate is one defensible line: *"N cases - caught C/N in real C# - clean
K/N fixes - F false positives"*. That is the RLVR reward scaffold: a deterministic
verifier over labeled real-C# data.

A *verdict* is any SARIF result at error/warning level. The advisory note level
(``OWN050`` "resolution skipped") is coverage honesty, not a verdict, so it counts
as neither a catch nor a false positive. The catch/clean metric is deliberately
code-agnostic: a leak reported as OWN001 vs OWN014 both count as "caught", so the
benchmark survives a classifier reclassification that ``test_corpus.py``'s
exact-code match would not.

Needs a .NET SDK (``own-check.sh`` runs the extractor); some WPF cases also need
``OWN_EXTRA_REF_DIRS`` to resolve framework events. ``--selftest`` validates the
scoring + SARIF-parsing logic with no SDK (embedded fixtures), so the lint job
keeps the harness honest on every push.

Usage:
  python scripts/benchmark.py [--root REPO] [--corpus DIR ...]   # run the benchmark
  python scripts/benchmark.py --selftest                          # logic check (no SDK)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass

# A verdict is a real finding; these SARIF levels are not (note = the advisory
# OWN050 "resolution skipped"; none = suppressed) — neither a catch nor an FP.
_NONVERDICT_LEVELS = frozenset({"note", "none"})


def sarif_codes(sarif_text: str) -> set[str]:
    """The set of *verdict* rule codes in a SARIF log: results at error/warning
    level. A note-level result (OWN050 resolution-skipped) is advisory coverage
    honesty, not a verdict, so it is excluded. Malformed input yields no codes
    (the caller treats that as "no verdict", surfaced as a missed catch)."""
    try:
        doc = json.loads(sarif_text)
    except (json.JSONDecodeError, ValueError):
        return set()
    if not isinstance(doc, dict):
        return set()
    codes: set[str] = set()
    runs = doc.get("runs")
    for run in runs if isinstance(runs, list) else []:
        if not isinstance(run, dict):
            continue
        results = run.get("results")
        for res in results if isinstance(results, list) else []:
            if not isinstance(res, dict):
                continue
            # SARIF's default level is "warning" — a result without one is a verdict.
            level = res.get("level", "warning")
            rid = res.get("ruleId")
            if isinstance(rid, str) and level not in _NONVERDICT_LEVELS:
                codes.add(rid)
    return codes


@dataclass
class CaseScore:
    """One corpus case scored on real C#: the expected codes, and the verdict
    codes found on ``before.cs`` (buggy) and ``after.cs`` (fixed)."""

    name: str
    expected: set[str]
    before: set[str]
    after: set[str]

    @property
    def caught(self) -> bool:
        """The bug is caught in the real ``before.cs``: at least one verdict."""
        return bool(self.before)

    @property
    def clean(self) -> bool:
        """The real fix (``after.cs``) is silent: no verdict (no false alarm)."""
        return not self.after

    @property
    def expected_hit(self) -> bool:
        """Secondary signal: the specific expected code(s) appear on ``before``
        (a stronger match than "some verdict"). Not part of the gate, so a sound
        reclassification of the leak code does not fail the benchmark."""
        return bool(self.expected) and self.expected <= self.before


def summarize(scores: list[CaseScore]) -> tuple[int, int, int, int]:
    """``(caught, clean, total, false_positives)`` over the scored cases."""
    caught = sum(1 for s in scores if s.caught)
    clean = sum(1 for s in scores if s.clean)
    fps = sum(len(s.after) for s in scores)
    return caught, clean, len(scores), fps


# ---- the SDK-backed half (the real run) --------------------------------------

class BenchmarkError(RuntimeError):
    """own-check could not analyze a file — a hard failure (extractor crash, no
    .NET SDK, drifted/bad facts: a non-zero return). The benchmark must fail
    loudly rather than score an unanalyzed file as 'clean' and pass on output that
    never actually ran."""


def _verdicts_or_raise(stdout: str, returncode: int, cs_file: str,
                       stderr: str = "") -> set[str]:
    """Verdict codes from a *completed* own-check run. own-check exits 0 for clean
    AND for findings (it is run without --fail-on-finding), so any non-zero return
    means the file was not analyzed — raise rather than treat empty/partial output
    as 'no verdict' (Codex: a silent analysis failure must not read as a clean fix
    or a hidden sub-floor miss)."""
    if returncode != 0:
        detail = stderr.strip()
        raise BenchmarkError(
            f"own-check failed (rc={returncode}) on {cs_file}"
            + (f"\n{detail}" if detail else ""))
    # rc==0 means clean OR findings — either way own-check emits a well-formed SARIF
    # log (build_sarif always writes runs:[{...}], possibly with empty results). If
    # stdout is not parseable SARIF, the file was not really analyzed; fail loudly
    # rather than let the permissive parser score garbage as a clean 'no verdict'
    # (CodeRabbit). A valid log with zero results is the legitimate clean case.
    try:
        doc = json.loads(stdout)
    except (json.JSONDecodeError, ValueError) as e:
        raise BenchmarkError(f"own-check emitted invalid SARIF on {cs_file}") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("runs"), list):
        raise BenchmarkError(f"own-check emitted malformed SARIF (no runs) on {cs_file}")
    return sarif_codes(stdout)


def _scan(root: str, cs_file: str, timeout: int = 300) -> set[str]:
    """Run own-check.sh over one .cs file and return its verdict codes (build
    chatter goes to stderr, so stdout is a clean SARIF log). Raises BenchmarkError
    on a hard own-check failure or a timeout (a hung extractor must not stall CI)."""
    script = os.path.join(root, "scripts", "own-check.sh")
    try:
        proc = subprocess.run(
            [script, "--root", root, "--format", "sarif", "--", cs_file],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise BenchmarkError(f"own-check timed out ({e.timeout}s) on {cs_file}") from e
    except OSError as e:
        # own-check.sh missing / not executable / no interpreter — a launch failure
        # must fail loud like any other, not escape run()'s BenchmarkError handler.
        raise BenchmarkError(f"own-check could not start on {cs_file}: {e}") from e
    return _verdicts_or_raise(proc.stdout, proc.returncode, cs_file, proc.stderr)


def discover(corpus_dirs: list[str]) -> list[str]:
    """Case directories carrying before.cs/after.cs/expected-diagnostics.txt."""
    cases: list[str] = []
    for base in corpus_dirs:
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            d = os.path.join(base, name)
            if (os.path.isdir(d)
                    and os.path.exists(os.path.join(d, "before.cs"))
                    and os.path.exists(os.path.join(d, "after.cs"))
                    and os.path.exists(os.path.join(d, "expected-diagnostics.txt"))):
                cases.append(d)
    return cases


def score_corpus(root: str, corpus_dirs: list[str]) -> list[CaseScore]:
    """Run the extractor + core over every case's before.cs and after.cs."""
    scores: list[CaseScore] = []
    for d in discover(corpus_dirs):
        with open(os.path.join(d, "expected-diagnostics.txt"), encoding="utf-8") as f:
            expected = {w for w in f.read().split() if w}
        before = _scan(root, os.path.join(d, "before.cs"))
        after = _scan(root, os.path.join(d, "after.cs"))
        scores.append(CaseScore(os.path.basename(d), expected, before, after))
    return scores


def gate(caught: int, clean: int, total: int, fps: int, min_recall: int) -> list[str]:
    """The regression gate, as a list of problem strings (empty == pass).

    Precision is non-negotiable — *every* fix must be silent and there must be no
    false positive on a fix; a regression there means the checker started crying
    wolf on correct code. Recall on real C# is a *tracked* number that ratchets up
    as the frontend's extraction coverage grows (the missed cases are the
    extractor's to-do list, not a failure of the core logic — test_corpus.py
    already shows the .own reductions all fire); the gate only forbids it dropping
    below the pinned floor."""
    problems: list[str] = []
    if clean != total:
        problems.append(f"specificity regressed: only {clean}/{total} fixes silent")
    if fps != 0:
        problems.append(f"precision regressed: {fps} false positive(s) on fixes")
    if caught < min_recall:
        problems.append(f"recall regressed: {caught}/{total} caught, floor is {min_recall}")
    return problems


def run(root: str, corpus_dirs: list[str], min_recall: int = 0) -> int:
    """Score the corpus on real C#, print the scorecard, and apply the gate."""
    try:
        scores = score_corpus(root, corpus_dirs)
    except BenchmarkError as e:
        # A hard own-check failure (extractor crash / no SDK / timeout) must fail
        # the benchmark loudly — never pass on output that never actually ran.
        print(f"BENCHMARK FAIL: {e}")
        return 1
    if not scores:
        print("BENCHMARK FAIL: no corpus cases found")
        return 1
    width = max(len(s.name) for s in scores)
    print("corpus benchmark (real C# through the extractor + core):")
    for s in scores:
        catch = "caught" if s.caught else "MISSED"
        clean = "clean" if s.clean else f"FP:{','.join(sorted(s.after))}"
        note = ("" if s.expected_hit
                else f"  (expected {sorted(s.expected)}, got {sorted(s.before)})")
        print(f"  {s.name:<{width}}  before[{catch}: {','.join(sorted(s.before)) or '-'}]"
              f"  after[{clean}]{note}")
    caught, clean, total, fps = summarize(scores)
    print(f"benchmark: {caught}/{total} bugs caught in real C# · "
          f"{clean}/{total} fixes clean · {fps} false positive(s) on fixes "
          f"(recall floor {min_recall})")
    problems = gate(caught, clean, total, fps, min_recall)
    for p in problems:
        print(f"BENCHMARK FAIL: {p}")
    return 1 if problems else 0


# ---- selftest (no SDK) -------------------------------------------------------

def _selftest() -> int:
    fails: list[str] = []

    # 1) sarif_codes: verdict levels counted (deduped), note level excluded, junk safe.
    sarif = json.dumps({"runs": [{"results": [
        {"ruleId": "OWN001", "level": "error"},
        {"ruleId": "OWN001", "level": "warning"},   # dedupes with the above
        {"ruleId": "DI001", "level": "error"},
        {"ruleId": "OWN050", "level": "note"},       # advisory -> excluded
        {"ruleId": "OWN999", "level": "none"},       # suppressed -> excluded
    ]}]})
    got = sarif_codes(sarif)
    if got != {"OWN001", "DI001"}:
        fails.append(f"sarif_codes: expected {{OWN001,DI001}}, got {sorted(got)}")
    for bad in ("not json", "{}", "[]", json.dumps({"runs": [{"results": []}]})):
        if sarif_codes(bad) != set():
            fails.append(f"sarif_codes: {bad!r} must yield no codes")
    # a result with no level defaults to a verdict (SARIF's default is "warning").
    if sarif_codes(json.dumps({"runs": [{"results": [{"ruleId": "OWN001"}]}]})) != {"OWN001"}:
        fails.append("sarif_codes: a level-less result must count as a verdict")

    # 2) scoring + aggregation.
    cases = [
        CaseScore("hit_clean", {"OWN001"}, {"OWN001"}, set()),       # caught + clean + hit
        CaseScore("drift_clean", {"OWN001"}, {"OWN014"}, set()),     # caught + clean, drifted
        CaseScore("missed", {"OWN003"}, set(), set()),               # not caught
        CaseScore("leaky_fix", {"OWN001"}, {"OWN001"}, {"OWN001"}),  # caught, fix has an FP
    ]
    checks = [
        (cases[0].caught and cases[0].clean and cases[0].expected_hit, "hit_clean misjudged"),
        (cases[1].caught and cases[1].clean and not cases[1].expected_hit,
         "drift case must be caught+clean but not an expected_hit"),
        (not cases[2].caught and cases[2].clean, "missed case must be not-caught but clean"),
        (cases[3].caught and not cases[3].clean, "leaky_fix must be caught but not clean"),
    ]
    for ok, msg in checks:
        if not ok:
            fails.append(f"scoring: {msg}")
    if summarize(cases) != (3, 3, 4, 1):
        fails.append(f"summarize: expected (3,3,4,1), got {summarize(cases)}")

    # 3) gate: precision absolute (a dirty fix or any FP fails regardless of recall),
    #    recall gated only against the floor.
    gate_checks = [
        (gate(3, 9, 9, 0, min_recall=3) == [], "measured baseline (floor 3) must pass"),
        (gate(2, 9, 9, 0, min_recall=3) != [], "recall below floor must fail"),
        (gate(9, 8, 9, 0, min_recall=3) != [], "a non-silent fix must fail even at full recall"),
        (gate(9, 9, 9, 1, min_recall=3) != [], "a false positive on a fix must fail"),
        (gate(3, 9, 9, 0, min_recall=0) == [], "floor 0 with clean fixes must pass"),
    ]
    for ok, msg in gate_checks:
        if not ok:
            fails.append(f"gate: {msg}")

    # 4) fail-fast guards: a hard own-check failure (bad rc, malformed SARIF, or a
    #    launch failure) must raise — never score garbage as clean; a valid empty
    #    log is the legitimate clean case; a negative recall floor is rejected.
    ok_sarif = json.dumps({"runs": [{"results": [{"ruleId": "OWN001", "level": "error"}]}]})
    empty_sarif = json.dumps({"runs": [{"results": []}]})
    if _verdicts_or_raise(ok_sarif, 0, "f.cs") != {"OWN001"}:
        fails.append("verdicts_or_raise: rc==0 valid SARIF must return parsed codes")
    if _verdicts_or_raise(empty_sarif, 0, "f.cs") != set():
        fails.append("verdicts_or_raise: a valid empty SARIF is a clean 'no verdict'")
    raise_cases = [
        ("non-zero exit", ("", 2, "f.cs", "drift")),
        ("invalid SARIF json", ("not json", 0, "f.cs")),
        ("SARIF without runs", ("{}", 0, "f.cs")),
    ]
    for label, vargs in raise_cases:
        try:
            _verdicts_or_raise(*vargs)
            fails.append(f"verdicts_or_raise: {label} must raise BenchmarkError")
        except BenchmarkError:
            pass
    try:  # a missing own-check.sh (launch failure) must also fail loud
        _scan(os.path.join(os.sep, "no", "such", "ownnet-root"), "x.cs", timeout=5)
        fails.append("_scan: a missing own-check.sh must raise BenchmarkError")
    except BenchmarkError:
        pass
    if _non_negative_int("3") != 3:
        fails.append("_non_negative_int: must accept a non-negative value")
    try:
        _non_negative_int("-1")
        fails.append("_non_negative_int: must reject a negative value")
    except argparse.ArgumentTypeError:
        pass

    guard_count = 2 + len(raise_cases) + 1 + 2
    for f in fails:
        print(f"SELFTEST FAIL: {f}")
    print(f"benchmark selftest: {'OK' if not fails else 'FAIL'} "
          f"— sarif-parse + scoring + gate + guards "
          f"({len(checks) + len(gate_checks) + guard_count} checks)")
    return 1 if fails else 0


def _non_negative_int(value: str) -> int:
    """An argparse int type that rejects negatives — a negative recall floor would
    trivially pass the gate and quietly weaken the regression contract."""
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError("--min-recall must be a non-negative integer")
    return n


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Corpus benchmark for the Own.NET checker.")
    ap.add_argument("--selftest", action="store_true",
                    help="validate the harness logic with no .NET SDK")
    ap.add_argument("--root", default=None, help="repo root (default: this script's repo)")
    ap.add_argument("--corpus", action="append", default=None, metavar="DIR",
                    help="corpus base dir(s) (default: corpus/real-world + corpus/wpf + corpus/di)")
    ap.add_argument("--min-recall", type=_non_negative_int, default=0, metavar="N",
                    help="fail if fewer than N before.cs cases are caught (the pinned "
                         "recall floor; specificity + zero-FP are always required)")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    corpus_dirs = args.corpus or [os.path.join(root, "corpus", "real-world"),
                                  os.path.join(root, "corpus", "wpf"),
                                  os.path.join(root, "corpus", "di")]
    return run(root, corpus_dirs, args.min_recall)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
