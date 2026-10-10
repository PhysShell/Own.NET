#!/usr/bin/env bash
# H-28-CMD gates. Results are explicitly PASS / FAIL / SKIP.
#
#   engine        Python-only handwritten reduction. Always runnable.
#   g3            G3: production Roslyn -> OwnIR -> summaries -> core verdict.
#   runtime       G1+G2: compile the C# falsifier, direct SQLite stmt counts, isolated Npgsql P4.
#   all           run every gate; environment SKIPs are reported but do not fail local use.
#   all-required  mandatory/CI gate; ANY SKIP is a non-zero failure.
#   g3-required / runtime-required are strict single-gate forms.
#
# NuGet is not probed with curl: dotnet restore is attempted first, so an offline but warm
# package cache can run. A restore failure is an explicit SKIP; a build/test failure is FAIL.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
EV="$HERE/evidence"
MODE="${1:-all}"
mkdir -p "$EV"

skip_status() {
  local label="$1" strict="$2"
  echo "SKIP $label"
  if [ "$strict" = 1 ]; then
    echo "FAIL required gate cannot skip: $label"
    return 2
  fi
  return 3
}

engine_half() {
  echo "=== ENGINE: handwritten OwnLang reduction ==="
  local out="$EV/engine-CommandDispose.txt" rc n_cmd n_reader
  ( cd "$ROOT" && python3 -m ownlang check \
      corpus/ownership-lab/h28-command/fx/CommandDispose.own ) >"$out" 2>&1
  rc=$?
  {
    echo "# exit code: $rc (OWN001 is error severity, so a finding run exits 1)"
    echo "# command: python3 -m ownlang check corpus/ownership-lab/h28-command/fx/CommandDispose.own"
    echo "# python: $(python3 --version 2>&1)"
  } >>"$out"
  cat "$out"
  n_cmd=$(grep -c "'command' is owned but not released" "$out")
  n_reader=$(grep -c "'reader' is owned but not released" "$out")
  if [ "$rc" = 1 ] && [ "$n_cmd" = 2 ] && [ "$n_reader" = 1 ]; then
    echo "PASS ENGINE: expected 2 command findings (B/E), 1 reader finding (E); A/D clean."
    return 0
  fi
  echo "FAIL ENGINE: rc=$rc command=$n_cmd reader=$n_reader; expected rc=1 command=2 reader=1."
  return 1
}

restore_project() {
  local label="$1" project="$2" strict="$3" log="$EV/$1-restore.log"
  echo "# dotnet restore $project --ignore-failed-sources -p:NuGetAudit=false"
  if dotnet restore "$project" --ignore-failed-sources --disable-parallel \
      -p:NuGetAudit=false >"$log" 2>&1; then
    tail -8 "$log"
    return 0
  fi
  echo "# restore output: $log"
  tail -20 "$log"
  skip_status "$label dependencies unavailable (restore failed; warm cache was tried)" "$strict"
}

g3_half() {
  local strict="$1"
  echo "=== G3: production Roslyn -> OwnIR -> summaries -> core ==="
  if ! command -v dotnet >/dev/null 2>&1; then
    skip_status "G3 requires the .NET 8 SDK" "$strict"
    return $?
  fi
  local project="$ROOT/frontend/roslyn/OwnSharp.Extractor/OwnSharp.Extractor.csproj"
  restore_project "g3" "$project" "$strict"
  local restore_rc=$?
  if [ "$restore_rc" -ne 0 ]; then return "$restore_rc"; fi
  if python3 "$HERE/scripts/verify_g3.py"; then
    return 0
  fi
  echo "FAIL G3: see $EV/g3-CommandDispose.log and the emitted facts/SARIF artifacts."
  return 1
}

