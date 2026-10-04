"""OX-02 live gate: the Owen IDE service, as Owen.VisualStudio uses it, outside any IDE.

docs/notes/owen-visual-studio-preregistration.md. Packs Owen.Build (with this platform's Rust
core), Owen.TypedBuilder and two synthetic extensions, creates a project OUTSIDE the checkout
that references Owen.TypedBuilder, and then — with no build of that project — proves:

  L0  a design-time build (what Visual Studio runs on load) writes obj/owen/live.txt naming
      the package's service, and analyses nothing;
  S*  `owen serve` speaks owen-live/1 and nothing else on stdout; malformed input is fatal (3);
  K1  an unsaved clean edit -> no OWN finding;           K2  an unsaved second Submit -> OWN002
  K3  the line deleted -> gone;                  K5  broken syntax -> an answer, then recovery
  K4s queued requests of one project: only the newest runs (superseded), cancel answers cancelled
  K7  an extension needing an unknown capability -> OWENB004, live
  K8  a second extension with its own generator -> its finding too, no host change
  P10 build/live parity on saved sources (code, severity, message, file, line)
  T   latency (warm p50/p95, cold start) and the service's working set after 10 and 100 runs
  C   tests/owen-live/LiveClientTests against the real service (K4, K6, M1/M2 controls)
  G   neither the service nor Owen.VisualStudio names an extension

Run: python scripts/owen_live_gate.py [--rust-core <own-cli>] [--keep]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owen_extension_gate as ox

ROOT = ox.ROOT
LIVE = os.path.join(ROOT, "tests", "owen-live")
FIXTURE = os.path.join(LIVE, "LiveFixture")
TEST_PROTOCOL = os.path.join(ROOT, "tests", "owen-extensions", "Owen.TestProtocol")
GENERIC_SOURCES = (
    os.path.join(ox.ROSLYN, "OwnSharp.Cli", "ServeCommand.cs"),
    os.path.join(ox.ROSLYN, "OwnSharp.Cli", "LiveAnalysis.cs"),
    os.path.join(ox.ROSLYN, "OwnSharp.Cli", "OwenHost.cs"),
    os.path.join(ox.ROSLYN, "Owen.VisualStudio"),
)
CANONICAL = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+)(?:,\d+)?\): (?P<sev>warning|error) "
    r"(?P<code>OW(?:EN)?[NB]?\d+): "
    r"(?P<msg>.*?)(?: \[[^\]]*\.csproj\])?$"
)

check = ox.check

USE_CLEAN = open(os.path.join(FIXTURE, "Use.cs.txt"), encoding="utf-8").read()
ANCHOR = "            var submitted = draft.Submit(now);\n"
STALE_LINE = "            draft.Submit(now);\n"
USE_STALE = USE_CLEAN.replace(ANCHOR, ANCHOR + STALE_LINE)
USE_BROKEN = USE_CLEAN.replace(ANCHOR, ANCHOR + "            draft.Submit(now\n")
USE_COPY = USE_CLEAN.replace(
    ANCHOR, "            var copy = draft;\n" + ANCHOR + "            copy.Submit(now);\n"
)
USE_RAW = USE_CLEAN.replace(ANCHOR, ANCHOR + "            var customer = order.Customer;\n")
USE_REFUSED = USE_CLEAN.replace(ANCHOR, ANCHOR + '            System.Console.WriteLine("x");\n')
GATE_CLEAN = open(os.path.join(FIXTURE, "Gate.cs.txt"), encoding="utf-8").read()
GATE_STALE = GATE_CLEAN.replace(
    "            var unlocked = locked.Coin();\n",
    "            var unlocked = locked.Coin();\n            locked.Coin();\n",
)


# ---- the service, as a client sees it ---------------------------------------------------------


class Service:
    def __init__(self, host: str, env: dict[str, str], cwd: str) -> None:
        env = dict(env, DOTNET_ROLL_FORWARD="Major")
        self.proc = subprocess.Popen(
            ["dotnet", "exec", host, "serve"],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.next_id = 0

    def send(self, message: dict[str, Any]) -> None:
        body = json.dumps(message).encode("utf-8")
        assert self.proc.stdin is not None
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.proc.stdin.flush()

    def read(self) -> dict[str, Any] | None:
        assert self.proc.stdout is not None
        length = None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                return None
            if line == b"\r\n":
                break
            m = re.fullmatch(rb"Content-Length: (\d+)\r\n", line)
            if m is None:
                raise AssertionError(f"not a frame header on the service's stdout: {line!r}")
            length = int(m.group(1))
        assert length is not None
        body = self.proc.stdout.read(length)
        result: dict[str, Any] = json.loads(body)
        return result

    def hello(self) -> dict[str, Any] | None:
        self.send({"type": "hello", "protocol": "owen-live/1"})
        return self.read()

    def submit(
        self,
        key: str,
        version: int,
        request: str,
        documents: list[tuple[str, str]],
        generated: list[tuple[str, str]],
    ) -> int:
        self.next_id += 1
        self.send(
            {
                "type": "analyze",
                "id": self.next_id,
                "key": key,
                "version": version,
                "request": request,
                "documents": [{"path": p, "text": t} for p, t in documents],
                "generated": [{"path": p, "text": t} for p, t in generated],
            }
        )
        return self.next_id

    def analyze(
        self,
        key: str,
        version: int,
        request: str,
        documents: list[tuple[str, str]],
        generated: list[tuple[str, str]],
    ) -> dict[str, Any]:
        self.submit(key, version, request, documents, generated)
        answer = self.read()
        assert answer is not None, "the service closed its stdout"
        return answer

    def close(self) -> tuple[int, str]:
        try:
            self.send({"type": "shutdown"})
        except OSError:
            pass
        try:
            _, err = self.proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            _, err = self.proc.communicate()
        return self.proc.returncode, err.decode("utf-8", "replace")


def raw_exchange(
    host: str, env: dict[str, str], cwd: str, payload: bytes
) -> tuple[int, bytes, str]:
    done = subprocess.run(
        ["dotnet", "exec", host, "serve"],
        cwd=cwd,
        env=dict(env, DOTNET_ROLL_FORWARD="Major"),
        input=payload,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return done.returncode, done.stdout, done.stderr.decode("utf-8", "replace")


def frame(message: dict[str, Any]) -> bytes:
    body = json.dumps(message).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n" % len(body) + body


def frames(data: bytes) -> list[dict[str, Any]] | None:
    """Every byte of stdout as frames, or None if anything else is there."""
    out = []
    while data:
        m = re.match(rb"Content-Length: (\d+)\r\n\r\n", data)
        if m is None:
            return None
        start = m.end()
        end = start + int(m.group(1))
        out.append(json.loads(data[start:end]))
        data = data[end:]
    return out


def codes(answer: dict[str, Any]) -> list[str]:
    return sorted(d["code"] for d in answer["diagnostics"])


# ---- the fixture ------------------------------------------------------------------------------


def scaffold(c: ox.Consumer, name: str) -> None:
    c.dir = os.path.join(c.ws, name)
    os.makedirs(c.dir)
    done = c.dotnet("new", "classlib", "-n", name, "-o", ".", "--framework", "net8.0")
    if done.returncode != 0:
        raise SystemExit(f"FAIL: dotnet new classlib: {done.stdout[-800:]}{done.stderr[-800:]}")
    os.remove(c.path("Class1.cs"))
    done = c.dotnet("add", "package", "Owen.TypedBuilder", "--version", ox.VERSION)
    if done.returncode != 0:
        raise SystemExit(f"FAIL: dotnet add package: {done.stdout[-1500:]}")
    write(c.path("Order.cs"), open(os.path.join(FIXTURE, "Order.cs.txt"), encoding="utf-8").read())
    write(c.path("Use.cs"), USE_CLEAN)


def write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def design_time(c: ox.Consumer) -> subprocess.CompletedProcess[str]:
    done = c.dotnet("restore", "-nologo")
    if done.returncode != 0:
        raise SystemExit(f"FAIL: restore: {done.stdout[-1500:]}")
    return c.dotnet(
        "msbuild",
        "-nologo",
        "-t:CoreCompile",
        "-p:DesignTimeBuild=true",
        "-p:SkipCompilerExecution=true",
        "-p:ProvideCommandLineArgs=true",
        "-p:BuildingProject=false",
    )


def read_request(path: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            key, _, value = line.rstrip("\r\n").partition("\t")
            if value:
                out.setdefault(key, []).append(value)
    return out


def generated_like_an_ide(
    c: ox.Consumer, packages: list[str], extra: dict[str, str]
) -> list[tuple[str, str]]:
    """What Visual Studio's workspace holds as source-generated documents, WITHOUT building the
    project: build a throwaway copy, and name each output <project dir>/<assembly>/<type>/<hint>
    — a base of the IDE's own, not obj/generated, so the service has to relocate it."""
    copy = ox.Consumer.__new__(ox.Consumer)
    copy.__dict__.update(c.__dict__)
    copy.dir = os.path.join(c.ws, "GenCopy-" + str(len(packages)))
    shutil.copytree(c.dir, copy.dir, ignore=shutil.ignore_patterns("bin", "obj"))
    for rel, text in extra.items():
        write(os.path.join(copy.dir, rel), text)
    done = copy.build("-p:OwenEnabled=false", "-p:EmitCompilerGeneratedFiles=true")
    if done.returncode != 0:
        raise SystemExit(f"FAIL: building the generator copy: {done.stdout[-1500:]}")
    root = os.path.join(copy.dir, "obj", "Debug", "net8.0", "generated")
    if not os.path.isdir(root):
        root = os.path.join(copy.dir, "obj", "generated")
    out = []
    for dirpath, _, files in os.walk(root):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            with open(full, encoding="utf-8") as f:
                out.append((os.path.join(c.dir, rel), f.read()))
    return sorted(out)


