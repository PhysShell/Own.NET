#!/usr/bin/env bash
#
# own-check — run the Own.NET C# leak check over a path.
#
# Chains the two halves of the P-001 pipeline into one command:
#
#   *.cs --[OwnSharp.Extractor (Roslyn)]--> facts.json --[python -m ownlang ownir]--> findings
#
# This is the body of the composite GitHub Action (action.yml) and also a
# standalone local command. There is one checker — the Python core; the C# side
# only extracts facts.
#
# Usage:
#   scripts/own-check.sh [--format human|github|msbuild|sarif] [--severity error|warning]
#                        [--engine python|rust|compare]
#                        [--fail-on-finding] [--legacy] [--stats] [--body-throw-edges]
#                        [--emit-facts <path>] [--config <own.toml>] [--root <own.net checkout>]
#                        [--] <path|file> [more ...]
#
# --engine selects the analysis engine (#262 Stage 1). Python is the DEFAULT and
# the reference; `rust` runs the Rust core (`own-cli ownir`) instead; `compare`
# runs both over one captured input and exposes the reference's result only when
# they agree byte for byte. `rust` and `compare` require the candidate binary's
# absolute path in OWEN_RUST_CORE — there is no discovery of any kind, so an
# unset or unusable OWEN_RUST_CORE is a configuration error (exit 2) and NEVER a
# silent fall back to Python. A Rust failure is never turned into a Python
# success in any mode.
#
# --config <own.toml> reads the project's [weak-subscription].subscribe wrapper
# names (P-035) and teaches the extractor to treat those calls as already-released
# weak subscriptions. A malformed config is a hard error.
#
# --emit-facts copies the OwnIR facts the extractor produced to <path> (the audit's
# XAML Phase-2 join consumes them alongside xaml-facts.json); the verdict is unchanged.
#
# Defaults: --format human, --severity error, scans ".", does not fail the shell
# on findings, --root is the repo this script lives in. --severity picks how a
# host shows findings (warning = advisory). With --fail-on-finding the exit code
# is the core's (1 = leaks found). A hard error (bad facts) always exits non-zero.
#
# Local IDisposables are checked by default with the path-sensitive flow analysis
# (--flow-locals): more precise (no Task/DataTable false positives; catches
# use-after-dispose / double-dispose / leak-on-a-path, any IDisposable type).
# Branches and while/foreach loops are analysed (P-016 A1); methods with a
# construct it can't model yet (for/do loops, try) are honestly skipped. --legacy
# falls back to the broad, name-based flat detector.
#
# Requirements: a .NET SDK (`dotnet`) and Python 3.11+ on PATH.

set -euo pipefail

