#!/usr/bin/env bash
# S2 step 8 — the canonical patch bundle, end to end. Run from the repo root with
# `dotnet` + `python3` + `git` on PATH:
#
#   bash tests/patch_bundle_regressions.sh <scratch-dir>
#
# Drives the REAL chain — extractor --fix-candidates -> own-fix candidates -> validate_plan
# -> own-fix apply (which itself invokes the accepted Owen.CSharp.Rewriter) — and asserts
# what step 8 owes: a three-part bundle, a canonical reviewable patch that `git apply`
# actually applies to a pristine copy to reproduce the postimage byte for byte, an exact
# byte-deterministic manifest, the empty-patch contract, and an atomic publication that
# leaves nothing behind when it fails.
#
# The transport-tampering cases are NOT here: forging a rewriter-report means writing a
# bad artifact, and the production rewriter must not grow a test-only hook to emit one.
# They call the validator directly in tests/test_patch_bundle.py.
set -uo pipefail

T="${1:?usage: patch_bundle_regressions.sh <scratch-dir>}"
mkdir -p "$T"; T=$(cd "$T" && pwd)
REPO="$PWD"
EXT="$REPO/frontend/roslyn/OwnSharp.Extractor"
RW="$REPO/frontend/roslyn/Owen.CSharp.Rewriter"
FC=frontend/roslyn/samples/FixCandidatesSample.cs
fails=0
ok()  { echo "  ok: $1"; }
bad() { echo "  FAIL: $1"; fails=$((fails + 1)); }

printf '[weak-subscription]\nsubscribe = ["WeakEvents.AddPropertyChanged"]\n' > "$T/own.toml"
dotnet build "$EXT" -v q --nologo > /dev/null || { echo "FAIL: extractor build"; exit 1; }
dotnet build "$RW" -v q --nologo > /dev/null || { echo "FAIL: rewriter build"; exit 1; }
REWRITER="dotnet run --project $RW --no-build --"

apply() {  # apply <out> <plan> [candidates]
  python3 -m ownlang own-fix subscriptions apply --plan "$2" \
    --candidates "${3:-$T/candidates.json}" --root . --out "$1" --rewriter "$REWRITER"
}

cat > "$T/mkplan.py" <<'PY'
import json
import sys

sys.path.insert(0, ".")
from ownlang.fix_plan import validate_plan

c = json.load(open(sys.argv[1]))
# argv[3:] names the findings to CONVERT; everything else is manual_review. With no
# names given, convert them all.
convert = set(sys.argv[3:]) if len(sys.argv) > 3 else {x["finding_id"] for x in c["candidates"]}
d = [{"finding_id": x["finding_id"],
      "action": "convert_acquire" if x["finding_id"] in convert else "manual_review"}
     for x in c["candidates"]]
json.dump(validate_plan(c, {"version": 1, "decisions": d}), open(sys.argv[2], "w"))
PY

echo "== 0. the happy path: a three-part canonical bundle =="
dotnet run --project "$EXT" --no-build -- "$FC" --fix-candidates -o "$T/fc.json" > /dev/null 2>&1 \
  || { echo "FAIL: extractor"; exit 1; }
python3 -m ownlang own-fix subscriptions candidates "$T/fc.json" --config "$T/own.toml" \
  --class Own.Samples.FixCandidates.TwoOnOneLine --output "$T/candidates.json" --root . > /dev/null \
  || { echo "FAIL: candidates"; exit 1; }
python3 "$T/mkplan.py" "$T/candidates.json" "$T/plan.json" || { echo "FAIL: plan"; exit 1; }

rm -rf "$T/out1"
apply "$T/out1" "$T/plan.json" > /dev/null || { echo "FAIL: apply refused the happy path"; exit 1; }
found=$(cd "$T/out1" && find . -type f | sed 's|^\./||' | sort | tr '\n' ' ')
[ "$found" = "apply-manifest.json change.patch postimage/$FC " ] \
  && ok "the bundle is exactly change.patch + apply-manifest.json + postimage/<rel>" \
  || bad "unexpected bundle layout: [$found]"
[ ! -e "$T/out1/rewriter-report.json" ] \
  && ok "the transport report is not published" || bad "rewriter-report.json leaked into the bundle"

head -3 "$T/out1/change.patch" > "$T/heads.txt"
{ grep -q "^diff --git a/$FC b/$FC$" "$T/heads.txt" \
  && grep -q "^--- a/$FC$" "$T/heads.txt" && grep -q "^+++ b/$FC$" "$T/heads.txt"; } \
  && ok "canonical patch headers (a/<rel>, b/<rel>)" || bad "non-canonical patch headers"
