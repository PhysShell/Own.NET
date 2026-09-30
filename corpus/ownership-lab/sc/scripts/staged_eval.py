"""Stage D metrics: per arm, walk its ranked list in order; each candidate with a witness verdict counts as one execution
(shared candidates executed once, credited to every arm that ranks them within budget); validated useful rows per 10 and
per 25 executions; contradictions (arm proposed fresh, witness cached); inconclusive cost (environment errors, null
results, unwitnessable). Label classes follow the frozen prereg: VALIDATED_FRESH / VALIDATED_SHARED_OR_CACHED /
INCONCLUSIVE / UNWITNESSABLE. Build failures are classified from the compiler diagnostic (never re-labelled by hand)."""
import json, collections, os, re
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
ranked=json.load(open(f'{S}/lab/sc/staged-ranked.json')); res={r['callable']:r for r in json.load(open(f'{S}/lab/sc/witness-results.json'))}
routed=json.load(open(f'{S}/lab/sc/witsyn-rows.json'))['routed']; llm=json.load(open(f'{S}/lab/sc/llm-arm-B.json'))['candidates'] if os.path.exists(f'{S}/lab/sc/llm-arm-B.json') else []
ranked['B']=[(c,1.0,0) for c in llm]
def label(r):
    v=r['verdict']
    if v=='fresh': return 'VALIDATED_FRESH'
    if v=='cached': return 'INCONCLUSIVE:reused-instance(sequential mode: the same object handed out again after disposal is pooling/reuse, not sharing)' if r.get('mode')=='sequential' else 'VALIDATED_SHARED_OR_CACHED'
    if v in ('inconclusive','null-result','environment-error'): return 'INCONCLUSIVE:'+v
    if v=='build-or-run-error':
        e=r.get('stderr','')
        if re.search(r'error CS1061|error CS0117|error CS0122',e): return 'UNWITNESSABLE:ABSENT_OR_INACCESSIBLE_IN_TESTED_BUILD'
        if re.search(r'error CS1620|error CS1503|error CS1501|error CS0121|error CS1729|error CS0029|error CS0266|error CS8917',e): return 'UNWITNESSABLE:ARGS'
        if 'error CS' in e: return 'UNWITNESSABLE:BUILD'
        return 'INCONCLUSIVE:runtime-error'
    return 'INCONCLUSIVE:'+v
labels={c:label(r) for c,r in res.items()}
out={}
for arm,lst in ranked.items():
    execs=[]
    for c,score,_ in lst:
        if c in res: execs.append((c,labels[c]))
        elif c in routed: execs.append((c,'UNWITNESSABLE:'+routed[c].split(':')[0]))
        if len(execs)>=25: break
    def tally(n):
        e=execs[:n]; return {'executions':len(e),'validated_fresh':sum(1 for _,v in e if v=='VALIDATED_FRESH'),'contradicted_cached':sum(1 for _,v in e if v=='VALIDATED_SHARED_OR_CACHED'),'inconclusive':sum(1 for _,v in e if v.startswith('INCONCLUSIVE')),'unwitnessable':sum(1 for _,v in e if v.startswith('UNWITNESSABLE'))}
    out[arm]={'at_10':tally(10),'at_25':tally(25),'order':execs[:25]}
tot=collections.Counter(labels.values()); tot.update('UNWITNESSABLE:'+v.split(':')[0] for v in routed.values())
out['_universe_totals']={'candidates':len(res)+len(routed),'executed':len(res),'labels':dict(tot)}
json.dump(out,open(f'{S}/lab/sc/staged-metrics.json','w'),indent=1)
for arm in out:
    if arm.startswith('_'): print(arm,out[arm]); continue
    print(arm, 'at10', out[arm]['at_10'], 'at25', out[arm]['at_25'])