root=""
format="human"
severity="error"
# D1: Python is the Stage-1 default on every launcher surface. This line is the
# one that decides it for this surface.
engine="python"
fail_on_finding=0
legacy=0
stats=0
body_throw_edges=0
emit_facts=""
config=""
paths=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      [[ $# -ge 2 ]] || { echo "own-check: --root requires a value" >&2; exit 2; }
      root="$2"; shift 2 ;;
    --format)
      [[ $# -ge 2 ]] || { echo "own-check: --format requires a value" >&2; exit 2; }
      format="$2"; shift 2 ;;
    --severity)
      [[ $# -ge 2 ]] || { echo "own-check: --severity requires a value" >&2; exit 2; }
      severity="$2"; shift 2 ;;
    --engine)
      [[ $# -ge 2 ]] || { echo "own-check: --engine requires a value" >&2; exit 2; }
      engine="$2"; shift 2 ;;
    --emit-facts)
      [[ $# -ge 2 ]] || { echo "own-check: --emit-facts requires a value" >&2; exit 2; }
      emit_facts="$2"; shift 2 ;;
    --config)
      [[ $# -ge 2 ]] || { echo "own-check: --config requires a value" >&2; exit 2; }
      config="$2"; shift 2 ;;
    --fail-on-finding) fail_on_finding=1; shift ;;
    --legacy)          legacy=1; shift ;;
    --stats)           stats=1; shift ;;
    --body-throw-edges) body_throw_edges=1; shift ;;
    --)                shift; while [[ $# -gt 0 ]]; do paths+=("$1"); shift; done ;;
    -h|--help)         sed -n '2,30p' "$0"; exit 0 ;;
    *)                 paths+=("$1"); shift ;;
  esac
done

# Default root = the Own.NET checkout this script lives in (scripts/..).
if [[ -z "$root" ]]; then
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
if [[ ${#paths[@]} -eq 0 ]]; then
  paths=(".")
fi

case "$engine" in
  python|rust|compare) ;;
  *) echo "own-check: unknown --engine '$engine' (choose: python, rust, compare)" >&2; exit 2 ;;
esac

# D3/D3.1 — the Stage-1 Rust candidate locator, resolved BEFORE anything is
# extracted, for the same reason the launcher resolves its engine runtime first:
# no point extracting facts just to fail on stage 2. OWEN_RUST_CORE is the one
# ratified spelling; there is NO discovery (no PATH lookup, no rust/target
# probing, no "first binary found"), because discovery is how a stale binary
# silently stands in for the one under test. Every rejection below is a
# configuration error (exit 2) — never exit 3 (that is Python-specific), never
# exit 5 (that is an internal failure), and never a fall back to Python.
rust_core=""
if [[ "$engine" == "rust" || "$engine" == "compare" ]]; then
  rust_core="${OWEN_RUST_CORE:-}"
  problem=""
  # D3 says an ABSOLUTE path, and this is where that stops being a description
  # and becomes a check: a relative locator that happens to exist resolves
  # against the current working directory, so the same OWEN_RUST_CORE would
  # select different binaries from different directories.
  #
  # "Absolute" is not one shape here. This script runs under git-bash on
  # Windows as well as a POSIX shell, so a genuinely absolute locator may
  # arrive as `/d/a/...` (the MSYS form), as `C:/...` or `C:\...` (a native
  # Windows path, which is what a Windows caller and MSYS's own environment
  # translation both hand over), or as a UNC path. A bare `/*` test would
  # reject the Windows forms and turn a correct configuration into a usage
  # error. This accepts the forms this surface actually receives and rejects
  # everything else; it deliberately does NOT convert between them — D3
  # ratified an absolute locator, not a path translation policy.
  #
  # The set of accepted shapes is the same one .NET's IsPathFullyQualified
  # accepts, which is what the other two implementations call. In particular a
  # DRIVE-RELATIVE `C:own-cli.exe` and a ROOT-RELATIVE `\own-cli.exe` are both
  # rejected: each still resolves against ambient state (the drive's current
  # directory, the current drive), which is the thing D3 forbids.
  #
  # The backslash inside the bracket expression is doubled because the shell's
  # pattern matcher treats `\` there as an escape: `[/\]` escapes the closing
  # bracket, leaving an unterminated set that matches NEITHER `C:/` nor `C:\`.
  # That typo shipped once and was caught by Windows CI rejecting every
  # correct Windows locator, so it is spelled out rather than left to be
  # rediscovered.
  is_absolute=0
  case "$rust_core" in
    /*) is_absolute=1 ;;  # POSIX, MSYS's /c/... form, and //srv/share
  esac
  # The drive and UNC forms are absolute only where Windows is doing the
  # resolving. On Linux `C:/rust/own-cli` names a directory called `C:` in the
  # current directory — the exact ambient-resolution case D3 forbids — so
  # accepting it everywhere would have left the defect half-fixed on this
  # surface and disagreed with the two implementations that call
  # IsPathFullyQualified.
  case "$(uname -s 2>/dev/null)" in
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
      case "$rust_core" in
        [A-Za-z]:[/\\]*) is_absolute=1 ;;  # C:/... or C:\... — drive-ROOTED
        \\\\*)           is_absolute=1 ;;  # \\server\share (UNC)
      esac
      ;;
  esac
  if [[ -z "$rust_core" ]]; then
    problem="is not set (or is empty)"
  elif [[ "$is_absolute" -eq 0 ]]; then
    problem="is not an absolute path: '$rust_core' (Stage 1 resolves the candidate from this variable alone, so a path relative to the current directory would select a different binary depending on where own-check was run)"
  elif [[ -d "$rust_core" ]]; then
    problem="points at a directory, not a file: '$rust_core'"
  elif [[ ! -f "$rust_core" ]]; then
    problem="points at a path that does not exist: '$rust_core'"
  elif [[ ! -x "$rust_core" ]]; then
    problem="points at a file that is not executable: '$rust_core'"
  fi
  if [[ -n "$problem" ]]; then
    echo "own-check: --engine $engine needs the candidate \`own-cli\` binary, but OWEN_RUST_CORE $problem." >&2
    echo "own-check: set OWEN_RUST_CORE to the absolute path of the \`own-cli\` executable to run. Owen did not fall back to Python." >&2
    exit 2
  fi
fi

# One digest helper for the compare evidence below: coreutils on Linux/git-bash,
# shasum where only that exists. Named once so the two sides cannot drift into
# two different hashes.
own_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum < "$1" | cut -d' ' -f1
  else
    shasum -a 256 < "$1" | cut -d' ' -f1
  fi
}

extractor="$root/frontend/roslyn/OwnSharp.Extractor"
facts="$(mktemp)"
trap 'rm -f "$facts"' EXIT

# Stage 1: extract facts. dotnet's build/run chatter goes to stderr so stdout
# stays clean for the host-parseable findings (-o writes the facts to a file).
# Default: the path-sensitive flow detector for local IDisposables (--flow-locals);
# --legacy keeps the flat name-based detector.
extractor_args=("${paths[@]}" -o "$facts")
[[ "$legacy" -eq 0 ]] && extractor_args+=(--flow-locals)
[[ "$stats" -eq 1 ]] && extractor_args+=(--stats)
# Opt-in P-016 throw tier: also flag body-level (no-try) dispose-not-called-on-throw — CodeQL
# cs/dispose-not-called-on-throw parity. CA2000-noisy, so off by default (oracle recall measurement).
[[ "$body_throw_edges" -eq 1 ]] && extractor_args+=(--body-throw-edges)
# P-035 / minimal P-015 (--config own.toml): read the project's declared
# weak-subscribe wrapper names ([weak-subscription].subscribe) and forward each to
# the extractor as an internal transport flag. The Python carrier is the one place
# that parses/validates the config; a malformed config is a hard error here.
#
# This carrier stays Python under EVERY --engine, including `rust`: it is a
# separately documented NON-CORE Python duty, not part of the core analysis
# seam, and it is #262's D9 tail (still an open owner decision). Making
# `--engine rust` skip or reimplement it here would be inventing D9's answer.
if [[ -n "$config" ]]; then
  if ! weak_pairs="$(PYTHONPATH="$root" python -m ownlang config "$config")"; then
    exit 2
  fi
  while IFS= read -r pair; do
    [[ -n "$pair" ]] && extractor_args+=(--weak-subscribe "$pair")
  done <<< "$weak_pairs"
fi
set +e
dotnet run --project "$extractor" -- "${extractor_args[@]}" 1>&2
extract_rc=$?
set -e
if [[ "$extract_rc" -ne 0 ]]; then
  # Stage 1 failed: the build broke, the extractor crashed, or it refused the
  # input. NO VERDICT WAS PRODUCED, so this must not land on exit 1 — that code
  # is reserved for "analysed, and there are findings", and a caller that
  # chooses not to gate on findings (the Action's default) would read it as a
  # clean run. Map it into the hard-error tier; the extractor's own contract
  # codes (2 = usage, 4 = no input) already live there and pass through.
  [[ "$extract_rc" -eq 1 ]] && extract_rc=2
  exit "$extract_rc"
fi

# Optional: persist the OwnIR facts (the audit's XAML Phase-2 join consumes them
# alongside xaml-facts.json). The verdict still comes from stage 2; this is just a
# copy of the intermediate the extractor already produced.
if [[ -n "$emit_facts" ]]; then
  cp "$facts" "$emit_facts"
fi

# Stage 2: the selected engine produces the verdict at the C# location.
case "$engine" in
  python)
    set +e
    PYTHONPATH="$root" python -m ownlang ownir "$facts" --format "$format" --severity "$severity"
    rc=$?
    set -e
    ;;

  rust)
    # The PRODUCTION Rust executable, never own-shadow-engine (that is #260's
    # dev oracle and is not wired into production by this stage). Same argument
    # vector as the reference: only the engine differs.
    set +e
    "$rust_core" ownir "$facts" --format "$format" --severity "$severity"
    rc=$?
    set -e
    # The candidate could not be STARTED at all: bash reports 126 for "found
    # but not executable" and 127 for "not found". That is still the locator's
    # side of D3.1's seam — cannot select the candidate — so it is a
    # configuration error (2), not an internal failure (5). On Windows, where
    # there is no execute bit to test up front, this is the ONLY place a
    # non-runnable candidate can be caught.
    if [[ "$rc" -eq 126 || "$rc" -eq 127 ]]; then
      echo "own-check: the candidate \`own-cli\` binary could not be started: '$rust_core' (exit $rc). Set OWEN_RUST_CORE to a runnable \`own-cli\` executable. Owen did not fall back to Python." >&2
      exit 2
    fi
    # 0/1/2 are verdicts and pass through. Anything else — 70, a panic, a
    # signal death, an arbitrary 42 — is NOT a verdict: it takes the public
    # internal-error path (5) with the raw status named on stderr, and it never
    # runs Python instead.
    if [[ "$rc" -ne 0 && "$rc" -ne 1 && "$rc" -ne 2 ]]; then
      echo "own-check: the Rust analysis core exited $rc, which is not a verdict (raw child status: $rc). Owen did not fall back to Python." >&2
      exit 5
    fi
    ;;

  compare)
    # D4/D4.1 — both engines over ONE capture.
    #
    # The extractor already ran exactly once above; these bytes are read once
    # into one file and each engine's input is materialised from THAT file and
    # then re-hashed against it. "Both were handed the same path" is an
    # assumption; two recorded digests equal to the capture's is a measurement,
    # and it is the measurement that makes "compare fed the engines different
    # bytes and still reported agreement" a control that can go red.
    cmp_dir="$(mktemp -d)"
    trap 'rm -f "$facts"; rm -rf "$cmp_dir"' EXIT
    capture="$cmp_dir/capture.json"
    cp "$facts" "$capture"
    capture_sha="$(own_sha256 "$capture")"

    # A compare that judged nothing agrees about nothing: a zero-document run
    # is a failure, not an agreement (a zero denominator wearing a pass).
    if ! PYTHONPATH="$root" python - "$capture" <<'ZERODOC'
import json, sys
try:
    doc = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    # A document the strict door should refuse is a legitimate compare case
    # (both engines must refuse it identically), so it is not "zero document".
    sys.exit(0)
if not isinstance(doc, dict):
    sys.exit(0)
units = ("components", "functions", "services", "effects", "protocols", "protocol_functions")
sys.exit(0 if any(isinstance(doc.get(k), list) and doc.get(k) for k in units) else 1)
ZERODOC
    then
      echo "own-check: --engine compare: the captured OwnIR contains nothing to analyse — a compare over zero documents proves nothing and is a failure, not an agreement." >&2
      exit 5
    fi

    py_in="$cmp_dir/python-input.json"
    rs_in="$cmp_dir/rust-input.json"
    cp "$capture" "$py_in"
    cp "$capture" "$rs_in"
    py_in_sha="$(own_sha256 "$py_in")"
    rs_in_sha="$(own_sha256 "$rs_in")"
    if [[ "$py_in_sha" != "$capture_sha" || "$rs_in_sha" != "$capture_sha" ]]; then
      echo "own-check: --engine compare: the two engine inputs are not byte-identical to the single capture (capture $capture_sha, python $py_in_sha, rust $rs_in_sha) — the same-input invariant failed, so no comparison may be reported." >&2
      exit 5
    fi

    set +e
    PYTHONPATH="$root" python -m ownlang ownir "$py_in" --format "$format" --severity "$severity" \
      >"$cmp_dir/python.out" 2>"$cmp_dir/python.err"
    py_rc=$?
    "$rust_core" ownir "$rs_in" --format "$format" --severity "$severity" \
      >"$cmp_dir/rust.out" 2>"$cmp_dir/rust.err"
    rs_rc=$?
    set -e

    # D4.1 (c): either engine failing to produce a verdict is an EXECUTION
    # failure — checked before divergence, because two results are only
    # comparable once both exist. No engine's answer substitutes for the
    # other's failure.
    # A candidate that never started is a configuration error, not a compare
    # execution failure: the compare did not happen.
    if [[ "$rs_rc" -eq 126 || "$rs_rc" -eq 127 ]]; then
      echo "own-check: the candidate \`own-cli\` binary could not be started: '$rust_core' (exit $rs_rc). Set OWEN_RUST_CORE to a runnable \`own-cli\` executable. Owen did not fall back to Python." >&2
      exit 2
    fi

    py_legal=0; rs_legal=0
    [[ "$py_rc" -eq 0 || "$py_rc" -eq 1 || "$py_rc" -eq 2 ]] && py_legal=1
    [[ "$rs_rc" -eq 0 || "$rs_rc" -eq 1 || "$rs_rc" -eq 2 ]] && rs_legal=1
    if [[ "$py_legal" -eq 0 || "$rs_legal" -eq 0 ]]; then
      echo "own-check: --engine compare: compare execution failure (python exit $py_rc, rust exit $rs_rc). No engine's result was substituted for the other's failure." >&2
      [[ "$rs_legal" -eq 0 ]] && echo "own-check: raw Rust child status: $rs_rc" >&2
      echo "own-check: reproduction — input sha256 $capture_sha, candidate $rust_core" >&2
      cat "$cmp_dir/python.err" >&2 || true
      cat "$cmp_dir/rust.err" >&2 || true
      exit 5
    fi

    # D4.1 (a)/(b): agreement or divergence, on BYTES and the exit code.
    diverged=""
    [[ "$py_rc" -ne "$rs_rc" ]] && diverged="exit ($py_rc vs $rs_rc)"
    cmp -s "$cmp_dir/python.out" "$cmp_dir/rust.out" || diverged="${diverged:+$diverged, }stdout"
    cmp -s "$cmp_dir/python.err" "$cmp_dir/rust.err" || diverged="${diverged:+$diverged, }stderr"
    if [[ -n "$diverged" ]]; then
      echo "own-check: --engine compare: engine divergence — the reference and the candidate disagree on $diverged. Neither verdict is exposed as authoritative." >&2
      echo "own-check: reproduction — input sha256 $capture_sha, candidate $rust_core, artifacts in $cmp_dir" >&2
      diff <(cat "$cmp_dir/python.out") <(cat "$cmp_dir/rust.out") >&2 || true
      diff <(cat "$cmp_dir/python.err") <(cat "$cmp_dir/rust.err") >&2 || true
      # Keep the artifacts for reproduction rather than deleting them on exit.
      trap 'rm -f "$facts"' EXIT
      exit 5
    fi

    # Agreement: the externally observed result is the Python/reference one.
    cat "$cmp_dir/python.out"
    cat "$cmp_dir/python.err" >&2
    rc=$py_rc
    ;;
esac

# rc: 0 = clean, 1 = findings, >=2 = a hard error (bad facts / drifted contract).
if [[ "$fail_on_finding" -eq 1 ]]; then
  exit "$rc"
fi
if [[ "$rc" -ge 2 ]]; then
  exit "$rc"
fi
exit 0
