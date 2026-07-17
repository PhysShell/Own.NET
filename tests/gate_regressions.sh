#!/usr/bin/env bash
# S2 step 9 — the structural self-gate, end to end. Run from the repo root with
# `dotnet` + `python3` + `git` on PATH:
#
#   bash tests/gate_regressions.sh <scratch-dir>
#
# Builds a REAL step 8 bundle (extractor -> candidates -> validate_plan -> apply, which
# runs the accepted Owen.CSharp.Rewriter), then gates it. Covers the filesystem-real and
# git-real cases; the pure-function + byte-tampering cases are in tests/test_gate_patch.py.
#
# Every forged fixture rebinds the upstream bindings it would otherwise trip first, so the
# refusal comes from the branch under test — a test that refuses for the wrong reason is
# not a test.
set -uo pipefail

T="${1:?usage: gate_regressions.sh <scratch-dir>}"
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

cat > "$T/mkplan.py" <<'PY'
import json
import sys

sys.path.insert(0, ".")
from ownlang.fix_plan import validate_plan

c = json.load(open(sys.argv[1]))
conv = set(sys.argv[3:]) if len(sys.argv) > 3 else {x["finding_id"] for x in c["candidates"]}
d = [{"finding_id": x["finding_id"],
      "action": "convert_acquire" if x["finding_id"] in conv else "manual_review"}
     for x in c["candidates"]]
json.dump(validate_plan(c, {"version": 1, "decisions": d}), open(sys.argv[2], "w"))
PY

# A helper to rebind a bundle's manifest after forging patch/postimage bytes, so a fixture
# reaches the git gates instead of dying at the hash gate.
cat > "$T/rebind.py" <<'PY'
import hashlib
import json
import sys


