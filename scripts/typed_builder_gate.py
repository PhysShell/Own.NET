#!/usr/bin/env python3
"""TB-MVP-01: the Typed Builder + ASP.NET Core + EF Core Order vertical slice, end to end.

The sample is `samples/OrderBackend`; what it must show, and why, is registered in
`docs/notes/tb-mvp-01-preregistration.md`. Needs `dotnet` on PATH; zero Python dependencies.
Steps, in the registered order:

1. **generator** — `frontend/roslyn/Own.TypedBuilder` generates `Domain/Order.Protocol.cs` from
   `Domain/Order.cs` twice, into two clean directories: both outputs must be the same bytes, and
   the committed file must be those bytes. Every token the generated surface constructs wraps
   the region entry's own argument or the token's own field: no copy, no second entity.
2. **build** — the backend and its acceptance runner build.
3. **sample** — the real extractor over the backend's project file: a region in each of the
   Submit, Approve and Ship handlers, the Ship helper as an OwnIR `proven_call`, and a clean
   verdict (on both public CLIs with `--rust`). The facts are pinned in `evidence/`.
4. **corpus** — every `corpus/<kind>/<Case>.cs.txt` is staged ALONE into a copy of the project
   and must meet its `expected.json` row: a C# compiler error (`compiler`), an extractor
   refusal (`extractor`), or a core verdict (`core`: codes, or a refusal text).
5. **acceptance** — the runner drives real HTTP against a real SQLite file with oracles that do
   not go through the typed API, twice: both transcripts must be the same bytes.

Run:  python scripts/typed_builder_gate.py                    (verify)
      python scripts/typed_builder_gate.py --write            (rewrite evidence/)
      python scripts/typed_builder_gate.py --rust <own-cli>   (also compare the two CLIs)
      python scripts/typed_builder_gate.py --clean-checkout [--runs N] [--rust <own-cli>]
          (the gate, N times (default 2), each in a fresh `git worktree` of HEAD with no
          build output; the evidence of every run must be the same bytes)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

from ownlang.ownir import OwnIRError, check_facts  # noqa: E402

SAMPLE_REL = "samples/OrderBackend"
SAMPLE = os.path.join(ROOT, *SAMPLE_REL.split("/"))
BACKEND = os.path.join(SAMPLE, "OrderBackend")
PROJECT_REL = f"{SAMPLE_REL}/OrderBackend/OrderBackend.csproj"
DECLARATION = os.path.join(BACKEND, "Domain", "Order.cs")
GENERATED = os.path.join(BACKEND, "Domain", "Order.Protocol.cs")
EVIDENCE = os.path.join(SAMPLE, "evidence")
GENERATOR = os.path.join(ROOT, "frontend", "roslyn", "Own.TypedBuilder")
EXTRACTOR = os.path.join(ROOT, "frontend", "roslyn", "OwnSharp.Extractor")

HANDLER_REGIONS = ("OrderBackend.OrderEndpoints.Submit$protocol",
                   "OrderBackend.OrderEndpoints.Approve$protocol",
                   "OrderBackend.OrderEndpoints.Ship$protocol")
HELPER = "OrderBackend.Shipping.TrackingNumber(int)"
ACCEPTANCE_CHECKS = 44
KINDS = ("positive", "negative", "limits")


def _run(cmd: list[str], cwd: str = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def _build(path: str, *extra: str, cwd: str = ROOT) -> subprocess.CompletedProcess[str]:
    return _run(["dotnet", "build", path, "-nologo", "-v", "q", *extra], cwd=cwd)


def _tool(project: str, dll: str, fails: list[str]) -> str | None:
    built = _build(project, "-c", "Release")
    if built.returncode != 0:
        fails.append(f"{os.path.basename(project)} does not build: {built.stdout.strip()[-600:]}")
        return None
    return os.path.join(project, "bin", "Release", "net8.0", dll)


def _verdict(facts: dict[str, object]) -> list[str] | str:
    try:
        return sorted({f.code for f in check_facts(facts)})
    except OwnIRError as e:
        return f"refused: {e}"


def _cli_parity(rust: str, facts_path: str, cwd: str, where: str, fails: list[str]) -> None:
    args = ["ownir", facts_path, "--format", "human", "--severity", "error"]
    py = subprocess.run([sys.executable, "-m", "ownlang", *args], cwd=cwd, capture_output=True,
                        check=False, env={**os.environ, "PYTHONPATH": ROOT})
    rs = subprocess.run([rust, *args], cwd=cwd, capture_output=True, check=False)
    if (py.returncode, py.stdout, py.stderr) != (rs.returncode, rs.stdout, rs.stderr):
        fails.append(f"{where}: the two public CLIs differ (python rc={py.returncode}, "
                     f"rust rc={rs.returncode})")


# ---- 1. generator ---------------------------------------------------------------------------

_NEW_TOKEN = re.compile(r"new (Draft|Submitted|Approved|Shipped)Order\((\w+)\)")


def generator(fails: list[str]) -> int:
    dll = _tool(GENERATOR, "own-typed-builder.dll", fails)
    if dll is None:
        return 0
    outputs = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "Order.Protocol.cs")
            done = _run(["dotnet", dll, DECLARATION, "-o", out])
            if done.returncode != 0:
                fails.append(f"generator: exit {done.returncode}: {done.stderr.strip()}")
                return 0
            with open(out, "rb") as f:
                outputs.append(f.read())
    if outputs[0] != outputs[1]:
        fails.append("generator/determinism: two clean generations differ")
    with open(GENERATED, "rb") as f:
        committed = f.read()
    if committed != outputs[0]:
        fails.append("generator/committed: Order.Protocol.cs is not what the generator writes from "
                     "Order.cs; regenerate it")
    text = outputs[0].decode("utf-8")
    if b"\r" in outputs[0] or outputs[0].startswith(b"\xef\xbb\xbf"):
        fails.append("generator/bytes: the output carries a CR or a BOM")
    # identity, structurally: a token wraps `order` (the region entry's argument) or `_order`
    # (the token's own field) and nothing else; no entity is created but the builder's one
    wrapped = _NEW_TOKEN.findall(text)
    if len(wrapped) != 6 or any(arg not in ("order", "_order") for _, arg in wrapped):
        fails.append(f"generator/identity: tokens are constructed over {wrapped}")
    if text.count("new()") != 2 or re.search(r"new Order\s*[({]", text):
        fails.append("generator/identity: the generated surface creates an Order outside Build()")
    return 2


# ---- 3. the real sample ---------------------------------------------------------------------

def sample(dll: str, rust: str | None, write: bool, fails: list[str]) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "facts.json")
        done = _run(["dotnet", dll, PROJECT_REL, "--flow-locals", "-o", out])
        if done.returncode != 0:
            fails.append(f"sample: the extractor exited {done.returncode}: "
                         f"{done.stderr.strip()[-400:]}")
            return {}
        with open(out, encoding="utf-8") as f:
            facts = json.load(f)
        if rust is not None:
            _cli_parity(rust, out, ROOT, "sample", fails)
    by_name = {fn["name"]: fn for fn in facts.get("functions", [])}
    regions = {}
    for name in HANDLER_REGIONS:
        body = by_name.get(name, {}).get("body", [])
        inner = [op for region in body if region.get("op") == "borrow_mut" for op in region["body"]]
        regions[name] = [op["op"] + (f" {op['callee']}" if "callee" in op else "") for op in inner]
        if not inner:
            fails.append(f"sample: no protocol region lowered for {name}")
    ship = regions.get("OrderBackend.OrderEndpoints.Ship$protocol", [])
    if f"proven_call {HELPER}" not in ship:
        fails.append(f"sample: the Ship region has no proven_call to {HELPER}: {ship}")
    keys = sorted(m["key"] for m in facts.get("heap_effects", {}).get("methods", []))
    if HELPER not in keys:
        fails.append(f"sample: heap_effects has no record of {HELPER}: {keys}")
    verdict = _verdict(facts)
    if verdict != []:
        fails.append(f"sample: verdict {verdict!r}, expected clean")
    _evidence("orderbackend.facts.json", json.dumps(facts, indent=2, ensure_ascii=False) + "\n",
              write, fails, as_json=True)
    return {"regions": regions, "heap_effects": keys, "verdict": verdict}


# ---- 4. corpus ------------------------------------------------------------------------------

def _stage(tmp: str) -> str:
    """A buildable copy of the sample's sources under `<tmp>/stage/`."""
    stage = os.path.join(tmp, "stage")
    shutil.copytree(BACKEND, os.path.join(stage, "OrderBackend"),
                    ignore=shutil.ignore_patterns("bin", "obj"))
    shutil.copyfile(os.path.join(SAMPLE, "nuget.config"), os.path.join(stage, "nuget.config"))
    return stage


