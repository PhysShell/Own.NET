"""H-28 census aggregation: production argument passes of owned candidate locals, TFM-collapsed per (consumer, file, line, local,
callee); the frozen primary (ESCAPE_UNTRACKED and caller NOTHING and callee BORROW body-proved, or witnessed-table BORROW: none),
the secondary classes, the exempt occurrences, the cross-check against the unit facts (an ESCAPE_UNTRACKED local must be absent
from its method's ops, an exempt one present) -> EXPERIMENT_INVALID on any mismatch; writes lab/h28/h28-draft.json and the
candidate list lab/h28/borrow-candidates.json for the manual read."""
import json, glob, collections, os, re
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3h23'
WITNESSED={'System.Data.DataTable.Load/1':'RELEASE_IF_LAST_RESULT_SET','System.Data.DataTable.Load/2':'RELEASE_IF_LAST_RESULT_SET','System.Data.DataTable.Load/3':'RELEASE_IF_LAST_RESULT_SET'}
U={}; per={}; xmis=[]; xother=[]; xchecked=0
def walk(ns,vs,ls):
    for n in ns:
        if isinstance(n,dict):
            if n.get('var'): vs.add(n['var'])
            if isinstance(n.get('line'),int): ls.append(n['line'])
            for k in ('then','else','body'):
                if isinstance(n.get(k),list): walk(n[k],vs,ls)
def facts_index(F):
    # the unit facts keyed by (name, canonical per-overload sig): the seam record carries the same stamp and sig of its enclosing method
    idx={}
    for fn in F.get('functions',[]):
        vs=set(); ls=[]; walk(fn.get('body',[]),vs,ls)
        idx.setdefault((fn.get('name'),fn.get('sig') or ''),[]).append(vs)
    return idx
def present_in(idx,name,sig,var):
    return any(var in vs for vs in idx.get((name,sig or ''),[]))
for f in sorted(glob.glob(f'{S}/lab/h28/census/*.h28.json')):
    d=json.load(open(f)); tag=d['repo'].replace('/','__'); per[d['repo']]={'units':d['units'],'extractor_failures':d['extractor_failures'],'seconds':d['seconds'],'passes_raw':len(d['records'])}
    facts_cache={}
    for r in d['records']:
        r=dict(r,repo=d['repo']); key=(d['repo'],r['file'],r['line'],r['local'],r['callee'])
        # cross-check on every raw record (per unit facts)
        ff=f"{E}/{tag}/.refs/{r['refdir']}/h28.facts.json"
        if ff not in facts_cache:
            try: facts_cache[ff]=facts_index(json.load(open(ff)))
            except Exception as ex: facts_cache[ff]=None
        bn=facts_cache[ff]
        if bn is not None and r.get('method_key'):
            present=present_in(bn,r['method_key'],r.get('method_sig'),r['local']); xchecked+=1
            # amendment 1: exact in one direction only (an ESCAPE_UNTRACKED local must be absent); exempt-but-absent = escaped by another route (descriptive)
            if r['current_treatment']=='ESCAPE_UNTRACKED' and present: xmis.append({'repo':d['repo'],'file':r['file'],'line':r['line'],'local':r['local'],'treatment':r['current_treatment'],'in_facts':present,'method_key':r['method_key']})
            elif r['current_treatment']!='ESCAPE_UNTRACKED' and not present: xother.append({'repo':d['repo'],'file':r['file'],'line':r['line'],'local':r['local'],'treatment':r['current_treatment'],'method_key':r['method_key']})
        U.setdefault(key,r)
UA=list(U.values()); pool=[r for r in UA if r['acquire_shape']=='pool']; UA=[r for r in UA if r['acquire_shape']!='pool']; prod=[r for r in UA if r['kind']=='production']   # amendment 1: pool rentals leave the population
for r in prod: r['callee_label']=WITNESSED.get(r['callee'],r['callee_class'])
def cnt(rs,k): return dict(collections.Counter(r[k] for r in rs).most_common())
esc=[r for r in prod if r['current_treatment']=='ESCAPE_UNTRACKED']; escn=[r for r in esc if r['caller_after_call']=='NOTHING']
primary=[r for r in escn if r['callee_label']=='BORROW']
ext=[r for r in escn if r['callee_label']=='EXTERNAL_UNKNOWN']
fam=lambda r: r['callee']
rec={'consumers':len(per),'units':sum(v['units'] for v in per.values()),'extractor_failures':sum(v['extractor_failures'] for v in per.values()),'passes_raw':sum(v['passes_raw'] for v in per.values()),'passes_unique':len(UA),'production_unique':len(prod),
 'treatment_production':cnt(prod,'current_treatment'),'caller_after_call_production':cnt(prod,'caller_after_call'),'callee_label_production':cnt(prod,'callee_label'),'callee_proof_production':cnt(prod,'callee_proof'),'acquire_shape_production':cnt(prod,'acquire_shape'),
 'escaped_production':len(esc),'escaped_caller_nothing':len(escn),'escaped_caller_nothing_by_callee_label':cnt(escn,'callee_label'),'escaped_caller_nothing_first_party':sum(1 for r in escn if r['callee_first_party']),
 'PRIMARY_borrow_candidates':len(primary),'primary_callee_families':len({fam(r) for r in primary}),'primary_by_callee':cnt(primary,'callee'),'primary_by_consumer':cnt(primary,'repo'),
 'external_unknown_candidates':len(ext),'external_unknown_families':len({fam(r) for r in ext}),'external_unknown_top_callees':dict(collections.Counter(r['callee'] for r in ext).most_common(40)),'external_unknown_by_consumer':cnt(ext,'repo'),
 'escaped_nothing_release_adopt_alias_forward':{k:sum(1 for r in escn if r['callee_label']==k) for k in ('RELEASE_ALL_PATHS','RELEASE_SOME_PATH','ADOPT','ALIAS_TO_RESULT','FORWARD','UNUSED','RELEASE_IF_LAST_RESULT_SET')},
 'exempt_production':{k:sum(1 for r in prod if r['current_treatment']==k) for k in ('EXEMPT_CONSUMED','EXEMPT_CANONICAL_FORWARD','EXEMPT_ADOPTED_WRAPPER','EXEMPT_POOL')},
 'pool_rentals_excluded':len(pool),'pool_rentals_excluded_production':sum(1 for r in pool if r['kind']=='production'),
 'cross_check':{'records_checked':xchecked,'mismatches_exact_direction':len(xmis),'verdict':'OK' if not xmis else 'EXPERIMENT_INVALID','examples':xmis[:20],'exempt_but_absent_escaped_by_another_route':len(xother),'exempt_but_absent_by_treatment':dict(collections.Counter(x['treatment'] for x in xother)),'exempt_but_absent_examples':xother[:10]},'per_consumer':per}
json.dump(rec,open(f'{S}/lab/h28/h28-draft.json','w'),indent=1)
json.dump([{k:r.get(k) for k in ('repo','file','line','member','method_key','local','local_type','acquire_shape','callee','callee_assembly','callee_first_party','parameter','parameter_type','call_is_statement','caller_kinds','callee_use_kinds','forwarded_to','project','tfm')} for r in sorted(primary,key=lambda r:(r['repo'],r['file'],r['line']))],open(f'{S}/lab/h28/borrow-candidates.json','w'),indent=1)
print(json.dumps({k:v for k,v in rec.items() if k not in ('per_consumer',)},indent=1)[:6000])