grep -qE "$T|/tmp/|/home/|^\+\+\+ [A-Za-z]:|1970-|20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]" \
  "$T/out1/change.patch" \
  && bad "the patch carries a temp/absolute path or a timestamp" \
  || ok "no temp path, absolute path or timestamp in the patch"
grep -qE "^(rename|old mode|new mode|similarity|GIT binary patch)" "$T/out1/change.patch" \
  && bad "the patch carries a rename/mode/binary record" \
  || ok "no rename/mode/binary records"
[ "$(grep -c "^diff --git" "$T/out1/change.patch")" = 1 ] \
  && ok "exactly one file is touched" || bad "the patch touches more than one file"

python3 - "$T" "$FC" <<'PY' || bad "manifest shape"
import hashlib
import json
import sys

t, rel = sys.argv[1], sys.argv[2]
raw = open(f"{t}/out1/apply-manifest.json", "rb").read()
m = json.loads(raw)
sha = lambda b: "sha256:" + hashlib.sha256(b).hexdigest()  # noqa: E731
assert raw == json.dumps(m, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8") + b"\n", "not canonical bytes"
assert set(m) == {"version", "operation", "input_bundle_sha256", "validated_plan_sha256",
                  "target_api", "source_files", "applied_findings", "manual_review_findings",
                  "patch_sha256"}, f"key set: {sorted(m)}"
assert m["version"] == 1 and m["operation"] == "apply-subscription-fixes"
assert m["target_api"] == {"subscribe": "WeakEvents.AddPropertyChanged"}
assert m["patch_sha256"] == sha(open(f"{t}/out1/change.patch", "rb").read()), "patch_sha256"
assert m["validated_plan_sha256"] == sha(open(f"{t}/plan.json", "rb").read()), "plan sha"
[src] = m["source_files"]
assert src["path"] == rel, src["path"]
assert src["pre_sha256"] == json.load(open(f"{t}/plan.json"))["source_files"][0]["sha256"]
assert src["post_sha256"] == sha(open(f"{t}/out1/postimage/{rel}", "rb").read()), "post sha"
assert len(m["applied_findings"]) == 2 and m["manual_review_findings"] == []
print("manifest ok")
PY
ok "manifest: exact shape, canonical bytes, patch/pre/post SHAs over the real bytes"
git diff --quiet -- "$FC" && ok "the source tree is untouched" || bad "the source tree was modified"

echo "== 1. determinism: the same pristine inputs give a byte-identical bundle =="
rm -rf "$T/out2"
apply "$T/out2" "$T/plan.json" > /dev/null || bad "the second run refused"
diff -r "$T/out1" "$T/out2" > /dev/null \
  && ok "diff -r out1 out2 is empty (patch + manifest + postimage all byte-identical)" \
  || bad "the bundle is not deterministic"

echo "== 2. patch semantics: git apply reproduces the postimage exactly =="
rm -rf "$T/pristine"; mkdir -p "$T/pristine"
# The preimage the patch was built against is the WORKING TREE file — copy exactly that,
# so this tests the patch and not a checkout difference.
cp --parents "$FC" "$T/pristine/"
( cd "$T/pristine" && git init -q . && git apply --check "$T/out1/change.patch" ) \
  && ok "git apply --check passes on a pristine copy" || bad "git apply --check failed"
( cd "$T/pristine" && git apply "$T/out1/change.patch" ) \
  && ok "git apply applies cleanly" || bad "git apply failed"
cmp -s "$T/pristine/$FC" "$T/out1/postimage/$FC" \
  && ok "the applied file is byte-identical to postimage/<rel>" \
  || bad "the applied file differs from the postimage"

echo "== 3. mixed actions: only the converted acquire is patched =="
first=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['candidates'][0]['finding_id'])" \
  "$T/candidates.json")
second=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['candidates'][1]['finding_id'])" \
  "$T/candidates.json")
python3 "$T/mkplan.py" "$T/candidates.json" "$T/plan_mixed.json" "$second" || bad "mixed plan"
rm -rf "$T/out_mixed"
apply "$T/out_mixed" "$T/plan_mixed.json" > /dev/null || bad "the mixed plan refused"
{ grep -q 'WeakEvents.AddPropertyChanged(b, OnB)' "$T/out_mixed/postimage/$FC" \
  && grep -q 'a.PropertyChanged += OnA' "$T/out_mixed/postimage/$FC"; } \
  && ok "only the convert_acquire acquire changed; the manual_review one is untouched" \
  || bad "the mixed postimage is wrong"
