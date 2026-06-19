#!/usr/bin/env bash
#
# mine.sh — clone a public C# repo (shallow) and run own-check over it, writing a
# structured Markdown report. Evaluation tooling for the analyser itself: see
# docs/notes/mining.md. Mine ONE repo at a time — shallow, read-only; this is a
# spot-check, not a crawler. Be a good citizen.
#
# Usage:
#   scripts/mine.sh [--ref <branch|tag|sha>] [--paths <subdir>] [--format sarif|human]
#                   [--out <dir>] [--keep-src] <owner/repo | git-url>
#
# Output goes to corpus/mined/<slug>/ (gitignored): findings.txt, extract.log,
# report.md, report.json (and src/ with --keep-src).
#
# Requires: git, a .NET SDK (dotnet), Python 3.11+.

set -euo pipefail

ref=""
subpaths=""
# SARIF by default: mine_report.py reads it structurally (no regex, no parser
# drift — the class of bug that silently dropped findings on the ScreenToGif run).
# findings.txt then holds a SARIF log; the human view is report.md. `--format human`
# still works (mine_report sniffs the format).
format="sarif"
outdir=""
keep_src=0
target=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)    [[ $# -ge 2 ]] || { echo "mine: --ref needs a value" >&2; exit 2; }; ref="$2"; shift 2 ;;
    --paths)  [[ $# -ge 2 ]] || { echo "mine: --paths needs a value" >&2; exit 2; }; subpaths="$2"; shift 2 ;;
    --format) [[ $# -ge 2 ]] || { echo "mine: --format needs a value" >&2; exit 2; }; format="$2"; shift 2 ;;
    --out)    [[ $# -ge 2 ]] || { echo "mine: --out needs a value" >&2; exit 2; }; outdir="$2"; shift 2 ;;
    --keep-src) keep_src=1; shift ;;
    -h|--help)  sed -n '2,19p' "$0"; exit 0 ;;
    --) shift; [[ $# -gt 0 ]] && { target="$1"; shift; } ;;
    *)  target="$1"; shift ;;
  esac
done

[[ -n "$target" ]] || { echo "mine: a target (owner/repo or git URL) is required" >&2; exit 2; }
command -v git    >/dev/null || { echo "mine: git not found" >&2; exit 2; }
command -v python >/dev/null || { echo "mine: python not found" >&2; exit 2; }
if ! command -v dotnet >/dev/null; then
  echo "mine: a .NET SDK (dotnet) is required to run the extractor." >&2
  echo "mine: run this in CI via .github/workflows/mine.yml, or install the SDK." >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# owner/repo -> https URL; pass full git URLs through untouched.
case "$target" in
  http://*|https://*|git@*) url="$target" ;;
  *) url="https://github.com/${target}.git" ;;
esac
slug="$(printf '%s' "$target" | sed -E 's#^https?://[^/]+/##; s#^git@[^:]+:##; s#\.git$##; s#[^A-Za-z0-9._-]#_#g')"
[[ -n "$outdir" ]] || outdir="$root/corpus/mined/$slug"

mkdir -p "$outdir"
src="$outdir/src"
rm -rf "$src"

echo "mine: $target  ->  $outdir" >&2
clone_args=(--quiet --depth 1)
[[ -n "$ref" ]] && clone_args+=(--branch "$ref")
git clone "${clone_args[@]}" "$url" "$src"
commit="$(git -C "$src" rev-parse HEAD)"

scan="$src"
[[ -n "$subpaths" ]] && scan="$src/$subpaths"
[[ -e "$scan" ]] || { echo "mine: scan path '$scan' does not exist in the repo" >&2; exit 2; }

echo "mine: scanning $scan (commit $commit)" >&2
# own-check sends host-parseable findings to stdout and dotnet/build chatter to
# stderr; keep them apart. Without --fail-on-finding it exits 0 even with leaks;
# rc>=2 is a hard error (bad facts) — note it but still report what we captured.
set +e
"$root/scripts/own-check.sh" --root "$root" --format "$format" --stats -- "$scan" \
  >"$outdir/findings.txt" 2>"$outdir/extract.log"
rc=$?
set -e
# --stats writes a one-line flow-locals coverage summary to the extractor's stderr
# (captured in extract.log); surface it in the report so a clean run reads as
# "analysed N, skipped M" rather than an ambiguous zero.
cov="$(grep -m1 '^coverage:' "$outdir/extract.log" 2>/dev/null || true)"
[[ "$rc" -ge 2 ]] && echo "mine: own-check hard error (rc=$rc); see $outdir/extract.log" >&2

python "$root/scripts/mine_report.py" "$outdir/findings.txt" \
  --repo "$target" --commit "$commit" --json "$outdir/report.json" \
  --coverage "$cov" >"$outdir/report.md"

[[ "$keep_src" -eq 1 ]] || rm -rf "$src"

echo "mine: done -> $outdir/report.md" >&2
grep -E '^- findings:' "$outdir/report.md" || true
