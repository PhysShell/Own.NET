#!/usr/bin/env python3
"""OX-01: the Owen extension substrate, with Typed Builder as extension #1, end to end.

What it must show is registered in `docs/notes/owen-extension-alpha-preregistration.md`. In
one sentence: a brand-new project with ONE `PackageReference` to `Owen.TypedBuilder` gets the
generated typed API, ordinary C# errors for illegal transitions and Owen's `OWNxxx` findings
from a plain `dotnet build`, on a machine with no Python, no Rust toolchain, no global `owen`
and no Own.NET checkout. The host that does it (`Owen.Build`) names no extension.

Steps:
1. **pack** — this platform's `own-cli` (built with cargo here, or given with
   `--rust-core`) is staged under its platform key; `Owen.Build`, `Owen.TypedBuilder` and the
   synthetic `Owen.TestExtension` are packed into a fresh feed.
2. **isolated consumer** — a fresh directory OUTSIDE the checkout, an environment with only
   the running `dotnet` (plus the system shell MSBuild's Exec needs) on PATH, fresh
   HOME / NUGET_PACKAGES, and a nuget.config that maps `Owen.*` to the feed alone. Python,
   cargo, rustc and owen must resolve to nothing there.
3. **A-H** — install and generation, compiler errors, Owen errors with their canonical
   MSBuild coordinates, no toolchain leakage, the whole TB-MVP corpus through the package, the
   TB-MVP acceptance runner against the consumer (byte-identical transcript), and a second
   extension beside the first.
4. **M1-M7** — mutations of the installed packages that the contract says must fail loud.

Run:  python scripts/owen_extension_gate.py [--rust-core <own-cli>] [--keep]
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ROSLYN = os.path.join(ROOT, "frontend", "roslyn")
SAMPLE = os.path.join(ROOT, "samples", "OrderBackend")
TEST_EXTENSION = os.path.join(ROOT, "tests", "owen-extensions", "Owen.TestExtension")
VERSION = "0.1.0"
WINDOWS = os.name == "nt"
KEY = (
    ("win" if WINDOWS else "linux")
    + "-"
    + {"x86_64": "x64", "AMD64": "x64", "amd64": "x64"}.get(platform.machine(), platform.machine())
)
CORE_NAME = "own-cli.exe" if WINDOWS else "own-cli"
# the TB-MVP sources a consumer writes by hand (the protocol and the vocabulary are generated)
CONSUMER_SOURCES = (
    "Program.cs",
    "OrderEndpoints.cs",
    "Shipping.cs",
    "Domain/Order.cs",
    "Data/OrdersDb.cs",
)
GENERATED_HINT = "Order.Protocol.g.cs"
HOST_SOURCES = (
    os.path.join(ROSLYN, "Owen.Build"),
    os.path.join(ROSLYN, "OwnSharp.Cli", "BuildCheckCommand.cs"),
    os.path.join(ROSLYN, "OwenRustCore.props"),
)

FAILS: list[str] = []
PASSED: list[str] = []


def check(name: str, holds: bool, detail: str) -> bool:
    (PASSED if holds else FAILS).append(f"{name}: {detail}")
    print(f"{'ok' if holds else 'FAIL'}[{name}]: {detail}", flush=True)
    return holds


def run(
    cmd: list[str], cwd: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# ---- 1. pack -------------------------------------------------------------------------------


def stage_core(work: str, given: str | None) -> str:
    stage = os.path.join(work, "rust-stage")
    os.makedirs(os.path.join(stage, KEY))
    if given is None:
        built = run(
            ["cargo", "build", "-p", "own-cli", "--release"], cwd=os.path.join(ROOT, "rust")
        )
        if built.returncode != 0:
            raise SystemExit(f"FAIL: cargo build own-cli: {built.stderr[-800:]}")
        given = os.path.join(ROOT, "rust", "target", "release", CORE_NAME)
    shutil.copy2(given, os.path.join(stage, KEY, CORE_NAME))
    return stage


def pack(work: str, stage: str) -> str:
    feed = os.path.join(work, "feed")
    os.makedirs(feed)
    for project, extra in (
        (os.path.join(ROSLYN, "Owen.Build"), [f"-p:OwenRustCoreDir={stage}"]),
        (os.path.join(ROSLYN, "Owen.TypedBuilder"), []),
        (TEST_EXTENSION, []),
    ):
        done = run(
            ["dotnet", "pack", project, "-c", "Release", "-o", feed, "-nologo", *extra], cwd=ROOT
        )
        if done.returncode != 0:
            raise SystemExit(f"FAIL: pack {os.path.basename(project)}: {done.stdout[-1500:]}")
    return feed


# ---- 2. the isolated consumer ------------------------------------------------------------


class Consumer:
    """A project outside the checkout, built in an environment with nothing of Owen's but the
    packages it restores."""

    def __init__(self, work: str, feed: str) -> None:
        self.work = work
        self.ws = os.path.join(work, "ws")
        self.dir = os.path.join(self.ws, "OrderBackend")
        self.home = os.path.join(work, "home")
        self.nuget = os.path.join(self.home, "nuget")
        os.makedirs(self.dir)
        os.makedirs(self.home)
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            raise SystemExit("FAIL: dotnet is not on PATH")
        dotnet_dir = os.path.dirname(os.path.realpath(dotnet))
        path = [dotnet_dir]
        env = {
            "HOME": self.home,
            "DOTNET_CLI_HOME": self.home,
            "NUGET_PACKAGES": self.nuget,
            "DOTNET_ROOT": dotnet_dir,
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
            "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
            "TEMP": tempfile.gettempdir(),
            "TMP": tempfile.gettempdir(),
            "TMPDIR": tempfile.gettempdir(),
        }
        if WINDOWS:
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            path.append(os.path.join(system_root, "System32"))
            env.update(
                {
                    "SystemRoot": system_root,
                    "ComSpec": os.path.join(system_root, "System32", "cmd.exe"),
                    "USERPROFILE": self.home,
                    "APPDATA": os.path.join(self.home, "AppData", "Roaming"),
                    "LOCALAPPDATA": os.path.join(self.home, "AppData", "Local"),
                    "ProgramData": os.environ.get("ProgramData", r"C:\ProgramData"),
                }
            )
            # what any Windows process expects to find; none of it is a toolchain
            for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "CommonProgramFiles",
                         "windir", "PATHEXT", "SystemDrive", "OS", "NUMBER_OF_PROCESSORS",
                         "PROCESSOR_ARCHITECTURE"):
                if name in os.environ:
                    env[name] = os.environ[name]
        else:
            # MSBuild's Exec runs `sh` from PATH; give it the shell and nothing else
            sysbin = os.path.join(work, "sysbin")
            os.makedirs(sysbin)
            os.symlink("/bin/sh", os.path.join(sysbin, "sh"))
            path.append(sysbin)
        env["PATH"] = os.pathsep.join(path)
        self.env = env
        with open(os.path.join(self.ws, "nuget.config"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f"""<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="owen-candidate" value="{feed}" />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
  <packageSourceMapping>
    <packageSource key="owen-candidate"><package pattern="Owen.*" /></packageSource>
    <packageSource key="nuget.org"><package pattern="*" /></packageSource>
  </packageSourceMapping>
