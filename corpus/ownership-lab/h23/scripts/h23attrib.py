"""H-23A population attribution (preregistered exposure unit): per frozen consumer, the trusted opportunities of the
frozen E2 census (before) versus the treatment census (after), by receiving shape and by production/test project; the
three counts (textual assignment candidates >= semantic assignment opportunities >= verdict-changing sites, the last
filled after the OFF/H23-ON scans); every newly reachable unit carries previously_reachable=false. Textual counts are
descriptive only."""
import json, glob, os, re, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'
TESTP=re.compile(r'(test|tests|testing|benchmark|bench|sample|samples|example|examples|demo|playground)',re.I)
TR=('identity_match','rederived_same_source','witnessed_exact_binary','witnessed_identity_match')
def units(d):
    out=set()
    for u in d['units_trusted']:
        u=list(u); shape=u[11] if len(u)>11 else 'declaration'
        out.add((u[0][:10],u[1],u[2],u[3],u[4],u[5],u[6],u[7],u[8],u[9],u[10],shape))
    return out
def span(u): return (u[0],u[1],u[3],u[4],u[5],u[6],u[7],u[8],u[9])   # TFM collapsed
before={}; after={}
for f in glob.glob(f'{S}/lab/sc/e2/*.e2.json'): d=json.load(open(f)); before[d['repo']]=d
for f in glob.glob(f'{S}/lab/sc/e2h23/*.e2.json'): d=json.load(open(f)); after[d['repo']]=d
rows=[]; tot=collections.Counter(); newunits=[]
for repo,a in sorted(after.items()):
    b=before.get(repo); ub=units(b) if b else set(); ua=units(a)
    if b and b['sha']!=a['sha']: print('SHA MISMATCH',repo,b['sha'][:10],a['sha'][:10])
    # 'before' units carry no shape (declaration by construction); match on the shape-free key
    kb={u[:11] for u in ub}
    new_all=[u for u in ua if u[:11] not in kb]; lost=[u for u in ub if u[:11] not in {x[:11] for x in ua}]
    # a DECLARATION-shaped unit cannot come from the seam: when the frozen census restored fewer projects (an SDK pin the
    # later e2.py sets aside; PerformanceMonitor) such units are environment drift and are kept OUT of the attribution
    new=[u for u in new_all if u[11]!='declaration']; drift=[u for u in new_all if u[11]=='declaration']
    restore_drift={'frozen_restored_ok':b['restored_ok'] if b else None,'treatment_restored_ok':a['restored_ok'],'frozen_sdk_pin_set_aside':(b or {}).get('sdk_pin_set_aside'),'treatment_sdk_pin_set_aside':a.get('sdk_pin_set_aside'),'declaration_units_not_attributable':len(drift)}
    prod=lambda U:[u for u in U if not TESTP.search(os.path.basename(u[1]))]
    tx=collections.Counter()
    for rel,p in a['per_project'].items():
        for t in (p.get('targets') or {}).values():
            for k,v in (t.get('textual_sites_trusted_methods') or {}).items(): tx[('test' if TESTP.search(os.path.basename(rel)) else 'production')+':'+k]+=v
    r={'repo':repo,'sha':a['sha'][:10],'before_units':len(ub),'after_units':len(ua),'new_units':len(new),'lost_units':len(lost),'restore_drift':restore_drift,'new_by_shape':dict(collections.Counter(u[11] for u in new)),'after_by_shape':dict(collections.Counter(u[11] for u in ua)),
       'before_spans_production':len({span(u) for u in prod(ub)}),'after_spans_production':len({span(u) for u in prod(ua) if u not in drift}),'after_spans_production_raw_including_drift':len({span(u) for u in prod(ua)}),'new_spans_production':len({span(u) for u in prod(new)}),'new_spans_test':len({span(u) for u in new if TESTP.search(os.path.basename(u[1]))}),
       # narrowed seam (h23a-population-kill-1): only the straight-line 'assignment' shape is APPLIED; nested / loop shapes are opportunities the seam does not apply
       'new_spans_production_applied':len({span(u) for u in prod(new) if u[11]=='assignment'}),'new_spans_production_not_applied_by_shape':dict(collections.Counter(u[11] for u in prod(new) if u[11]!='assignment')),
       'textual_sites':dict(tx),'h23_census':a.get('h23_census',[])[:3],'engine_or_extractor_failures':sum(1 for x in a.get('extractor_runs',[]) if x.get('rc') not in (0,))}
    rows.append(r)
    for u in new: newunits.append({'repo':repo,'project':u[1],'tfm':u[2],'file':u[3],'span':[u[4],u[5],u[6],u[7]],'callable':u[8],'effect':u[9],'assembly':u[10],'shape':u[11],'previously_reachable':False,'kind':'test' if TESTP.search(os.path.basename(u[1])) else 'production'})
    for k in ('before_units','after_units','new_units','lost_units','before_spans_production','after_spans_production','new_spans_production','new_spans_test','new_spans_production_applied'): tot[k]+=r[k]
    tot['consumers_with_new_production_spans']+= 1 if r['new_spans_production']>0 else 0
fam_after=sorted({u[10] for a in after.values() for u in units(a) if not TESTP.search(os.path.basename(u[1]))})
summary={'consumers_censused':len(after),'totals':dict(tot),'production_families_after':fam_after,'gate_note':'after h23a-population-kill-1 the gate is evaluated on new_spans_production_applied (straight-line assignment units the narrowed seam applies); new_spans_production counts every assignment-shaped opportunity the oracle recognised','gate_frozen':{'KEEP_FOR_PRODUCTION_EXPERIMENT':'after_spans_production >= 16 OR new_spans_production >= 20 (and zero suppressed real leaks and FALSE <= TRUE+BENIGN in the scan)','KEEP_AS_ANALYSIS_SUBSTRATE':'8 <= new_spans_production < 16','NARROW':'new_spans_production < 8'},'new_units':newunits,'per_consumer':rows}
json.dump(summary,open(f'{S}/lab/sc/h23-attrib.json','w'),indent=1)
for r in rows: print(r['repo'].split('/')[-1].ljust(20),'before',r['before_units'],'after',r['after_units'],'new',r['new_units'],r['new_by_shape'],'prod spans',r['before_spans_production'],'->',r['after_spans_production'],'lost',r['lost_units'],'textual',{k:v for k,v in r['textual_sites'].items() if 'assignment' in k})
print('TOTALS',dict(tot),'families',fam_after)