_CS_ERROR = re.compile(r"^(?P<file>[^\n(]+)\(\d+,\d+\): error (?P<code>CS\d+): (?P<msg>.*?) \[",
                       re.M)


def corpus(dll: str, rust: str | None, fails: list[str]) -> list[dict[str, object]]:
    cases: list[tuple[str, str, dict[str, object]]] = []
    for kind in KINDS:
        folder = os.path.join(SAMPLE, "corpus", kind)
        with open(os.path.join(folder, "expected.json"), encoding="utf-8") as f:
            expected = json.load(f)
        on_disk = sorted(n[:-7] for n in os.listdir(folder) if n.endswith(".cs.txt"))
        if on_disk != sorted(expected):
            fails.append(f"corpus/{kind}: expected.json {sorted(expected)} != sources {on_disk}")
            return []
        cases += [(kind, case, expected[case]) for case in on_disk]

    observed: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as tmp:
        stage = _stage(tmp)
        project = "OrderBackend/OrderBackend.csproj"
        base = _build(project, cwd=stage)
        if base.returncode != 0:
            fails.append(f"corpus: the staged backend does not build: {base.stdout.strip()[-400:]}")
            return []
        for kind, case, want in cases:
            where = f"corpus/{kind}/{case}"
            staged = os.path.join(stage, "OrderBackend", f"{case}.cs")
            shutil.copyfile(os.path.join(SAMPLE, "corpus", kind, f"{case}.cs.txt"), staged)
            try:
                got = _one(stage, project, case, want, dll, rust, where, fails)
            finally:
                os.remove(staged)
            observed.append({"kind": kind, "case": case, "expected": want, "observed": got})
        # the staged project, back to its own sources, is still the clean sample
        rebuilt = _build(project, cwd=stage)
        if rebuilt.returncode != 0:
            fails.append("corpus: the staged backend does not rebuild without the staged cases")
    return observed


