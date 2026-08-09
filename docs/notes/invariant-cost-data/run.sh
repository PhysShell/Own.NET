#!/usr/bin/env bash
# Reproduces the table in ../invariant-cost-static-vs-runtime.md.
# Requires a .NET 9 SDK. The published numbers were taken on 9.0.316; any 9.0.x
# should reproduce the ORDER and the spread, but exact multipliers will differ
# by machine and patch level -- the selected SDK/runtime is printed below so a
# rerun is self-describing rather than merely claiming reproduction.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Only clean up a workdir we created ourselves; never delete a caller's.
if [[ $# -ge 1 ]]; then
  WORK="$1"
else
  WORK="$(mktemp -d)"
  trap 'rm -rf -- "$WORK"' EXIT
fi

mkdir -p "$WORK"; cp "$HERE"/{Program.cs,linq.csproj} "$WORK/"
cd "$WORK"

echo "== toolchain actually used =="
dotnet --version
dotnet --list-runtimes | grep -E '^Microsoft\.NETCore\.App 9\.0\.' || true
echo

dotnet build -c Release -v q --nologo
# Tiering disabled: every method is compiled straight to FullOpts, so the
# measurement is steady-state code. (This is non-tiered mode -- "tier 1" is a
# tiering concept and does not apply when tiering is off.)
DOTNET_TieredCompilation=0 dotnet bin/Release/net9.0/linq.dll
