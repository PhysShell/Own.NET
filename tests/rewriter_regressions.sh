#!/usr/bin/env bash
# owen-rewrite (S2) regressions. Run from the repo root with `dotnet` + `python3` on PATH:
#
#   bash tests/rewriter_regressions.sh <scratch-dir>
#
# Drives the REAL chain end to end — extractor --fix-candidates -> own-fix candidates ->
# validate_plan -> owen-rewrite — and asserts the rewriter's own guarantees, none of which
# may depend on the Python gate having run: input/hash/root validation, the strict UTF-8
# decoder, the target-API grammar, extractor-compatible identity normalization, and
# transactional (all-or-nothing) publication.
set -uo pipefail

T="${1:?usage: rewriter_regressions.sh <scratch-dir>}"
mkdir -p "$T"; T=$(cd "$T" && pwd)   # absolute: subshells cd into the variant roots
REPO="$PWD"
EXT="$REPO/frontend/roslyn/OwnSharp.Extractor"
RW="$REPO/frontend/roslyn/Owen.CSharp.Rewriter"
FC=frontend/roslyn/samples/FixCandidatesSample.cs
FR=frontend/roslyn/samples/FixRewriteSample.cs
fails=0
ok()  { echo "  ok: $1"; }
bad() { echo "  FAIL: $1"; fails=$((fails + 1)); }

printf '[weak-subscription]\nsubscribe = ["WeakEvents.AddPropertyChanged"]\n' > "$T/own.toml"
cat > "$T/mkplan.py" <<'PY'
import json
import sys

sys.path.insert(0, ".")
from ownlang.fix_plan import validate_plan

c = json.load(open(sys.argv[1]))
d = [{"finding_id": x["finding_id"], "action": "convert_acquire"} for x in c["candidates"]]
json.dump(validate_plan(c, {"version": 1, "decisions": d}), open(sys.argv[2], "w"))
PY

dotnet build "$EXT" -v q --nologo > /dev/null || { echo "FAIL: extractor build"; exit 1; }
dotnet build "$RW" -v q --nologo > /dev/null || { echo "FAIL: rewriter build"; exit 1; }
ext() { dotnet run --project "$EXT" --no-build -- "$@"; }
rw()  { dotnet run --project "$RW"  --no-build -- "$@"; }

# candidates + a validated all-convert plan for <class> over <facts>, rooted at <root>.
plan_for() {  # plan_for <facts> <class> <root> <prefix>
  python3 -m ownlang own-fix subscriptions candidates "$1" --config "$T/own.toml" \
    --class "$2" --output "$4-candidates.json" --root "$3" > /dev/null \
    && python3 "$T/mkplan.py" "$4-candidates.json" "$4-plan.json"
}

echo "== 0. the happy path: both acquires convert, twice, byte-identically =="
ext "$FC" --fix-candidates -o "$T/fc.json" > /dev/null 2>&1 || { echo "FAIL: extractor"; exit 1; }
plan_for "$T/fc.json" Own.Samples.FixCandidates.TwoOnOneLine . "$T/fc" \
  || { echo "FAIL: candidates/plan"; exit 1; }
rw --plan "$T/fc-plan.json" --candidates "$T/fc-candidates.json" --root . --out "$T/out1" \
  || { echo "FAIL: owen-rewrite refused the happy path"; exit 1; }
post="$T/out1/postimage/$FC"
{ grep -q 'WeakEvents.AddPropertyChanged(a, OnA)' "$post" \
  && grep -q 'WeakEvents.AddPropertyChanged(b, OnB)' "$post"; } \
  && ok "both acquires converted to the weak wrapper" || bad "postimage missing the wrappers"
rw --plan "$T/fc-plan.json" --candidates "$T/fc-candidates.json" --root . --out "$T/out2" > /dev/null \
  && diff -r "$T/out1" "$T/out2" > /dev/null \
  && ok "a re-run is byte-identical (deterministic)" || bad "the rewriter is not deterministic"
git diff --quiet -- "$FC" && ok "the source tree is untouched" || bad "owen-rewrite modified the source tree"

echo "== 1. self-contained input / hash / root validation (no gate assumed) =="
python3 - "$T" <<'PY' || exit 1
import json
import sys

