"""Stage D ranking arms over the frozen candidate universe: A names/signature, C relational rules (CT gate0 rules,
frozen), D logistic regression (CT features, trained on the 131 CT positives of the OTHER libraries: library holdout),
U usage share (from usage-share.json when present). Outputs ranked lists per arm; no labels are used for ranking."""
import json, os, math, collections, sys
sys.path.insert(0, '/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad/lab/ct')
import numpy as np
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'; C=f'{S}/lab/ct'
uni=json.load(open(f'{S}/lab/sc/stagec-universe.json'))['universe']
TOK=['Create','Open','Decode','From','Begin','Execute','Push','Acquire','Connect','Load','Read','Parse','Build','Clone','Copy','New','To','As','Get']
NAMETOK=TOK+['Add','With','Set','Try','Make','Start','Write','Encode','Register','Find','Select','Take','Rent','Lease','Compile','Wrap']
def feats(r):
    br=r.get('before_ret',{})
    x=[1.0, float(r['is_static']), float(r['ret_is_declaring_type']), float(r['ret_is_interface']), float(r['ret_is_abstract']), float(r['declaring_type_disposable']),
       float(r['declaring_type_is_static']), float(r['declaring_type_has_finalizer']), float(r['declaring_type_is_safehandle']), float(r['has_bool_param']), float(r['has_disposable_param']),
       float(r['has_string_param']), float(r['has_stream_param']), float(r['is_getter']), float(r['is_virtual']), float(r['is_extension']), float(r['ret_async_wrapped']), float(r['is_pinvoke']),
       float(r['newobj_disposable']>0), math.log1p(r['newobj_disposable']), float(r['calls_disposable_returning']>0), math.log1p(r['calls_disposable_returning']), float(r['calls_dispose']>0),
       float(r['calls_pinvoke']>0), float(r['stfld_disposable']>0), float(r['ldfld_disposable']>0), float(r['ldsfld_disposable']>0), float(r['stsfld_disposable']>0),
       float(br.get('newobj',0)>0), float(br.get('call',0)>0)+float(br.get('callvirt',0)>0), float(br.get('ldfld',0)>0), float(br.get('ldsfld',0)>0), float(br.get('ldarg',0)>0)+float(br.get('ldarg.0',0)>0),
       float(any(k.startswith('ldloc') for k in br)), float(r['throws']>0), math.log1p(r['il_size']), math.log1p(r['arity']), float(r['has_body'])]
    return x+[float(r['name_token']==t) for t in NAMETOK]
def scoreA(r): return 1.0 if (r['name_token'] in TOK and r['ret_disposable'] and not r['is_getter']) else 0.0
def scoreRules(r):
    br=r.get('before_ret',{}); s=0.0
    if r['is_getter']: s-=2
    if r['newobj_disposable']>0: s+=2
    if br.get('newobj',0)>0: s+=2
    if r['calls_disposable_returning']>0 and (br.get('call',0)+br.get('callvirt',0))>0: s+=1
    if r['ldfld_disposable']>0 or r['ldsfld_disposable']>0: s-=1
    if br.get('ldfld',0)>0 or br.get('ldsfld',0)>0: s-=2
    if r['ret_is_declaring_type'] and r['is_static']: s+=1
    if r['calls_pinvoke']>0: s+=0.5
    if r['is_pinvoke']: s-=1
    return s
def train_lr(X,y,l2=1.0,iters=400,lr=0.1):
    mu=X.mean(0); sd=X.std(0)+1e-6; Xs=(X-mu)/sd; Xs[:,0]=1.0; w=np.zeros(X.shape[1]); npos=y.sum(); wpos=(len(y)-npos)/max(npos,1); sw=np.where(y==1,wpos,1.0)
    for _ in range(iters):
        p=1/(1+np.exp(-Xs@w)); g=Xs.T@((p-y)*sw)/len(y)+l2*w/len(y); w-=lr*g
    return (w,mu,sd)
def predict(m,X): w,mu,sd=m; Xs=(X-mu)/sd; Xs[:,0]=1.0; return Xs@w
# relation records for the universe (new dumps) and the CT training set (old dumps + CT positives)
rel={}
for pid in {u['package'] for u in uni}:
    for r in json.load(open(f'{S}/lab/sc/rel/rel-{pid}.json'))['records']: rel.setdefault(r['callable'],[]).append(r)
usage={}
if os.path.exists(f'{S}/lab/sc/usage-share.json'): usage={r['callable']:r for r in json.load(open(f'{S}/lab/sc/usage-share.json'))['rows']}
# training data: CT dumps of the 22 libraries except the candidate's own library (library holdout per candidate library)
train={}
import glob
for f in glob.glob(f'{C}/rel-*.json'):
    pid=os.path.basename(f)[4:-5]
    if '@' in pid or not os.path.exists(f'{D}/libs/{pid}/rows-applied.json'): continue
    pos={e['callable'] for e in json.load(open(f'{D}/libs/{pid}/rows-applied.json'))['entries'] if e['effect']=='return_fresh_owned'}
    recs=[r for r in json.load(open(f))['records'] if r['ret_disposable']]
    if recs: train[pid]=(np.array([feats(r) for r in recs]), np.array([1.0 if r['callable'] in pos else 0.0 for r in recs]))
models={}
for held in {u['package'] for u in uni}:
    X=np.vstack([v[0] for p,v in train.items() if p!=held]); y=np.concatenate([v[1] for p,v in train.items() if p!=held]); models[held]=train_lr(X,y)
ranked={'A':[],'C':[],'D':[],'U':[]}
for u in uni:
    recs=rel.get(u['callable'],[])
    if not recs: continue
    a=max(scoreA(r) for r in recs); c=max(scoreRules(r) for r in recs); d=float(max(predict(models[u['package']],np.array([feats(r)])) [0] for r in recs))
    us=usage.get(u['callable'],{}).get('using_share')
    ranked['A'].append((u['callable'],a,u['matches'])); ranked['C'].append((u['callable'],c,u['matches'])); ranked['D'].append((u['callable'],d,u['matches']))
    if us is not None: ranked['U'].append((u['callable'],us,u['matches']))
for k in ranked: ranked[k].sort(key=lambda t:(-t[1],-t[2]))   # ties broken by public use (frozen, label-free)
json.dump(ranked,open(f'{S}/lab/sc/staged-ranked.json','w'),indent=1)
for k in ranked: print(k, [(c.split('.')[-2]+'.'+c.split('.')[-1], round(s,2)) for c,s,_ in ranked[k][:12]])