runtime_half() {
  local strict="$1"
  echo "=== G1+G2: compiled provider falsifier ==="
  if ! command -v dotnet >/dev/null 2>&1; then
    skip_status "runtime falsifier requires the .NET 8 SDK" "$strict"
    return $?
  fi
  local project="$HERE/falsifier/h28cmd.csproj" dll="$HERE/falsifier/bin/Release/net8.0/h28cmd-falsifier.dll"
  restore_project "runtime" "$project" "$strict"
  local restore_rc=$?
  if [ "$restore_rc" -ne 0 ]; then return "$restore_rc"; fi

  local build_log="$EV/runtime-build.log"
  if ! dotnet build "$project" -c Release --no-restore --nologo -v q >"$build_log" 2>&1; then
    echo "FAIL G1: runtime falsifier / abstract C# fixture did not compile."
    cat "$build_log"
    return 1
  fi
  cat "$build_log"
  if [ ! -f "$dll" ]; then
    echo "FAIL G1: build succeeded but expected executable is missing: $dll"
    return 1
  fi
  echo "PASS G1: falsifier and CommandDispose.cs compile under net8.0."

  # Run G2 by itself first. This makes SQLite observability useful even if no PostgreSQL
  # server/pgserver is present; it does not replace the mandatory Npgsql run below.
  local sqlite_out="$EV/runtime-sqlite-only.out" rc
  dotnet "$dll" sqlite-only >"$sqlite_out" 2>&1
  rc=$?
  cat "$sqlite_out"
  if [ "$rc" -ne 0 ]; then
    echo "FAIL G2: direct sqlite3_next_stmt checks failed (rc=$rc)."
    return 1
  fi
  grep -q '^PASS G2' "$sqlite_out" || {
    echo "FAIL G2: no PASS marker in $sqlite_out"; return 1;
  }
  echo "PASS G2: direct native statement-lifecycle checks passed."

  local full_out="$EV/runtime-full.out"
  if [ -n "${H28_PG_DSN:-}" ]; then
    echo "# Using caller-supplied H28_PG_DSN."
    H28_PG_DSN="$H28_PG_DSN" dotnet "$dll" >"$full_out" 2>&1
    rc=$?
  elif python3 -c "import pgserver" >/dev/null 2>&1; then
    python3 "$HERE/falsifier/run_with_pgserver.py" "$dll" >"$full_out" 2>&1
    rc=$?
    if [ "$rc" = 3 ]; then
      cat "$full_out"
      skip_status "PostgreSQL arm requires pgserver or H28_PG_DSN" "$strict"
      return $?
    fi
  else
    skip_status "Npgsql G1/P4/P5 requires pgserver (pip install pgserver) or H28_PG_DSN" "$strict"
    return $?
  fi
  cat "$full_out"
  if [ "$rc" -ne 0 ]; then
    echo "FAIL G1/P4/P5: Npgsql runtime assertions failed (rc=$rc)."
    return 1
  fi
  grep -q '^PASS runtime falsifier' "$full_out" || {
    echo "FAIL G1/P4/P5: no PASS marker in $full_out"; return 1;
  }
  echo "PASS G1/P4/P5: Npgsql runtime assertions passed."
  return 0
}

case "$MODE" in
  engine) engine_half ;;
  g3)
    g3_half 0; rc=$?
    [ "$rc" = 3 ] && exit 0
    exit "$rc"
    ;;
  g3-required) g3_half 1 ;;
  runtime)
    runtime_half 0; rc=$?
    [ "$rc" = 3 ] && exit 0
    exit "$rc"
    ;;
  runtime-required) runtime_half 1 ;;
  all)
    overall=0
    engine_half || overall=1
    g3_half 0; rc=$?; [ "$rc" != 0 ] && [ "$rc" != 3 ] && overall=1
    runtime_half 0; rc=$?; [ "$rc" != 0 ] && [ "$rc" != 3 ] && overall=1
    exit "$overall"
    ;;
  all-required)
    overall=0
    engine_half || overall=1
    g3_half 1 || overall=1
    runtime_half 1 || overall=1
    exit "$overall"
    ;;
  *)
    echo "usage: $0 [engine|g3|g3-required|runtime|runtime-required|all|all-required]" >&2
    exit 2
    ;;
esac