def _one(stage: str, project: str, case: str, want: dict[str, object], dll: str,
         rust: str | None, where: str, fails: list[str]) -> object:
    built = _build(project, cwd=stage)
    if want["stage"] == "compiler":
        errors = sorted({(os.path.basename(m["file"]), m["code"], m["msg"])
                         for m in _CS_ERROR.finditer(built.stdout)})
        got = [f"{f}: {code}: {msg}" for f, code, msg in errors]
        if built.returncode == 0:
            fails.append(f"{where}: the C# compiler accepts it")
        elif not errors or any(f != f"{case}.cs" or code != want["code"] for f, code, _ in errors):
            fails.append(f"{where}: expected only {want['code']} in {case}.cs, got {got}")
        elif not all(re.search(rf"'[^']*\b{re.escape(str(want['member']))}\b[^']*'", msg)
                     for _, _, msg in errors):
            fails.append(f"{where}: the {want['code']} errors do not name "
                         f"'{want['member']}': {got}")
        return got
    if built.returncode != 0:
        codes = sorted(set(re.findall(r"error (CS\d+)", built.stdout)))
        fails.append(f"{where}: the staged backend does not build: {codes}")
        return f"does not build: {codes}"
    out = os.path.join(stage, "facts.json")
    if os.path.exists(out):
        os.remove(out)
    done = _run(["dotnet", dll, project, "--flow-locals", "-o", "facts.json"], cwd=stage)
    if want["stage"] == "extractor":
        line = next((x for x in done.stderr.splitlines() if "refused" in x), done.stderr.strip())
        if done.returncode != 2:
            fails.append(f"{where}: the extractor exited {done.returncode}, expected a refusal (2)")
        elif os.path.exists(out):
            fails.append(f"{where}: a facts file was written despite the refusal")
        elif str(want["text"]) not in done.stderr or f"{case}.cs" not in done.stderr:
            fails.append(f"{where}: refusal text lacks {want['text']!r}: "
                         f"{done.stderr.strip()[-300:]}")
        return f"exit {done.returncode}: {line}"
    # core
    if done.returncode != 0:
        fails.append(f"{where}: the extractor exited {done.returncode}: "
                     f"{done.stderr.strip()[-300:]}")
        return f"extractor exit {done.returncode}"
    with open(out, encoding="utf-8") as f:
        facts = json.load(f)
    verdict = _verdict(facts)
    if "verdict" in want and verdict != want["verdict"]:
        fails.append(f"{where}: verdict {verdict!r}, expected {want['verdict']!r}")
    if "refusal" in want and not (isinstance(verdict, str) and str(want["refusal"]) in verdict):
        fails.append(f"{where}: expected a core refusal with {want['refusal']!r}, got {verdict!r}")
    if "proven_call" in want:
        calls = re.findall(r'"op": "proven_call",[^}]*"callee": "([^"]+)"', json.dumps(facts))
        if want["proven_call"] not in calls:
            fails.append(f"{where}: no proven_call to {want['proven_call']} in the facts: {calls}")
    if rust is not None:
        _cli_parity(rust, "facts.json", stage, where, fails)
    return verdict


