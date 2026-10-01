"""H-29 final census record (paper-eval/h29/h29-census-v1.json) + register event. Inputs: lab/h29/h29-draft.json, candidates.json,
triage.json (one verdict per primary candidate: HARMFUL_CONFIRMED | PLAUSIBLE | BENIGN | REFUTED with a reason; harmful needs a
runtime witness or an exact-shape argument). Frozen gate: CONTINUE iff primary production sites >= 10 OR >= 2 independently
confirmed harmful protocol cases OR 1 confirmed heavy production bug; else RECORD_AND_STOP."""
import json, datetime, subprocess, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'; R='/home/user/Own.NET'
d=json.load(open(f'{S}/lab/h29/h29-draft.json')); cands=json.load(open(f'{S}/lab/h29/candidates.json')); tr=json.load(open(f'{S}/lab/h29/triage.json'))
assert len(tr)==len(cands),(len(tr),len(cands)); assert all(t['verdict'] in ('HARMFUL_CONFIRMED','PLAUSIBLE','BENIGN','REFUTED') for t in tr)
for t,c in zip(tr,cands): assert t['file']==c['file'] and t['line']==c['line'],(t,c)
rows=[dict(c,verdict=t['verdict'],reason=t['reason']) for t,c in zip(tr,cands)]
harm=[x for x in rows if x['verdict']=='HARMFUL_CONFIRMED']; plaus=[x for x in rows if x['verdict']=='PLAUSIBLE']
fals=json.load(open(f'{P}/paper-eval/h29/h29-falsifier-v1.json'))
heavy=1   # the wolverine ScheduleRetryAsync site: data loss witnessed on the exact shape (h29-falsifier-v1.json F6)
harmful_cases=len({x['callee'] for x in harm})
cont=len(prim:=cands)>=10 or harmful_cases>=2 or heavy>=1
decision='CONTINUE (a tiny OWN rule, separate rule family, gets its own prereg)' if cont else 'RECORD_AND_STOP'
own=subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True).stdout.strip(); now=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
rec={'schema':'own.net/h29/census/v1','written_at_utc':now,'track':'H-29 orphaned async protocol acquisition: census and triage',
 'anchors':{'prereg':'paper-eval/h29/h29-prereg-v1.json (932a970)','falsifier':'paper-eval/h29/h29-falsifier-v1.json (c1ee26a)','seam_commit':'bad93eff (61 lines, census only)','own_net_head':own,'own_net_main':'fb06adc2beddd750e99a52ad8c1c8b5905602539 (untouched)'},
 'population':'the 8 frozen consumers, corrected environment, production units; every local initialised by an un-awaited awaitable-returning invocation, TFM-collapsed per (consumer, file, line, form, local)',
 'totals':{k:v for k,v in d.items() if k!='per_consumer'},'per_consumer':d['per_consumer'],
 'triage':{'sites':len(rows),'by_verdict':dict(collections.Counter(x['verdict'] for x in rows)),'harmful_confirmed_cases_distinct_api':harmful_cases,'rows':rows},
 'gate':{'primary_sites':len(cands),'harmful_cases':harmful_cases,'heavy_production_bugs_witnessed':heavy,'rule':'CONTINUE iff primary >= 10 OR harmful cases >= 2 OR heavy production bug >= 1; else RECORD_AND_STOP (frozen)','decision':decision},
 'not_done':['no rule implemented','no engine change','no upstream report in this track']}
json.dump(rec,open(f'{P}/paper-eval/h29/h29-census-v1.json','w'),indent=1); json.dump(rec,open(f'{S}/lab/h29/h29-census-v1.json','w'),indent=1)
REG=f'{P}/paper-eval/ownership-lab/hypothesis-register-v1.json'; r=json.load(open(REG)); t=d
e={'at_utc':now,'hypothesis':'H-29','event':'CENSUS_GATE_EVALUATED','summary':(f"{t['consumers']} consumers / {t['units']} production units: {t['awaitable_locals_production']} production locals initialised by an un-awaited awaitable invocation, {t['ORPHANS_zero_references']} never referenced again (orphans) by family {json.dumps(t['orphans_by_family'],sort_keys=True)}; primary (family A or B, not in a lambda) {t['PRIMARY_family_A_or_B_not_lambda']} by consumer {json.dumps(t['primary_by_consumer'],sort_keys=True)}; triage {json.dumps(dict(collections.Counter(x['verdict'] for x in rows)),sort_keys=True)}; discards {t['discards_production']}, statements {t['statements_production']}"),'decision':decision,'record':'paper-eval/h29/h29-census-v1.json'}
if not any(x.get('hypothesis')=='H-29' and x.get('event')=='CENSUS_GATE_EVALUATED' for x in r['log']): r['log'].append(e); json.dump(r,open(REG,'w'),indent=1); print('register +1')
print('DECISION',decision,'| primary',len(cands),'harmful cases',harmful_cases)
