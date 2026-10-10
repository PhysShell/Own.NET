#!/usr/bin/env bash
# H-28-CMD reproduction driver. Two halves, deliberately separable:
#
#   half 1 (ENGINE)    fx/CommandDispose.own -> python -m ownlang check
#                      needs only python3. Runs anywhere, including the sandbox that
#                      produced the report. Artifact: evidence/engine-CommandDispose.txt
#
#   half 2 (RUNTIME)   falsifier/ -> dotnet run against a real PostgreSQL
#                      needs a .NET SDK, a NuGet feed, and PostgreSQL. Artifact:
#                      evidence/falsifier.out
#                      If any of those is missing this half prints SKIP-WHY and exits 0:
#                      a missing runtime arm is recorded, never silently pretended.
#
# Usage:  corpus/ownership-lab/h28-command/run.sh [engine|runtime|all]
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
EV="$HERE/evidence"
MODE="${1:-all}"
mkdir -p "$EV"

engine_half() {
  echo "=== half 1: ENGINE (python -m ownlang check) ==="
  local out="$EV/engine-CommandDispose.txt"
  ( cd "$ROOT" && python3 -m ownlang check \
      corpus/ownership-lab/h28-command/fx/CommandDispose.own ) >"$out" 2>&1
  local rc=$?
  {
    echo "# exit code: $rc  (OWN001 is error-severity, so non-zero is the expected result)"
    echo "# command  : python3 -m ownlang check corpus/ownership-lab/h28-command/fx/CommandDispose.own"
    echo "# cwd      : repository root"
    echo "# python   : $(python3 --version 2>&1)"
  } >>"$out"
  cat "$out"
  # The prediction the report makes: 3 findings -- OWN001 on 'command' in B, and OWN001 on
  # BOTH 'command' and 'reader' in E. A and D clean. Any other shape means the report is stale.
  local n_cmd n_reader
  n_cmd=$(grep -c "'command' is owned but not released" "$out")
  n_reader=$(grep -c "'reader' is owned but not released" "$out")
  echo
  if [ "$n_cmd" = "2" ] && [ "$n_reader" = "1" ]; then
    echo "PREDICTION HOLDS: 2x OWN001 'command' (B, E) + 1x OWN001 'reader' (E), A/D clean."
    return 0
  fi
  echo "PREDICTION BROKE: got command=$n_cmd reader=$n_reader; expected command=2 reader=1."
  echo "Re-read docs/notes/h28-npgsql-command-resolution.md section 7 before trusting it."
  return 1
}

runtime_half() {
  echo
  echo "=== half 2: RUNTIME (real PostgreSQL + Npgsql + Microsoft.Data.Sqlite) ==="
  if ! command -v dotnet >/dev/null 2>&1; then
    echo "SKIP-WHY: no .NET SDK on PATH. The report's runtime arm was NOT executed;"
    echo "          its claims are source-derived (evidence/*.txt) and marked PREDICTED."
    echo "          Install .NET 8 SDK + reach api.nuget.org, then re-run: $0 runtime"
    return 0
  fi
  if ! curl -sS -m 8 -o /dev/null https://api.nuget.org/v3/index.json 2>/dev/null; then
    echo "SKIP-WHY: dotnet is present but api.nuget.org is unreachable, so Npgsql 10.0.3 and"
    echo "          Microsoft.Data.Sqlite 10.0.12 cannot be restored."
    return 0
  fi

  # PostgreSQL: pgserver (PyPI) is what the original H-28 falsifier used -- a self-contained
  # PostgreSQL 16 on a Unix socket, no root, no container.
  local dsn="${H28_PG_DSN:-}"
  if [ -z "$dsn" ] && python3 -c "import pgserver" 2>/dev/null; then
    echo "starting PostgreSQL via pgserver ..."
    dsn=$(python3 - "$HERE" <<'PY'
import os, re, sys, pgserver
d = "/tmp/h28cmd-pgdata"
srv = pgserver.get_server(d, cleanup_mode=None)
uri = srv.get_uri()                      # postgresql://postgres:@/postgres?host=<socketdir>
m = re.search(r"host=([^&\s]+)", uri)
print(f"Host={m.group(1) if m else d};Username=postgres;Database=postgres" if m else "")
PY
)
  fi
  if [ -z "$dsn" ]; then
    echo "SKIP-WHY: no PostgreSQL. Either 'pip install pgserver' or export H28_PG_DSN."
    echo "          The SQLite arm still runs: dotnet run --project falsifier -- sqlite-only"
  fi
  export H28_PG_DSN="$dsn"
  echo "DSN: ${H28_PG_DSN:-<none>}"

  local out="$EV/falsifier.out"
  ( cd "$HERE/falsifier" && dotnet run -c Release ) 2>&1 | tee "$out"
  local rc=${PIPESTATUS[0]}
  echo "# exit code: $rc" >>"$out"
  return $rc
}

case "$MODE" in
  engine)  engine_half ;;
  runtime) runtime_half ;;
  all)     engine_half; runtime_half ;;
  *) echo "usage: $0 [engine|runtime|all]" >&2; exit 2 ;;
esac
