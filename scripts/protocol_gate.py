#!/usr/bin/env python3
"""State protocols (P-010, pillar 9): real C# -> OwnIR v2 -> core, tied back to source.

The Layer 2/3 ledgers freeze the facts the Roslyn lowering emits for the state-protocol
surface, and both engines replay them with zero `dotnet`. This script is the other half: it
runs the REAL extractor over the C# those facts came from, so a frozen fact can never drift
away from the program it claims to describe. Six questions (needs `dotnet` on PATH; zero
Python dependencies). Every path below is under `frontend/roslyn/protocol-samples/`:

1. **cases** — every `cases/<Case>.cs` is run through the extractor (with the sample API
   beside it). The facts must equal the committed fixture
   `tests/fixtures/lowered/typestate_cs_<case>.facts.json` (JSON-equal: the extractor writes
   platform newlines), and the reference engine's verdict on them must equal
   `cases/expected.json`.

2. **refused** — every `refused/<Case>.cs.txt` compiles, and the extractor must REFUSE it
   (exit 2) with the text in `expected.json`: a shape the core cannot check, code with no
   contract inside a region, a protocol that is not admitted. An entry
   `{"stage": "core", "text": ...}` is a call the lowering hands to the core as an OwnIR v2
   `proven_call` (H1): the extractor writes the facts, and the core must refuse them with
   that text because the effect summaries cannot prove the call harmless.

3. **does-not-compile** — every `does-not-compile/<Case>.cs.txt` must be rejected by the C#
   compiler itself, built against the API as a SEPARATE assembly (so `internal` means what
   it means to a real consumer).

4. **same-assembly** — every `same-assembly/<Case>.cs.txt` compiles when it shares an
   assembly with the API (where `internal` protects nothing), and the extractor must refuse
   it all the same: a token made by hand, the protocol's state written past every token. A
   control with a null expectation must be ACCEPTED: a mention is not an operation.

5. **unrelated** — every `unrelated/<Case>.cs.txt` is a program from a codebase that declares
   NO state protocol and happens to own attributes named `ProtocolToken` / `ProtocolRegion`
   (`unrelated/WireAttributes.cs.txt`). The names are reserved only in the profile's shapes —
   a ref struct, a method that takes a delegate — so a case with a null expectation must be
   ACCEPTED, with not one region lowered, alone and beside the sample protocol. The two
   cases that do have the reserved shape are pinned as refusals: the residual is stated, not
   discovered.

6. **efcore** — `efcore/` is an ordinary ASP.NET Core + EF Core backend. It must run (its
   acceptance runner drives real HTTP against real SQLite); the extractor must lower its
   handlers to the committed `tests/fixtures/lowered/typestate_ef_orderbackend.facts.json`
   with a clean verdict, from the project file alone; a copy whose handlers rely on IMPLICIT
   usings must be refused rather than silently lose its regions; and the handlers under
   `efcore/refused/`, `efcore/accepted/` and `efcore/known-gaps/` — all of which the C#
   compiler accepts inside that same project — must be refused, accepted, and (still)
   accepted.

The refused / does-not-compile sources carry a `.cs.txt` suffix on purpose: a directory
scan must not pick up programs whose whole point is to be refused. The samples live under
`frontend/roslyn/` rather than `examples/` for a related reason: `examples/` is swept as one
document by the #260 shadow sweep, and a backend whose references that walk does not have
is, correctly, a refusal of the whole scan.

Run:  python scripts/protocol_gate.py            (verify)
      python scripts/protocol_gate.py --write    (regenerate the fixtures from C#)
      python scripts/protocol_gate.py --rust <own-cli>   (also compare the two public CLIs)
"""

from __future__ import annotations

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

PROTO = os.path.join(ROOT, "frontend", "roslyn", "protocol-samples")
EXTRACTOR = os.path.join(ROOT, "frontend", "roslyn", "OwnSharp.Extractor")
FIXDIR = os.path.join(ROOT, "tests", "fixtures", "lowered")
SAMPLES_REL = "frontend/roslyn/protocol-samples"
API_REL = f"{SAMPLES_REL}/Api"