sys.path.insert(0, ".")
from ownlang.fix_plan import bundle_sha256

t = sys.argv[1]
c = json.load(open(f"{t}/fc-candidates.json"))
p = json.load(open(f"{t}/fc-plan.json"))
cp = lambda o: json.loads(json.dumps(o))  # noqa: E731
w = lambda n, o: json.dump(o, open(f"{t}/{n}.json", "w"))  # noqa: E731

x = cp(c); x["candidates"][0]["acquire_span"]["start"] += 1; w("c_tampered", x)
x = cp(p); x["decisions"] = x["decisions"][:1]; w("p_partial", x)
x = cp(p); x["decisions"][0]["action"] = "convert_teardown"; w("p_badaction", x)
x = cp(p); x["autofix_everything"] = True; w("p_extrakey", x)
x = cp(p); x["decisions"].reverse(); w("p_reordered", x)
x = cp(p); x["selection"]["constraints"]["allow_suppressions"] = True; w("p_suppress", x)
x = cp(p); x["decisions"] = "all of them"; w("p_malformed", x)
x = cp(p); del x["decisions"][0]["acquire_span"]; w("p_nospan", x)

# Path confinement must hold against an attacker who owns BOTH files: the bundle carries
# the escaping path and the plan is re-bound to it with a recomputed input_bundle_sha256,
# so every earlier check passes and only the rewriter's own confinement can refuse.
for name, path in (("escape", "../../../etc/passwd"), ("rooted", "/etc/passwd"),
                   ("backslash", "frontend\\roslyn\\samples\\FixCandidatesSample.cs"),
                   ("dotdot", "frontend/roslyn/../roslyn/samples/FixCandidatesSample.cs")):
    b = cp(c)
    b["source_files"][0]["path"] = path
    b["selection"]["allowed_types"][0]["file"] = path
    for cand in b["candidates"]:
        cand["file"] = path
    w(f"c_{name}", b)
    e = cp(p)
    e["input_bundle_sha256"] = bundle_sha256(b)
    e["source_files"][0]["path"] = path
    e["selection"]["allowed_types"][0]["file"] = path
    for dec in e["decisions"]:
        dec["file"] = path
    w(f"p_{name}", e)

for name, tgt in (("invoke", "WeakEvents.Add()"), ("generic", "WeakEvents.Add<Foo>"),
                  ("cond", "WeakEvents?.Add"), ("expr", "a + b"),
                  ("arg", "Weak.Add(evil, x)"), ("assign", "x = y"),
                  ("trailing", "Weak.Add; Evil()"), ("empty", "")):
    x = cp(p)
    x["target_api"]["subscribe"] = tgt
    w(f"t_{name}", x)
PY

refuse() {  # refuse <name> <plan> <cands> <expect> [root]
  local out="$T/r_${1// /_}"
  rm -rf "$out"
  dotnet run --project "$RW" --no-build -- --plan "$2" --candidates "$3" \
    --root "${5:-.}" --out "$out" > /dev/null 2>"$T/err.txt"
  local rc=$?
  [ "$rc" = 2 ] || { bad "$1: expected exit 2, got $rc"; return; }
  [ ! -e "$out" ] || { bad "$1: a refused run left an out-dir"; return; }
  grep -q "$4" "$T/err.txt" || { bad "$1: wrong refusal: $(cat "$T/err.txt")"; return; }
  ok "$1"
}

refuse "tampered candidates bundle" "$T/fc-plan.json"     "$T/c_tampered.json"   "does not bind these candidates"
refuse "partial decision set"       "$T/p_partial.json"   "$T/fc-candidates.json" "a decision is required for each"
refuse "action not allowed"         "$T/p_badaction.json" "$T/fc-candidates.json" "out-of-scope action"
refuse "unknown envelope key"       "$T/p_extrakey.json"  "$T/fc-candidates.json" "unexpected key set"
refuse "decisions out of order"     "$T/p_reordered.json" "$T/fc-candidates.json" "out of candidate order"
refuse "constraints relaxed"        "$T/p_suppress.json"  "$T/fc-candidates.json" "must be false"
refuse "malformed decisions"        "$T/p_malformed.json" "$T/fc-candidates.json" "must be an array"
refuse "missing acquire_span"       "$T/p_nospan.json"    "$T/fc-candidates.json" "unexpected key set"
refuse "source path escapes root"   "$T/p_escape.json"    "$T/c_escape.json"     "canonical root-relative"
refuse "absolute source path"       "$T/p_rooted.json"    "$T/c_rooted.json"     "canonical root-relative"
refuse "backslash source path"      "$T/p_backslash.json" "$T/c_backslash.json"  "canonical root-relative"
refuse "non-canonical .. inside"    "$T/p_dotdot.json"    "$T/c_dotdot.json"     "canonical root-relative"

