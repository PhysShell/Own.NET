#!/usr/bin/env bash
# Reproduces the table in ../invariant-cost-static-vs-runtime.md.
# Requires the .NET SDK 9 (tested 9.0.316).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:-$(mktemp -d)}"
mkdir -p "$WORK"; cp "$HERE"/{Program.cs,linq.csproj} "$WORK/"
cd "$WORK"
dotnet build -c Release -v q --nologo
# steady state: measure tier-1 code, not the tier-0 warmup
DOTNET_TieredCompilation=0 dotnet bin/Release/net9.0/linq.dll
