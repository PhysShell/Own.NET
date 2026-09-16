#!/usr/bin/env python3
"""#263 step 7 — controls on host qualification and the execution binding.

    hostqual-memory-vocabulary    one closed set, three files, no drift
    hostqual-ci-predicate         ci == false, not "the field is absent"
    hostqual-provisioning-shape   a declaration with a hole is not a declaration
    hostqual-quiesce-arithmetic   quiet passes; spike, mean, gap and rewind do not
    hostqual-session-binds        a qualified host outside this campaign is refused
    hostqual-not-a-certificate    qualification proves capability, never session fitness
    execbinding-references        the binding carries references, not copies
    execbinding-strata            two strata, two metrics, both qualified
    execbinding-no-overwrite      a rebuild is deliberate, never silent
    tools-do-not-import-harness   qualification never reaches into the frozen instrument

Both platform branches are exercised through synthetic fixtures, so the Windows
rules are driven on Linux and the Linux rules on Windows. Where a control can
only observe the live branch it says so rather than claiming both were run.

Failures print `FAIL[<check>]: <detail>`; nothing stops at the first one.

Run:  python tests/test_step7_hostqual.py
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "step7"))

import execbinding as eb  # noqa: E402
import hostqual as hq  # noqa: E402
import perf_baseline as pb  # noqa: E402

_FAILURES: list[tuple[str, str]] = []
_PASSES: list[str] = []


def fail(check: str, detail: str) -> None:
    _FAILURES.append((check, detail))
    print(f"FAIL[{check}]: {detail}")


def ok(check: str, detail: str = "") -> None:
    _PASSES.append(check)
    print(f"ok[{check}]: {detail}" if detail else f"ok[{check}]")


def guarded(check: str, control: Callable[[], None]) -> None:
    try:
        control()
    except Exception as exc:  # a crashing control is a finding, not a traceback
        fail(check, f"the control raised {type(exc).__name__}: {exc}")


def manifest(ci: bool = False, fingerprint: str = "sha256:abc",
             environment_id: str = "env-1") -> dict:
    return {
        "identity": {
            "environment_id": {"status": "observed", "value": environment_id},
            "host_fingerprint": {"status": "observed", "value": fingerprint},
        },
        "provenance": {"ci": ci, "runner_name": None},
    }


def provisioning(**overrides: object) -> dict:
    doc: dict[str, object] = {
        "kind": hq.PROVISIONING_SCHEMA,
        "schema": 1,
        "environment_id": "env-1",
        "host_fingerprint": "sha256:abc",
        "operator": "owner",
        "recorded_at": "2026-09-16T00:00:00+00:00",
        "dedicated_to_p022": True,
        "no_concurrent_user_workload": True,
        "hosted_ci_runner": False,
        "prohibited_background_declared_inactive": True,
        "virtualization": {"is_vm": False,
                           "fixed_vcpu": "n/a: bare metal",
                           "fixed_ram": "n/a: bare metal",
                           "live_migration_disabled": "n/a: bare metal",
                           "dynamic_memory_disabled": "n/a: bare metal"},
    }
    doc.update(overrides)
    return doc


def write(tmp: Path, name: str, doc: dict) -> Path:
    path = tmp / name
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def qualification(stratum: str = "linux", qualified: bool = True, **overrides) -> dict:
    doc = {
        "kind": "own.net/p022/host-qualification",
        "schema": 1,
        "stratum": stratum,
        "environment_id": f"env-{stratum}",
        "host_fingerprint": "sha256:abc",
        "provisioning": {"sha256": "0" * 64},
        "environment_manifest": {"sha256": "1" * 64},
        "qualification_tool": {"sha256": "2" * 64},
        "predicate": {k: "pass" for k in hq.PREDICATE_KEYS},
        "memory_metric": hq.STRATUM_METRIC[stratum],
        "qualified": qualified,
        "qualified_at": "2026-09-16T00:00:00+00:00",
    }
    doc.update(overrides)
    return doc


# --- the vocabulary ---------------------------------------------------------


def control_memory_vocabulary() -> None:
    """One closed set, declared in three files, proved identical here.

    The tools do not import the frozen instrument, so the set is written down
    more than once. That is a deliberate decoupling with a control on top: a
    drift between the copies fails a test rather than mislabelling a campaign.
    """
    tool_set = set(hq.STRATUM_METRIC.values())
    binding_set = set(eb.STRATUM_METRIC.values())
    if tool_set != pb.MEMORY_METRICS:
        fail("hostqual-memory-vocabulary",
             f"hostqual declares {sorted(tool_set)}, the instrument {sorted(pb.MEMORY_METRICS)}")
        return
    if binding_set != pb.MEMORY_METRICS:
        fail("hostqual-memory-vocabulary",
             f"execbinding declares {sorted(binding_set)}, the instrument "
             f"{sorted(pb.MEMORY_METRICS)}")
        return
    if hq.STRATUM_METRIC != eb.STRATUM_METRIC:
        fail("hostqual-memory-vocabulary", "the two tools map strata to metrics differently")
        return
    if hq.STRATUM_METRIC["linux"] == hq.STRATUM_METRIC["windows"]:
        fail("hostqual-memory-vocabulary", "both strata map to one metric; they measure "
             "different physical quantities")
        return
    ok("hostqual-memory-vocabulary",
       f"linux={hq.STRATUM_METRIC['linux']}, windows={hq.STRATUM_METRIC['windows']}, "
       "identical to the instrument's closed set in both tools")


# --- the predicate ----------------------------------------------------------


def control_ci_predicate() -> None:
    """`ci == false`, never "the field is absent".

    The capture tool writes `ci` as a boolean on every manifest, so a predicate
    demanding its absence could not be satisfied by any real manifest — which is
    exactly the ambiguity the freeze review found.
    """
    cases = [("ci false", manifest(ci=False), "pass"),
             ("ci true", manifest(ci=True), "fail")]
    for label, doc, expected in cases:
        got = hq.check_ci(doc)["result"]
        if got != expected:
            fail("hostqual-ci-predicate", f"{label} gave {got}, expected {expected}")
            return
    missing = manifest()
    del missing["provenance"]["ci"]
    if hq.check_ci(missing)["result"] != "fail":
        fail("hostqual-ci-predicate", "a manifest with no ci field was accepted")
        return
    wrong_type = manifest()
    wrong_type["provenance"]["ci"] = "false"
    if hq.check_ci(wrong_type)["result"] != "fail":
        fail("hostqual-ci-predicate", "the string 'false' was accepted as a boolean")
        return
    ok("hostqual-ci-predicate",
       "false passes, true fails, and an absent or non-boolean ci is refused rather than "
       "read as absence-means-not-CI")


def control_provisioning_shape() -> None:
    if validate := hq.validate_provisioning(provisioning()):
        fail("hostqual-provisioning-shape", f"a complete declaration was refused: {validate}")
        return
    holed = provisioning()
    del holed["dedicated_to_p022"]
    if not hq.validate_provisioning(holed):
        fail("hostqual-provisioning-shape", "a declaration with a missing key was accepted")
        return
    vague = provisioning(fixed_vcpu="unknown")
    vague["virtualization"]["fixed_vcpu"] = "unknown"
    if not hq.validate_provisioning(vague):
        fail("hostqual-provisioning-shape",
             "a bare string was accepted where a boolean or an explicit 'n/a: <reason>' "
             "is required")
        return
    if hq.check_single_tenant(provisioning(dedicated_to_p022=False),
                              manifest())["result"] != "fail":
        fail("hostqual-provisioning-shape", "a host declared not dedicated was qualified")
        return
    if hq.check_single_tenant(provisioning(hosted_ci_runner=True),
                              manifest())["result"] != "fail":
        fail("hostqual-provisioning-shape", "a declared hosted CI runner was qualified")
        return
    if hq.check_single_tenant(provisioning(), manifest(fingerprint="sha256:other")
                              )["result"] != "fail":
        fail("hostqual-provisioning-shape",
             "a declaration describing a different machine than the manifest was accepted")
        return
    ok("hostqual-provisioning-shape",
       "complete declarations pass, a hole is refused, 'unknown' is not an n/a, and a "
       "declaration that names another machine cannot qualify this one")


def control_quiesce_arithmetic() -> None:
    """Driven on injected counters, so the rule is proved without waiting 120 s."""
    def counters(series: list[tuple[int, int]]):
        it = iter(series)
        return lambda: next(it, None)

    quiet = [(0, 0)] + [(i, i * 100) for i in range(1, hq.QUIESCE_INTERVALS + 1)]
    result = hq.quiesce(sleep=lambda _s: None, counters=counters(quiet))
    if not result["eligible"]:
        fail("hostqual-quiesce-arithmetic", f"a 1% machine was refused: {result['reason']}")
        return
    if len(result["samples"]) != hq.QUIESCE_INTERVALS:
        fail("hostqual-quiesce-arithmetic",
             f"{len(result['samples'])} samples, expected {hq.QUIESCE_INTERVALS}")
        return

    spike = [(0, 0)] + [(i * 30 if i == 4 else i, i * 100) for i in
                        range(1, hq.QUIESCE_INTERVALS + 1)]
    if hq.quiesce(sleep=lambda _s: None, counters=counters(spike))["eligible"]:
        fail("hostqual-quiesce-arithmetic", "an interval above the cap was accepted")
        return

    busy = [(0, 0)] + [(i * 10, i * 100) for i in range(1, hq.QUIESCE_INTERVALS + 1)]
    if hq.quiesce(sleep=lambda _s: None, counters=counters(busy))["eligible"]:
        fail("hostqual-quiesce-arithmetic", "a 10% mean was accepted below a 5% limit")
        return

    short = [(0, 0)] + [(i, i * 100) for i in range(1, 4)]
    gap = hq.quiesce(sleep=lambda _s: None, counters=counters(short))
    if gap["eligible"] or "sample" not in str(gap["reason"]):
        fail("hostqual-quiesce-arithmetic", f"a missing sample was not refused: {gap}")
        return

    rewind = [(0, 0), (5, 100), (1, 50)]
    back = hq.quiesce(sleep=lambda _s: None, counters=counters(rewind))
    if back["eligible"]:
        fail("hostqual-quiesce-arithmetic", "a counter that went backwards was accepted")
        return
    ok("hostqual-quiesce-arithmetic",
       f"{hq.QUIESCE_INTERVALS} intervals of {hq.QUIESCE_INTERVAL_S}s; quiet passes, a spike "
       "over 20%, a 10% mean, a missing sample and a rewound counter each refuse")


# --- the two artifacts stay two ---------------------------------------------


def control_not_a_certificate() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        qual = write(tmp, "q.json", qualification())
        record = json.loads(qual.read_text(encoding="utf-8"))
        leaked = [k for k in ("quiesce", "eligible", "cpu_samples") if k in record]
        if leaked:
            fail("hostqual-not-a-certificate",
                 f"the qualification carries session-fitness fields {leaked}; a qualification "
                 "that certifies quiet makes 'a fresh manifest per session' decorative")
            return
    ok("hostqual-not-a-certificate",
       "the qualification proves capability against named bytes and carries no session "
       "quiesce, no eligibility and no Rust-vs-Python number")


def control_session_binds_campaign() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        qual = write(tmp, "q.json", qualification())
        fresh = write(tmp, "m.json", manifest())
        bound = {"linux": {"qualification_sha256": hq.sha256_file(qual),
                           "memory_metric": hq.STRATUM_METRIC["linux"]}}
        good = write(tmp, "b.json", bound)
        quiet = {"eligible": True, "reason": "", "samples": [0.01], "mean": 0.01, "max": 0.01}
        record = hq.session_eligibility(good, qual, fresh, quiesce_result=quiet)
        for key in ("execution_binding_sha256", "qualification_sha256",
                    "fresh_environment_manifest_sha256"):
            if not record.get(key):
                fail("hostqual-session-binds", f"the session record does not carry {key}")
                return

        other = write(tmp, "b2.json", {"linux": {"qualification_sha256": "9" * 64,
                                                 "memory_metric": hq.STRATUM_METRIC["linux"]}})
        substituted = hq.session_eligibility(other, qual, fresh, quiesce_result=quiet)
        if substituted["eligible"]:
            fail("hostqual-session-binds",
                 "a qualified host the binding does not name was allowed into the campaign")
            return
        noisy = hq.session_eligibility(good, qual, fresh,
                                       quiesce_result={"eligible": False, "reason": "loud",
                                                       "samples": [], "mean": None, "max": None})
        if noisy["eligible"]:
            fail("hostqual-session-binds", "a session was eligible despite a failed quiesce")
            return
    ok("hostqual-session-binds",
       "a session names binding, qualification and its fresh manifest; a qualified host outside "
       "this campaign and a failed quiesce each refuse the start")


def control_execbinding_references() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        lin = write(tmp, "ql.json", qualification("linux"))
        win = write(tmp, "qw.json", qualification("windows"))
        cand_l = tmp / "cand.linux"
        cand_l.write_bytes(b"linux candidate")
        cand_w = tmp / "cand.win"
        cand_w.write_bytes(b"windows candidate bytes")
        t0 = tmp / "t0.md"
        t0.write_text("T0", encoding="utf-8")
        loads = write(tmp, "w.json", {"decisive": []})
        binding = eb.build(t0, "c0ffee", "b10b", "acce97", "104c384d", loads,
                           {"linux": (lin, cand_l), "windows": (win, cand_w)})
        problems = eb.validate(binding)
        if problems:
            fail("execbinding-references", f"a well-formed binding was refused: {problems}")
            return
        blob = json.dumps(binding)
        copied = [word for word in ("governor", "power_plan", "scaling_governor", "cpu_samples",
                                    "provisioning", "predicate_detail") if word in blob]
        if copied:
            fail("execbinding-references",
                 f"the binding copies qualification detail {copied}; it must carry references, "
                 "because two copies of one fact drift")
            return
        if binding["linux"]["candidate_bytes"] == binding["windows"]["candidate_bytes"]:
            fail("execbinding-references", "the fixture cannot tell the two candidates apart")
            return
    ok("execbinding-references",
       "the binding carries t0, instrument, workloads and one reference block per stratum, "
       "and no copy of the qualification's own facts")


def control_execbinding_strata() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        cand = tmp / "c"
        cand.write_bytes(b"x")
        t0 = tmp / "t0.md"
        t0.write_text("T0", encoding="utf-8")
        loads = write(tmp, "w.json", {"decisive": []})
        lin = write(tmp, "ql.json", qualification("linux"))
        win = write(tmp, "qw.json", qualification("windows"))

        try:
            eb.build(t0, "c", "b", "a", "d", loads, {"linux": (lin, cand)})
        except eb.BindingRefused:
            pass
        else:
            fail("execbinding-strata", "a campaign with one stratum was bound")
            return

        unqualified = write(tmp, "qu.json", qualification("windows", qualified=False))
        try:
            eb.build(t0, "c", "b", "a", "d", loads,
                     {"linux": (lin, cand), "windows": (unqualified, cand)})
        except eb.BindingRefused:
            pass
        else:
            fail("execbinding-strata", "an unqualified host entered a campaign")
            return

        mislabelled = write(tmp, "qm.json",
                            qualification("windows", memory_metric=hq.MEMORY_METRIC_RESIDENT))
        try:
            eb.build(t0, "c", "b", "a", "d", loads,
                     {"linux": (lin, cand), "windows": (mislabelled, cand)})
        except eb.BindingRefused:
            pass
        else:
            fail("execbinding-strata", "a Windows stratum carrying the resident metric was bound")
            return

        both_same = eb.build(t0, "c", "b", "a", "d", loads,
                             {"linux": (lin, cand), "windows": (win, cand)})
        both_same["windows"]["memory_metric"] = hq.MEMORY_METRIC_RESIDENT
        if not eb.validate(both_same):
            fail("execbinding-strata", "a binding whose strata share one metric validated")
            return
    ok("execbinding-strata",
       "both strata are required, an unqualified or mislabelled host is refused, and two "
       "strata carrying one metric do not validate")


def control_execbinding_no_overwrite() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        existing = tmp / "binding.json"
        existing.write_text("{}", encoding="utf-8")
        # Captured, not printed: a green run that prints a refusal teaches readers
        # to ignore refusals.
        noise = io.StringIO()
        with contextlib.redirect_stderr(noise):
            rc = eb.main(["--emit", str(existing)])
        if "refused" not in noise.getvalue():
            fail("execbinding-no-overwrite", "the refusal was silent")
            return
        if rc != 2:
            fail("execbinding-no-overwrite",
                 f"emitting over an existing binding returned {rc}, not a refusal")
            return
        if existing.read_text(encoding="utf-8") != "{}":
            fail("execbinding-no-overwrite", "the existing binding was modified")
            return
    ok("execbinding-no-overwrite",
       "a rebuild before the first clock is legitimate but never silent: the emitter refuses "
       "to overwrite and says so")


def control_tools_do_not_import_harness() -> None:
    """The qualification layer does not reach into the frozen instrument.

    Proved by AST rather than by text, because this file's own docstrings name
    `perf_baseline` to say the tools do not import it.
    """
    for name in ("hostqual.py", "execbinding.py"):
        tree = ast.parse((ROOT / "scripts" / "step7" / name).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        reached = [m for m in imported if m.split(".")[0] in ("perf_baseline", "envcapture")]
        if reached:
            fail("tools-do-not-import-harness", f"{name} imports {reached}")
            return
    ok("tools-do-not-import-harness",
       "neither tool imports the instrument or the capture tool; the shared vocabulary is "
       "held together by a control instead of by coupling")


def run() -> int:
    guarded("hostqual-memory-vocabulary", control_memory_vocabulary)
    guarded("hostqual-ci-predicate", control_ci_predicate)
    guarded("hostqual-provisioning-shape", control_provisioning_shape)
    guarded("hostqual-quiesce-arithmetic", control_quiesce_arithmetic)
    guarded("hostqual-not-a-certificate", control_not_a_certificate)
    guarded("hostqual-session-binds", control_session_binds_campaign)
    guarded("execbinding-references", control_execbinding_references)
    guarded("execbinding-strata", control_execbinding_strata)
    guarded("execbinding-no-overwrite", control_execbinding_no_overwrite)
    guarded("tools-do-not-import-harness", control_tools_do_not_import_harness)
    print()
    print(f"step 7 host qualification controls: {len(_PASSES)} passed, {len(_FAILURES)} failed")
    return 1 if _FAILURES else 0


if __name__ == "__main__":
    sys.exit(run())