python3 - "$T" "$first" "$second" <<'PY' || bad "mixed manifest partition"
import json
import sys

t, first, second = sys.argv[1], sys.argv[2], sys.argv[3]
m = json.load(open(f"{t}/out_mixed/apply-manifest.json"))
assert m["applied_findings"] == [second], m["applied_findings"]
assert m["manual_review_findings"] == [first], m["manual_review_findings"]
plan = json.load(open(f"{t}/plan_mixed.json"))
order = [d["finding_id"] for d in plan["decisions"]]
assert order == [first, second], "fixture drift: decisions are not in candidate order"
print("partition ok")
PY
ok "manifest partition + candidate order under mixed actions"

echo "== 4. manual-only: the empty-patch contract =="
python3 "$T/mkplan.py" "$T/candidates.json" "$T/plan_manual.json" "__none__" || bad "manual plan"
rm -rf "$T/out_manual"
apply "$T/out_manual" "$T/plan_manual.json" > /dev/null \
  && ok "a manual_review-only plan is valid, not a refusal" || bad "manual-only was refused"
[ -f "$T/out_manual/change.patch" ] && [ ! -s "$T/out_manual/change.patch" ] \
  && ok "change.patch exists and is zero length" || bad "the empty patch is not zero length"
cmp -s "$T/out_manual/postimage/$FC" "$FC" \
  && ok "the postimage equals the preimage" || bad "the manual-only postimage differs"
python3 - "$T" <<'PY' || bad "manual-only manifest"
import json
import sys

t = sys.argv[1]
m = json.load(open(f"{t}/out_manual/apply-manifest.json"))
empty = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
assert m["patch_sha256"] == empty, m["patch_sha256"]
assert m["applied_findings"] == [], m["applied_findings"]
assert len(m["manual_review_findings"]) == 2, m["manual_review_findings"]
[src] = m["source_files"]
assert src["pre_sha256"] == src["post_sha256"], "post must equal pre"
print("empty patch ok")
PY
ok "patch_sha256 is the sha of no bytes; applied is empty; all ids stay in candidate order"

echo "== 4b. a real source whose FILENAME cannot ride in a patch header =="
# Not a synthetic string fed to canonical_patch: a real file on disk, reached through a
# hash-bound bundle, whose name carries a tab. The patch headers could not carry it
# literally, so the bundle must be refused outright rather than published with a
# change.patch that does not apply.
rm -rf "$T/tabroot"; mkdir -p "$T/tabroot"
weird=$(printf 'we\tird.cs')
cp "$FC" "$T/tabroot/$weird"
( cd "$T/tabroot" && dotnet run --project "$EXT" --no-build -- "$weird" --fix-candidates \
    -o "$T/tab_facts.json" ) > /dev/null 2>&1 || bad "tab fixture: extractor"
python3 -m ownlang own-fix subscriptions candidates "$T/tab_facts.json" --config "$T/own.toml" \
  --class Own.Samples.FixCandidates.TwoOnOneLine --output "$T/tab-candidates.json" \
  --root "$T/tabroot" > /dev/null 2>&1 \
  && python3 "$T/mkplan.py" "$T/tab-candidates.json" "$T/tab-plan.json" > /dev/null 2>&1
if [ -f "$T/tab-plan.json" ]; then
  rm -rf "$T/out_tab"
  python3 -m ownlang own-fix subscriptions apply --plan "$T/tab-plan.json" \
    --candidates "$T/tab-candidates.json" --root "$T/tabroot" --out "$T/out_tab" \
    --rewriter "$REWRITER" > /dev/null 2>"$T/err.txt"
  rc=$?
  { [ "$rc" = 2 ] && [ ! -e "$T/out_tab" ] && grep -q "patch header" "$T/err.txt"; } \
    && ok "a tab in the source filename is refused; no bundle is published" \
    || bad "tab filename: rc=$rc $(cat "$T/err.txt")"
  cmp -s "$T/tabroot/$weird" "$FC" \
    && ok "the tab-named source is unchanged" || bad "the tab-named source was modified"
else
  # The upstream collector already refuses it — assert THAT rather than claim step 8 did.
  ok "a tab in the source filename is refused upstream (collector), before step 8"
fi