def _run(cmd: list[str], cwd: str = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def _extractor_dll() -> str:
    built = _run(["dotnet", "build", EXTRACTOR, "-c", "Release", "-nologo", "-v", "q"])
    if built.returncode != 0:
        print(built.stdout[-2000:])
        raise SystemExit("FAIL: the extractor does not build")
    return os.path.join(EXTRACTOR, "bin", "Release", "net8.0", "ownsharp-extract.dll")


def _fixture(case: str) -> str:
    return os.path.join(FIXDIR, f"typestate_cs_{case.lower()}.facts.json")


def _verdict(facts: dict[str, object]) -> list[str] | str:
    try:
        return sorted({f.code for f in check_facts(facts)})
    except OwnIRError as e:
        return f"refused: {e}"


def cases(dll: str, write: bool, fails: list[str]) -> int:
    with open(os.path.join(PROTO, "cases", "expected.json"), encoding="utf-8") as f:
        expected = json.load(f)
    on_disk = sorted(n[:-3] for n in os.listdir(os.path.join(PROTO, "cases"))
                     if n.endswith(".cs"))
    if on_disk != sorted(expected):
        fails.append(f"cases: expected.json {sorted(expected)} != sources {on_disk}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        for case in on_disk:
            out = os.path.join(tmp, f"{case}.json")
            # relative, forward-slash inputs: the `file` fields are part of the fixture
            done = _run(["dotnet", dll, API_REL, f"{SAMPLES_REL}/cases/{case}.cs",
                         "--flow-locals", "-o", out])
            if done.returncode != 0:
                fails.append(f"cases/{case}: the extractor exited {done.returncode}: "
                             f"{done.stderr.strip()[-300:]}")
                continue
            with open(out, encoding="utf-8") as f:
                facts = json.load(f)
            fixture = _fixture(case)
            if write:
                with open(fixture, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(facts, f, indent=2, ensure_ascii=False)
                    f.write("\n")
            elif not os.path.exists(fixture):
                fails.append(f"cases/{case}: fixture missing ({os.path.basename(fixture)}); "
                             f"run with --write")
            else:
                with open(fixture, encoding="utf-8") as f:
                    if json.load(f) != facts:
                        fails.append(f"cases/{case}: the extractor no longer emits the "
                                     f"committed facts ({os.path.basename(fixture)})")
            got = _verdict(facts)
            if got != expected[case]:
                fails.append(f"cases/{case}: verdict {got!r}, expected {expected[case]!r}")
    return len(on_disk)


def _staged(sub: str, case: str, tmp: str) -> str:
    """Copy `<case>.cs.txt` to `<tmp>/<case>.cs` and return it relative to ROOT-less tmp."""
    dst = os.path.join(tmp, f"{case}.cs")
    shutil.copyfile(os.path.join(PROTO, sub, f"{case}.cs.txt"), dst)
    return dst


def refused(dll: str, fails: list[str]) -> int:
    with open(os.path.join(PROTO, "refused", "expected.json"), encoding="utf-8") as f:
        expected = json.load(f)
    on_disk = sorted(n[:-7] for n in os.listdir(os.path.join(PROTO, "refused"))
                     if n.endswith(".cs.txt"))
    if on_disk != sorted(expected):
        fails.append(f"refused: expected.json {sorted(expected)} != sources {on_disk}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        for case in on_disk:
            src = _staged("refused", case, tmp)
            out = os.path.join(tmp, f"{case}.json")
            done = _run(["dotnet", dll, API_REL, src, "--flow-locals", "-o", out])
            want = expected[case]
            if isinstance(want, dict):
                # OwnIR v2 (H1): a call the lowering hands to the core as a `proven_call`
                # is refused by the CORE when the summaries cannot prove it harmless —
                # still a refusal of the whole document, one stage later. The facts are
                # written, and the reference must refuse them with the pinned text.
                if want.get("stage") != "core":
                    fails.append(f"refused/{case}: unknown expectation {want!r}")
                elif done.returncode != 0 or not os.path.exists(out):
                    fails.append(f"refused/{case}: the extractor exited {done.returncode}; "
                                 f"a core-stage refusal needs its facts written")
                else:
                    with open(out, encoding="utf-8") as f:
                        got = _verdict(json.load(f))
                    if not (isinstance(got, str) and want["text"] in got):
                        fails.append(f"refused/{case}: the core did not refuse with "
                                     f"{want['text']!r}: {got!r}")
                continue
            if done.returncode != 2:
                fails.append(f"refused/{case}: the extractor exited {done.returncode}, "
                             f"expected a refusal (2)")
            elif os.path.exists(out):
                fails.append(f"refused/{case}: a facts file was written despite the refusal")
            elif want not in done.stderr:
                fails.append(f"refused/{case}: refusal text lacks {want!r}: "
                             f"{done.stderr.strip()[-300:]}")
    return len(on_disk)


_PROJECT = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <LangVersion>12</LangVersion>
    <Nullable>enable</Nullable>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <NoWarn>CS1998;CS0169;CS0649;CS0168;CS0219;CS0414</NoWarn>
  </PropertyGroup>
  <ItemGroup>{items}</ItemGroup>
</Project>
"""


def does_not_compile(fails: list[str]) -> int:
    with open(os.path.join(PROTO, "does-not-compile", "expected.json"), encoding="utf-8") as f:
        expected = json.load(f)
    on_disk = sorted(n[:-7] for n in os.listdir(os.path.join(PROTO, "does-not-compile"))
                     if n.endswith(".cs.txt"))
    if on_disk != sorted(expected):
        fails.append(f"does-not-compile: expected.json {sorted(expected)} != sources {on_disk}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        api = os.path.join(tmp, "Api")
        os.makedirs(api)
        shutil.copyfile(os.path.join(PROTO, "Api", "ProtocolApi.cs"),
                        os.path.join(api, "ProtocolApi.cs"))
        with open(os.path.join(api, "Api.csproj"), "w", encoding="utf-8") as f:
            f.write(_PROJECT.format(items='<Compile Include="ProtocolApi.cs" />'))
        # the positive control: the compilable cases DO build against the same API
        ok = os.path.join(tmp, "Ok")
        os.makedirs(ok)
        for n in os.listdir(os.path.join(PROTO, "cases")):
            if n.endswith(".cs"):
                shutil.copyfile(os.path.join(PROTO, "cases", n), os.path.join(ok, n))
        for n in os.listdir(os.path.join(PROTO, "refused")):
            if n.endswith(".cs.txt"):
                shutil.copyfile(os.path.join(PROTO, "refused", n), os.path.join(ok, n[:-4]))
        with open(os.path.join(ok, "Ok.csproj"), "w", encoding="utf-8") as f:
            f.write(_PROJECT.format(items='<Compile Include="*.cs" />'
                                    '<ProjectReference Include="../Api/Api.csproj" />'))
        built = _run(["dotnet", "build", ok, "-nologo", "-v", "q"], cwd=tmp)
        if built.returncode != 0:
            codes = sorted(set(re.findall(r"error (CS\d+)", built.stdout)))
            fails.append(f"does-not-compile: the positive control (cases + refused) does not "
                         f"build: {codes}")
        for case in on_disk:
            proj = os.path.join(tmp, case)
            os.makedirs(proj)
            shutil.copyfile(os.path.join(PROTO, "does-not-compile", f"{case}.cs.txt"),
                            os.path.join(proj, f"{case}.cs"))
            with open(os.path.join(proj, f"{case}.csproj"), "w", encoding="utf-8") as f:
                f.write(_PROJECT.format(items='<Compile Include="*.cs" />'
                                        '<ProjectReference Include="../Api/Api.csproj" />'))
            built = _run(["dotnet", "build", proj, "-nologo", "-v", "q"], cwd=tmp)
            codes = sorted(set(re.findall(r"error (CS\d+)", built.stdout)))
            if built.returncode == 0:
                fails.append(f"does-not-compile/{case}: it COMPILES")
            elif not set(codes) & set(expected[case]):
                fails.append(f"does-not-compile/{case}: errors {codes}, expected one of "
                             f"{expected[case]}")
    return len(on_disk)


def same_assembly(dll: str, fails: list[str]) -> int:
    """The protocol and its users in ONE assembly. There `internal` holds nothing, so every
    program under `same-assembly/` COMPILES; the scan has to hold the boundary instead
    (exit 2, the text in `expected.json`), and must still accept the control whose expected
    text is null — the same assembly, the entity's public surface only."""
    with open(os.path.join(PROTO, "same-assembly", "expected.json"), encoding="utf-8") as f:
        expected = json.load(f)
    on_disk = sorted(n[:-7] for n in os.listdir(os.path.join(PROTO, "same-assembly"))
                     if n.endswith(".cs.txt"))
    if on_disk != sorted(expected):
        fails.append(f"same-assembly: expected.json {sorted(expected)} != sources {on_disk}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        one = os.path.join(tmp, "One")
        os.makedirs(one)
        shutil.copyfile(os.path.join(PROTO, "Api", "ProtocolApi.cs"),
                        os.path.join(one, "ProtocolApi.cs"))
        for case in on_disk:
            shutil.copyfile(os.path.join(PROTO, "same-assembly", f"{case}.cs.txt"),
                            os.path.join(one, f"{case}.cs"))
        with open(os.path.join(one, "One.csproj"), "w", encoding="utf-8") as f:
            f.write(_PROJECT.format(items='<Compile Include="*.cs" />'))
        built = _run(["dotnet", "build", one, "-nologo", "-v", "q"], cwd=tmp)
        if built.returncode != 0:
            codes = sorted(set(re.findall(r"error (CS\d+)", built.stdout)))
            fails.append(f"same-assembly: the programs do not build in one assembly: {codes}")
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        for case in on_disk:
            staged = _staged("same-assembly", case, src)
            out = os.path.join(tmp, f"{case}.json")
            done = _run(["dotnet", dll, API_REL, staged, "--flow-locals", "-o", out])
            if expected[case] is None:
                if done.returncode != 0:
                    fails.append(f"same-assembly/{case}: the control was not accepted (exit "
                                 f"{done.returncode}): {done.stderr.strip()[-300:]}")
            elif done.returncode != 2:
                fails.append(f"same-assembly/{case}: the extractor exited {done.returncode}, "
                             f"expected a refusal (2)")
            elif os.path.exists(out):
                fails.append(f"same-assembly/{case}: a facts file was written despite the "
                             f"refusal")
            elif expected[case] not in done.stderr:
                fails.append(f"same-assembly/{case}: refusal text lacks {expected[case]!r}: "
                             f"{done.stderr.strip()[-300:]}")
    return len(on_disk)


def _lowers_a_region(facts: dict[str, object]) -> bool:
    def walk(nodes: object) -> bool:
        return isinstance(nodes, list) and any(
            isinstance(n, dict) and (n.get("op") == "borrow_mut" or walk(n.get("body"))
                                     or walk(n.get("then")) or walk(n.get("else")))
            for n in nodes)
    functions = facts.get("functions")
    return isinstance(functions, list) and any(
        isinstance(fn, dict) and walk(fn.get("body")) for fn in functions)


def unrelated(dll: str, fails: list[str]) -> int:
    """A codebase with no state protocol, and attributes that share the profile's names.

    The programs compile on their own (with `WireAttributes.cs.txt`). A null expectation
    means the scan must ACCEPT the program — exit 0, a clean verdict, no region lowered —
    both alone and with the sample protocol in the same scan; a text means the program has
    the reserved shape and the refusal carrying that text is the pinned residual."""
    here = os.path.join(PROTO, "unrelated")
    with open(os.path.join(here, "expected.json"), encoding="utf-8") as f:
        expected = json.load(f)
    shared = "WireAttributes"
    on_disk = sorted(n[:-7] for n in os.listdir(here) if n.endswith(".cs.txt") and n[:-7] != shared)
    if on_disk != sorted(expected):
        fails.append(f"unrelated: expected.json {sorted(expected)} != sources {on_disk}")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        one = os.path.join(tmp, "Wire")
        os.makedirs(one)
        for case in [shared, *on_disk]:
            shutil.copyfile(os.path.join(here, f"{case}.cs.txt"), os.path.join(one, f"{case}.cs"))
        with open(os.path.join(one, "Wire.csproj"), "w", encoding="utf-8") as f:
            f.write(_PROJECT.format(items='<Compile Include="*.cs" />'))
        built = _run(["dotnet", "build", one, "-nologo", "-v", "q"], cwd=tmp)
        if built.returncode != 0:
            codes = sorted(set(re.findall(r"error (CS\d+)", built.stdout)))
            fails.append(f"unrelated: the programs do not build: {codes}")
        attributes = os.path.join(one, f"{shared}.cs")
        for case in on_disk:
            src = os.path.join(one, f"{case}.cs")
            want = expected[case]
            scans = [("alone", [attributes, src])]
            if want is None:
                scans.append(("beside the sample protocol", [API_REL, attributes, src]))
            for label, inputs in scans:
                out = os.path.join(tmp, f"{case}.json")
                if os.path.exists(out):
                    os.remove(out)
                done = _run(["dotnet", dll, *inputs, "--flow-locals", "-o", out])
                where = f"unrelated/{case} ({label})"
                if want is None:
                    if done.returncode != 0:
                        fails.append(f"{where}: a codebase with no state protocol was not "
                                     f"accepted (exit {done.returncode}): "
                                     f"{done.stderr.strip()[-300:]}")
                        continue
                    with open(out, encoding="utf-8") as f:
                        facts = json.load(f)
                    got = _verdict(facts)
                    if got != []:
                        fails.append(f"{where}: verdict {got!r}, expected clean")
                    if _lowers_a_region(facts):
                        fails.append(f"{where}: a region was lowered from a name alone")
                elif done.returncode != 2:
                    fails.append(f"{where}: the extractor exited {done.returncode}; the "
                                 f"reserved shape is pinned as a refusal (2)")
                elif want not in done.stderr:
                    fails.append(f"{where}: refusal text lacks {want!r}: "
                                 f"{done.stderr.strip()[-300:]}")
    return len(on_disk)


EF = os.path.join(PROTO, "efcore")
EF_REL = f"{SAMPLES_REL}/efcore/OrderBackend"
EF_PROJECT = f"{EF_REL}/OrderBackend.csproj"
EF_FIXTURE = os.path.join(FIXDIR, "typestate_ef_orderbackend.facts.json")
EF_REGIONS = ("OrderBackend.OrderHandlers.Ship$protocol",
              "OrderBackend.OrderHandlers.SubmitAndApprove$protocol")
EF_CHECKS = 13
# Textual, and labelled as such: the handler file carries no attribute, and the backend's own
# sources reach for neither reflection nor a custom query provider.
_EF_FORBIDDEN = ("System.Reflection", ".GetType()", "Activator.", "dynamic ", "IQueryProvider",
                 "ExpressionVisitor", "Expression<")
# The usings a Web SDK project gets implicitly. The scan does not read `obj/`, so a handler
# that leans on them does not bind; the staged copy below removes exactly these lines.
_EF_IMPLICIT = re.compile(r"^using (System|System\.Threading|System\.Threading\.Tasks|"
                          r"System\.Linq|Microsoft\.AspNetCore\.Http|"
                          r"Microsoft\.Extensions\.Logging);\n", flags=re.M)
# What a staged handler's directory promises: the extractor's answer to it.
_EF_STAGED = {"refused": "refuse", "accepted": "accept", "known-gaps": "accept"}


def _ef_sources() -> list[str]:
    out = []
    for base, dirs, names in os.walk(os.path.join(EF, "OrderBackend")):
        dirs[:] = [d for d in dirs if d not in ("bin", "obj")]
        out += [os.path.join(base, n) for n in names if n.endswith(".cs")]
    return sorted(out)


def _has_region(flow: list[dict[str, object]]) -> bool:
    return any(op.get("op") == "borrow_mut" for op in flow)


def _stage_backend(tmp: str, name: str) -> str:
    """A buildable copy of the backend project (sources only) under `<tmp>/<name>/`."""
    stage = os.path.join(tmp, name)
    shutil.copytree(os.path.join(EF, "OrderBackend"), os.path.join(stage, "OrderBackend"),
                    ignore=shutil.ignore_patterns("bin", "obj"))
    shutil.copyfile(os.path.join(EF, "nuget.config"), os.path.join(stage, "nuget.config"))
    return stage


def efcore(dll: str, write: bool, fails: list[str]) -> int:
    """The same lowering over a REAL ASP.NET Core + EF Core backend.

    * the backend runs: a real HTTP listener, a real SQLite file, the transitions are seen by
      the ChangeTracker on the instance EF tracks and are saved (`Acceptance`, its own exit code);
    * the handler file is plain: no attribute; the sources use no reflection, no custom LINQ;
    * the scan of the project file alone emits the committed facts, both regions are present
      in them, and the verdict is clean — with the opaque calls (logger, EF, `Results.*`,
      `await using`, `try`/`catch`, `return`) sitting AROUND the regions;
    * the same handlers leaning on implicit usings still compile, and are REFUSED (exit 2)
      instead of losing their regions;
    * staged handlers the compiler accepts are refused / accepted as their directory says."""
    n = 0
    built = _run(["dotnet", "build", os.path.join(EF, "Acceptance"), "-nologo", "-v", "q"])
    if built.returncode != 0:
        fails.append(f"efcore: the backend does not build: {built.stdout.strip()[-400:]}")
        return n
    ran = _run(["dotnet", os.path.join(EF, "Acceptance", "bin", "Debug", "net8.0",
                                       "Acceptance.dll")])
    oks = len(re.findall(r"^ok\[", ran.stdout, flags=re.M))
    if (ran.returncode != 0 or "all checks hold" not in ran.stdout or oks != EF_CHECKS
            or "FAIL[" in ran.stdout):
        fails.append(f"efcore/acceptance: exit {ran.returncode}, {oks}/{EF_CHECKS} checks: "
                     f"{ran.stdout.strip()[-400:]}")
    n += oks

    with open(os.path.join(EF, "OrderBackend", "OrderHandlers.cs"), encoding="utf-8") as f:
        handlers = f.read()
    if re.search(r"^\s*\[", handlers, flags=re.M):
        fails.append("efcore/plain: OrderHandlers.cs carries an attribute")
    for path in _ef_sources():
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for word in _EF_FORBIDDEN:
            if word in text:
                fails.append(f"efcore/plain: {os.path.basename(path)} uses {word!r}")
    n += 1

    with tempfile.TemporaryDirectory() as tmp:
        # (a) the scan of the project file alone: the committed facts, both regions, clean
        out = os.path.join(tmp, "bound.json")
        done = _run(["dotnet", dll, EF_PROJECT, "--flow-locals", "-o", out])
        if done.returncode != 0:
            fails.append(f"efcore/bound: the extractor exited {done.returncode}: "
                         f"{done.stderr.strip()[-300:]}")
        else:
            with open(out, encoding="utf-8") as f:
                facts = json.load(f)
            by_name = {fn["name"]: fn for fn in facts.get("functions", [])}
            for region in EF_REGIONS:
                if region not in by_name or not _has_region(by_name[region]["body"]):
                    fails.append(f"efcore/bound: no protocol region lowered for {region}")
            if write:
                with open(EF_FIXTURE, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(facts, f, indent=2, ensure_ascii=False)
                    f.write("\n")
            elif not os.path.exists(EF_FIXTURE):
                fails.append("efcore/bound: fixture missing; run with --write")
            else:
                with open(EF_FIXTURE, encoding="utf-8") as f:
                    if json.load(f) != facts:
                        fails.append("efcore/bound: the extractor no longer emits the committed "
                                     f"facts ({os.path.basename(EF_FIXTURE)})")
            got = _verdict(facts)
            if got != []:
                fails.append(f"efcore/bound: verdict {got!r}, expected clean")
        n += 1

        # (b) the same project with its handlers leaning on IMPLICIT usings. It compiles —
        #     the SDK generates them into obj/ — and the scan, which does not read obj/, must
        #     say that it cannot bind the region rather than drop it.
        stage = _stage_backend(tmp, "implicit")
        handler = os.path.join(stage, "OrderBackend", "OrderHandlers.cs")
        with open(handler, encoding="utf-8") as f:
            stripped, removed = _EF_IMPLICIT.subn("", f.read())
        with open(handler, "w", encoding="utf-8", newline="\n") as f:
            f.write(stripped)
        project = os.path.join(stage, "OrderBackend", "OrderBackend.csproj")
        built = _run(["dotnet", "build", project, "-nologo", "-v", "q"], cwd=stage)
        out = os.path.join(tmp, "implicit.json")
        done = _run(["dotnet", dll, project, "--flow-locals", "-o", out])
        if removed == 0:
            fails.append("efcore/implicit: the handler file has no explicit usings to remove")
        elif built.returncode != 0:
            codes = sorted(set(re.findall(r"error (CS\d+)", built.stdout)))
            fails.append(f"efcore/implicit: the staged backend does not build: {codes}")
        elif done.returncode != 2 or os.path.exists(out) or "does not resolve" not in done.stderr:
            fails.append(f"efcore/implicit: exit {done.returncode}, expected a refusal naming "
                         f"the unresolved type: {done.stderr.strip()[-300:]}")
        n += 1

        # (c) handlers staged INTO a copy of the project, which must still compile:
        #     `refused/`    - the scan must refuse each (exit 2, the expected text);
        #     `accepted/`   - the scan must accept each: a mention is not an operation;
        #     `known-gaps/` - the scan ACCEPTS each although the row changes state past every
        #                     token: outside what the profile claims, pinned so that it is a
        #                     stated limit and never a forgotten one.
        staged: list[tuple[str, str, str]] = []
        for kind in _EF_STAGED:
            with open(os.path.join(EF, kind, "expected.json"), encoding="utf-8") as f:
                expected = json.load(f)
            on_disk = sorted(x[:-7] for x in os.listdir(os.path.join(EF, kind))
                             if x.endswith(".cs.txt"))
            if on_disk != sorted(expected):
                fails.append(f"efcore/{kind}: expected.json {sorted(expected)} != sources "
                             f"{on_disk}")
                return n
            staged += [(kind, case, expected[case]) for case in on_disk]
        stage = _stage_backend(tmp, "staged")
        for kind, case, _ in staged:
            shutil.copyfile(os.path.join(EF, kind, f"{case}.cs.txt"),
                            os.path.join(stage, "OrderBackend", f"{case}.cs"))
        project = os.path.join(stage, "OrderBackend", "OrderBackend.csproj")
        built = _run(["dotnet", "build", project, "-nologo", "-v", "q"], cwd=stage)
        if built.returncode != 0:
            codes = sorted(set(re.findall(r"error (CS\d+)", built.stdout)))
            fails.append(f"efcore/staged: the staged backend does not build: {codes}")
            return n
        for kind, case, want in staged:
            # one staged handler per scan: the project's own sources plus this file
            keep = os.path.join(stage, "OrderBackend", f"{case}.cs")
            hidden = [os.path.join(stage, "OrderBackend", f"{other}.cs")
                      for _, other, _ in staged if other != case]
            for path in hidden:
                os.replace(path, path + ".off")
            out = os.path.join(tmp, f"{case}.json")
            done = _run(["dotnet", dll, project, "--flow-locals", "-o", out])
            for path in hidden:
                os.replace(path + ".off", path)
            where = f"efcore/{kind}/{case}"
            if _EF_STAGED[kind] == "accept":
                if done.returncode != 0:
                    fails.append(f"{where}: the scan does not accept it (exit "
                                 f"{done.returncode}): {done.stderr.strip()[-300:]}")
                else:
                    with open(out, encoding="utf-8") as f:
                        got = _verdict(json.load(f))
                    if got != []:
                        fails.append(f"{where}: verdict {got!r}, expected clean")
            elif done.returncode != 2:
                fails.append(f"{where}: the extractor exited {done.returncode}, expected a "
                             f"refusal (2)")
            elif os.path.exists(out):
                fails.append(f"{where}: a facts file was written despite the refusal")
            elif want not in done.stderr or os.path.basename(keep) not in done.stderr:
                fails.append(f"{where}: refusal text lacks {want!r}: "
                             f"{done.stderr.strip()[-300:]}")
            n += 1
    return n


def rust_cli(binary: str, fails: list[str]) -> int:
    """The two PUBLIC engines over the frozen C#-derived facts: exit code, stdout and
    stderr must be byte-identical."""
    n = 0
    for name in sorted(os.listdir(FIXDIR)):
        if not (name.startswith(("typestate_cs_", "typestate_ef_"))
                and name.endswith(".facts.json")):
            continue
        rel = f"tests/fixtures/lowered/{name}"
        args = ["ownir", rel, "--format", "human", "--severity", "error"]
        py = subprocess.run([sys.executable, "-m", "ownlang", *args], cwd=ROOT,
                            capture_output=True, check=False)
        rs = subprocess.run([binary, *args], cwd=ROOT, capture_output=True, check=False)
        if (py.returncode, py.stdout, py.stderr) != (rs.returncode, rs.stdout, rs.stderr):
            fails.append(f"rust/{name}: the two engines differ (python rc={py.returncode}, "
                         f"rust rc={rs.returncode})")
        n += 1
    return n


def main() -> int:
    write = "--write" in sys.argv[1:]
    rust = None
    if "--rust" in sys.argv[1:]:
        rust = sys.argv[sys.argv.index("--rust") + 1]
    fails: list[str] = []
    if rust is not None and "--rust-only" in sys.argv[1:]:
        n = rust_cli(rust, fails)
        for f in fails:
            print(f"FAIL: {f}")
        print(f"protocol gate (rust CLI parity): {n} C#-derived documents, {len(fails)} failure(s)")
        return 1 if fails else 0
    dll = _extractor_dll()
    n_cases = cases(dll, write, fails)
    n_refused = refused(dll, fails)
    n_nocompile = does_not_compile(fails)
    n_same = same_assembly(dll, fails)
    n_unrelated = unrelated(dll, fails)
    n_ef = efcore(dll, write, fails)
    n_rust = rust_cli(rust, fails) if rust is not None else 0
    for f in fails:
        print(f"FAIL: {f}")
    print(f"protocol gate: {n_cases} cases lowered from C# and judged, {n_refused} refused by "
          f"the lowering, {n_nocompile} rejected by the C# compiler, {n_same} same-assembly "
          f"programs held to the boundary, {n_unrelated} programs with the reserved names and "
          f"no protocol, {n_ef} checks on the real "
          f"ASP.NET Core + EF Core backend"
          + (f", {n_rust} documents byte-identical on both CLIs" if rust else "")
          + f"; {len(fails)} failure(s)" + (" [fixtures written]" if write else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