echo "== 2. target API grammar, enforced BEFORE any replacement is built =="
for t in invoke generic cond expr arg assign trailing empty; do
  refuse "target: $t" "$T/t_$t.json" "$T/fc-candidates.json" "target_api.subscribe"
done

echo "== 3. out-dir confinement + transactional publication =="
rm -rf "$T/exists"; mkdir -p "$T/exists"; touch "$T/exists/stale-artifact"
rw --plan "$T/fc-plan.json" --candidates "$T/fc-candidates.json" --root . --out "$T/exists" \
  > /dev/null 2>"$T/err.txt"
{ [ $? = 2 ] && grep -q "already exists" "$T/err.txt" && [ -f "$T/exists/stale-artifact" ]; } \
  && ok "a pre-existing out-dir is refused, untouched" \
  || bad "pre-existing out-dir: $(cat "$T/err.txt")"

rw --plan "$T/fc-plan.json" --candidates "$T/fc-candidates.json" --root . --out ./inside_out \
  > /dev/null 2>"$T/err.txt"
{ [ $? = 2 ] && grep -q "inside the source root" "$T/err.txt" && [ ! -e ./inside_out ]; } \
  && ok "an out-dir inside the source root is refused" \
  || bad "out-dir inside root: $(cat "$T/err.txt")"

# A write failure during publication: the staging parent is read-only, so the bundle can
# never be published. Nothing may survive — no out-dir and no staging leftover.
rm -rf "$T/ro"; mkdir -p "$T/ro"; chmod 555 "$T/ro"
rw --plan "$T/fc-plan.json" --candidates "$T/fc-candidates.json" --root . --out "$T/ro/out" \
  > /dev/null 2>"$T/err.txt"
rc=$?
chmod 755 "$T/ro"
{ [ "$rc" = 2 ] && [ ! -e "$T/ro/out" ] && [ -z "$(ls -A "$T/ro")" ]; } \
  && ok "a failed publication leaves no out-dir and no staging dir" \
  || bad "failed publication: rc=$rc leftovers=[$(ls -A "$T/ro")] $(cat "$T/err.txt")"

echo "== 4. extractor-compatible normalization (handler / receiver / containing type) =="
ext "$FR" --fix-candidates -o "$T/fr.json" > /dev/null 2>&1 || { echo "FAIL: extractor"; exit 1; }
norm() {  # norm <class> <expected-substring>
  rm -rf "$T/n_out"
  plan_for "$T/fr.json" "$1" . "$T/fr" > /dev/null 2>&1 \
    || { bad "$1: candidates/plan"; return; }
  rw --plan "$T/fr-plan.json" --candidates "$T/fr-candidates.json" --root . --out "$T/n_out" \
    > /dev/null 2>"$T/err.txt" || { bad "$1: $(cat "$T/err.txt")"; return; }
  grep -qF "$2" "$T/n_out/postimage/$FR" && ok "$1 -> $2" \
    || { bad "$1: expected [$2], got: $(grep -n 'WeakEvents\|PropertyChanged +=' "$T/n_out/postimage/$FR")"; }
}
# `new PropertyChangedEventHandler(OnChanged)` must reach the wrapper NORMALIZED, the same
# delegate-creation peel the extractor's handler identity applies.
norm Own.Samples.FixRewrite.ExplicitDelegate    'WeakEvents.AddPropertyChanged(pub, OnChanged);'
norm Own.Samples.FixRewrite.ThisQualified       'WeakEvents.AddPropertyChanged(pub, this.OnChanged);'
# A generic containing type: the candidate says `...GenericHolder<T>`, so the rewriter's
# syntactic FQN must carry the type parameter list the same way SymbolDisplay prints it.
norm 'Own.Samples.FixRewrite.GenericHolder<T>'  'WeakEvents.AddPropertyChanged(pub, OnChanged);'
# A nested type is refused by S0's own MVP policy, so the rewriter is never handed one.
{ python3 -m ownlang own-fix subscriptions candidates "$T/fr.json" --config "$T/own.toml" \
    --class 'Own.Samples.FixRewrite.Outer<T>.Inner<U>' --output "$T/nested.json" --root . 2>&1 \
    || true; } | grep -q "nested; refused by MVP policy" \
  && ok "Outer<T>.Inner<U> -> refused upstream (S0 nested-type policy)" \
  || bad "nested generic: expected the S0 nested-type refusal"