</configuration>
""")

    def dotnet(self, *args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        return run(["dotnet", *args], cwd=cwd or self.dir, env=self.env)

    def build(self, *props: str) -> subprocess.CompletedProcess[str]:
        return self.dotnet("build", "-nologo", *props)

    def path(self, *parts: str) -> str:
        return os.path.join(self.dir, *parts)

    def installed(self, package: str, *parts: str) -> str:
        return os.path.join(self.nuget, package.lower(), VERSION, *parts)


def isolation(c: Consumer) -> None:
    leaked = {
        tool: found
        for tool in ("python", "python3", "py", "cargo", "rustc", "owen")
        if (found := shutil.which(tool, path=c.env["PATH"])) is not None
    }
    check(
        "E-no-toolchain",
        not leaked,
        f"on the consumer PATH: {leaked or 'no python/cargo/rustc/owen'}",
    )
    try:
        inside = os.path.commonpath([os.path.realpath(c.dir), ROOT]) == ROOT
    except ValueError:  # Windows: different drives, so certainly not inside
        inside = False
    check("E-outside-checkout", not inside, "the consumer is outside the Own.NET checkout")


def scaffold(c: Consumer) -> None:
    done = c.dotnet("new", "web", "-n", "OrderBackend", "-o", ".", "--framework", "net8.0")
    if done.returncode != 0:
        raise SystemExit(f"FAIL: dotnet new web: {done.stdout[-800:]}{done.stderr[-800:]}")
    os.remove(c.path("Program.cs"))
    for args in (
        ["Owen.TypedBuilder", "--version", VERSION],
        ["Microsoft.EntityFrameworkCore.Sqlite", "--version", "8.0.11"],
    ):
        done = c.dotnet("add", "package", *args)
        if done.returncode != 0:
            raise SystemExit(f"FAIL: dotnet add package {args[0]}: {done.stdout[-1500:]}")
    for rel in CONSUMER_SOURCES:
        os.makedirs(os.path.dirname(c.path(rel)) or c.dir, exist_ok=True)
        shutil.copyfile(
            os.path.join(SAMPLE, "OrderBackend", *rel.split("/")), c.path(*rel.split("/"))
        )
    with open(c.path("OrderBackend.csproj"), encoding="utf-8") as f:
        project = f.read()
    owen = re.findall(r'<PackageReference Include="(Owen\.[^"]+)"', project)
    check(
        "U1-one-reference",
        owen == ["Owen.TypedBuilder"],
        f"the consumer project references {owen} (and nothing else of Owen's)",
    )


# ---- 3. A-H --------------------------------------------------------------------------------


def owen_lines(output: str) -> list[str]:
    return sorted(
        {
            line.split(" [")[0].strip()
            for line in output.splitlines()
            if re.search(r": (?:warning|error) OW(?:EN)?[NB]\d", line)
        }
    )


def cs_errors(output: str) -> list[tuple[str, str, str]]:
    return sorted(
        {
            (os.path.basename(m[0]), m[1], m[2])
            for m in re.findall(
                r"^\s*(.+?)\(\d+,\d+\): error (CS\d+): (.*?) \[", output, flags=re.M
            )
        }
    )


def generation(c: Consumer) -> None:
    built = c.build()
    check("A-build", built.returncode == 0, f"the fresh consumer builds (exit {built.returncode})")
    found = [
        os.path.join(base, n)
        for base, _, names in os.walk(c.path("obj"))
        for n in names
        if n == GENERATED_HINT
    ]
    with open(os.path.join(SAMPLE, "OrderBackend", "Domain", "Order.Protocol.cs"), "rb") as f:
        golden = f.read()
    text = b""
    if len(found) == 1:
        with open(found[0], "rb") as f:
            text = f.read().removeprefix(b"\xef\xbb\xbf")
    check(
        "A-generated-is-golden",
        text == b"#nullable enable\n" + golden,
        f"{len(found)} generated {GENERATED_HINT}; text = '#nullable enable' + the committed "
        f"golden ({len(golden)} bytes): {text == b'#nullable enable' + chr(10).encode() + golden}",
    )
    manifest = c.path("obj", "owen", "extensions.json")
    data = json.load(open(manifest, encoding="utf-8")) if os.path.exists(manifest) else {}
    exts = [(e["id"], e["version"], e["capabilities"]) for e in data.get("extensions", [])]
    check(
        "A-manifest",
        exts
        == [
            (
                "Owen.TypedBuilder",
                VERSION,
                ["heap-effects", "ownership", "proven-call", "state-protocol"],
            )
        ]
        and data.get("ownir") == 2,
        f"obj/owen/extensions.json: {exts}",
    )
    check(
        "A-clean",
        owen_lines(built.stdout) == [],
        f"no Owen diagnostic on the clean sample: {owen_lines(built.stdout)}",
    )


def staged(c: Consumer, kind: str, case: str) -> str:
    target = c.path(f"{case}.cs")
    shutil.copyfile(os.path.join(SAMPLE, "corpus", kind, f"{case}.cs.txt"), target)
    return target


def owen_found(output: str, code: str) -> list[str]:
    return [line for line in owen_lines(output) if f" {code}:" in line]


def compiler_and_owen(c: Consumer) -> bool:
    target = staged(c, "negative", "C1_draft_approve")
    try:
        built = c.build()
        errs = cs_errors(built.stdout)
        check(
            "B-compiler",
            built.returncode != 0
            and errs != []
            and all(code == "CS1061" and "'Approve'" in msg for _, code, msg in errs),
            f"draft.Approve(...) -> {errs}",
        )
    finally:
        os.remove(target)

    target = staged(c, "negative", "C8_stale_draft")
    try:
        built = c.build("-p:OwenSeverity=error")
        lines = owen_found(built.stdout, "OWN002")
        ok = check(
            "C-owen-error",
            built.returncode != 0 and len(lines) == 1 and " error OWN002:" in lines[0],
            f"draft spent twice, OwenSeverity=error -> exit {built.returncode}, {lines}",
        )
        m = re.match(r"^(?P<file>.+)\((?P<line>\d+)\): error OWN002: ", lines[0]) if lines else None
        check(
            "D-coordinates",
            m is not None
            and os.path.isabs(m["file"])
            and os.path.realpath(m["file"]) == os.path.realpath(target)
            and m["line"] == "18",
            f"canonical origin {m['file'] + '(' + m['line'] + ')' if m else None} "
            "is the staged file, line 18",
        )
        relaxed = c.build()
        warn = owen_found(relaxed.stdout, "OWN002")
        check(
            "D-default-is-warning",
            relaxed.returncode == 0 and len(warn) == 1 and " warning OWN002:" in warn[0],
            f"default OwenSeverity -> exit {relaxed.returncode}, {warn}",
        )
        leaks = [line for line in (built.stdout + relaxed.stdout).splitlines() if ROOT in line]
        check("E-no-checkout-path", not leaks, f"build output mentions the checkout: {leaks[:2]}")
        return ok
    finally:
        os.remove(target)


def corpus(c: Consumer) -> None:
    facts = os.path.join(c.work, "facts.json")
    n = 0
    for kind in ("positive", "negative", "limits"):
        with open(os.path.join(SAMPLE, "corpus", kind, "expected.json"), encoding="utf-8") as f:
            expected = json.load(f)
        for case, want in sorted(expected.items()):
            target = staged(c, kind, case)
            if os.path.exists(facts):
                os.remove(facts)
            try:
                built = c.build("-p:OwenSeverity=error", f"-p:OwenEmitFacts={facts}")
            finally:
                os.remove(target)
            n += 1
            owen = owen_lines(built.stdout)
            where = f"F-{kind}/{case}"
            if want["stage"] == "compiler":
                errs = cs_errors(built.stdout)
                check(
                    where,
                    built.returncode != 0
                    and errs != []
                    and all(
                        f == f"{case}.cs"
                        and code == want["code"]
                        and re.search(rf"'[^']*\b{re.escape(want['member'])}\b[^']*'", msg)
                        for f, code, msg in errs
                    ),
                    f"{want['code']} {want['member']!r}: {errs[:2]}",
                )
            elif want["stage"] == "extractor":
                hit = [
                    line
                    for line in owen
                    if " error OWENB010:" in line and want["text"] in line and f"{case}.cs(" in line
                ]
                check(
                    where,
                    built.returncode != 0 and len(hit) == 1,
                    f"OWENB010 {want['text'][:60]!r}: {owen}",
                )
            elif "refusal" in want:
                hit = [
                    line
                    for line in owen
                    if " error OWENB011:" in line
                    and want["refusal"] in line
                    and f"{case}.cs(" in line
                ]
                check(where, built.returncode != 0 and len(hit) == 1, f"OWENB011: {owen}")
            else:
                hits = (re.search(r" error (OWN\d+):", line) for line in owen)
                codes = sorted({m[1] for m in hits if m})
                clean = want["verdict"] == []
                proven = True
                if "proven_call" in want:
                    proven = (
                        os.path.exists(facts)
                        and want["proven_call"] in open(facts, encoding="utf-8").read()
                    )
                check(
                    where,
                    codes == want["verdict"] and (built.returncode == 0) == clean and proven,
                    f"verdict {codes} (expected {want['verdict']}), exit {built.returncode}"
                    + (
                        f", proven_call to {want['proven_call']}: {proven}"
                        if "proven_call" in want
                        else ""
                    ),
                )
    check(
        "F-count",
        n == 30,
        f"{n} corpus cases went through the package (8 positive, 20 negative, 2 limits)",
    )


def acceptance(c: Consumer) -> None:
    runner = os.path.join(c.ws, "Acceptance")
    shutil.copytree(
        os.path.join(SAMPLE, "Acceptance"), runner, ignore=shutil.ignore_patterns("bin", "obj")
    )
    # The runner is a test harness, not the product under test, and it opens a region in
    # top-level statements, which the extractor does not model: with Owen on, the host refuses
    # it (OWENB010) rather than skipping it, so the harness turns Owen off for itself.
    built = c.dotnet("build", "-nologo", "-p:OwenEnabled=false", cwd=runner)
    if not check(
        "G-build",
        built.returncode == 0,
        f"the TB-MVP acceptance runner builds against the consumer "
        f"(exit {built.returncode}) {built.stdout[-400:] if built.returncode else ''}",
    ):
        return
    ran = c.dotnet(os.path.join("bin", "Debug", "net8.0", "Acceptance.dll"), cwd=runner)
    with open(os.path.join(SAMPLE, "evidence", "acceptance.txt"), encoding="utf-8") as f:
        committed = f.read()
    oks = len(re.findall(r"^ok\[", ran.stdout, flags=re.M))
    check(
        "G-acceptance",
        ran.returncode == 0 and ran.stdout.replace("\r\n", "\n") == committed,
        f"44-check acceptance over the PACKAGE-generated API: exit {ran.returncode}, {oks} ok, "
        "transcript byte-identical to samples/OrderBackend/evidence/acceptance.txt: "
        f"{ran.stdout.replace(chr(13), '') == committed}",
    )


def second_extension(c: Consumer) -> None:
    done = c.dotnet("add", "package", "Owen.TestExtension", "--version", VERSION)
    check("H-add", done.returncode == 0, "Owen.TestExtension added beside Owen.TypedBuilder")
    target = staged(c, "negative", "C8_stale_draft")
    try:
        built = c.build("-p:OwenSeverity=error")
    finally:
        os.remove(target)
    data = json.load(open(c.path("obj", "owen", "extensions.json"), encoding="utf-8"))
    ids = [e["id"] for e in data["extensions"]]
    lines = owen_found(built.stdout, "OWN002")
    check(
        "H-two-extensions",
        ids == ["Owen.TestExtension", "Owen.TypedBuilder"] and len(lines) == 1,
        f"manifest {ids}; the project is analysed once: {len(lines)} OWN002",
    )
    c.dotnet("remove", "package", "Owen.TestExtension")


# ---- 4. mutations --------------------------------------------------------------------------


def mutate(
    c: Consumer, name: str, files: Mapping[str, bytes | None], probe: Callable[[], None]
) -> None:
    """Rewrite (bytes) or delete (None) installed package files, run `probe`, restore."""
    saved: dict[str, bytes | None] = {}
    for path, content in files.items():
        saved[path] = open(path, "rb").read() if os.path.exists(path) else None
        if content is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "wb") as f:
                f.write(content)
    try:
        probe()
    finally:
        for path, content in saved.items():
            if content is None:
                if os.path.exists(path):
                    os.remove(path)
            else:
                with open(path, "wb") as f:
                    f.write(content)


def mutations(c: Consumer) -> None:
    descriptor = c.installed("Owen.TypedBuilder", "buildTransitive", "owen-extension.json")
    descriptor_build = c.installed("Owen.TypedBuilder", "build", "owen-extension.json")
    original = json.load(open(descriptor, encoding="utf-8"))

    def with_c8(
        props: tuple[str, ...] = ("-p:OwenSeverity=error",),
    ) -> subprocess.CompletedProcess[str]:
        target = staged(c, "negative", "C8_stale_draft")
        try:
            return c.build(*props)
        finally:
            os.remove(target)

    def m1a() -> None:
        built = with_c8()
        check(
            "M1a-descriptor-missing",
            built.returncode != 0
            and owen_found(built.stdout, "OWENB002") != []
            and owen_found(built.stdout, "OWN002") == [],
            f"declared descriptor deleted -> exit {built.returncode}, OWENB002 'cannot be read': "
            f"{owen_found(built.stdout, 'OWENB002')[:1]}",
        )

    mutate(c, "M1a", {descriptor: None, descriptor_build: None}, m1a)

    def m1b() -> None:
        built = with_c8()
        check(
            "M1b-not-declared",
            owen_found(built.stdout, "OWENB001") != []
            and owen_found(built.stdout, "OWN002") == [],
            "extension declaration (props + descriptor) deleted -> OWENB001 "
            "'no Owen extension is active', and no OWN002: the C check would fail",
        )

    declaration = {
        p: None
        for d in ("build", "buildTransitive")
        for p in (
            c.installed("Owen.TypedBuilder", d, "owen-extension.json"),
            c.installed("Owen.TypedBuilder", d, "Owen.TypedBuilder.props"),
        )
    }
    mutate(c, "M1b", declaration, m1b)

    def descriptor_with(**requires: object) -> bytes:
        d = json.loads(json.dumps(original))
        d["requires"].update(requires)
        return json.dumps(d).encode()

    def expect(name: str, code: str, needle: str) -> Callable[[], None]:
        def probe() -> None:
            built = with_c8()
            hit = [line for line in owen_found(built.stdout, code) if needle in line]
            check(
                name,
                built.returncode != 0 and hit != [] and owen_found(built.stdout, "OWN002") == [],
                f"-> exit {built.returncode}, {hit[:1]}",
            )

        return probe

    caps = [*original["requires"]["capabilities"], "teleportation"]
    mutate(
        c,
        "M2",
        {
            descriptor: descriptor_with(capabilities=caps),
            descriptor_build: descriptor_with(capabilities=caps),
        },
        expect("M2-unknown-capability", "OWENB004", "'teleportation'"),
    )
    mutate(
        c,
        "M4a",
        {descriptor: descriptor_with(ownir=3), descriptor_build: descriptor_with(ownir=3)},
        expect("M4-ownir", "OWENB003", "requires OwnIR 3"),
    )
    mutate(
        c,
        "M4b",
        {
            descriptor: descriptor_with(host="9.0.0"),
            descriptor_build: descriptor_with(host="9.0.0"),
        },
        expect("M4-host", "OWENB003", "requires Owen host 9.0.0"),
    )
    core = c.installed("Owen.Build", "tools", "net8.0", "any", "rust-core", KEY, CORE_NAME)
    # the host may have materialised an executable copy in its cache: remove that too
    cache = os.path.join(c.home, ".owen", "rust-core")
    if os.path.isdir(cache):
        shutil.rmtree(cache)
    mutate(c, "M3", {core: None}, expect("M3-no-core", "OWENB005", "own-cli"))
    empty = b"<Project />\n"
    targets = [
        c.installed("Owen.Build", d, "Owen.Build.targets") for d in ("build", "buildTransitive")
    ]

    def m5() -> None:
        built = with_c8()
        check(
            "M5-no-target",
            owen_found(built.stdout, "OWN002") == [],
            f"host target removed -> no OWN002 (exit {built.returncode}): the C check would fail",
        )

    mutate(c, "M5", dict.fromkeys(targets, empty), m5)

    hits = []
    for src in HOST_SOURCES:
        files = (
            [src]
            if os.path.isfile(src)
            else [
                os.path.join(b, n)
                for b, _, ns in os.walk(src)
                for n in ns
                if "/obj/" not in os.path.join(b, n).replace("\\", "/")
                and "/bin/" not in os.path.join(b, n).replace("\\", "/")
            ]
        )
        for path in files:
            with open(path, encoding="utf-8", errors="replace") as f:
                if "TypedBuilder" in f.read():
                    hits.append(os.path.relpath(path, ROOT))
    check("M7-host-is-generic", hits == [], f"host sources naming TypedBuilder: {hits}")


def main() -> int:
    argv = sys.argv[1:]
    given = argv[argv.index("--rust-core") + 1] if "--rust-core" in argv else None
    keep = "--keep" in argv
    work = tempfile.mkdtemp(prefix="owen-ext-gate-")
    try:
        stage = stage_core(work, given)
        feed = pack(work, stage)
        c = Consumer(work, feed)
        isolation(c)
        scaffold(c)
        generation(c)
        compiler_and_owen(c)
        corpus(c)
        acceptance(c)
        second_extension(c)
        mutations(c)
    finally:
        if keep:
            print(f"kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    print(f"owen extension gate ({KEY}): {len(PASSED)} checks passed, {len(FAILS)} failed")
    for f in FAILS:
        print(f"FAIL: {f}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
