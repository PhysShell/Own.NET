#!/usr/bin/env bash
# Build both frozen probe versions and regenerate every committed result under data/.
# Prerequisite: scripts/fetch.sh (samples/ and targets/). Needs the .NET 8 SDK.
set -euo pipefail
cd "$(dirname "$0")/.."
norm() { tr '\\\\' '/'; }   # Windows path separators in probe output
for v in v1 v2; do
  dotnet build "probe-$v" -c Release -o "build/$v" -nologo -v q > /dev/null
  probe() { dotnet "build/$v/DictRefProbe.dll" "$@"; }
  probe controls | norm > "data/controls.$v.out"
  for t in meziantou-base meziantou-fix maui-base maui-fix; do
    echo "## $t"; probe "targets/$t" --implicit-usings | norm
  done > "data/targets.$v.out"
done
# Each round is measured with the probe version frozen for it (PRECISION-PREREG.md).
dotnet build/v1/DictRefProbe.dll samples/r1 --per-file --implicit-usings --json data/r1/findings.json \
  | norm > data/r1/findings.out
dotnet build/v2/DictRefProbe.dll samples/r2 --per-file --implicit-usings --json data/r2/findings.json \
  | norm > data/r2/findings.out
python scripts/findings_table.py   # also normalises the separators inside findings.json
