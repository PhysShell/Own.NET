"""H-25 probe aggregation and record (paper-eval/h25/h25-probe-v1.json): the OFF (rows, no seam) versus ON (rows +
OWEN_H25=1) scans over the 8 frozen consumers in the corrected environment with the erratum-3 rows; the applied metric
(hit-log lines with an +await shape on production units, TFM-collapsed), new / lost findings with context, engine
errors, parity, facts identity per unit; the decision by the AMENDED classes (h25-probe-amendment-1)."""
import json, glob, os, re, collections, datetime, subprocess
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'; R='/home/user/Own.NET'
E=f'{S}/lab/sc/e3h25'; W0=f'{S}/lab/sc/e3h23'
TESTP=re.compile(r'(test|tests|testing|benchmark|bench|sample|samples|example|examples|demo|playground)',re.I)
cons=[]; new=[]; lost=[]; errs=[]; par=[]; applied=set(); applied_raw=0; applied_sites=[]
for f in sorted(glob.glob(f'{E}/*.e3.json')):
    d=json.load(open(f)); tag=d['repo'].replace('/','__'); W=f'{W0}/{tag}'
    ident=sum(1 for u in d['per_project_tfm'].values() if u['off']['facts_sha256_normalised']==u['on']['facts_sha256_normalised'])
    row={'repo':d['repo'],'sha':d['sha'][:10],'units':len(d['per_project_tfm']),'engine_internal_errors':d['engine_internal_errors'],'new_raw':len(d['new_findings']),'lost_raw':len(d['lost_findings']),'facts_identical_units':ident,'off_findings':sum(u['off_findings'] for u in d['per_project_tfm'].values()),'on_findings':sum(u['on_findings'] for u in d['per_project_tfm'].values())}
    for k,u in d['per_project_tfm'].items():
        if u['on'].get('engine_internal_error') and not u['off'].get('engine_internal_error'): errs.append({'repo':d['repo'],'unit':k,'on_errors':u['on']['engine_internal_error']})
        for arm in ('off','on'):
            if u[arm].get('python_equals_rust') is False: par.append({'repo':d['repo'],'unit':k,'arm':arm})
        rel=k.split('|')[0]; kind='test' if TESTP.search(os.path.basename(rel)) else 'production'
        ud=u['on'].get('unit_dir'); hf=f'{W}/.refs/{ud}/h25on.hits.jsonl' if ud else None
        if hf and os.path.exists(hf):
            for l in open(hf):
                if not l.strip(): continue
                j=json.loads(l)
                if '+await' in j.get('shape',''):
                    applied_raw+=1
                    key=(d['repo'],os.path.relpath(j['file'],W) if j['file'].startswith(W) else j['file'],j['line'],j['callable'],j['shape'])
                    if key not in applied: applied.add(key); applied_sites.append({'repo':d['repo'],'file':key[1],'line':j['line'],'callable':j['callable'],'shape':j['shape'],'kind':kind,'project':rel})
    for x in d['new_findings']: new.append({'repo':d['repo'],'project':x[0],'tfm':x[1],'file':x[2],'line':x[3],'rule':x[4],'msg':x[5],'kind':'test' if TESTP.search(os.path.basename(x[0])) or TESTP.search(x[2]) else 'production'})
    for x in d['lost_findings']: lost.append({'repo':d['repo'],'project':x[0],'tfm':x[1],'file':x[2],'line':x[3],'rule':x[4],'msg':x[5],'kind':'test' if TESTP.search(os.path.basename(x[0])) or TESTP.search(x[2]) else 'production'})
    cons.append(row)
def uniq(L): return sorted({(x['repo'],x['file'],x['line'],x['rule']) for x in L})
ap_prod=[s for s in applied_sites if s['kind']=='production']
summary={'consumers':len(cons),'units':sum(c['units'] for c in cons),'applied_await_hits_raw':applied_raw,'applied_await_sites_unique':len(applied_sites),'applied_await_sites_production_unique':len(ap_prod),'applied_by_shape_production':dict(collections.Counter(s['shape'] for s in ap_prod)),'applied_by_callable_production':dict(collections.Counter(s['callable'].split('.')[-1] for s in ap_prod)),
 'new_raw':len(new),'new_unique':len(uniq(new)),'lost_raw':len(lost),'lost_unique':len(uniq(lost)),'engine_error_units_on_only':len(errs),'parity_failures':len(par),'facts_identical_units':sum(c['facts_identical_units'] for c in cons),'off_findings_total':sum(c['off_findings'] for c in cons),'on_findings_total':sum(c['on_findings'] for c in cons)}
