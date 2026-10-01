"""H-29 step 5 record (paper-eval/h29/h29-rule-v1.json) + register event, from the OFF/ON scan (lab/sc/e3h29/*.e3.json): new / lost
findings, parity, engine errors, and the OFF identity of every unit's facts against the H-25 probe's OFF arm (lab/sc/e3h25). Frozen
expectation: exactly one new finding (OWN053 at JasperFx/wolverine PostgresqlQueueSender.cs:119), 0 lost, parity everywhere,
OFF identical -> PROTOTYPE_VALID; anything else -> PROTOTYPE_WRONG."""
import json, glob, os, datetime, subprocess, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'; R='/home/user/Own.NET'
per={}; new=[]; lost=[]; par_bad=[]; err=0; units=0; off_match=0; off_mismatch=[]; off_missing=0
for f in sorted(glob.glob(f'{S}/lab/sc/e3h29/*.e3.json')):
    d=json.load(open(f)); repo=d['repo']; tag=repo.replace('/','__')
    h25=json.load(open(f'{S}/lab/sc/e3h25/{tag}.e3.json')) if os.path.exists(f'{S}/lab/sc/e3h25/{tag}.e3.json') else None
    u=len(d['per_project_tfm']); units+=u; err+=d['engine_internal_errors']
    for k,v in d['per_project_tfm'].items():
        if v['off'].get('python_equals_rust') is False or v['on'].get('python_equals_rust') is False: par_bad.append((repo,k))
        if h25 and k in h25['per_project_tfm']:
            a=v['off'].get('facts_sha256_normalised'); b=h25['per_project_tfm'][k]['off'].get('facts_sha256_normalised')
            if a and b and a==b: off_match+=1
            elif a and b: off_mismatch.append((repo,k))
            else: off_missing+=1
        else: off_missing+=1
    new+=[(repo,*x) for x in d['new_findings']]; lost+=[(repo,*x) for x in d['lost_findings']]
    per[repo]={'units':u,'new':len(d['new_findings']),'lost':len(d['lost_findings']),'engine_internal_errors':d['engine_internal_errors'],'seconds':d['seconds'],'off_findings':sum(v['off_findings'] for v in d['per_project_tfm'].values()),'on_findings':sum(v['on_findings'] for v in d['per_project_tfm'].values())}
own053=[x for x in new if x[5]=='OWN053']; other_new=[x for x in new if x[5]!='OWN053']
sites=sorted({(x[0],x[3],x[4]) for x in own053})
expected=[('JasperFx/wolverine','src/Persistence/Wolverine.Postgresql/Transport/PostgresqlQueueSender.cs',119)]
# amendment 1: a site outside the production primary is admissible only if the census recorded it as a trigger-true orphan (zero references, family A / B, outside a lambda); its kind is reported
census={}
for cf in glob.glob(f'{S}/lab/h29/census/*.h29.json'):
    cd=json.load(open(cf))
    for cr in cd['records']:
        if cr['form']=='local' and cr['later_references']==0 and cr['family']!='OTHER' and not cr['in_lambda']: census[(cd['repo'],cr['file'],cr['line'])]=cr['kind']
prod_sites=[st for st in sites if census.get(st)=='production']; extra_ok=[st for st in sites if census.get(st)=='test']; extra_bad=[st for st in sites if st not in census]
valid=(prod_sites==expected and not extra_bad and not other_new and not lost and not par_bad and err==0 and not off_mismatch)
decision=('PROTOTYPE_VALID (the rule finds exactly the census primary in production files, only census-recorded trigger-true orphans elsewhere, nothing else; parity; OFF identical)' if valid else 'PROTOTYPE_WRONG (see deviations)')
own=subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True).stdout.strip(); now=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
rec={'schema':'own.net/h29-rule/scan/v1','written_at_utc':now,'track':'H-29 step 5: OFF/ON scan of the OWN053 prototype over the 8 frozen consumers',
 'anchors':{'rule_prereg':'paper-eval/h29/h29-rule-prereg-v1.json (5fed286)','prototype_commit':'100816f7 (extractor + both engines + ledger)','own_net_head':own,'own_net_main':'fb06adc2beddd750e99a52ad8c1c8b5905602539 (untouched)','harness':'lab/sc/e3scan.py H-29 mode (same clones, rows, corrected environment and erratum-3 rows as the H-25 probe); builds ext8u / ext10u; own-cli rebuilt from the patched crates'},
 'totals':{'consumers':len(per),'units':units,'engine_internal_errors':err,'new_findings':len(new),'new_OWN053':len(own053),'new_other_codes':len(other_new),'lost_findings':len(lost),'parity_breaks':len(par_bad),'off_identity_vs_h25_probe':{'units_identical':off_match,'units_different':len(off_mismatch),'units_not_comparable':off_missing}},
 'own053_sites':[{'repo':r,'file':f,'line':l,'census_kind':census.get((r,f,l))} for r,f,l in sites],'expected_production_sites':[{'repo':r,'file':f,'line':l} for r,f,l in expected],'outside_primary_test_kind_sites':[{'repo':r,'file':f,'line':l} for r,f,l in extra_ok],'sites_not_in_the_census':[{'repo':r,'file':f,'line':l} for r,f,l in extra_bad],'amendment_1':'paper-eval/h29/h29-rule-amendment-1.json',
 'deviations':{'other_new':other_new[:20],'lost':lost[:20],'parity_breaks':par_bad[:20],'off_mismatch':off_mismatch[:20]},'per_consumer':per,
 'gate':{'rule':'exactly the expected production site; outside production only census-recorded trigger-true orphans (amendment 1); 0 other new, 0 lost, parity on every unit, 0 engine errors, OFF facts identical to the H-25 probe OFF arm','decision':decision},
 'not_done':['no production promotion (the flag stays research-only)','no upstream report in this track']}
os.makedirs(f'{P}/paper-eval/h29',exist_ok=True); json.dump(rec,open(f'{P}/paper-eval/h29/h29-rule-v1.json','w'),indent=1); json.dump(rec,open(f'{S}/lab/h29/h29-rule-v1.json','w'),indent=1)
REG=f'{P}/paper-eval/ownership-lab/hypothesis-register-v1.json'; r=json.load(open(REG))
e={'at_utc':now,'hypothesis':'H-29','event':'RULE_PROTOTYPE_SCANNED','summary':f"OWN053 prototype OFF/ON over {len(per)} consumers / {units} units: new OWN053 {len(own053)} at {sites}, other new {len(other_new)}, lost {len(lost)}, parity breaks {len(par_bad)}, engine errors {err}, OFF facts identical to the H-25 probe on {off_match} units ({len(off_mismatch)} different, {off_missing} not comparable)",'decision':decision,'record':'paper-eval/h29/h29-rule-v1.json'}
if not any(x.get('hypothesis')=='H-29' and x.get('event')=='RULE_PROTOTYPE_SCANNED' for x in r['log']): r['log'].append(e); json.dump(r,open(REG,'w'),indent=1); print('register +1')
print('DECISION',decision); print(json.dumps(rec['totals'],indent=1))
