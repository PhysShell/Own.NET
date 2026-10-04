"""OX-02 P14: prepare the solution the real Visual Studio acceptance opens.

Packs Owen.Build (with this machine's natively built Rust core) and Owen.TypedBuilder into a
local feed, then creates OUTSIDE the checkout a solution whose one project references
Owen.TypedBuilder and holds tests/owen-live/LiveFixture's Order.cs and Use.cs. It is restored
and NOT built: the acceptance must reach a live finding without any build.

Writes <out>/fixture.json: {"sln", "project", "use", "nuget_packages", "feed"}.

Run: python scripts/vs/prepare_vs_fixture.py --out <dir> [--rust-core <own-cli>]
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owen_extension_gate as ox

FIXTURE = os.path.join(ox.ROOT, "tests", "owen-live", "LiveFixture")


def main() -> int:
    argv = sys.argv[1:]
    out = os.path.abspath(argv[argv.index("--out") + 1])
    given = argv[argv.index("--rust-core") + 1] if "--rust-core" in argv else None
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    stage = ox.stage_core(out, given)
    feed = ox.pack(out, stage)
    packages = os.path.join(out, "nuget")
    ws = os.path.join(out, "ws")
    project_dir = os.path.join(ws, "LiveFixture")
    os.makedirs(project_dir)
    env = dict(
        os.environ, NUGET_PACKAGES=packages, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1"
    )
    with open(os.path.join(ws, "nuget.config"), "w", encoding="utf-8", newline="\n") as f:
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

    def dotnet(*args: str, cwd: str = project_dir) -> None:
        done = subprocess.run(
            ["dotnet", *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            raise SystemExit(
                f"FAIL: dotnet {' '.join(args)}: {done.stdout[-1500:]}{done.stderr[-800:]}"
            )

    dotnet("new", "classlib", "-n", "LiveFixture", "-o", ".", "--framework", "net8.0")
    os.remove(os.path.join(project_dir, "Class1.cs"))
    dotnet("add", "package", "Owen.TypedBuilder", "--version", ox.VERSION)
    for name in ("Order.cs", "Use.cs"):
        shutil.copyfile(os.path.join(FIXTURE, name + ".txt"), os.path.join(project_dir, name))
    dotnet("new", "sln", "-n", "LiveFixture", "--format", "sln", cwd=ws)
    dotnet(
        "sln", "LiveFixture.sln", "add", os.path.join("LiveFixture", "LiveFixture.csproj"), cwd=ws
    )
    dotnet("restore", "LiveFixture.sln", cwd=ws)
    for leftover in ("bin",):
        if os.path.exists(os.path.join(project_dir, leftover)):
            raise SystemExit(f"FAIL: the fixture has a {leftover}/ before Visual Studio opened it")
    info = {
        "sln": os.path.join(ws, "LiveFixture.sln"),
        "project": os.path.join(project_dir, "LiveFixture.csproj"),
        "use": os.path.join(project_dir, "Use.cs"),
        "nuget_packages": packages,
        "feed": feed,
    }
    with open(os.path.join(out, "fixture.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