triage=json.load(open(f'{S}/lab/h25/h25-probe-triage.json')) if os.path.exists(f'{S}/lab/h25/h25-probe-triage.json') else {'new':[],'lost':[]}
real_lost=any(t.get('real_leak_suppressed') for t in triage['lost'])
cls=collections.Counter(t['class'] for t in triage['new'])
if real_lost or errs or par: decision='KILL'
elif cls.get('TRUE_PRODUCTION',0)>=1 and any(t.get('competitor')=='OWN_NET_ONLY' for t in triage['new']): decision='KEEP_FOR_PRODUCTION_EXPERIMENT'
elif len(ap_prod)>=4: decision='KEEP_AS_ANALYSIS_SUBSTRATE'
else: decision='NARROW'
own=subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True).stdout.strip()
rec={'schema':'own.net/h25/probe/v1','written_at_utc':datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),'track':'H-25 await-wrapped acquire: the predicate probe and the OFF/ON scan',
 'anchors':{'probe_prereg':'paper-eval/h25/h25-probe-prereg-v1.json (8283aef)','amendment_1':'paper-eval/h25/h25-probe-amendment-1.json (e4a5b7c, before the scan)','seam_commit':'8b921a1d (13 non-comment lines: await / ConfigureAwait unwrap inside ReOracle.ReturnsFreshOwned; the Task-local guard at the declaration minting site)','own_net_head':own,'own_net_main':'fb06adc2beddd750e99a52ad8c1c8b5905602539 (untouched)'},
 'environment':'corrected (invariant 0) on the e3h23 clones; unit row files rebuilt per unit with the erratum-3 rows (NpgsqlDataSource.OpenConnection / OpenConnectionAsync, exact tested binary only); OFF = rows without the seam, ON = rows + OWEN_H25=1; NOTE: the OFF arm of this scan is NOT the frozen E3 ON arm (different environment, erratum 2 + 3), so only within-run comparisons are made',
 'off_identity':{'fixtures':'no-oracle OFF and rows-without-seam byte-identical to the previous build (ext8m2) on the H-23, H-24 and H-25 fixtures','consumer_units':json.load(open(f'{S}/lab/h23/offcheck-p1.json')) if os.path.exists(f'{S}/lab/h23/offcheck-p1.json') else 'offcheck-p1 pending'},
 'fixture':'corpus/ownership-lab/h25/out/H25_ON.result.json, H25_ON_H23A.result.json, H25_OFF_ROWS.result.json: AW4 clean, AW5 OWN001, HW8 untracked (using declaration by design), HW1 Task local not minted under the seam (and FALSELY charged by the rows-without-seam arm: the pre-existing hazard), HW2 / HW3 / HW5 / HW6 silent, AW1-AW3 clean with OWEN_H23A=1, AW6 silent (nested write)',
 'summary':summary,'per_consumer':cons,'applied_sites':applied_sites,'engine_error_audit':errs,'parity_failures':par,'new_findings':new,'lost_findings':lost,'triage':triage,
 'decision':{'primary':decision,'alternative_reading':'the amended class KEEP_AS_ANALYSIS_SUBSTRATE asked for applied == the non-using trusted sites and wrote that count as 4-5; the triage count correction shows the applicable set is 2 declarations (the 3 marten assignments are nested in try and excluded by the H-23A narrowing, which the scan does not enable), and both were applied with 0 lost, 0 engine errors, parity on every unit and OFF identity; under the corrected count the mechanism qualifies as an analysis substrate; the primary decision keeps the letter of the frozen threshold (NARROW) because the population value is 2 sites, both ownership transfers, 0 findings','rule':'amended classes (h25-probe-amendment-1): KILL on a lost real finding / engine error / parity failure; KEEP_FOR_PRODUCTION_EXPERIMENT on >= 1 TRUE_PRODUCTION unique finding competitors miss; KEEP_AS_ANALYSIS_SUBSTRATE when the non-using trusted sites (expected 4-5; 2 declarations without H-23A) are applied with 0 lost / 0 errors; NARROW otherwise','not_production_ready':True}}
if os.path.exists(f'{S}/lab/h23/offcheck-p1.json'):
    oc=json.load(open(f'{S}/lab/h23/offcheck-p1.json')); rec['off_identity']['consumer_units']={'identical':sum(1 for r in oc if r[4]),'of':len(oc)}
os.makedirs(f'{P}/paper-eval/h25',exist_ok=True); json.dump(rec,open(f'{P}/paper-eval/h25/h25-probe-v1.json','w'),indent=1); json.dump(rec,open(f'{S}/lab/h25/h25-probe-v1.json','w'),indent=1)
print(json.dumps(summary,indent=1)); print('DECISION',decision); [print('  APPLIED',s) for s in applied_sites]; [print('  NEW',n) for n in new]; [print('  LOST',l) for l in lost]
