"""Writes paper-eval/h23/h23a-population-kill-1.json (append-only record): the first population scan of the H-23A seam
(af92d7d9) lost a production project's verdicts through an engine internal error; the seam is narrowed to straight-line
writes; the tiny gate and the OFF identity are re-run on the narrowed build. Reads the probe results, the gate re-run
outputs, offcheck-n1.json and the NpgsqlRest rescan/re-census when present."""
import json, os, glob, hashlib, subprocess, datetime
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; H=f'{S}/lab/h23'; P='/home/user/Own.NET-paperwork'; R='/home/user/Own.NET'
def load(p): return json.load(open(p)) if os.path.exists(p) else None
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
probe=load(f'{H}/nest/results.json') or {}
gate_on=load(f'{H}/out/ON/result.json'); gate_on_n1=load(f'{H}/out/ON_N1/result.json')
def table(r): return {k:v['rust'] for k,v in r['per_method'].items() if k} if r else None
offcheck=load(f'{H}/offcheck-n1.json')
rescan=load(f'{S}/lab/sc/e3h23/NpgsqlRest__NpgsqlRest.e3.json'); recensus=load(f'{S}/lab/sc/e2h23/NpgsqlRest__NpgsqlRest.e2.json')
own_head=subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True).stdout.strip()
rec={
 'schema':'own.net/h23/population-kill/v1',
 'written_at_utc':datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
 'track':'H-23 call-site enrollment / assignment semantics (EXPLORATORY), H-23A existing-local assignment',
 'anchors':{'seam_as_gated':'Own.NET af92d7d95f9b7b67cc4519cfa9faa7ec56581c14 (research/ownership-semantics-lab-v1 == ccr-73cdecbf-0qsiyu)','prereg':'paper-eval/h23/h23-prereg-v1.json (b2acd84)','gate_record':'paper-eval/h23/h23a-gate-v1.json (81b1c01)','own_net_main':'fb06adc2beddd750e99a52ad8c1c8b5905602539 (untouched)','issues':'#304 open FROZEN (updated 2026-09-28T06:29:31Z), #382 open (updated == created 2026-09-29T19:00:02Z), both re-read through the GitHub API on 2026-09-30 (they are issues, not pull requests; the PR endpoint answers 404 for both numbers)'},
 'event':'H23A_POPULATION_KILL_1 (the seam as gated at af92d7d9 is KILLED for nested writes; NARROWED to straight-line writes)',
 'what_happened':{
  'where':'the first treatment scan (OFF = frozen rows with the seam off; ON = the same rows + OWEN_H23A=1) on NpgsqlRest/NpgsqlRest at 6cc6f55fa6, project NpgsqlRest/NpgsqlRest.csproj net10.0 (production)',
  'symptom':"both engines (own-cli and python -m ownlang) answered `error: internal: the core reported [OWN030] on the lowered facts that the bridge cannot map back to a C# subscription (subject=None, message=\"undefined name 'loc_7'\")` on the ON facts; the file-level failure dropped EVERY verdict of the project: OFF 2 findings -> ON 0 findings (lost: NpgsqlRest/ConnectionHelper.cs:75 OWN001 event 'connection.Notice' subscribed, never unsubscribed; NpgsqlRest/NpgsqlRestEndpoint.cs:205 OWN001 same rule); the other 10 project/TFM units of the consumer were unchanged and parity held on every unit",
  'lost_findings_are_not_semantic_suppression':'the two lost findings are event-subscription advisories (OWN001 subscription token), not resource leaks discharged by the reassignment model; they were lost because the WHOLE FILE failed, which the engine-error audit of the prereg treats as a silent verdict loss, i.e. the same class as suppression',
  'root_cause':{
   'shape':'`NpgsqlConnection connection;` followed by an if / else-if chain that assigns `connection = <factory>()` on some paths and `throw`s on the others, then uses `connection` after the merge (NpgsqlRest.ConnectionHelper.OpenConnectionAsync)',
   'lowering_under_the_seam':'each branch write minted a version (connection__v2 / __v3 / __v4 acquired inside then/else arms; the first write at line 40 is `namedDataSource.CreateConnection()` on a receiver the rows do not cover, hence an untracked version); the post-merge references resolve to the textually latest version (connection__v4), acquired inside a nested arm',
   'core_rule':"the bridge hoists a branch-scoped acquire to the function scope only when `branch_hoist_safe` holds: \"hoisting is leak-safe only if no path can exit before the post-merge release on a path that did not acquire `name`\" (rust/crates/own-bridge/src/lower.rs: branch_hoist_safe / hoisted_branch_locals; ownlang/ownir.py: _branch_hoist_safe / _hoisted_branch_locals). A sibling `throw` / `return` path fails that gate, the acquire is not hoisted, and the post-merge reference is an undefined handle -> OWN030 -> the bridge reports an internal error for the file",
   'why_the_tiny_gate_missed_it':'H6 / H6b / H6c write inside a branch whose sibling path does NOT exit (both arms fall through), so the hoist gate held and the fixture showed only the fail-closed false positives; the exiting-sibling shape (the ordinary `T x; if (a) x = A(); else if (b) x = B(); else throw;` initialisation idiom) was not in the fixture',
   'synthetic_probe':{k:{'engines':{e:(x['message'] or x['findings']) for e,x in v['engines'].items()},'body':v['body']} for k,v in probe.items()},
   'probe_reading':'a branch-scoped acquire referenced after the merge fails in BOTH engines at depth 1 already whenever a sibling path exits; the failure is a core/bridge property, not a depth or version-count property'},
  'not_patched':'the bridge / core are outside the H-23 budget (no engine change, no phi/SSA, no second lattice); the failure is recorded as a core limitation that any assignment-site enrollment inherits'},
 'decision':{
  'class':'H23A_NARROW (prereg kill_conditions.H23A_NARROW_OR_KILL: the branch-write case cannot be made sound within the budget without a phi / SSA merge)',
  'narrowing':'a local with ANY write nested in a statement other than the method body (if/else, switch, try/catch/finally, using, lock, a loop, a bare block) is excluded from the seam, fail closed = exactly today\'s behaviour for that local (the write stays invisible: an obligation follows the NAME); the seam now applies only to locals whose writes are all straight-line simple-assignment statements of the method body',
  'census_preserved':'the oracle predicate is still evaluated for every write, so the hit log keeps the semantic opportunity and labels it by shape: assignment (straight-line), assignment_nested, assignment_loop; the extractor counters gain excluded_nested_write',
  'prereg_amendment':'h23-prereg-v1.json reassignment_model said a nested write is \"handled fail-closed (textual-latest)\"; amended (append-only, here) to \"excluded (as today)\": textual-latest is not fail-closed when the core cannot resolve the post-merge name',
  'code_delta':{'narrowing_non_comment_inserted_lines':9,'research_path_total_non_comment_inserted_lines_vs_caf87e26':126,'budget':150,'files':'frontend/roslyn/OwnSharp.Extractor/Program.cs only (H23AAcquireShaped shape label; H23AWrites nested/loop exclusion after predicate evaluation)'},
  'builds':{'net8_narrowed':f'{S}/ext8n/ownsharp-extract.dll sha256 '+(sha(f'{S}/ext8n/ownsharp-extract.dll')[:16] if os.path.exists(f'{S}/ext8n/ownsharp-extract.dll') else '?'),'net10_narrowed':f'{S}/ext10n/ownsharp-extract.dll sha256 '+(sha(f'{S}/ext10n/ownsharp-extract.dll')[:16] if os.path.exists(f'{S}/ext10n/ownsharp-extract.dll') else '?'),'source':'Program.cs at the commit named in own_net_head_after_narrowing','own_net_head_after_narrowing':own_head}},
 'gate_rerun_on_the_narrowed_build':{
  'ON_before_narrowing_af92d7d9':table(gate_on),'ON_N1_narrowed':table(gate_on_n1),
  'gate_shapes':'A2 leak found; A3 clean; A4 leak found; H1 first resource kept; H2 clean; H3 obligation kept; H4 only the fresh one; H5 obligation kept -> PASS (unchanged)',
  'now_identical_to_OFF':'H6 (branch overwrite: clean = the leak stays hidden, as today), H6b (OWN003 false double-dispose, as today), H6c (clean), H8 (loop, already excluded), H9 (try/finally write), H10 (write inside a condition, already excluded); H7 alias limitation unchanged',
  'honest_reading':'the narrowed seam does not IMPROVE branch overwrites; it leaves them exactly as unsound-silent as the baseline instead of turning them into false positives or file failures',
  'engine_internal_error_on_fixture':(gate_on_n1 or {}).get('engine_internal_error'),'parity':(gate_on_n1 or {}).get('parity'),
  'census_line':[l for l in ((gate_on_n1 or {}).get('stderr_tail','')).splitlines() if l.startswith('h23a')]},
 'off_identity_on_the_narrowed_build':{
  'fixture':'OFF_AFTER_N1 (rows, seam off) facts byte-identical to BASE and OFF_AFTER; NOORACLE_N1 byte-identical to NOORACLE',
  'consumer_units_52':({'identical':sum(1 for r in offcheck if r[4]),'of':len(offcheck),'differs':[r[:4] for r in offcheck if not r[4]]} if offcheck else 'offcheck-n1 pending')},
 'npgsqlrest_after_narrowing':{
  'rescan':({'units':len(rescan['per_project_tfm']),'engine_internal_errors':rescan['engine_internal_errors'],'new':rescan['new_findings'],'lost':rescan['lost_findings'],'per_unit':{k:{'off':u['off_findings'],'on':u['on_findings'],'on_err':u['on']['engine_internal_error'],'parity':[u['off']['python_equals_rust'],u['on']['python_equals_rust']]} for k,u in rescan['per_project_tfm'].items()}} if rescan and rescan.get('h23_treatment') else 'pending'),
  'recensus_by_shape':(recensus or {}).get('units_trusted_by_shape'),'recensus_counters':(recensus or {}).get('h23_census')},
 'consequences_for_the_population_run':'the treatment census of the consumers censused before the switch (weasel, NpgsqlRest, marten, wolverine) is re-run with the narrowed build after the chain completes (same rows, same revisions; only the shape labels and the loop-shape hits are new); every consumer censused after the switch already carries the labels; the OFF vs H23-ON scans run on the narrowed build only',
 'rules_kept':['no production change; no PR; no merge','append-only: the gate record and the prereg stand; this record amends them','the population, the rows, the revisions and the derivation rules are unchanged']}
os.makedirs(f'{P}/paper-eval/h23',exist_ok=True); json.dump(rec,open(f'{P}/paper-eval/h23/h23a-population-kill-1.json','w'),indent=1)
print('written; offcheck', 'pending' if not offcheck else (sum(1 for r in offcheck if r[4]),len(offcheck)), '; rescan', 'pending' if not rescan else (rescan['engine_internal_errors'],len(rescan['new_findings']),len(rescan['lost_findings'])), '; recensus', (recensus or {}).get('units_trusted_by_shape'))
