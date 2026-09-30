import json, hashlib, collections
def load(path):
    d=json.load(open(path)); by=collections.defaultdict(list)
    for r in d['records']: by[r['metadata_name']].append(r)
    for t,hsh in d.get('cctors',{}).items(): by[t+'::.cctor'].append({'metadata_name':t+'::.cctor','il_hash':hsh,'callees':[],'external_callees':[],'ret_disposable':True,'ret_is_type_parameter':False,'static_field_types':[]})
    return d, by
def meta_name(by, callable_):
    for k,v in by.items():
        if v and v[0].get('callable')==callable_: return k
    return None
def closure(name, dumps, typed, seen=None):
    seen=set() if seen is None else seen
    if name in seen: return seen
    seen.add(name); recs=None
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
    cl=closure(name, dumps, typed); parts=[]; unres=0
    for n in sorted(cl):
        recs=None
        for by in dumps:
            if n in by: recs=by[n]; break
        if recs is None: parts.append(n+'=EXTERNAL_UNRESOLVED'); unres+=1; continue
        hs='|'.join(sorted((x['il_hash'] or 'NOBODY') for x in recs)); parts.append(n+'='+hs); unres+= ('NOBODY' in hs)
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()[:16], len(cl), unres
