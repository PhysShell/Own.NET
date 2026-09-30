"""Stage C: the non-provable remainder and the preregistered candidate filter (sc-prereg-v1 C): factory-surface callables
of the 8 libraries without a whole-source row, materially used (>= 10 public matches), resource-relevant; filters: bodiless
-> NEEDS_IMPLEMENTATION_EVIDENCE; getters -> ALIAS_OR_SHARED; internal namespaces excluded; effect-compatible return."""
import json, os, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'
LIBS=['SkiaSharp','RabbitMQ.Client','MailKit','StackExchange.Redis','Npgsql','MQTTnet','SSH.NET','LibGit2Sharp']
cen={r['callable']:r for r in json.load(open(f'{S}/lab/sc/surface-census.json'))['rows']}
universe=[]; removed=collections.Counter(); classes=collections.defaultdict(list)
for pid in LIBS:
    L=f'{D}/libs/{pid}'; w=json.load(open(f'{L}/rows-whole.json')); api=json.load(open(f'{L}/api.json'))
    rows={r['callable'] for r in w['rows']}; rel=json.load(open(f'{S}/lab/sc/rel/rel-{pid}.json'))['records']
    byname=collections.defaultdict(list)
    for r in rel: byname[r['callable']].append(r)
    seen=set()
    for f in api['factories']:
        c=f['callable']
        if c in rows or c in seen: continue
        seen.add(c)
        m=(cen.get(c) or {}).get('line_matches',0)
        if m<10: removed['not_material_use(<10 matches)']+=1; continue
        recs=byname.get(c,[])
        if not recs: removed['no_reldump_record']+=1; continue
        if '.Internal' in c: removed['internal_namespace']+=1; continue
        if f.get('property') or all(r['is_getter'] for r in recs): classes['ALIAS_OR_SHARED'].append((pid,c,m)); removed['getter->ALIAS_OR_SHARED']+=1; continue
        if all(not r['has_body'] for r in recs): classes['NEEDS_IMPLEMENTATION_EVIDENCE'].append((pid,c,m)); removed['bodiless->NEEDS_IMPLEMENTATION_EVIDENCE']+=1; continue
        if not any(r['ret_disposable'] for r in recs): removed['return_not_effect_compatible']+=1; continue
        universe.append({'package':pid,'callable':c,'matches':m,'is_static':bool(f.get('is_static')),'async_wrapped':bool(f.get('async_wrapped')),'returns':f.get('returns'),'parameters':f.get('parameters'),'arity':f.get('arity')})
universe.sort(key=lambda x:-x['matches'])
out={'universe':universe,'removed_by_filter':dict(removed),'routed_classes':{k:v for k,v in classes.items()},'size':len(universe)}
json.dump(out,open(f'{S}/lab/sc/stagec-universe.json','w'),indent=1)
print('universe',len(universe),'removed',dict(removed)); [print(f"  {u['package']:20s} {u['callable']:70s} {u['matches']:5d} {'static' if u['is_static'] else 'inst'} {'async' if u['async_wrapped'] else ''}") for u in universe[:60]]
print('by package', collections.Counter(u['package'] for u in universe))
