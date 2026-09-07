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

REQUIRED_ENV = "OWN_SHADOW_COMPARE_REQUIRED"


def _adapter() -> str | None:
    """The real adapter, if it has been built."""
    from_env = os.environ.get("OWN_SHADOW_ENGINE")
    if from_env and os.path.exists(from_env):
        return from_env
    for profile in ("release", "debug"):
        candidate = os.path.join(ROOT, "rust", "target", profile, "own-shadow-engine")
        if os.path.exists(candidate):
            return candidate
    return None


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
        def expect(label: str, mode: str, code: int, needle: str,
                   artifact_forbidden: bool = True,
                   extra_env: dict[str, str] | None = None,
                   args: list[str] | None = None,
                   timeout: float = 300.0) -> subprocess.CompletedProcess[str] | None:
            case_out = os.path.join(out, mode)
            try:
                done = _run([*(args or [BASE]), "--out", case_out],
                            engine=FAKE, mode=mode, extra_env=extra_env,
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
        done = _run([target], engine=FAKE, mode="rewrite_input",
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
                  "own-shadow-engine binary. Build it (cd rust && cargo build -p "
                  "own-shadow --bin own-shadow-engine) or run the shadow compare "
                  "CI job, which sets " + REQUIRED_ENV + "=1 and cannot skip.")
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
          f"divergence)"
          f"{through_adapter}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