def sha(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()


bundle, rel = sys.argv[1], sys.argv[2]
m = json.load(open(f"{bundle}/apply-manifest.json"))
m["patch_sha256"] = sha(open(f"{bundle}/change.patch", "rb").read())
m["source_files"][0]["post_sha256"] = sha(open(f"{bundle}/postimage/{rel}", "rb").read())
blob = json.dumps(m, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
open(f"{bundle}/apply-manifest.json", "wb").write(blob)
PY

gate() {  # gate <out> <bundle> [plan] [candidates] [root]
  python3 -m ownlang own-fix subscriptions gate --bundle "$2" \
    --plan "${3:-$T/plan.json}" --candidates "${4:-$T/candidates.json}" \
    --root "${5:-.}" --out "$1" > /dev/null 2>"$T/err.txt"
}
refuse() {  # refuse <name> <out> <bundle> <category> [plan] [candidates] [root]
  rm -rf "$2"
  gate "$2" "$3" "${5:-$T/plan.json}" "${6:-$T/candidates.json}" "${7:-.}"
  local rc=$?
  [ "$rc" = 2 ] || { bad "$1: expected exit 2, got $rc"; return; }
  [ ! -e "$2" ] || { bad "$1: a refused run left an out-dir"; return; }
  grep -q "own-fix: refuse: $4:" "$T/err.txt" \
    || { bad "$1: wrong category: $(cat "$T/err.txt")"; return; }
  ok "$1 -> $4"
}

echo "== build the real step 8 bundle =="
dotnet run --project "$EXT" --no-build -- "$FC" --fix-candidates -o "$T/fc.json" > /dev/null 2>&1 \
  || { echo "FAIL: extractor"; exit 1; }
python3 -m ownlang own-fix subscriptions candidates "$T/fc.json" --config "$T/own.toml" \
  --class Own.Samples.FixCandidates.TwoOnOneLine --output "$T/candidates.json" --root . > /dev/null \
  || { echo "FAIL: candidates"; exit 1; }
python3 "$T/mkplan.py" "$T/candidates.json" "$T/plan.json" || { echo "FAIL: plan"; exit 1; }
rm -rf "$T/bundle"
python3 -m ownlang own-fix subscriptions apply --plan "$T/plan.json" \
  --candidates "$T/candidates.json" --root . --out "$T/bundle" --rewriter "$REWRITER" > /dev/null \
  || { echo "FAIL: apply"; exit 1; }

echo "== 0. happy path =="
rm -rf "$T/g0"
gate "$T/g0" "$T/bundle" && ok "the gate passes a valid bundle" || bad "gate: $(cat "$T/err.txt")"
python3 - "$T/g0/gate-result.json" "$FC" <<'PY' || bad "evidence shape"
import json
import sys

m = json.load(open(sys.argv[1]))
raw = open(sys.argv[1], "rb").read()
assert raw == json.dumps(m, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode() + b"\n", "not canonical bytes"
assert m["operation"] == "gate-subscription-fix-bundle"
assert set(m["gates"].values()) == {"pass"}, m["gates"]
assert set(m["gates"]) == {"bundle_layout", "manifest_shape", "authority_binding",
                           "artifact_hashes", "pristine_preimage", "patch_structure",
                           "git_apply_check", "git_apply", "postimage_equality",
                           "isolated_tree"}, sorted(m["gates"])
assert m["source_files"][0]["path"] == sys.argv[2]
for banned in ("1970", "/tmp", "/home", "runner", "owen-gate"):
    assert banned not in raw.decode(), banned
print("evidence ok")
PY
ok "evidence: exact shape, canonical bytes, all gates pass, no host/temp/timestamp"
git diff --quiet -- "$FC" && ok "source tree untouched" || bad "source tree modified"

echo "== 1. determinism =="
rm -rf "$T/g0b"
gate "$T/g0b" "$T/bundle"
diff -r "$T/g0" "$T/g0b" > /dev/null && ok "two runs give byte-identical evidence" \
  || bad "evidence is not deterministic"

echo "== 2. manual-only: empty patch, git not_applicable =="
python3 "$T/mkplan.py" "$T/candidates.json" "$T/plan_m.json" __none__
rm -rf "$T/bundle_m"
python3 -m ownlang own-fix subscriptions apply --plan "$T/plan_m.json" \
  --candidates "$T/candidates.json" --root . --out "$T/bundle_m" --rewriter "$REWRITER" > /dev/null \
  || bad "manual-only apply"
[ -f "$T/bundle_m/change.patch" ] && [ ! -s "$T/bundle_m/change.patch" ] \
  && ok "the step 8 patch is zero length" || bad "manual-only patch is not empty"
rm -rf "$T/gm"
gate "$T/gm" "$T/bundle_m" "$T/plan_m.json" && ok "the gate passes a manual-only bundle" \
  || bad "manual-only gate: $(cat "$T/err.txt")"
python3 - "$T/gm/gate-result.json" <<'PY' || bad "manual-only evidence"
import json
import sys

m = json.load(open(sys.argv[1]))
for g in ("git_apply_check", "git_apply", "isolated_tree"):
    assert m["gates"][g] == "not_applicable", (g, m["gates"][g])
for g in ("bundle_layout", "manifest_shape", "authority_binding", "artifact_hashes",
          "pristine_preimage", "patch_structure", "postimage_equality"):
    assert m["gates"][g] == "pass", (g, m["gates"][g])
assert m["applied_findings"] == []
assert len(m["manual_review_findings"]) == 2
print("manual-only ok")
PY
ok "manual-only: git gates not_applicable, applied empty, all else pass"

echo "== 3. apply semantics (git is the independent applier) =="
# git apply --check must fail: forge a context line the source will not match, rebind.
cp -r "$T/bundle" "$T/bundle_ctx"
sed -i 's/     public sealed class TwoOnOneLine/     public sealed class SomethingElse/' \
  "$T/bundle_ctx/change.patch" 2>/dev/null || true
# ...rebind so the hash gate passes and git apply --check is what fires.
python3 "$T/rebind.py" "$T/bundle_ctx" "$FC"
refuse "structurally valid but git apply --check fails" "$T/g_ctx" "$T/bundle_ctx" APPLY_CHECK

# git apply succeeds but the result != postimage: forge the postimage, rebind post_sha.
cp -r "$T/bundle" "$T/bundle_pm"
printf '// forged\n' >> "$T/bundle_pm/postimage/$FC"
python3 "$T/rebind.py" "$T/bundle_pm" "$FC"
refuse "applied bytes != postimage" "$T/g_pm" "$T/bundle_pm" APPLY_MISMATCH

# a modified postimage WITHOUT rebinding is caught earlier, at the hash gate.
cp -r "$T/bundle" "$T/bundle_h"
printf '// forged\n' >> "$T/bundle_h/postimage/$FC"
refuse "modified postimage (no rebind)" "$T/g_h" "$T/bundle_h" HASH_MISMATCH

echo "== 4. bundle layout =="
cp -r "$T/bundle" "$T/bundle_extra"; touch "$T/bundle_extra/surprise.txt"
refuse "an extra file in the bundle" "$T/g_extra" "$T/bundle_extra" BUNDLE_LAYOUT
cp -r "$T/bundle" "$T/bundle_sym"; rm "$T/bundle_sym/change.patch"
ln -s /etc/hostname "$T/bundle_sym/change.patch"
refuse "a symlink entry in the bundle" "$T/g_sym" "$T/bundle_sym" BUNDLE_LAYOUT
cp -r "$T/bundle" "$T/bundle_pi_extra"
touch "$T/bundle_pi_extra/postimage/frontend/roslyn/samples/Extra.cs"
refuse "an extra postimage file" "$T/g_pie" "$T/bundle_pi_extra" BUNDLE_LAYOUT
# An extra EMPTY directory (a file-set check alone would miss it).
cp -r "$T/bundle" "$T/bundle_ed"; mkdir -p "$T/bundle_ed/postimage/frontend/roslyn/samples/empty"
refuse "an extra empty directory" "$T/g_ed" "$T/bundle_ed" BUNDLE_LAYOUT
cp -r "$T/bundle" "$T/bundle_hd"; mkdir -p "$T/bundle_hd/postimage/.hidden"
refuse "a hidden empty directory" "$T/g_hd" "$T/bundle_hd" BUNDLE_LAYOUT
cp -r "$T/bundle" "$T/bundle_nd"; mkdir -p "$T/bundle_nd/postimage/a/b/c"
refuse "a nested empty directory" "$T/g_nd" "$T/bundle_nd" BUNDLE_LAYOUT
# A symlinked bundle ROOT (rejected by lstat before realpath).
ln -s "$T/bundle" "$T/bundle_link"
refuse "a symlinked bundle root" "$T/g_bl" "$T/bundle_link" BUNDLE_LAYOUT

echo "== 5. pristine source =="
zero=$(printf '0%.0s' $(seq 1 64))
# stale preimage: the manifest/plan say a pre_sha the real source no longer has. Rebind the
# candidates + plan + manifest so ONLY the pristine compare can refuse.
python3 - "$T" "$FC" "$zero" <<'PY'
import hashlib
import json
import os
import sys

sys.path.insert(0, ".")
from ownlang.fix_plan import bundle_sha256

t, fc, zero = sys.argv[1], sys.argv[2], sys.argv[3]
stale = "sha256:" + zero
cand = json.load(open(f"{t}/candidates.json"))
cand["source_files"][0]["sha256"] = stale
json.dump(cand, open(f"{t}/cand_stale.json", "w"))
plan = json.load(open(f"{t}/plan.json"))
plan["source_files"][0]["sha256"] = stale
plan["input_bundle_sha256"] = bundle_sha256(cand)
json.dump(plan, open(f"{t}/plan_stale.json", "w"))
os.makedirs(f"{t}/bundle_stale/postimage/{os.path.dirname(fc)}", exist_ok=True)
for f in ("change.patch",):
    with open(f"{t}/bundle/{f}", "rb") as r, open(f"{t}/bundle_stale/{f}", "wb") as w:
        w.write(r.read())
with open(f"{t}/bundle/postimage/{fc}", "rb") as r, open(f"{t}/bundle_stale/postimage/{fc}", "wb") as w:
    w.write(r.read())
m = json.load(open(f"{t}/bundle/apply-manifest.json"))
m["input_bundle_sha256"] = bundle_sha256(cand)
plan_bytes = open(f"{t}/plan_stale.json", "rb").read()
m["validated_plan_sha256"] = "sha256:" + hashlib.sha256(plan_bytes).hexdigest()
m["source_files"][0]["pre_sha256"] = stale
blob = json.dumps(m, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"
open(f"{t}/bundle_stale/apply-manifest.json", "wb").write(blob)
PY
refuse "a stale preimage" "$T/g_stale" "$T/bundle_stale" PRISTINE_SOURCE \
  "$T/plan_stale.json" "$T/cand_stale.json" .

# a source reached through a symlinked directory that escapes the root.
rm -rf "$T/symroot"; mkdir -p "$T/symroot/outside"
cp -r "$REPO/frontend" "$T/symroot/outside/frontend"
ln -s outside/frontend "$T/symroot/frontend"
mkdir -p "$T/symroot/real"
refuse "source through a symlinked dir (escape)" "$T/g_symsrc" "$T/bundle" PRISTINE_SOURCE \
  "$T/plan.json" "$T/candidates.json" "$T/symroot/real"

echo "== 6. publication =="
rm -rf "$T/exists"; mkdir -p "$T/exists"; touch "$T/exists/stale"
gate "$T/exists" "$T/bundle"
{ [ $? = 2 ] && grep -q "PUBLICATION" "$T/err.txt" && [ -f "$T/exists/stale" ]; } \
  && ok "a pre-existing out is refused, untouched" || bad "pre-existing out: $(cat "$T/err.txt")"
gate "./gate_inside" "$T/bundle"
{ [ $? = 2 ] && grep -q "inside the source root" "$T/err.txt" && [ ! -e ./gate_inside ]; } \
  && ok "an out inside the source root is refused" || bad "out inside root: $(cat "$T/err.txt")"
rm -rf "$T/ro"; mkdir -p "$T/ro"; chmod 555 "$T/ro"
gate "$T/ro/out" "$T/bundle"; rc=$?; chmod 755 "$T/ro"
{ [ "$rc" = 2 ] && [ ! -e "$T/ro/out" ] && [ -z "$(ls -A "$T/ro")" ]; } \
  && ok "a failed publication leaves no out and no staging" \
  || bad "read-only parent: rc=$rc leftovers=[$(ls -A "$T/ro")]"

git diff --quiet -- "$FC" && ok "source tree still untouched after every refusal" \
  || bad "source tree was modified"

echo
[ "$fails" = 0 ] && echo "GATE REGRESSIONS: ALL PASS" || echo "GATE REGRESSIONS: $fails FAILURE(S)"
exit "$fails"
