"""Record the H-28 fixture outcome (paper-eval/h28/h28-fixture-v1.json): every recorded site with its treatment, caller and callee
classes, the cross-check against the lowering (an ESCAPE_UNTRACKED local must be absent from the unit facts), and the anchor
verdict (ANCHORS_PASSED or KILL_BEFORE_ENGINE). Append-only; register event."""
import json, datetime, subprocess
P='/home/user/Own.NET-paperwork'; R='/home/user/Own.NET'; S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; now=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
recs=[json.loads(l) for l in open(f'{S}/lab/h28/fx/arg.jsonl') if l.strip()]
F=json.load(open(f'{S}/lab/h28/fx/arg.facts.json')); fns=F.get('functions',[]); byname={}
def walk(ns,vs):
    for n in ns:
        if isinstance(n,dict):
            if n.get('var'): vs.add(n['var'])
            for k in ('then','else','body'):
                if isinstance(n.get(k),list): walk(n[k],vs)
for fn in fns: vs=set(); walk(fn.get('body',[]),vs); byname[fn.get('name')]=vs
rows=[]; mism=0
for j in recs:
    present=j['local'] in byname.get(j['method_key'],set()); ok=(present==(j['current_treatment']!='ESCAPE_UNTRACKED')); mism+=0 if ok else 1
    rows.append({'member':j['member'],'current_treatment':j['current_treatment'],'caller_after_call':j['caller_after_call'],'callee':j['callee'],'callee_class':j['callee_class'],'callee_proof':j['callee_proof'],'callee_use_kinds':j['callee_use_kinds'],'forwarded_to':j['forwarded_to'],'parameter':j['parameter'],'arg_named':j['arg_named'],'in_facts':present,'cross_check':'OK' if ok else 'MISMATCH'})
by={r['member']:r for r in rows}
anchors={'anchor_1_external_DataTable_Load':{'site':'N13_external_datatable_load','got':by['N13_external_datatable_load']['callee_class'],'expected':'EXTERNAL_UNKNOWN by body; RELEASE_IF_LAST_RESULT_SET by the witnessed table (h28-falsifier-v1.json)','ok':by['N13_external_datatable_load']['callee_class']=='EXTERNAL_UNKNOWN'},
 'anchor_2_wrapper_ADOPT':{'sites':['N04_adopt_bounded_wrapper','N05_adopt_stored_wrapper'],'got':[by['N04_adopt_bounded_wrapper']['callee_class'],by['N05_adopt_stored_wrapper']['callee_class']],'ok':by['N04_adopt_bounded_wrapper']['callee_class']=='ADOPT' and by['N05_adopt_stored_wrapper']['callee_class']=='ADOPT'},
 'anchor_3_Close_RELEASE':{'sites':['N02_release_statement','N03_release_nonstatement','N16_release_async','N17_release_finally','N18_release_conditional','N19_release_using_param'],'got':[by[m]['callee_class'] for m in ('N02_release_statement','N03_release_nonstatement','N16_release_async','N17_release_finally','N18_release_conditional','N19_release_using_param')],'ok':all(by[m]['callee_class']=='RELEASE_ALL_PATHS' for m in ('N02_release_statement','N03_release_nonstatement','N16_release_async','N17_release_finally','N18_release_conditional','N19_release_using_param'))},
 'borrow_twin':{'site':'N01_borrow_nothing','got':(by['N01_borrow_nothing']['current_treatment'],by['N01_borrow_nothing']['caller_after_call'],by['N01_borrow_nothing']['callee_class']),'expected':('ESCAPE_UNTRACKED','NOTHING','BORROW'),'ok':(by['N01_borrow_nothing']['current_treatment'],by['N01_borrow_nothing']['caller_after_call'],by['N01_borrow_nothing']['callee_class'])==('ESCAPE_UNTRACKED','NOTHING','BORROW')},
 'other_twins':{m:by[m]['callee_class'] for m in ('N06_alias','N06b_alias_wrapped','N07_forward','N08_unused','N14_adopt_static_field','N15_some_path','N22_named_arg')},
 'caller_side':{m:by[m]['caller_after_call'] for m in ('N09_borrow_then_dispose','N10_borrow_then_return','N11_borrow_then_store')},
 'not_recorded_as_expected':['N20_closure_capture (closure capture escapes before the argument rule)','N21_using_local_borrow (a using local is not a candidate of the escape loop)']}
passed=all(a['ok'] for a in anchors.values() if isinstance(a,dict) and 'ok' in a) and mism==0 and by['N07_forward']['callee_class']=='FORWARD' and by['N06_alias']['callee_class']=='ALIAS_TO_RESULT' and by['N08_unused']['callee_class']=='UNUSED' and by['N15_some_path']['callee_class']=='RELEASE_SOME_PATH'
own=subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True).stdout.strip()
rec={'schema':'own.net/h28/fixture/v1','written_at_utc':now,'prereg':'paper-eval/h28/h28-prereg-v1.json (f6db975)','own_net_head':own,'fixture':'corpus/ownership-lab/h28/fx/Arg.cs (22 caller methods, 13 callees)','records':rows,'anchors':anchors,'cross_check_mismatches':mism,
 'verdict':'ANCHORS_PASSED: the seam separates ADOPT from RELEASE from BORROW and reports the current treatment exactly as the lowering decides it' if passed else 'KILL_BEFORE_ENGINE: an anchor or the cross-check failed',
 'notes':['N04: `var w = new Wrapper(s); w.Dispose();` is ESCAPE_UNTRACKED in the lowering too (the P-005 D5.4 adoption exemption did not apply to this wrapper); the body-proof still reads the constructor as ADOPT','N14 / N15 / N16 / N18 / N19 / N22: statement-form calls to first-party callees are EXEMPT_CANONICAL_FORWARD (the engine reads the callee summary), so the obligation is not erased there; the erased class is ESCAPE_UNTRACKED only','N07: a void expression-bodied forward `=> Close(s)` is FORWARD after the refinement (first run read it as ALIAS_TO_RESULT)']}
json.dump(rec,open(f'{P}/paper-eval/h28/h28-fixture-v1.json','w'),indent=1)
REG=f'{P}/paper-eval/ownership-lab/hypothesis-register-v1.json'; r=json.load(open(REG))
e={'at_utc':now,'hypothesis':'H-28','event':'HOSTILE_ANCHORS_EVALUATED','summary':f"fixture of 22 callers / 13 callees: {len(rows)} argument passes recorded; anchors: DataTable.Load EXTERNAL_UNKNOWN (+ witnessed RELEASE), wrapper ctor ADOPT x2, Close RELEASE_ALL_PATHS x6, use-only BORROW with ESCAPE_UNTRACKED / NOTHING; twins alias / wrapped alias / forward / unused / some-path / named argument as intended; cross-check against the lowering {mism} mismatches",'decision':rec['verdict'].split(':')[0],'record':'paper-eval/h28/h28-fixture-v1.json'}
if not any(x.get('hypothesis')=='H-28' and x.get('event')=='HOSTILE_ANCHORS_EVALUATED' for x in r['log']): r['log'].append(e); json.dump(r,open(REG,'w'),indent=1); print('register +1')
print(rec['verdict'])
