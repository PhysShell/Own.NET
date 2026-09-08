#!/usr/bin/env python3
"""The compare driver's own controls (P-022 step 7a, #260 acceptance — owner
decisions R-1, R-2, B-2).

`scripts/shadow_compare.py` is the thing that makes the acceptance claim, so it
is the thing that needs adversarial controls. Every rule it states must have an
input that breaks exactly that rule and is refused for it — otherwise the
driver could degrade to "run both engines and print OK" and every positive run
would still pass.

The controls come in two groups, and the split is deliberate rather than
convenient:

* **The double-driven group** runs everywhere, including the Python-only test
  matrix. Its subject is the DRIVER's reaction to a child that misbehaves — a
  crash, a timeout, garbage on stdout, a protocol it does not speak, a
  `consumed` computed over the wrong bytes. `tests/fake_shadow_engine.py`
  replays a capture a real run already wrote into the tree and perturbs exactly
  one thing; it emulates no engine and asserts nothing about the port.
* **The adapter-driven group** needs the real `own-shadow-engine`, because its
  subject is what the two engines actually do with a byte sequence. It runs
  when the binary is present and is REQUIRED under
  `OWN_SHADOW_COMPARE_REQUIRED=1` — the same shape the Tier-B suites use, so
  the gate that has the toolchain cannot silently skip it.

The summary line says which groups ran, because "controls passed" means nothing
without "these controls ran".

Run:  python tests/test_shadow_compare.py
      python tests/run_tests.py           (runs it in the suite)
      OWN_SHADOW_COMPARE_REQUIRED=1 python tests/test_shadow_compare.py
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from ownlang.repro import canonical_hash, load_bytes

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DRIVER = os.path.join(ROOT, "scripts", "shadow_compare.py")
FAKE = os.path.join(HERE, "fake_shadow_engine.py")
FIXDIR = os.path.join(HERE, "fixtures", "repro")
VARIANTS = os.path.join(FIXDIR, "variants")
BASE = os.path.join(FIXDIR, "canonical_minimal.facts.json")

# The driver's exit vocabulary, restated here rather than imported: a control
# that read the codes from the thing it is testing would agree with it by
# construction, including when both are wrong.
EXIT_AGREED = 0
EXIT_DIVERGED = 1
EXIT_EXECUTION_FAILURE = 2
EXIT_INPUT_REFUSED = 3
EXIT_INPUT_DISAGREEMENT = 4
EXIT_USAGE = 5

REQUIRED_ENV = "OWN_SHADOW_COMPARE_REQUIRED"


def _adapter() -> str | None:
    """The real adapter, named EXPLICITLY or not used.

    This used to discover `rust/target/{release,debug}/own-shadow-engine`, and
    the mutation campaign measured why that was wrong: a campaign restores the
    SOURCE it mutated but not the binary a previous mutation's `cargo test`
    left behind, so this group silently ran against an adapter built from
    another mutation's tree. A control whose subject depends on build state
    nobody declared is a control that measures the wrong thing on some runs and
    the right thing on others.

    Explicit is therefore the contract: CI names the binary it just built, and
    a run that does not name one runs the double-driven group only — the group
    whose subject is the DRIVER, which is what a campaign over the driver
    mutates. `OWN_SHADOW_COMPARE_REQUIRED=1` makes the absence a failure rather
    than a stand-down."""
    from_env = os.environ.get("OWN_SHADOW_ENGINE")
    if from_env and os.path.exists(from_env):
        return from_env
    return None


def _double_engine(directory: str) -> str:
    """The stand-in, in a form this platform can actually start.

    The driver runs its adapter as ONE argv entry, because the real adapter is
    a binary that takes no arguments (owner decision R-1). POSIX starts
    `fake_shadow_engine.py` from its shebang. Windows cannot start a `.py` at
    all — `CreateProcess` does not consult file associations — so every
    double-driven control failed there with `WinError 193`, and the group whose
    whole point is that it "runs everywhere, including the Python-only test
    matrix" did not run on Windows at all. A one-line launcher beside it is the
    smallest thing that keeps the driver's contract intact and the controls
    running on both platforms; it is also the file whose digest the driver then
    records, which is correct — it is the file that ran."""
    if os.name != "nt":
        return FAKE
    launcher = os.path.join(directory, "fake_shadow_engine.cmd")
    with open(launcher, "w", encoding="ascii", newline="\r\n") as f:
        f.write("@echo off\n")
        f.write(f'"{sys.executable}" "{FAKE}" %*\n')
    return launcher


def _digest(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _run(args: list[str], *, engine: str, mode: str | None = None,
         extra_env: dict[str, str] | None = None,
         timeout: float = 300.0) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["OWN_SHADOW_ENGINE"] = engine
    env.pop("OWN_FAKE_ENGINE_MODE", None)
    env.pop("OWN_FAKE_ENGINE_REWRITE", None)
    if mode is not None:
        env["OWN_FAKE_ENGINE_MODE"] = mode
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, DRIVER, "--engine", "compare", *args],
        capture_output=True, text=True, env=env, timeout=timeout, check=False)


def _double_controls() -> list[tuple[str, str]]:
    """The driver's reaction to a child that misbehaves (owner decision R-2)."""
    fails: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory() as out:
        fake_engine = _double_engine(out)

        def expect(label: str, mode: str, code: int, needle: str,
                   artifact_forbidden: bool = True,
                   extra_env: dict[str, str] | None = None,
                   args: list[str] | None = None,
                   timeout: float = 300.0) -> subprocess.CompletedProcess[str] | None:
            case_out = os.path.join(out, mode)
            try:
                done = _run([*(args or [BASE]), "--out", case_out],
                            engine=fake_engine, mode=mode, extra_env=extra_env,
                            timeout=timeout)
            except subprocess.TimeoutExpired:
                fails.append(("compare-control",
                              f"{label}: the driver itself did not terminate — a "
                              f"timeout must be the DRIVER's, not the caller's"))
                return None
            blob = done.stdout + done.stderr
            if done.returncode != code:
                fails.append(("compare-control",
                              f"{label}: driver exited {done.returncode}, "
                              f"expected {code}. Output: {blob[:400]}"))
            if needle not in blob:
                fails.append(("compare-control",
                              f"{label}: the driver did not say why (expected "
                              f"{needle!r}). Output: {blob[:400]}"))
            written = (sorted(os.listdir(case_out))
                       if os.path.isdir(case_out) else [])
            if artifact_forbidden and any(n.endswith(".compare.json")
                                          and "artifact" in _read(case_out, n)
                                          for n in written):
                fails.append(("compare-control",
                              f"{label}: a reproduction ARTIFACT was written for a "
                              f"run in which no capture was produced (owner "
                              f"decision R-2: that information belongs in a "
                              f"failure report)"))
            return done

        # 1. A crash is a run-level hard failure: non-zero exit, a failure
        #    report, and NO artifact. Never a refusal, never a fallback.
        done = expect("an engine that exits non-zero", "crash",
                      EXIT_EXECUTION_FAILURE, "exited 9")
        reports = [n for n in sorted(os.listdir(os.path.join(out, "crash")))
                   if n.endswith(".failure.json")] if done else []
        if done and not reports:
            fails.append(("compare-control",
                          "a crashing engine produced no failure report — the raw "
                          "input, the exit information and stderr have to land "
                          "somewhere, and it is not a reproduction artifact"))
        elif done:
            report = json.loads(_read(os.path.join(out, "crash"), reports[0]))
            for field in ("exit_code", "stderr", "input", "engine"):
                if field not in report:
                    fails.append(("compare-control",
                                  f"the failure report carries no {field!r}"))
            if report.get("input", {}).get("raw", {}).get("base64") is None:
                fails.append(("compare-control",
                              "the failure report does not carry the raw input, so "
                              "the failure cannot be re-run from it"))

        # 2. A timeout is the same class, and it is the DRIVER's timeout.
        expect("an engine that never terminates", "hang",
               EXIT_EXECUTION_FAILURE, "did not finish within",
               args=[BASE, "--timeout", "2"], timeout=60.0)

        # 3. Output that is not a capture, and a protocol this driver does not
        #    speak. Both are execution failures rather than empty captures: a
        #    driver that read around either would compare against nothing.
        expect("an engine that writes garbage", "garbage",
               EXIT_EXECUTION_FAILURE, "not a JSON capture")
        expect("an engine speaking another protocol", "bad_protocol",
               EXIT_EXECUTION_FAILURE, "speaks protocol")

        # 4. THE trap owner decision B-2 exists to catch: a child that hashes
        #    what it PARSED instead of what it READ. Every raw variant of one
        #    document would then attest one identity, and the byte-level
        #    invariant would silently be the canonical-level one again.
        expect("an engine that hashes the canonical bytes instead of the raw ones",
               "canonical_consumed", EXIT_DIVERGED, "is not input.raw's identity",
               artifact_forbidden=False)

        # 5. Bytes swapped between the capture and the pipe.
        expect("an engine that attests bytes it never read", "foreign_consumed",
               EXIT_DIVERGED, "is not input.raw's identity",
               artifact_forbidden=False)

        # 6. A pre-v3 capture, carrying no attestation at all (owner decision
        #    B-3): refused, never filled in.
        expect("an engine that attests nothing", "no_consumed",
               EXIT_DIVERGED, "consumed is missing", artifact_forbidden=False)

        # 7. THE one-read invariant, driven adversarially: the input changes on
        #    disk WHILE the run is in flight. The double is the only thing that
        #    can act between the two engine runs, and the driver runs the port
        #    FIRST for exactly this reason — a driver that re-read the file for
        #    its second capture would pick up the rewrite, and both the
        #    attestation and this assertion would catch it.
        with open(BASE, "rb") as f:
            base_raw = f.read()
        target = os.path.join(out, "rewritten.facts.json")
        os.makedirs(out, exist_ok=True)
        shutil.copyfile(BASE, target)
        done = _run([target], engine=fake_engine, mode="rewrite_input",
                    extra_env={"OWN_FAKE_ENGINE_REWRITE": target})
        if done.returncode != EXIT_AGREED:
            fails.append(("compare-one-read",
                          f"the input changed on disk mid-run and compare exited "
                          f"{done.returncode}: the driver read the file more than "
                          f"once. {done.stderr[:400]}"))
        else:
            result = _result_of(done, "the one-read invariant", fails)
            if (result is not None
                    and result["input"]["raw"]["digest"]
                    != hashlib.sha256(base_raw).hexdigest()):
                fails.append(("compare-one-read",
                              "the artifact names the REWRITTEN bytes: the driver "
                              "re-read its input"))
        with open(target, "rb") as f:
            if f.read() == base_raw:
                fails.append(("compare-one-read",
                              "the control's stand-in did not actually rewrite the "
                              "input, so the one-read property was never tested"))

        # 8. THE branch that is nobody's to decide: one engine names the input
        #    and the other does not. No corpus document reaches it (F.0 measured
        #    zero disagreements), so the driver's stop-and-report path had no
        #    control at all until a surviving mutation said so.
        expect("an engine that cannot name an input the reference can",
               "cannot_name_it", EXIT_INPUT_DISAGREEMENT,
               "domain decision for the repository owner")

        # 9. Equal verdict layers, different rendered SARIF: the one thing the
        #    derived surface is compared separately in order to catch.
        done = expect("a renderer that drops a relatedLocations entry",
                      "renderer_drop", EXIT_DIVERGED, "renderer-only divergence",
                      artifact_forbidden=False)
        if done is not None:
            written = [n for n in sorted(os.listdir(os.path.join(out, "renderer_drop")))
                       if n.endswith(".compare.json")]
            if written:
                result = json.loads(_read(os.path.join(out, "renderer_drop"), written[0]))
                documents = result.get("artifact", {}).get("derived_documents", {})
                if set(documents) != {"python-ownlang", "rust-own-bridge"}:
                    fails.append(("compare-control",
                                  f"a renderer-only divergence retained "
                                  f"{sorted(documents)} — owner decision D-6 says "
                                  f"the full documents are kept on mismatch, and "
                                  f"one side's alone is not a diff"))
    return fails


