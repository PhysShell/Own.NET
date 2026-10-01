"""H-27 step 4 census aggregation (draft record + the LEAK_CANDIDATE list for the manual read). Reads lab/h27s4/census/*.h27.json
(the step-4 seam) and lab/h27s4/census2/*.h26b.json (the corrected H-26B seam, same pass): production, TFM-collapsed per
(consumer, file, line, callable); class distribution for the frozen pair (sync twins descriptive); the cross-check of the shared
sites (sink, using_declaration, returned/stored transfer) -> any disagreement = EXPERIMENT_INVALID; the v2 step-3 value re-derived
here independently of h26bagg_v2 (must agree). Writes lab/h27s4/h27-step4-draft.json and lab/h27s4/leak-candidates.json."""
import json, glob, collections, re
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
FRAMEWORK=re.compile(r'^(System(\.|$)|Microsoft\.Extensions\.|Microsoft\.AspNetCore(\.|$)|netstandard|mscorlib|Microsoft\.CSharp)')
U={}; per={}
for f in sorted(glob.glob(f'{S}/lab/h27s4/census/*.h27.json')):
    d=json.load(open(f)); per[d['repo']]={'units':d['units'],'extractor_failures':d['extractor_failures'],'seconds':d['seconds'],'sites_raw':len(d['records'])}
    for r in d['records']: U.setdefault((d['repo'],r['file'],r['line'],r['callable']),dict(r,repo=d['repo']))
U2={}
for f in sorted(glob.glob(f'{S}/lab/h27s4/census2/*.h26b.json')):
    d=json.load(open(f))
    for r in d['records']: U2.setdefault((d['repo'],r['file'],r['line'],r['callable']),dict(r,repo=d['repo']))
UA=list(U.values()); prod=[r for r in UA if r['kind']=='production']; pair=[r for r in prod if not r['sync_twin']]; twin=[r for r in prod if r['sync_twin']]
# cross-check on the shared sites (the H-26B seam records only library callables with a disposable result; the H-27 seam records the pair / twins of any declaring type)
shared=[(k,U[k],U2[k]) for k in U if k in U2]; dis=[]
for k,a,b in shared:
    ta=sorted(x for x in a['transferred'] if x in ('returned','stored')); tb=sorted(x for x in b['transferred'] if x in ('returned','stored'))
    if a['sink']!=b['sink'] or bool(a['using_declaration'])!=bool(b['using_declaration']) or ta!=tb: dis.append({'key':list(k),'h27':{'sink':a['sink'],'using':a['using_declaration'],'xfer':ta},'h26b_v2':{'sink':b['sink'],'using':b['using_declaration'],'xfer':tb}})
# the v2 step-3 value, re-derived from the H-26B v2 seam (frozen definition: non-using, non-transferred (returned/stored), local sink, frozen pair)
P2=re.compile(r'\.(ExecuteReaderAsync|BeginTransactionAsync)/')
v2=[r for r in U2.values() if r['kind']=='production' and P2.search(r['callable']) and not r['using_declaration'] and not any(x in ('returned','stored') for x in r['transferred']) and r['sink'] in ('local_declaration','local_assignment')]
# the same value from the H-27 seam's own fields (must agree with v2)
v27all=[r for r in pair if not r['using_declaration'] and not any(x in ('returned','stored') for x in r['transferred']) and r['sink'] in ('local_declaration','local_assignment')]   # the frozen value definition on the raw transfer field (handle_release ranks an explicit release above TRANSFERRED, so it is not the value filter)
# the H-26B seam records library / framework callables only (declaring assembly outside the compilation); the H-27 seam records the pair of ANY declaring type, first-party included: the value comparison is made on the shared (library) population, the first-party remainder is reported
v27=[r for r in v27all if (r['repo'],r['file'],r['line'],r['callable']) in U2]; v27fp=[r for r in v27all if (r['repo'],r['file'],r['line'],r['callable']) not in U2]
def cnt(rs,k): return dict(collections.Counter(r[k] for r in rs))
cls=cnt(pair,'site_class'); leak=[r for r in pair if r['site_class']=='LEAK_CANDIDATE']
rec={'consumers':len(per),'units':sum(v['units'] for v in per.values()),'extractor_failures':sum(v['extractor_failures'] for v in per.values()),'sites_raw':sum(v['sites_raw'] for v in per.values()),'sites_unique':len(UA),'production_unique':len(prod),
 'frozen_pair_production':len(pair),'sync_twin_production':len(twin),'class_distribution_pair':cls,'class_distribution_twins':cnt(twin,'site_class'),
 'handle_release_pair':cnt(pair,'handle_release'),'receiver_lifetime_pair':cnt(pair,'receiver_lifetime'),'receiver_kind_pair':cnt(pair,'receiver_kind'),
 'value_sites_pair_h27_library_callables':len(v27),'value_sites_pair_h27_first_party_callables':len(v27fp),'value_sites_pair_h26b_v2':len(v2),'value_agreement':len(v27)==len(v2) and {(r['repo'],r['file'],r['line'],r['callable']) for r in v27}=={(r['repo'],r['file'],r['line'],r['callable']) for r in v2},
 'value_sites_by_class':cnt(v27,'site_class'),'value_sites_by_handle_release':cnt(v27,'handle_release'),'value_sites_first_party_by_class':cnt(v27fp,'site_class'),
 'value_sites_not_released':[{k:r.get(k) for k in ('repo','file','line','member','callable','site_class','handle_release','transferred','receiver_kind','receiver_static_type','receiver_lifetime','awaited')} for r in v27all if r['site_class']!='RELEASED'],
 'cross_check':{'shared_sites':len(shared),'disagreements':len(dis),'verdict':'OK' if not dis else 'EXPERIMENT_INVALID','examples':dis[:20]},
 'leak_candidates_pair_production':len(leak),'leak_by_callable':cnt(leak,'callable'),'leak_by_consumer':cnt(leak,'repo'),'leak_by_receiver_kind':cnt(leak,'receiver_kind'),'leak_connection_using_flag':cnt(leak,'connection_local_released_by_using_in_member'),
 'per_consumer':per}
json.dump(rec,open(f'{S}/lab/h27s4/h27-step4-draft.json','w'),indent=1)
json.dump([{k:r.get(k) for k in ('repo','file','line','member','callable','declaring_assembly','sink','handle_release','transferred','receiver_kind','receiver_static_type','receiver_lifetime','connection_local_released_by_using_in_member','project','tfm')} for r in sorted(leak,key=lambda r:(r['repo'],r['file'],r['line']))],open(f'{S}/lab/h27s4/leak-candidates.json','w'),indent=1)
print(json.dumps({k:v for k,v in rec.items() if k not in ('per_consumer',)},indent=1)[:5000])