# ---- 5. acceptance --------------------------------------------------------------------------

def acceptance(fails: list[str]) -> str:
    runner = os.path.join(SAMPLE, "Acceptance")
    built = _build(runner)
    if built.returncode != 0:
        fails.append(f"acceptance: does not build: {built.stdout.strip()[-400:]}")
        return ""
    dll = os.path.join(runner, "bin", "Debug", "net8.0", "Acceptance.dll")
    transcripts = []
    for n in (1, 2):
        ran = _run(["dotnet", dll], cwd=SAMPLE)
        oks = len(re.findall(r"^ok\[", ran.stdout, flags=re.M))
        if (ran.returncode != 0 or "all checks hold" not in ran.stdout or oks != ACCEPTANCE_CHECKS
                or "FAIL[" in ran.stdout or ran.stderr.strip()):
            fails.append(f"acceptance/run{n}: exit {ran.returncode}, "
                         f"{oks}/{ACCEPTANCE_CHECKS} checks: "
                         f"{(ran.stdout + ran.stderr).strip()[-600:]}")
        transcripts.append(ran.stdout)
    if transcripts[0] != transcripts[1]:
        fails.append("acceptance/determinism: the two transcripts differ")
    return transcripts[0]


# ---- evidence -------------------------------------------------------------------------------