def build_lines(c: ox.Consumer) -> tuple[int, set[tuple[str, int, str, str, str]]]:
    done = c.build()
    found = set()
    for raw in (done.stdout + done.stderr).splitlines():
        m = CANONICAL.match(raw.strip())
        if m and m.group("code").startswith(("OWN", "OWENB")):
            found.add(
                (
                    os.path.normcase(os.path.realpath(m.group("file"))),
                    int(m.group("line")),
                    m.group("sev"),
                    m.group("code"),
                    m.group("msg"),
                )
            )
    return done.returncode, found


def live_set(answer: dict[str, Any]) -> set[tuple[str, int, str, str, str]]:
    return {
        (
            os.path.normcase(os.path.realpath(d["file"])),
            int(d["line"] or 0),
            d["severity"],
            d["code"],
            d["message"],
        )
        for d in answer["diagnostics"]
    }


# ---- the gate ---------------------------------------------------------------------------------


def generic() -> None:
    hits = []
    for src in GENERIC_SOURCES:
        paths = (
            [src]
            if os.path.isfile(src)
            else [
                os.path.join(d, n)
                for d, _, fs in os.walk(src)
                for n in fs
                if n.endswith((".cs", ".csproj", ".vsixmanifest"))
                and os.sep + "obj" + os.sep not in d
                and os.sep + "bin" + os.sep not in d
            ]
        )
        for path in paths:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if "TypedBuilder" in text or "TestProtocol" in text or "Turnstile" in text:
                hits.append(os.path.relpath(path, ROOT))
    check("G-host-is-generic", hits == [], f"service/VSIX sources naming an extension: {hits}")