echo "== 5. strict UTF-8: BOM / CRLF preserved, invalid bytes refused =="
# Each variant needs its OWN root: the SHA is checked before the decode, so to reach the
# decoder at all the candidates must have been built from the very bytes under test.
uvariant() {  # uvariant <name> <expected-rc> <expect>
  local name="$1" root="$T/u_$name" out="$T/uo_$name"
  rm -rf "$out"
  ( cd "$root" && dotnet run --project "$EXT" --no-build -- sample.cs --fix-candidates \
      -o "$T/u_facts.json" ) > /dev/null 2>&1 || { bad "$name: extractor"; return; }
  plan_for "$T/u_facts.json" Own.Samples.FixRewrite.ExplicitDelegate "$root" "$T/u" \
    > /dev/null 2>&1 || { bad "$name: candidates/plan"; return; }
  rw --plan "$T/u-plan.json" --candidates "$T/u-candidates.json" --root "$root" --out "$out" \
    > /dev/null 2>"$T/err.txt"
  local rc=$?
  [ "$rc" = "$2" ] || { bad "$name: expected exit $2, got $rc ($(cat "$T/err.txt"))"; return; }
  if [ "$2" = 2 ]; then
    { grep -q "$3" "$T/err.txt" && [ ! -e "$out" ]; } && ok "$name -> refused, nothing written" \
      || bad "$name: wrong refusal / out-dir left: $(cat "$T/err.txt")"
    return
  fi
  [ "$3" = "$(od -An -tx1 -N3 "$out/postimage/sample.cs" | tr -d ' ')" ] \
    && ok "$name -> postimage head is $3" \
    || bad "$name: head $(od -An -tx1 -N3 "$out/postimage/sample.cs" | tr -d ' ') != $3"
}
umk() { rm -rf "$T/u_$1"; mkdir -p "$T/u_$1"; cp "$FR" "$T/u_$1/sample.cs"; }

umk bom
printf '\xef\xbb\xbf' > "$T/u_bom/t" && cat "$T/u_bom/sample.cs" >> "$T/u_bom/t" \
  && mv "$T/u_bom/t" "$T/u_bom/sample.cs"
uvariant bom 0 efbbbf

umk bad
printf '// \xff\xfe invalid\n' >> "$T/u_bad/sample.cs"
uvariant bad 2 "not valid UTF-8"

umk crlf
sed -i 's/$/\r/' "$T/u_crlf/sample.cs"
pre=$(grep -c $'\r$' "$T/u_crlf/sample.cs")
uvariant crlf 0 "$(printf '// ' | od -An -tx1 -N3 | tr -d ' ')"
post_crlf=$(grep -c $'\r$' "$T/uo_crlf/postimage/sample.cs" 2>/dev/null || true)
lone=$(grep -cv $'\r$' "$T/uo_crlf/postimage/sample.cs" 2>/dev/null || true)
{ [ "$pre" = "$post_crlf" ] && [ "$lone" = 0 ]; } \
  && ok "crlf -> all $post_crlf CRLF endings preserved, no lone LF introduced" \
  || bad "crlf: pre=$pre post=$post_crlf lone_lf=$lone"

echo
[ "$fails" = 0 ] && echo "OWEN-REWRITE REGRESSIONS: ALL PASS" \
  || echo "OWEN-REWRITE REGRESSIONS: $fails FAILURE(S)"
exit "$fails"
