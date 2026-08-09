#!/usr/bin/env bash
# Reproduce the measurements in ../llvm-codegen-feasibility.md.
#
# Requires: clang (tested: 18.1.3), .NET SDK 9 (tested: 9.0.316), x86-64-v3 CPU.
# Usage: ./run.sh [workdir]
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${1:-$(mktemp -d)}"
mkdir -p "$WORK/cs"

echo "== part 1: which loop shapes does LLVM -O3 vectorize? =="
for f in lenprobe matrix; do
  echo "--- $f.c ---"
  clang -O3 -march=x86-64-v3 -c "$HERE/$f.c" -o /dev/null \
    -Rpass=loop-vectorize -Rpass-missed=loop-vectorize 2>&1 | grep remark || true
done
echo "--- checkfree.c (range check hoisted out of the loop) ---"
clang -O3 -march=x86-64-v3 -c "$HERE/checkfree.c" -o /dev/null \
  -Rpass=loop-vectorize -Rpass-missed=loop-vectorize 2>&1 | grep remark || true

echo
echo "== part 2: RyuJIT vs LLVM -O3, same kernels =="
cp "$HERE"/{Program.cs,Kernels.cs,bench.csproj} "$WORK/cs/"
clang -O3 -march=x86-64-v3 -shared -fPIC "$HERE/native.c"  -o "$WORK/cs/libnative.so"
clang -O3 -march=x86-64-v3 -shared -fPIC "$HERE/native2.c" -o "$WORK/cs/libnative2.so"
# native3 = native2 kernels + the check-hoisted variants from checkfree.c
cat "$HERE/native2.c" > "$WORK/native3.c"
sed '/^#include/d; /own_throw_ioor(void) { abort/d' "$HERE/checkfree.c" >> "$WORK/native3.c"
clang -O3 -march=x86-64-v3 -shared -fPIC "$WORK/native3.c" -o "$WORK/cs/libnative3.so"

cd "$WORK/cs"
dotnet build -c Release -v q --nologo
cp ./*.so bin/Release/net9.0/

# TieredCompilation=0 measures steady-state code. With tiering on, the default
# warmup is NOT enough and the managed numbers come out ~1.4x pessimistic --
# see the "Two measurement traps" section of the note.
for run in 1 2 3; do
  DOTNET_TieredCompilation=0 dotnet bin/Release/net9.0/bench.dll
  echo
done

echo "== part 3: RyuJIT disassembly of the scalar loop =="
DOTNET_JitDisasm="AxpyManaged" DOTNET_TieredCompilation=0 \
  dotnet bin/Release/net9.0/bench.dll 2>&1 | sed -n '/Assembly listing/,/^$/p' | head -60