def protocol_errors(host: str, env: dict[str, str], cwd: str) -> None:
    for name, payload in (
        ("S-bad-protocol", b'Content-Length: 41\r\n\r\n{"type":"hello","protocol":"owen-live/9"}'),
        ("S-bad-header", b"Content-Lenght: 2\r\n\r\n{}"),
        ("S-not-json", b"Content-Length: 5\r\n\r\nhello"),
        (
            "S-unknown-type",
            frame({"type": "hello", "protocol": "owen-live/1"}) + frame({"type": "poke"}),
        ),
    ):
        rc, out, err = raw_exchange(host, env, cwd, payload)
        parsed = frames(out)
        fatal = parsed is not None and parsed and parsed[-1].get("type") == "fatal"
        check(
            name,
            rc == 3 and bool(fatal) and "fatal" in err,
            f"exit {rc}, stdout frames {[p.get('type') for p in parsed or []]}, "
            f"stderr {err.strip()[:120]!r}",
        )


def main() -> int:
    argv = sys.argv[1:]
    given = argv[argv.index("--rust-core") + 1] if "--rust-core" in argv else None
    keep = "--keep" in argv
    work = tempfile.mkdtemp(prefix="owen-live-gate-")
    try:
        run_gate(work, given)
    finally:
        if keep:
            print(f"kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    print(f"owen live gate ({ox.KEY}): {len(ox.PASSED)} checks passed, {len(ox.FAILS)} failed")
    for f in ox.FAILS:
        print(f"FAIL: {f}")
    return 1 if ox.FAILS else 0


def run_gate(work: str, given: str | None) -> None:
    generic()
    stage = ox.stage_core(work, given)
    feed = ox.pack(work, stage)
    done = ox.run(
        ["dotnet", "pack", TEST_PROTOCOL, "-c", "Release", "-o", feed, "-nologo"], cwd=ROOT
    )
    if done.returncode != 0:
        raise SystemExit(f"FAIL: pack Owen.TestProtocol: {done.stdout[-1500:]}")
    c = ox.Consumer(work, feed)
    ox.isolation(c)
    scaffold(c, "LiveFixture")
    project = c.path("LiveFixture.csproj")
    use = c.path("Use.cs")

    # ---- L0: the live request, from a design-time build only --------------------------------
    dt = design_time(c)
    live_txt = c.path("obj", "owen", "live.txt")
    request = read_request(live_txt) if os.path.exists(live_txt) else {}
    host = (request.get("host") or [""])[-1]
    check(
        "L0-live-request",
        dt.returncode == 0
        and bool(host)
        and os.path.isfile(host)
        and os.path.realpath(host).startswith(os.path.realpath(c.nuget))
        and len(request.get("descriptor", [])) == 1,
        f"design-time build exit {dt.returncode}; live.txt keys {sorted(request)}; host {host}",
    )
    built = [n for _, _, fs in os.walk(c.path("bin")) for n in fs]
    check(
        "L0-no-build",
        built == []
        and not os.path.exists(c.path("obj", "owen", "request.txt"))
        and not os.path.exists(c.path("obj", "owen", "extensions.json")),
        f"no bin/ output ({built}), no build-check request, no manifest: nothing was analysed",
    )

    generated = generated_like_an_ide(c, ["Owen.TypedBuilder"], {})
    check(
        "L0-generated-in-memory",
        len(generated) >= 2 and not os.path.exists(c.path("obj", "Debug", "net8.0", "generated")),
        f"{len(generated)} generated documents held in memory, none on disk: "
        f"{[os.path.relpath(p, c.dir) for p, _ in generated]}",
    )

    # ---- the service ------------------------------------------------------------------------
    protocol_errors(host, c.env, c.dir)
    t0 = time.perf_counter()
    svc = Service(host, c.env, c.dir)
    hello = svc.hello()
    check(
        "S-hello", hello is not None and hello.get("protocol") == "owen-live/1", f"hello: {hello}"
    )
    first = svc.analyze(project, 1, live_txt, [(use, USE_CLEAN)], generated)
    cold = (time.perf_counter() - t0) * 1000
    check(
        "K1-clean",
        first["status"] == "ok" and not [x for x in codes(first) if x.startswith("OWN")],
        f"unsaved clean text: status {first['status']}, codes {codes(first)}, "
        f"extensions {first['extensions']}",
    )

    k2 = svc.analyze(project, 2, live_txt, [(use, USE_STALE)], generated)
    own002 = [d for d in k2["diagnostics"] if d["code"] == "OWN002"]
    stale_line = USE_STALE.splitlines().index(STALE_LINE.rstrip("\n")) + 1
    region_line = (
        USE_STALE.splitlines().index("        OrderProtocol.WithDraft(order, draft =>") + 1
    )
    with open(use, encoding="utf-8") as f:
        on_disk = f.read()
    check(
        "K2-unsaved-own002",
        len(own002) == 1
        and os.path.realpath(own002[0]["file"]) == os.path.realpath(use)
        and own002[0]["line"] == region_line
        and any(r["line"] == stale_line for r in own002[0]["related"])
        and on_disk == USE_CLEAN,
        f"disk still clean={on_disk == USE_CLEAN}; OWN002 at line {[d['line'] for d in own002]} "
        f"(region entry {region_line}), witness lines "
        f"{[r['line'] for d in own002 for r in d['related']]} (inserted line {stale_line}); "
        f"message {[d['message'] for d in own002]}",
    )

    k3 = svc.analyze(project, 3, live_txt, [(use, USE_CLEAN)], generated)
    check("K3-deleted-gone", "OWN002" not in codes(k3), f"line deleted again: codes {codes(k3)}")

    k5 = svc.analyze(project, 4, live_txt, [(use, USE_BROKEN)], generated)
    k5b = svc.analyze(project, 5, live_txt, [(use, USE_STALE)], generated)
    check(
        "K5-broken-syntax",
        k5["status"] == "ok" and "OWN002" in codes(k5b),
        f"broken edit answered {k5['status']} with {codes(k5)}; "
        f"the next edit recovered: {codes(k5b)}",
    )

    # K4 on the service: three queued requests of one project, the newest wins
    ids = [svc.submit(project, v, live_txt, [(use, USE_STALE)], generated) for v in (6, 7, 8)]
    cancel_id = svc.submit(project + ".other", 1, live_txt, [(use, USE_CLEAN)], generated)
    svc.send({"type": "cancel", "id": cancel_id})
    answers: dict[int, dict[str, Any]] = {}
    while len(answers) < 4:
        got = svc.read()
        assert got is not None
        answers[got["id"]] = got
    statuses = [answers[i]["status"] for i in ids]
    check(
        "K4s-newest-runs",
        statuses[-1] == "ok"
        and set(statuses[:-1]) <= {"ok", "superseded"}
        and "superseded" in statuses
        and answers[cancel_id]["status"] in ("cancelled", "ok"),
        f"versions 6,7,8 -> {statuses}; cancelled request -> {answers[cancel_id]['status']}",
    )

    # latency and footprint
    times = []
    sets = []
    phases = []
    for i in range(100):
        start = time.perf_counter()
        a = svc.analyze(
            project, 100 + i, live_txt, [(use, USE_STALE if i % 2 else USE_CLEAN)], generated
        )
        times.append((time.perf_counter() - start) * 1000)
        phases.append((a["timing"].get("extract", 0), a["timing"].get("core", 0)))
        if i in (9, 99):
            sets.append(a["timing"].get("working_set_kb", 0))
    warm = sorted(times[5:])
    p50 = statistics.median(warm)
    p95 = warm[int(len(warm) * 0.95) - 1]
    check(
        "T-warm-latency",
        p95 < 750,
        f"warm analysis round trip p50 {p50:.0f} ms, p95 {p95:.0f} ms "
        f"(threshold 750; in the service: "
        f"extract median {statistics.median(x for x, _ in phases[5:]):.0f} ms, core median "
        f"{statistics.median(y for _, y in phases[5:]):.0f} ms); cold start "
        f"(spawn + hello + first analysis) {cold:.0f} ms",
    )
    check(
        "T-memory",
        sets[1] < 2 * sets[0],
        f"working set after 10 analyses {sets[0] // 1024} MB, after 100 {sets[1] // 1024} MB",
    )

    # ---- K7: an extension that needs what this host lacks -----------------------------------
    descriptor = request["descriptor"][0]
    with open(descriptor, "rb") as f:
        original = f.read()
    try:
        doc = json.loads(original)
        doc["requires"]["capabilities"].append("telepathy")
        with open(descriptor, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        k7 = svc.analyze(project, 300, live_txt, [(use, USE_STALE)], generated)
        check(
            "K7-unknown-capability",
            codes(k7) == ["OWENB004"] and "telepathy" in k7["diagnostics"][0]["message"],
            f"live answer: {[(d['code'], d['message'][:90]) for d in k7['diagnostics']]}",
        )
    finally:
        with open(descriptor, "wb") as f:
            f.write(original)

    # ---- K8: a second extension with its own generator ----------------------------------------
    done = c.dotnet("add", "package", "Owen.TestProtocol", "--version", ox.VERSION)
    if done.returncode != 0:
        raise SystemExit(f"FAIL: add Owen.TestProtocol: {done.stdout[-1500:]}")
    write(c.path("Gate.cs"), GATE_CLEAN)
    dt = design_time(c)
    request = read_request(live_txt)
    generated2 = generated_like_an_ide(c, ["Owen.TypedBuilder", "Owen.TestProtocol"], {})
    gate = c.path("Gate.cs")
    k8 = svc.analyze(project, 400, live_txt, [(use, USE_STALE), (gate, GATE_STALE)], generated2)
    files = sorted(os.path.basename(d["file"]) for d in k8["diagnostics"] if d["code"] == "OWN002")
    check(
        "K8-two-extensions",
        len(request.get("descriptor", [])) == 2
        and sorted(k8["extensions"]) == ["Owen.TestProtocol", "Owen.TypedBuilder"]
        and files == ["Gate.cs", "Use.cs"],
        f"descriptors {len(request.get('descriptor', []))}; active {k8['extensions']}; "
        f"OWN002 in {files}",
    )

    rc, err = svc.close()
    check("S-shutdown", rc == 0, f"shutdown exit {rc}; stderr {err.strip()[-200:]!r}")

    # ---- P10: build/live parity on saved sources ---------------------------------------------
    write(gate, GATE_CLEAN)
    svc = Service(host, c.env, c.dir)
    svc.hello()
    for name, text in (
        ("clean", USE_CLEAN),
        ("stale", USE_STALE),
        ("copy", USE_COPY),
        ("raw", USE_RAW),
        ("refused", USE_REFUSED),
    ):
        write(use, text)
        rc, built_set = build_lines(c)
        live = svc.analyze(project, 500, live_txt, [], [])
        live_found = live_set(live)
        check(
            f"P10-parity-{name}",
            built_set == live_found and (name == "clean" or bool(built_set)),
            f"build {sorted(x[3:] for x in built_set)} vs live {sorted(x[3:] for x in live_found)}"
            + (
                ""
                if built_set == live_found
                else f"; build-only {built_set - live_found}; live-only {live_found - built_set}"
            ),
        )
    svc.close()
    write(use, USE_CLEAN)

    # ---- C: the client library against the real service --------------------------------------
    tests = os.path.join(LIVE, "LiveClientTests")
    done = ox.run(["dotnet", "build", tests, "-c", "Release", "-nologo", "-v", "q"], cwd=ROOT)
    if done.returncode != 0:
        raise SystemExit(f"FAIL: LiveClientTests build: {done.stdout[-1500:]}")
    dll = os.path.join(tests, "bin", "Release", "net8.0", "LiveClientTests.dll")
    done = ox.run(["dotnet", dll, host, live_txt], cwd=c.dir, env=c.env)
    print(done.stdout, end="")
    last = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else done.stderr[-300:]
    check(
        "C-client-tests",
        done.returncode == 0 and "0 failed" in done.stdout,
        f"LiveClientTests exit {done.returncode}: {last}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
