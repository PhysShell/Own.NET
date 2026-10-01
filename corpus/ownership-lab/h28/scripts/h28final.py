"""H-28 final record (paper-eval/h28/h28-census-v1.json) + register events. Inputs: lab/h28/h28-draft.json, borrow-candidates.json,
manual-read.json (one verdict per candidate: CONFIRMED | REFUTED, reason; optional missed_by_ca2000_and_off: true when a CA2000
reproduction and the OFF scan were both run on the site and both miss it). Frozen gate: cross-check mismatch = EXPERIMENT_INVALID;
BUILD iff confirmed >= 10 AND confirmed callee families >= 3, OR >= 1 confirmed site missed by CA2000 and the OFF scan; else
RECORD_AND_STOP."""
import json, datetime, subprocess, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'; R='/home/user/Own.NET'
d=json.load(open(f'{S}/lab/h28/h28-draft.json')); cands=json.load(open(f'{S}/lab/h28/borrow-candidates.json')); mr=json.load(open(f'{S}/lab/h28/manual-read.json'))
assert len(mr)==len(cands),(len(mr),len(cands)); assert all(m['verdict'] in ('CONFIRMED','REFUTED') for m in mr)
for m,c in zip(mr,cands): assert m['file']==c['file'] and m['line']==c['line'],(m,c)
confirmed=[dict(c,reason=m['reason'],missed_by_ca2000_and_off=m.get('missed_by_ca2000_and_off',False)) for m,c in zip(mr,cands) if m['verdict']=='CONFIRMED']
refuted=[dict(c,reason=m['reason']) for m,c in zip(mr,cands) if m['verdict']=='REFUTED']
fams={c['callee'] for c in confirmed}; missed=[c for c in confirmed if c['missed_by_ca2000_and_off']]
if d['cross_check']['verdict']!='OK': decision='EXPERIMENT_INVALID (harness: the recorded treatment disagrees with the lowering)'
elif (len(confirmed)>=10 and len(fams)>=3) or len(missed)>=1: decision='BUILD (a trusted callee-parameter effect gets its own prereg)'
else: decision='RECORD_AND_STOP (the census is the whole result; the conservative default is not built)'
own=subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True).stdout.strip(); now=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
rec={'schema':'own.net/h28/census/v1','written_at_utc':now,'track':'H-28 argument / callee ownership transfer census',
 'anchors':{'prereg':'paper-eval/h28/h28-prereg-v1.json (f6db975)','falsifier':'paper-eval/h28/h28-falsifier-v1.json','fixture':'paper-eval/h28/h28-fixture-v1.json (ANCHORS_PASSED)','seam_commit':'8e780c3f (93 lines, census only)','own_net_head':own,'own_net_main':'fb06adc2beddd750e99a52ad8c1c8b5905602539 (untouched)'},
 'population':'the 8 frozen consumers, corrected environment, production units; argument passes of the extractor\'s own candidate locals, TFM-collapsed per (consumer, file, line, local, callee)',
 'totals':{k:v for k,v in d.items() if k!='per_consumer'},'per_consumer':d['per_consumer'],
 'manual_read':{'sites_read':len(cands),'confirmed':len(confirmed),'refuted':len(refuted),'confirmed_callee_families':sorted(fams),'refutations_by_reason':dict(collections.Counter(m['reason'] for m in mr if m['verdict']=='REFUTED')),'confirmed_sites':confirmed,'refuted_sites':refuted},
 'gate':{'confirmed_primary':len(confirmed),'confirmed_families':len(fams),'confirmed_missed_by_ca2000_and_off':len(missed),'rule':'BUILD iff confirmed >= 10 AND families >= 3, OR >= 1 confirmed site missed by CA2000 (default options) and the OFF scan; else RECORD_AND_STOP; cross-check mismatch = EXPERIMENT_INVALID (frozen)','decision':decision},
 'not_done':['no engine change','no conservative default','no callee effect rows','no vocabulary change']}
json.dump(rec,open(f'{P}/paper-eval/h28/h28-census-v1.json','w'),indent=1); json.dump(rec,open(f'{S}/lab/h28/h28-census-v1.json','w'),indent=1)
REG=f'{P}/paper-eval/ownership-lab/hypothesis-register-v1.json'; r=json.load(open(REG)); t=d
e={'at_utc':now,'hypothesis':'H-28','event':'CENSUS_GATE_EVALUATED','summary':(f"{t['consumers']} consumers / {t['units']} production units, {t['extractor_failures']} failures: {t['passes_raw']} raw / {t['passes_unique']} TFM-collapsed argument passes of candidate locals, {t['production_unique']} production; "
   f"treatment {json.dumps(t['treatment_production'],sort_keys=True)}; escaped with the caller doing nothing afterwards {t['escaped_caller_nothing']} by callee label {json.dumps(t['escaped_caller_nothing_by_callee_label'],sort_keys=True)}; "
   f"PRIMARY body-proved BORROW candidates {t['PRIMARY_borrow_candidates']} over {t['primary_callee_families']} callee families, read by hand: {len(confirmed)} confirmed ({len(fams)} families), {len(refuted)} refuted; external-unknown exposure {t['external_unknown_candidates']} passes over {t['external_unknown_families']} callee families; cross-check {t['cross_check']['records_checked']} records, {t['cross_check']['mismatches']} mismatches"),
   'decision':decision,'record':'paper-eval/h28/h28-census-v1.json'}
if not any(x.get('hypothesis')=='H-28' and x.get('event')=='CENSUS_GATE_EVALUATED' for x in r['log']): r['log'].append(e); json.dump(r,open(REG,'w'),indent=1); print('register +1')
print('DECISION',decision,'| confirmed',len(confirmed),'families',len(fams),'missed',len(missed))