def _manifest_controls() -> list[tuple[str, str]]:
    """The v2 surfaces: the adapter's identity, a manifest run's provenance and
    denominators, and the rule that an empty set is not agreement.

    Double-driven throughout — the subject is the driver's bookkeeping, not
    what the two engines say about a document, so every entry names the same
    committed document under a different source label. Three copies of one file
    is exactly the point: the counts must come from the OUTCOMES, and nothing
    else about these three differs."""
    fails: list[tuple[str, str]] = []
    with open(BASE, "rb") as f:
        base_raw = f.read()
    base_digest = hashlib.sha256(base_raw).hexdigest()

    with tempfile.TemporaryDirectory() as work:
        engine = _double_engine(work)
        engine_digest = _digest(engine)
        # A SECOND adapter on disk, one line different, so "the digest of the
        # file that ran" and "the digest of some adapter" cannot be the same
        # answer. Without it, a driver that hashed the wrong file would still
        # produce a digest and every assertion below would pass.
        decoy = os.path.join(work, "decoy_engine" + os.path.splitext(engine)[1])
        with open(engine, "rb") as f:
            decoy_bytes = f.read() + b"\n@rem a different adapter\n"
        with open(decoy, "wb") as f:
            f.write(decoy_bytes)
        decoy_digest = hashlib.sha256(decoy_bytes).hexdigest()
        if decoy_digest == engine_digest:
            fails.append(("compare-adapter-identity",
                          "the decoy adapter hashes to the same value as the one "
                          "that runs, so this control proves nothing"))

        def manifest(name: str, documents: list[dict[str, object]],
                     targets: list[str] | None = None) -> str:
            path = os.path.join(work, f"{name}.manifest.json")
            body: dict[str, object] = {"schema": 1, "documents": documents}
            if targets is not None:
                body["targets"] = targets
            with open(path, "w", encoding="utf-8") as f:
                json.dump(body, f, indent=2)
            return path

        def entry(source: str, target: str,
                  digest: str = base_digest) -> dict[str, object]:
            path = os.path.join(work, source)
            with open(path, "wb") as f:
                f.write(base_raw)
            return {"source": path, "target": target,
                    "target_commit": "0" * 40,
                    "extraction_mode": "directory-walk",
                    "extraction_command": "scripts/own-check.sh --emit-facts …",
                    "facts_sha256": digest, "timeout_seconds": 120.0}

        # 1. THE adapter identity, in a green result: the digest is of the file
        #    that ran, and provably not of the other adapter beside it.
        done = _run([BASE], engine=engine, mode="faithful")
        result = _result_of(done, "the adapter identity", fails)
        if result is not None:
            if result.get("engine_binary_sha256") != engine_digest:
                fails.append(("compare-adapter-identity",
                              f"the result names adapter digest "
                              f"{result.get('engine_binary_sha256')}, the file the "
                              f"driver was told to run hashes to {engine_digest} — "
                              f"a recorded comparison that names the wrong engine "
                              f"is a recorded comparison of nothing"))
            if result.get("engine_binary_sha256") == decoy_digest:
                fails.append(("compare-adapter-identity",
                              "the result names the DECOY adapter's digest: the "
                              "identity was taken from a file other than the one "
                              "that ran"))
            if result.get("engine_binary_bytes") != os.path.getsize(engine):
                fails.append(("compare-adapter-identity",
                              f"the result names "
                              f"{result.get('engine_binary_bytes')} adapter bytes, "
                              f"the file that ran is {os.path.getsize(engine)}"))
            if result.get("shadow_compare_version") != 2:
                fails.append(("compare-adapter-identity",
                              f"the result declares shadow_compare_version "
                              f"{result.get('shadow_compare_version')!r}; the "
                              f"adapter identity is what version 2 IS"))

        # 2. ...and in a FAILURE REPORT, where it matters at least as much: a
        #    crash you cannot attribute to a build is a crash you cannot chase.
        crash_out = os.path.join(work, "crash")
        done = _run([BASE, "--out", crash_out], engine=engine, mode="crash")
        reports = ([n for n in sorted(os.listdir(crash_out))
                    if n.endswith(".failure.json")]
                   if os.path.isdir(crash_out) else [])
        if done.returncode != EXIT_EXECUTION_FAILURE or not reports:
            fails.append(("compare-adapter-identity",
                          f"a crashing adapter produced no failure report (exit "
                          f"{done.returncode})"))
        else:
            report = json.loads(_read(crash_out, reports[0]))
            if report.get("engine_binary_sha256") != engine_digest:
                fails.append(("compare-adapter-identity",
                              f"the failure report names adapter digest "
                              f"{report.get('engine_binary_sha256')}, expected "
                              f"{engine_digest}"))

        # 3. An EMPTY manifest is a failure, not agreement — #250's fifth
        #    failure mode, as an executable rule.
        empty_out = os.path.join(work, "empty")
        done = _run(["--manifest", manifest("empty", []), "--out", empty_out],
                    engine=engine, mode="faithful")
        if done.returncode != EXIT_USAGE:
            fails.append(("compare-empty-set",
                          f"an empty manifest exited {done.returncode}, expected "
                          f"{EXIT_USAGE}: a run that compared zero documents "
                          f"reported something other than failure"))
        # The wording of the check that is SUPPOSED to fire, not merely "some
        # check fired": the totals backstop says ZERO too, so a needle both
        # messages match would let a mutation of either one survive.
        if "the manifest lists no documents" not in done.stdout + done.stderr:
            fails.append(("compare-empty-set",
                          f"an empty run did not refuse it at the manifest, "
                          f"where the rule is stated. Output: "
                          f"{(done.stdout + done.stderr)[:400]}"))

        # 4. A DIGEST MISMATCH stops the run before any engine is started. The
        #    double is in `crash` mode: had one been started, the exit would be
        #    the execution-failure code rather than the usage one, and a failure
        #    report would exist.
        stale_out = os.path.join(work, "stale")
        stale = manifest("stale", [entry("stale.facts.json", "T", "0" * 64)])
        done = _run(["--manifest", stale, "--out", stale_out],
                    engine=engine, mode="crash")
        blob = done.stdout + done.stderr
        if done.returncode != EXIT_USAGE:
            fails.append(("compare-manifest-digest",
                          f"a manifest whose facts_sha256 does not match the file "
                          f"exited {done.returncode}, expected {EXIT_USAGE}"))
        if "no engine was run" not in blob:
            fails.append(("compare-manifest-digest",
                          f"the driver did not say that it refused before running "
                          f"an engine. Output: {blob[:400]}"))
        written = sorted(os.listdir(stale_out)) if os.path.isdir(stale_out) else []
        if written:
            fails.append(("compare-manifest-digest",
                          f"the driver wrote {written} for a manifest it refused: "
                          f"the digest check happens BEFORE any engine runs, so "
                          f"there is nothing to report about"))

        # 5. The counts come from the OUTCOMES. The same three documents twice:
        #    once with a faithful double (all agree) and once with one that
        #    attests nothing (all diverge). A summary that counted entries
        #    rather than outcomes would be identical in both runs.
        documents = [entry("a.facts.json", "alpha"),
                     entry("b.facts.json", "alpha"),
                     entry("c.facts.json", "beta")]
        good = manifest("good", documents, targets=["alpha", "beta"])
        for mode, code, agreed, diverged in (("faithful", EXIT_AGREED, 3, 0),
                                             ("no_consumed", EXIT_DIVERGED, 0, 3)):
            run_out = os.path.join(work, f"summary_{mode}")
            done = _run(["--manifest", good, "--out", run_out, "--quiet"],
                        engine=engine, mode=mode)
            if done.returncode != code:
                fails.append(("compare-summary",
                              f"a manifest run with a {mode} double exited "
                              f"{done.returncode}, expected {code}. "
                              f"{done.stderr[:300]}"))
            path = os.path.join(run_out, "summary.json")
            if not os.path.exists(path):
                fails.append(("compare-summary",
                              f"a {mode} manifest run wrote no summary.json — the "
                              f"run summary is the record, and it is written "
                              f"whether or not the run agreed"))
                continue
            summary = json.loads(_read(run_out, "summary.json"))
            totals = summary.get("totals", {})
            want = {"documents_extracted": 3, "compare_attempted": 3,
                    "agreed": agreed, "diverged": diverged}
            for field, value in want.items():
                if totals.get(field) != value:
                    fails.append(("compare-summary",
                                  f"{mode}: totals[{field!r}] is "
                                  f"{totals.get(field)!r}, expected {value}"))
            rows = {row["target"]: row for row in summary.get("targets", [])}
            if sorted(rows) != ["alpha", "beta"]:
                fails.append(("compare-summary",
                              f"{mode}: the summary names targets {sorted(rows)}, "
                              f"expected the two the manifest declares"))
            elif (rows["alpha"]["compare_attempted"] != 2
                  or rows["beta"]["compare_attempted"] != 1):
                fails.append(("compare-summary",
                              f"{mode}: the per-target denominators are not the "
                              f"manifest's ({rows['alpha']}, {rows['beta']})"))
            if summary.get("engine_binary_sha256") != engine_digest:
                fails.append(("compare-summary",
                              f"{mode}: the summary names adapter digest "
                              f"{summary.get('engine_binary_sha256')}, expected "
                              f"{engine_digest}"))
            results = [n for n in sorted(os.listdir(run_out))
                       if n.endswith(".result.json")]
            if len(results) != 3:
                fails.append(("compare-summary",
                              f"{mode}: {len(results)} per-document result(s) "
                              f"written, expected 3 — a manifest run IS the "
                              f"record, so every document's result is written"))

        # 6. A DECLARED target the run never reached fails it. Without the
        #    declaration such a target is simply absent from the summary, which
        #    is the shape a skipped repository would have.
        skipped_out = os.path.join(work, "skipped")
        skipped = manifest("skipped", documents,
                           targets=["alpha", "beta", "gamma"])
        done = _run(["--manifest", skipped, "--out", skipped_out, "--quiet"],
                    engine=engine, mode="faithful")
        blob = done.stdout + done.stderr
        if done.returncode != EXIT_USAGE:
            fails.append(("compare-skipped-target",
                          f"a declared target with no documents exited "
                          f"{done.returncode}, expected {EXIT_USAGE}: every "
                          f"document that DID run agreed, and the run still is "
                          f"not evidence about 'gamma'"))
        if "gamma" not in blob:
            fails.append(("compare-skipped-target",
                          f"the driver did not name the target it never reached. "
                          f"Output: {blob[:400]}"))
    return fails


