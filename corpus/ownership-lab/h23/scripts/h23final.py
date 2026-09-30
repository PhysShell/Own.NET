"""H-23A final assembly (mechanical part): reads the treatment census (e2h23), the attribution (h23-attrib.json), the
OFF vs H23-ON scans (e3h23) and the frozen semantic-coverage scans (e3) and writes h23-final-mech.json with
  * the engine-error audit (a unit whose ON arm reports an internal engine error while OFF does not has silently lost
    verdicts; parity failures on either arm),
  * the OFF-baseline check (treatment OFF arm == frozen ON arm: finding counts per unit, and the normalised facts hash
    against the frozen clone's on.facts.json where that clone was kept),
  * raw project/TFM and unique (TFM-collapsed) new / lost findings with their source context for triage,
  * the reassignment ledger from the extractor census counters,
  * the value / complexity ledger inputs (runtime OFF vs treatment).
Triage classes and the twenty answers are written by hand afterwards (h23a-final-v1.json); this file never guesses a class."""
import json, glob, os, re, collections, hashlib
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
E3=f'{S}/lab/sc/e3'; E3H=f'{S}/lab/sc/e3h23'; E2=f'{S}/lab/sc/e2'; E2H=f'{S}/lab/sc/e2h23'
TESTP=re.compile(r'(test|tests|testing|benchmark|bench|sample|samples|example|examples|demo|playground)',re.I)
out={'schema':'own.net/h23/final-mech/v1'}
# ---- census: runtime and the reassignment ledger (extractor census counters, summed over every extractor run)
census={'consumers':0,'seconds_frozen':0,'seconds_treatment':0,'extractor_seconds_frozen':0.0,'extractor_seconds_treatment':0.0,'counters':collections.Counter(),'per_consumer':{}}
for f in sorted(glob.glob(f'{E2H}/*.e2.json')):
    b=json.load(open(f)); tag=os.path.basename(f)[:-8]; fa=f'{E2}/{tag}.e2.json'
    a=json.load(open(fa)) if os.path.exists(fa) else None
    c=collections.Counter()
    for l in b.get('h23_census',[]):
        for kv in l.split()[1:]:
            k,v=kv.split('='); c[k]+=int(v)
    census['counters'].update(c); census['consumers']+=1
    census['seconds_treatment']+=b['seconds']; census['extractor_seconds_treatment']+=sum(x.get('seconds') or 0 for x in b.get('extractor_runs',[]))
    if a: census['seconds_frozen']+=a['seconds']; census['extractor_seconds_frozen']+=sum(x.get('seconds') or 0 for x in a.get('extractor_runs',[]))
    census['per_consumer'][b['repo']]={'seconds_frozen':a['seconds'] if a else None,'seconds_treatment':b['seconds'],'trusted_frozen':a['unit_count_trusted'] if a else None,'trusted_treatment':b['unit_count_trusted'],'by_shape':b.get('units_trusted_by_shape'),'h23_counters':dict(c),'sha_match':(a['sha']==b['sha']) if a else None}
census['counters']=dict(census['counters']); out['census']=census
# ---- scans
scan={'consumers':[],'engine_error_audit':[],'parity_failures':[],'off_baseline':{'units':0,'count_equal':0,'count_differs':[],'facts_compared':0,'facts_identical':0,'facts_differ':[]},'new_raw':[],'lost_raw':[]}
def norm_hash(path,W):
    return hashlib.sha256(open(path,'rb').read().replace(W.encode(),b'<W>')).hexdigest()
for f in sorted(glob.glob(f'{E3H}/*.e3.json')):
    d=json.load(open(f)); tag=os.path.basename(f)[:-8]; fz=f'{E3}/{tag}.e3.json'; z=json.load(open(fz)) if os.path.exists(fz) else None
    Wz=f'{E3}/{tag}'; Wh=f'{E3H}/{tag}'
    row={'repo':d['repo'],'sha':d['sha'][:10],'units':len(d['per_project_tfm']),'new_raw':len(d['new_findings']),'lost_raw':len(d['lost_findings']),'engine_internal_errors':d.get('engine_internal_errors'),'frozen_record':bool(z)}
    for k,u in d['per_project_tfm'].items():
        rel,tfm=k.split('|')
        if u['on'].get('engine_internal_error') and not u['off'].get('engine_internal_error'): scan['engine_error_audit'].append({'repo':d['repo'],'unit':k,'on_errors':u['on']['engine_internal_error'],'off_findings':u['off_findings'],'on_findings':u['on_findings']})
        for arm in ('off','on'):
            if u[arm].get('python_equals_rust') is False: scan['parity_failures'].append({'repo':d['repo'],'unit':k,'arm':arm})
        if z and k in z['per_project_tfm']:
            zu=z['per_project_tfm'][k]; scan['off_baseline']['units']+=1
            if zu['on_findings']==u['off_findings']: scan['off_baseline']['count_equal']+=1
            else: scan['off_baseline']['count_differs'].append({'repo':d['repo'],'unit':k,'frozen_on':zu['on_findings'],'treatment_off':u['off_findings']})
            ud=u['off'].get('unit_dir'); zf=f'{Wz}/.refs/{ud}/on.facts.json' if ud else None
            if zf and os.path.exists(zf) and u['off'].get('facts_sha256_normalised'):
                scan['off_baseline']['facts_compared']+=1
                if norm_hash(zf,Wz)==u['off']['facts_sha256_normalised']: scan['off_baseline']['facts_identical']+=1
                else: scan['off_baseline']['facts_differ'].append({'repo':d['repo'],'unit':k})
    for kind in ('new_findings','lost_findings'):
        for x in d[kind]:
            rel,tfm,file,line,rule,msg=x
            scan['new_raw' if kind=='new_findings' else 'lost_raw'].append({'repo':d['repo'],'project':rel,'tfm':tfm,'file':file,'line':line,'rule':rule,'msg':msg,'kind':'test' if TESTP.search(os.path.basename(rel)) or TESTP.search(file) else 'production'})
    scan['consumers'].append(row)
def uniq(L): return sorted({(x['repo'],x['file'],x['line'],x['rule']) for x in L})
scan['new_unique']=[{'repo':a,'file':b,'line':c,'rule':d} for a,b,c,d in uniq(scan['new_raw'])]
scan['lost_unique']=[{'repo':a,'file':b,'line':c,'rule':d} for a,b,c,d in uniq(scan['lost_raw'])]
scan['summary']={'consumers_scanned':len(scan['consumers']),'new_raw_project_tfm':len(scan['new_raw']),'new_unique_source_sites':len(scan['new_unique']),'lost_raw_project_tfm':len(scan['lost_raw']),'lost_unique_source_sites':len(scan['lost_unique']),'engine_error_units_on_only':len(scan['engine_error_audit']),'parity_failures':len(scan['parity_failures']),'off_baseline':{k:(v if not isinstance(v,list) else len(v)) for k,v in scan['off_baseline'].items()}}
out['scan']=scan
# ---- attribution
try: out['attribution']=json.load(open(f'{S}/lab/sc/h23-attrib.json'))
except Exception as e: out['attribution']={'error':str(e)}
json.dump(out,open(f'{S}/lab/sc/h23-final-mech.json','w'),indent=1)
print(json.dumps({'census':{k:v for k,v in census.items() if k!='per_consumer'},'scan_summary':scan['summary'],'engine_error_audit':scan['engine_error_audit'],'parity_failures':scan['parity_failures'],'off_count_differs':scan['off_baseline']['count_differs'],'facts_differ':scan['off_baseline']['facts_differ']},indent=1))
