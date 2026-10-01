"""H-29 census aggregation: un-awaited awaitable-returning invocations assigned to locals (form = local) with ZERO later references,
TFM-collapsed per (consumer, file, line, local); production; families A / B / OTHER; discards and statements descriptive. Writes
lab/h29/h29-draft.json and lab/h29/candidates.json (primary = production, form local, refs 0, family A or B, not in a lambda)."""
import json, glob, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
U={}; per={}
for f in sorted(glob.glob(f'{S}/lab/h29/census/*.h29.json')):
    d=json.load(open(f)); per[d['repo']]={'units':d['units'],'extractor_failures':d['extractor_failures'],'seconds':d['seconds'],'records_raw':len(d['records'])}
    for r in d['records']: U.setdefault((d['repo'],r['file'],r['line'],r['form'],r.get('local')),dict(r,repo=d['repo']))
UA=list(U.values()); prod=[r for r in UA if r['kind']=='production']
loc=[r for r in prod if r['form']=='local']; orphan=[r for r in loc if r['later_references']==0]
prim=[r for r in orphan if r['family'] in ('A_owned_result','B_protocol_lifecycle') and not r['in_lambda']]
disc=[r for r in prod if r['form']=='discard']; stmt=[r for r in prod if r['form']=='statement']
def cnt(rs,k): return dict(collections.Counter(r[k] for r in rs).most_common())
rec={'consumers':len(per),'units':sum(v['units'] for v in per.values()),'extractor_failures':sum(v['extractor_failures'] for v in per.values()),'records_raw':sum(v['records_raw'] for v in per.values()),'records_unique':len(UA),'production_unique':len(prod),
 'awaitable_locals_production':len(loc),'awaitable_locals_by_family':cnt(loc,'family'),'awaitable_locals_refs_distribution':dict(collections.Counter(min(r['later_references'],5) for r in loc)),
 'ORPHANS_zero_references':len(orphan),'orphans_by_family':cnt(orphan,'family'),'orphans_by_callee':dict(collections.Counter(r['callee'] for r in orphan).most_common(40)),'orphans_by_consumer':cnt(orphan,'repo'),'orphans_in_lambda':sum(1 for r in orphan if r['in_lambda']),'orphans_in_try':sum(1 for r in orphan if r['in_try']),'orphans_in_async_member':sum(1 for r in orphan if r['in_async_member']),
 'PRIMARY_family_A_or_B_not_lambda':len(prim),'primary_by_family':cnt(prim,'family'),'primary_lifecycle_members':sum(1 for r in prim if r.get('lifecycle_member')),'primary_by_callee':cnt(prim,'callee'),'primary_by_consumer':cnt(prim,'repo'),
 'discards_production':len(disc),'discards_by_family':cnt(disc,'family'),'discards_top_callees':dict(collections.Counter(r['callee'] for r in disc).most_common(15)),
 'statements_production':len(stmt),'statements_by_family':cnt(stmt,'family'),'statements_top_callees':dict(collections.Counter(r['callee'] for r in stmt).most_common(15)),
 'other_family_orphans_top_callees':dict(collections.Counter(r['callee'] for r in orphan if r['family']=='OTHER').most_common(25)),'per_consumer':per}
json.dump(rec,open(f'{S}/lab/h29/h29-draft.json','w'),indent=1)
json.dump([{k:r.get(k) for k in ('repo','file','line','member','method_key','local','callee','callee_assembly','callee_first_party','return_type','result_type','family','lifecycle_member','in_async_member','in_try','project','tfm')} for r in sorted(prim,key=lambda r:(r['repo'],r['file'],r['line']))],open(f'{S}/lab/h29/candidates.json','w'),indent=1)
print(json.dumps({k:v for k,v in rec.items() if k!='per_consumer'},indent=1)[:7000])