def _result_of(done: subprocess.CompletedProcess[str], label: str,
               fails: list[tuple[str, str]]) -> dict[str, object] | None:
    """The driver's JSON result, or a reported failure.

    Never a raised `JSONDecodeError`: the driver writes its result to stdout on
    agreement and its reason to stderr otherwise, so a control that called
    `json.loads` on stdout unconditionally turned every unexpected divergence
    into a traceback with no FAIL line — which the campaign then recorded as an
    unattributed catch. A control that cannot say what it saw is worth less than
    one that can."""
    try:
        parsed = json.loads(done.stdout)
    except json.JSONDecodeError:
        fails.append(("compare-control",
                      f"{label}: the driver wrote no result on stdout (exit "
                      f"{done.returncode}). stderr: {done.stderr[:400]}"))
        return None
    return parsed if isinstance(parsed, dict) else None


def _read(directory: str, name: str) -> str:
    with open(os.path.join(directory, name), encoding="utf-8") as f:
        return f.read()


def _adapter_controls(adapter: str) -> list[tuple[str, str]]:
    """What the two ENGINES do with a byte sequence — the real adapter, always.

    A double cannot answer any of these: the question is what the port itself
    accepts, refuses and computes."""
    fails: list[tuple[str, str]] = []
    with open(BASE, "rb") as f:
        base_raw = f.read()
    base_canonical = canonical_hash(load_bytes(base_raw))["digest"]

    with tempfile.TemporaryDirectory() as work:
        # 1. The raw-variant controls. Each is the SAME document written as
        #    DIFFERENT bytes, so compare must agree AND the artifact must name
        #    the variant's own digest — not the base's, and not the canonical
        #    one. This is B-1's sentence, driven end to end.
        for variant in ("crlf", "whitespace_expanded", "whitespace_compact",
                        "key_order_reversed", "no_trailing_newline"):
            source = os.path.join(VARIANTS, f"{variant}.bin")
            if not os.path.exists(source):
                fails.append(("compare-variant", f"{variant}: no committed variant"))
                continue
            with open(source, "rb") as f:
                raw = f.read()
            target = os.path.join(work, f"{variant}.facts.json")
            with open(target, "wb") as f:
                f.write(raw)
            done = _run([target], engine=adapter)
            if done.returncode != EXIT_AGREED:
                fails.append(("compare-variant",
                              f"{variant}: compare exited {done.returncode} on a "
                              f"raw variant of a document both engines accept. "
                              f"{done.stderr[:300]}"))
                continue
            result = _result_of(done, variant, fails)
            if result is None:
                continue
            digest = result["input"]["raw"]["digest"]
            expected = hashlib.sha256(raw).hexdigest()
            if digest != expected:
                fails.append(("compare-variant",
                              f"{variant}: the driver reports raw digest {digest}, "
                              f"but the bytes it was given hash to {expected} — it "
                              f"did not attest what it read"))
            if digest == base_canonical:
                fails.append(("compare-variant",
                              f"{variant}: the driver reported the CANONICAL digest "
                              f"as the raw one; the two are different questions and "
                              f"this variant exists to keep them apart"))
            if raw != base_raw and digest == hashlib.sha256(base_raw).hexdigest():
                fails.append(("compare-variant",
                              f"{variant}: the driver reported the BASE document's "
                              f"digest for a different byte sequence"))

        # 2. The negative class, measured in F.0: both readers refuse these, so
        #    the driver reports `input-refused` and writes no artifact.
        for variant, why in (("bom", "a UTF-8 BOM"),
                             ("invalid_utf8", "a lone continuation byte"),
                             ("malformed_json", "a truncated document")):
            source = os.path.join(VARIANTS, f"{variant}.bin")
            if not os.path.exists(source):
                fails.append(("compare-negative", f"{variant}: no committed variant"))
                continue
            target = os.path.join(work, f"neg_{variant}.facts.json")
            shutil.copyfile(source, target)
            out = os.path.join(work, f"out_{variant}")
            done = _run([target, "--out", out], engine=adapter)
            if done.returncode != EXIT_INPUT_REFUSED:
                fails.append(("compare-negative",
                              f"{variant} ({why}): compare exited "
                              f"{done.returncode}, expected {EXIT_INPUT_REFUSED} "
                              f"(input-refused). {done.stderr[:300]}"))
            written = sorted(os.listdir(out)) if os.path.isdir(out) else []
            for name in written:
                if "artifact" in _read(out, name):
                    fails.append(("compare-negative",
                                  f"{variant}: an artifact was written for bytes "
                                  f"neither engine can name"))

    # 3. The whole committed corpus, which is the acceptance claim itself.
    done = _run(["--corpus", "--quiet"], engine=adapter, timeout=1800.0)
    if done.returncode != EXIT_AGREED:
        fails.append(("compare-corpus",
                      f"compare over the committed corpus exited "
                      f"{done.returncode}: {done.stderr[:1200]}"))
    return fails


