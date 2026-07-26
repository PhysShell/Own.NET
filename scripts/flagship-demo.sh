#!/usr/bin/env bash
# The flagship leak-to-retention-path demo, as a DUMB orchestrator (alpha A4).
#
# It prepares nothing clever and decides nothing clever: build the sample and
# the witness, run the bad app held live, attach the witness through its
# PUBLIC CLI, machine-validate the JSON artifact against the human verdict,
# print ONE stable summary line, clean up. All classification/verdict logic
# stays in the witness — a demo script that grows its own opinion about
# retention becomes a second, worse witness.
#
# Usage:  scripts/flagship-demo.sh [bad|ok]     (default: bad)
#
# Exit: 0 — the variant behaved exactly as documented (bad: RETAINED via
#           static-event; ok: no established retention);
#       1 — it did not, or the human and JSON verdicts DISAGREE;
#       2 — orchestration failure (build/launch/timeout).
set -u

VARIANT="${1:-bad}"
case "$VARIANT" in bad|ok) ;; *) echo "usage: $0 [bad|ok]" >&2; exit 2 ;; esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT/examples/flagship/console/$VARIANT"
WITNESS_DIR="$ROOT/audit/runtime/RetentionPath"
WORK="$(mktemp -d)"
APP_PID=""

cleanup() {
    [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null
    rm -rf "$WORK"
}
trap cleanup EXIT INT TERM

fail() { echo "flagship-demo: FAIL: $*" >&2; exit "${2:-2}"; }

# ---- build (quietly; full logs kept for the failure path) --------------------
dotnet build "$APP_DIR" -c Release -v quiet > "$WORK/build-app.log" 2>&1 \
    || { cat "$WORK/build-app.log" >&2; fail "sample build failed"; }
dotnet build "$WITNESS_DIR" -c Release -v quiet > "$WORK/build-witness.log" 2>&1 \
    || { cat "$WORK/build-witness.log" >&2; fail "witness build failed"; }

APP_DLL=$(ls "$APP_DIR"/bin/Release/net8.0/*DocumentApp.dll) || fail "sample dll not found"
WITNESS_DLL="$WITNESS_DIR/bin/Release/net8.0/RetentionPath.dll"

# ---- launch the app held live (the OWEN_FLAGSHIP_HOLD contract) --------------
mkfifo "$WORK/stdin"
OWEN_FLAGSHIP_HOLD=1 dotnet "$APP_DLL" > "$WORK/app.log" 2>&1 < "$WORK/stdin" &
APP_PID=$!
exec 9> "$WORK/stdin"   # keep ReadLine blocked

for _ in $(seq 1 30); do
    grep -q "holding (pid" "$WORK/app.log" 2>/dev/null && break
    kill -0 "$APP_PID" 2>/dev/null || { cat "$WORK/app.log" >&2; fail "app exited before holding"; }
    sleep 1
done
grep -q "holding (pid" "$WORK/app.log" || { cat "$WORK/app.log" >&2; fail "app did not reach the hold point in 30s"; }

# ---- the witness, through its public CLI -------------------------------------
timeout 120 dotnet "$WITNESS_DLL" roots --pid "$APP_PID" \
    --type Owen.Flagship.DocumentView --out "$WORK/witness.json" \
    > "$WORK/witness.log" 2>&1
WITNESS_RC=$?
echo >&9 || true   # release the app

# ---- machine validation: JSON is the artifact, grep is not a parser ----------
SUMMARY=$(python3 - "$VARIANT" "$WITNESS_RC" "$WORK/witness.json" "$WORK/witness.log" "$WORK/app.log" <<'PY'
import json, re, sys
variant, rc, json_path, log_path, app_log = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
human = open(log_path, encoding="utf-8", errors="replace").read()
app = open(app_log, encoding="utf-8", errors="replace").read()
m = re.search(r"still subscribed", app)
subs = re.search(r"(\d[\d,]*) still subscribed", app)
problems = []

if variant == "bad":
    if rc != 1:
        problems.append(f"witness exit {rc}, want 1 (RETAINED)")
    try:
        doc = json.load(open(json_path, encoding="utf-8"))
    except Exception as e:
        problems.append(f"JSON artifact unreadable: {e}")
        doc = {}
    if doc.get("verdict") != "RETAINED":
        problems.append(f"JSON verdict {doc.get('verdict')!r}, want RETAINED")
    if "verdict: RETAINED" not in human:
        problems.append("human output lacks 'verdict: RETAINED'")
    roots = (doc.get("retained") or [{}])[0].get("roots") or []
    kinds = {r.get("kind") for r in roots}
    if "static-event" not in kinds:
        problems.append(f"no static-event root in JSON (got {sorted(kinds)})")
    # stable semantic anchors, not verbatim addresses/paths
    path_text = " ".join(" ".join(r.get("path", [])) for r in roots)
    for anchor in ("AppSettings", "PropertyChanged", "_invocationList", "DocumentView"):
        if anchor not in path_text + " ".join(str(r.get("holder", "")) for r in roots) + human:
            problems.append(f"retention path lacks the '{anchor}' anchor")
    if ("verdict: RETAINED" in human) != (doc.get("verdict") == "RETAINED"):
        problems.append("human and JSON verdicts DISAGREE")
    verdict_line = "leak DEMONSTRATED: static-event retention, path root->view established"
else:
    # The user-level contract only: exit 0, verdict in {ABSENT, OBSERVED_ONLY},
    # zero durable retainers. Which of the two verdicts shows up depends on JIT
    # liveness of a loop local — an internal CLR decision, not a public API;
    # the witness selftest pins the verdict semantics deterministically.
    if rc != 0:
        problems.append(f"witness exit {rc}, want 0 (nothing durably retained)")
    try:
        doc = json.load(open(json_path, encoding="utf-8"))
    except Exception as e:
        problems.append(f"JSON artifact unreadable: {e}")
        doc = {}
    if doc.get("verdict") not in ("ABSENT", "OBSERVED_ONLY"):
        problems.append(f"JSON verdict {doc.get('verdict')!r}, want ABSENT or OBSERVED_ONLY")
    roots = (doc.get("retained") or [{}])[0].get("roots") or []
    durable = [r.get("kind") for r in roots if r.get("kind") not in ("stack", "finalizer")]
    if durable:
        problems.append(f"ok variant has durable retainer(s): {durable}")
    if "verdict: RETAINED" in human:
        problems.append("ok variant must not be RETAINED")
    if (doc.get("verdict") in ("ABSENT", "OBSERVED_ONLY")) != ("verdict: RETAINED" not in human):
        problems.append("human and JSON verdicts DISAGREE")
    verdict_line = f"fix VERIFIED: no established retention ({doc.get('verdict')})"

if problems:
    for p in problems:
        print(f"flagship-demo: FAIL: {p}", file=sys.stderr)
    sys.exit(1)
subs_n = subs.group(1) if subs else "?"
print(f"flagship-demo[{variant}]: app reported {subs_n} live subscription(s); {verdict_line}")
PY
) || { cat "$WORK/witness.log" >&2; fail "validation failed (witness log above)" 1; }

echo "$SUMMARY"
