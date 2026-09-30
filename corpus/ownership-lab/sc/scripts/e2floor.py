"""Stage E2 exposure floor over the census outputs: consumers with >= 1 TRUSTED semantic opportunity, unique opportunities,
dependency families (packages of the applied rows); the frozen floor: >= 10 consumers AND >= 30 unique semantic opportunities
AND >= 5 consumers with >= 1 AND >= 3 dependency families; the unverified (version-drift / TFM-variant) units are reported
separately and never counted toward the floor."""
import json, glob, collections, os
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
out=[]; units=set(); fam=set(); unv=0; per=[]
for f in sorted(glob.glob(f'{S}/lab/sc/e2/*.e2.json')):
    d=json.load(open(f)); n=d['unit_count_trusted']
    pk=set()
    for rel,p in d['per_project'].items():
        for tfm,t in (p.get('targets') or {}).items():
            for r in t['resolved']:
                if r['status'] in ('identity_match','rederived_same_source','witnessed_exact_binary','witnessed_identity_match'): pk.add(r['package'])
    ufam={u[10] for u in d['units_trusted']}   # assembly name of the hit
    fam|=ufam; units|={tuple(u) for u in d['units_trusted']}; unv+=d['unit_count_unverified']
    per.append({'repo':d['repo'],'sha':d['sha'][:10],'production_projects':d['production_projects'],'restored_ok':d['restored_ok'],'trusted_units':n,'unverified_units':d['unit_count_unverified'],'units_by_class':d.get('units_by_class',{}),'families_hit':sorted(ufam),'extractor_failures':sum(1 for x in d.get('extractor_runs',[]) if x.get('rc') not in (0,)),'textual_assignment_sites':sum((t.get('textual_sites_trusted_methods') or {}).get('assignment_shape',0) for p in d['per_project'].values() for t in (p.get('targets') or {}).values()),'textual_declaration_sites':sum((t.get('textual_sites_trusted_methods') or {}).get('declaration_shape',0) for p in d['per_project'].values() for t in (p.get('targets') or {}).values())})
# production / test split by PROJECT NAME (post hoc, name pattern; the frozen restore filter used path segments only)
import re
TESTP=re.compile(r'(test|tests|testing|benchmark|bench|sample|samples|example|examples|demo|playground)',re.I)
prod_units=set(); test_units=set()
for f in sorted(glob.glob(f'{S}/lab/sc/e2/*.e2.json')):
    d=json.load(open(f))
    for u in d['units_trusted']:
        (test_units if TESTP.search(os.path.basename(u[1])) else prod_units).add(tuple(u))
for x in per:
    full=[u for u in prod_units if u[0][:10]==x['sha']]; x['trusted_units_production']=len(full)
cons=len(per); with1=sum(1 for x in per if x['trusted_units']>=1); with1p=sum(1 for x in per if x['trusted_units_production']>=1)
famp={u[10] for u in prod_units}
# TFM-collapsed view: one source span counted once even when the project multi-targets (stricter than the frozen unit)
spans=lambda U:{(u[0],u[1],u[3],u[4],u[5],u[6],u[7],u[8],u[9]) for u in U}
span_all=len(spans(units)); span_prod=len(spans(prod_units))
floor={'consumers':cons,'unique_trusted_opportunities':len(units),'unique_trusted_opportunities_production':len(prod_units),'unique_trusted_opportunities_test_projects':len(test_units),'consumers_with_at_least_one':with1,'consumers_with_at_least_one_production':with1p,'dependency_families':sorted(fam),'dependency_families_production':sorted(famp),'unverified_units_total':unv,'unique_source_spans_tfm_collapsed':span_all,'unique_source_spans_tfm_collapsed_production':span_prod,
       'met_all_projects':cons>=10 and len(units)>=30 and with1>=5 and len(fam)>=3,'met_production_only':cons>=10 and len(prod_units)>=30 and with1p>=5 and len(famp)>=3,
       'rule':'>=10 consumers AND >=30 unique semantic opportunities AND >=5 consumers with >=1 AND >=3 dependency families; decided on the stricter production-only count (test-project opportunities reported separately)'}
json.dump({'per_consumer':per,'floor':floor},open(f'{S}/lab/sc/e2-floor.json','w'),indent=1)
for x in per: print(x['repo'],'trusted',x['trusted_units'],'unverified',x['unverified_units'],x['units_by_class'],'asg/decl',x['textual_assignment_sites'],x['textual_declaration_sites'],'restore',x['restored_ok'],'/',x['production_projects'],'xfail',x['extractor_failures'])
print('FLOOR',floor)