def run() -> int:
    fails: list[tuple[str, str]] = []
    fails += _double_controls()
    fails += _manifest_controls()
    adapter = _adapter()
    required = os.environ.get(REQUIRED_ENV) == "1"
    if adapter is None:
        if required:
            fails.append(("compare-adapter",
                          f"{REQUIRED_ENV}=1 but no own-shadow-engine binary is "
                          f"built. Build it: cd rust && cargo build -p own-shadow "
                          f"--bin own-shadow-engine"))
        else:
            print("shadow compare: SKIPPED the adapter-driven controls — no "
                  "OWN_SHADOW_ENGINE names a built adapter. Build it (cd rust && "
                  "cargo build -p own-shadow --bin own-shadow-engine) and export "
                  "OWN_SHADOW_ENGINE, or run the shadow compare CI job, which "
                  "sets it beside " + REQUIRED_ENV + "=1 and cannot skip.")
    else:
        fails += _adapter_controls(adapter)

    if fails:
        for check, detail in fails:
            print(f"FAIL[{check}]: shadow compare {detail}")
        return 1
    through_adapter = ("" if adapter is None else
                       ", 5 raw-variant + 3 negative controls and the whole "
                       "committed corpus through the real adapter")
    print(f"shadow compare controls OK: 10 double-driven controls held (crash, "
          f"timeout, garbage, protocol skew, three attestation traps, the "
          f"one-read invariant, an input disagreement and a renderer-only "
          f"divergence), 6 manifest/identity controls (the adapter named by the "
          f"digest of the file that ran, in a result and in a failure report; an "
          f"empty run; a stale facts_sha256 refused before any engine; the "
          f"summary counts derived from the outcomes; a declared target nothing "
          f"reached)"
          f"{through_adapter}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