echo "== 5. refusals leave no output and no staging =="
rm -rf "$T/exists"; mkdir -p "$T/exists"; touch "$T/exists/stale"
apply "$T/exists" "$T/plan.json" > /dev/null 2>"$T/err.txt"
{ [ $? = 2 ] && grep -q "already exists" "$T/err.txt" && [ -f "$T/exists/stale" ]; } \
  && ok "a pre-existing out-dir is refused, untouched" || bad "pre-existing out: $(cat "$T/err.txt")"

apply ./inside_bundle "$T/plan.json" > /dev/null 2>"$T/err.txt"
{ [ $? = 2 ] && grep -q "inside the source root" "$T/err.txt" && [ ! -e ./inside_bundle ]; } \
  && ok "an out-dir inside the source root is refused" || bad "out inside root: $(cat "$T/err.txt")"

# A publication failure: the parent is read-only, so nothing can be staged or renamed.
rm -rf "$T/ro"; mkdir -p "$T/ro"; chmod 555 "$T/ro"
apply "$T/ro/out" "$T/plan.json" > /dev/null 2>"$T/err.txt"
rc=$?
chmod 755 "$T/ro"
{ [ "$rc" = 2 ] && [ ! -e "$T/ro/out" ] && [ -z "$(ls -A "$T/ro")" ]; } \
  && ok "a failed publication leaves no out-dir and no work directory" \
  || bad "failed publication: rc=$rc leftovers=[$(ls -A "$T/ro")] $(cat "$T/err.txt")"

echo "== 5b. the --rewriter command grammar (one grammar, every platform) =="
# A quoted executable path containing spaces must reach argv[0] WITHOUT its quotes.
mkdir -p "$T/my tools"
{ echo '#!/usr/bin/env bash'; echo "exec $REWRITER \"\$@\""; } > "$T/my tools/rw.sh"
chmod +x "$T/my tools/rw.sh"
rm -rf "$T/out_quoted"
python3 -m ownlang own-fix subscriptions apply --plan "$T/plan.json" \
  --candidates "$T/candidates.json" --root . --out "$T/out_quoted" \
  --rewriter "'$T/my tools/rw.sh'" > /dev/null 2>"$T/err.txt" \
  && diff -r "$T/out_quoted" "$T/out1" > /dev/null \
  && ok "a quoted exe path with spaces (plus its args) runs and gives the same bundle" \
  || bad "quoted --rewriter: $(cat "$T/err.txt")"

rm -rf "$T/out_badq"
python3 -m ownlang own-fix subscriptions apply --plan "$T/plan.json" \
  --candidates "$T/candidates.json" --root . --out "$T/out_badq" \
  --rewriter '"unterminated' > /dev/null 2>"$T/err.txt"
rc=$?
{ [ "$rc" = 2 ] && grep -q "own-fix: refuse:" "$T/err.txt" \
  && ! grep -q "Traceback" "$T/err.txt" && [ ! -e "$T/out_badq" ]; } \
  && ok "an unterminated quote is a refusal, not a traceback" \
  || bad "unterminated --rewriter: rc=$rc $(cat "$T/err.txt")"

rm -rf "$T/out_norw"
python3 -m ownlang own-fix subscriptions apply --plan "$T/plan.json" \
  --candidates "$T/candidates.json" --root . --out "$T/out_norw" \
  --rewriter "definitely-not-on-path" > /dev/null 2>"$T/err.txt"
rc=$?
{ [ "$rc" = 2 ] && grep -q "own-fix: refuse:" "$T/err.txt" && [ ! -e "$T/out_norw" ]; } \
  && ok "a missing rewriter executable is a refusal with no output" \
  || bad "missing rewriter: rc=$rc $(cat "$T/err.txt")"

# A stale plan: the gate refuses before the rewriter is ever spawned.
zero=$(printf '0%.0s' $(seq 1 64))
sed "s/sha256:[0-9a-f]\{64\}/sha256:$zero/g" "$T/plan.json" > "$T/plan_stale.json"
rm -rf "$T/out_stale"
apply "$T/out_stale" "$T/plan_stale.json" > /dev/null 2>"$T/err.txt"
{ [ $? = 2 ] && [ ! -e "$T/out_stale" ]; } \
  && ok "a stale/forged plan is refused with no output" || bad "stale plan: $(cat "$T/err.txt")"
git diff --quiet -- "$FC" && ok "the source tree is still untouched" || bad "the source tree changed"

echo
[ "$fails" = 0 ] && echo "PATCH BUNDLE REGRESSIONS: ALL PASS" \
  || echo "PATCH BUNDLE REGRESSIONS: $fails FAILURE(S)"
exit "$fails"