def _evidence(name: str, text: str, write: bool, fails: list[str], as_json: bool = False) -> None:
    path = os.path.join(EVIDENCE, name)
    out_dir = os.environ.get("TB_GATE_EVIDENCE_OUT")
    if out_dir:
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    if write:
        os.makedirs(EVIDENCE, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return
    if not os.path.exists(path):
        fails.append(f"evidence/{name}: missing; run with --write")
        return
    with open(path, encoding="utf-8") as f:
        committed = f.read()
    same = json.loads(committed) == json.loads(text) if as_json else committed == text
    if not same:
        fails.append(f"evidence/{name}: the gate no longer produces the committed evidence")


def gate(rust: str | None, write: bool) -> int:
    fails: list[str] = []
    n_gen = generator(fails)
    built = _build(os.path.join(BACKEND, "OrderBackend.csproj"))
    if built.returncode != 0:
        fails.append(f"build: the backend does not build: {built.stdout.strip()[-400:]}")
    dll = _tool(EXTRACTOR, "ownsharp-extract.dll", fails)
    summary: dict[str, object] = {}
    observed: list[dict[str, object]] = []
    transcript = ""
    if dll is not None and built.returncode == 0:
        summary = sample(dll, rust, write, fails)
        observed = corpus(dll, rust, fails)
        transcript = acceptance(fails)
    _evidence("corpus.json", json.dumps({"sample": summary, "corpus": observed}, indent=2,
                                        ensure_ascii=False) + "\n", write, fails)
    _evidence("acceptance.txt", transcript, write, fails)
    counts: dict[str, int] = {}
    for row in observed:
        counts[str(row["kind"])] = counts.get(str(row["kind"]), 0) + 1
    oks = len(re.findall(r"^ok\[", transcript, flags=re.M))
    for f in fails:
        print(f"FAIL: {f}")
    print(f"typed builder gate: generator {n_gen} clean generations, "
          f"{counts.get('positive', 0)} positive / {counts.get('negative', 0)} negative / "
          f"{counts.get('limits', 0)} limit cases, {oks} acceptance checks x2"
          + (", both CLIs compared" if rust else "")
          + f"; transcript sha256 {hashlib.sha256(transcript.encode()).hexdigest()[:16]}"
          + f"; {len(fails)} failure(s)" + (" [evidence written]" if write else ""))
    return 1 if fails else 0


def clean_checkout(runs: int, rust: str | None) -> int:
    """The gate in `runs` fresh worktrees of HEAD; their evidence must be the same bytes."""
    head = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    digests: list[dict[str, str]] = []
    rc = 0
    for n in range(1, runs + 1):
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "tree")
            evidence = os.path.join(tmp, "evidence")
            os.makedirs(evidence)
            added = _run(["git", "worktree", "add", "--detach", tree, head])
            if added.returncode != 0:
                print(f"FAIL: clean-checkout/run{n}: git worktree add: {added.stderr.strip()}")
                return 1
            try:
                leftovers = [d for _, dirs, _ in os.walk(tree) for d in dirs
                             if d in ("bin", "obj")]
                if leftovers:
                    print(f"FAIL: clean-checkout/run{n}: the worktree has build output: "
                          f"{leftovers}")
                    rc = 1
                cmd = [sys.executable, os.path.join(tree, "scripts", "typed_builder_gate.py")]
                if rust:
                    cmd += ["--rust", rust]
                done = subprocess.run(cmd, cwd=tree, check=False, capture_output=True, text=True,
                                      env={**os.environ, "TB_GATE_EVIDENCE_OUT": evidence})
                last = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else "no output"
                print(f"clean-checkout/run{n} @ {head[:12]}: {last}")
                if done.returncode != 0:
                    print(done.stdout + done.stderr)
                    rc = 1
                run: dict[str, str] = {}
                for name in sorted(os.listdir(evidence)):
                    with open(os.path.join(evidence, name), "rb") as f:
                        run[name] = hashlib.sha256(f.read()).hexdigest()
                digests.append(run)
            finally:
                _run(["git", "worktree", "remove", "--force", tree])
    for name in sorted(digests[0]) if digests else []:
        line = " ".join(d.get(name, "<missing>")[:16] for d in digests)
        same = len({d.get(name) for d in digests}) == 1
        print(f"clean-checkout/digest {name}: {line} {'identical' if same else 'DIFFER'}")
        if not same:
            rc = 1
    print(f"typed builder clean-checkout: {runs} run(s) from fresh worktrees of {head[:12]}; "
          + ("PASS" if rc == 0 else "FAIL"))
    return rc


def main() -> int:
    argv = sys.argv[1:]
    rust = argv[argv.index("--rust") + 1] if "--rust" in argv else None
    if rust is not None:
        rust = os.path.abspath(rust)
    if "--clean-checkout" in argv:
        runs = int(argv[argv.index("--runs") + 1]) if "--runs" in argv else 2
        return clean_checkout(runs, rust)
    return gate(rust, "--write" in argv)


if __name__ == "__main__":
    raise SystemExit(main())
