"""A2: proof identities from RelDump relations. id_full(m) = H(il(m), sorted il of the transitive same-assembly callee
closure, plus external callee closures resolved in the dependency dumps); id_typed(m) = the same over callees whose
return type is disposable (the callees that can produce the returned object). Bodiless callees contribute a marker."""
import json, hashlib, sys, collections, time
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'
def load(path):
    d=json.load(open(path)); by=collections.defaultdict(list)
    for r in d['records']: by[r['metadata_name']].append(r)
    for t,hsh in d.get('cctors',{}).items(): by[t+'::.cctor'].append({'metadata_name':t+'::.cctor','il_hash':hsh,'callees':[],'external_callees':[],'ret_disposable':True,'ret_is_type_parameter':False,'static_field_types':[]})
    return d, by
def closure(name, dumps, typed, seen=None):
    """dumps: list of (by) dicts to resolve names; returns the set of (name, il_hash or 'NOBODY') reached"""
    seen=set() if seen is None else seen
    if name in seen: return seen
    seen.add(name)
    recs=None
    for by in dumps:
        if name in by: recs=by[name]; break
    if not recs: return seen
    for r in recs:
        for c in list(r['callees'])+list(r['external_callees'])+[t+'::.cctor' for t in r.get('static_field_types',[])]:
            if typed:
                crec=None
                for by in dumps:
                    if c in by: crec=by[c]; break
                if crec is not None and not any(x['ret_disposable'] or x.get('ret_is_type_parameter') for x in crec): continue
            closure(c, dumps, typed, seen)
    return seen
def ident(name, dumps, typed):
    cl=closure(name, dumps, typed); parts=[]
    for n in sorted(cl):
        recs=None
        for by in dumps:
            if n in by: recs=by[n]; break
        if recs is None: parts.append(n+'=EXTERNAL_UNRESOLVED'); continue
        parts.append(n+'='+'|'.join(sorted((x['il_hash'] or 'NOBODY') for x in recs)))
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()[:16], len(cl), sum(1 for p in parts if p.endswith('EXTERNAL_UNRESOLVED') or 'NOBODY' in p)
out={}
# --- A1 fixture sensitivity and no-op stability
A=f'{S}/lab/sc/a1/out'
_,cv1=load(f'{A}/rel-caller.v1.json'); _,hv1=load(f'{A}/rel-helper.v1.json'); _,hv1b=load(f'{A}/rel-helper.v1b.json'); _,hv2=load(f'{A}/rel-helper.v2.json')
sens=[]
for m in ['MakeDirect','MakeOneHop','MakeTwoHop','MakeVirtual','MakeViaProperty','MakeGeneric']:
    n='CallerLib.Caller::'+m
    f1,s1,u1=ident(n,[cv1,hv1],False); f2,s2,u2=ident(n,[cv1,hv2],False); f1b,_,_=ident(n,[cv1,hv1b],False)
    t1,ts1,_=ident(n,[cv1,hv1],True); t2,ts2,_=ident(n,[cv1,hv2],True)
    sens.append({'variant':m,'id_full_v1':f1,'id_full_v2':f2,'full_changes':f1!=f2,'id_full_size':s1,'unresolved_or_bodiless_in_slice':u1,'noop_rebuild_stable':f1==f1b,'id_typed_v1':t1,'id_typed_v2':t2,'typed_changes':t1!=t2,'id_typed_size':ts1})
out['a1_sensitivity']=sens
mv=lambda p: json.load(open(p))['mvid']
out['a1_noop_rebuild']={'helper_v1_mvid':mv(f'{A}/rel-helper.v1.json'),'helper_v1b_mvid':mv(f'{A}/rel-helper.v1b.json'),'il_hashes_identical':all((hv1[k][0]['il_hash']==hv1b[k][0]['il_hash']) for k in hv1)}
# --- SkiaSharp: identity size, TFM stability, fanout, time
def skia(tag): return load(f'{S}/lab/ct/relh-SkiaSharp@{tag}.json')[1]
t0=time.time(); tags=['3.119.4@net6.0','4.152.0@net6.0','4.153.1@net6.0','4.153.1@netstandard2.0']; ids={}; sizes={}
for tag in tags:
    by=skia(tag); ids[tag]={}; sizes[tag]=[]
    for n in by:
        if any(r['ret_disposable'] for r in by[n]):
            f,sz,_=ident(n,[by],False); t,tsz,_=ident(n,[by],True); ids[tag][n]=(f,t); sizes[tag].append((sz,tsz))
out['skia_derivation_seconds']=round(time.time()-t0,1)
rows=['SkiaSharp.SKBitmap::Decode','SkiaSharp.SKBitmap::FromImage','SkiaSharp.SKData::AsStream','SkiaSharp.SKFont::GetTextPath','SkiaSharp.SKPath::ParseSvgPathData','SkiaSharp.SKTypeface::ToFont']
def cmp(a,b):
    common=[n for n in ids[a] if n in ids[b]]
    return {'common':len(common),'full_changed':sum(1 for n in common if ids[a][n][0]!=ids[b][n][0]),'typed_changed':sum(1 for n in common if ids[a][n][1]!=ids[b][n][1]),
            'rows_full_changed':[n for n in rows if n in ids[a] and n in ids[b] and ids[a][n][0]!=ids[b][n][0]],'rows_typed_changed':[n for n in rows if n in ids[a] and n in ids[b] and ids[a][n][1]!=ids[b][n][1]]}
out['skia_tfm_stability_4.153.1_net6_vs_ns20']=cmp('4.153.1@net6.0','4.153.1@netstandard2.0')
out['skia_fanout_4.152.0_to_4.153.1']=cmp('4.152.0@net6.0','4.153.1@net6.0')
out['skia_fanout_3.119.4_to_4.153.1']=cmp('3.119.4@net6.0','4.153.1@net6.0')
import statistics
sz=sizes['4.153.1@net6.0']; out['skia_identity_size_4.153.1']={'surface_callables':len(sz),'full_mean':round(statistics.mean(s for s,_ in sz),1),'full_max':max(s for s,_ in sz),'typed_mean':round(statistics.mean(t for _,t in sz),1),'typed_max':max(t for _,t in sz)}
by=skia('4.153.1@net6.0'); out['skia_row_slices']={n:{'full_size':ident(n,[by],False)[1],'typed_size':ident(n,[by],True)[1],'typed_slice':sorted(closure(n,[by],True))[:12]} for n in rows if n in by}
json.dump(out,open(f'{S}/lab/sc/a2-results.json','w'),indent=1); print(json.dumps(out,indent=1)[:6000])
