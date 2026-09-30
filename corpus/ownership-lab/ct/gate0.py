"""CT Gate 0: relational signal for trusted-row candidates. Baselines A (name/signature), B (LLM S3 candidates),
C (cheap relational: rules + logistic regression, numpy only). LIBRARY HOLDOUT = leave-one-library-out over the
libraries with >= 1 applied row. Metrics: known-positive recall@k at the callable level; top-k precision; and the
ranked UNLABELLED candidates per arm for validation (novelty queue)."""
import json, glob, os, math, random, collections, re, sys
import numpy as np
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'; C=f'{S}/lab/ct'
TOK=['Create','Open','Decode','From','Begin','Execute','Push','Acquire','Connect','Load','Read','Parse','Build','Clone','Copy','New','To','As','Get']  # frozen A tokens
NAMETOK=TOK+['Add','With','Set','Try','Make','Start','Write','Encode','Register','Find','Select','Take','Rent','Lease','Compile','Wrap']
libs={}
for f in sorted(glob.glob(f'{C}/rel-*.json')):
    pid=os.path.basename(f)[4:-5]
    if '@' in pid: continue
    L=f'{D}/libs/{pid}'
    if not os.path.exists(f'{L}/rows-applied.json'): continue
    d=json.load(open(f)); rows=json.load(open(f'{L}/rows-applied.json'))['entries']
    pos={e['callable'] for e in rows if e['effect']=='return_fresh_owned'}
    s3=json.load(open(f'{L}/s3-llm-candidates.json')) if os.path.exists(f'{L}/s3-llm-candidates.json') else {}
    llm={r['callable'] for r in s3.get('suggested_rows',[]) if r.get('effect')=='return_fresh_owned'}
    negw={r['callable'] for r in s3.get('suggested_negatives',[])}
    ds=json.load(open(f'{L}/derive-summary.json')) if os.path.exists(f'{L}/derive-summary.json') else {}
    e1seen=set(x.split('(')[0] for x in ds.get('fresh_summaries_all',[]))
    recs=[r for r in d['records'] if r['ret_disposable'] and not r['is_getter'] or (r['ret_disposable'] and r['is_getter'])]
    libs[pid]={'records':[r for r in d['records'] if r['ret_disposable']],'pos':pos,'llm':llm,'negw':negw,'e1seen':e1seen,'mvid':d['mvid']}
print('libraries',len(libs),'with positives',sum(1 for v in libs.values() if v['pos']))
def feats(r):
    br=r.get('before_ret',{})
    x=[1.0, float(r['is_static']), float(r['ret_is_declaring_type']), float(r['ret_is_interface']), float(r['ret_is_abstract']), float(r['declaring_type_disposable']),
       float(r['declaring_type_is_static']), float(r['declaring_type_has_finalizer']), float(r['declaring_type_is_safehandle']), float(r['has_bool_param']), float(r['has_disposable_param']),
       float(r['has_string_param']), float(r['has_stream_param']), float(r['is_getter']), float(r['is_virtual']), float(r['is_extension']), float(r['ret_async_wrapped']), float(r['is_pinvoke']),
       float(r['newobj_disposable']>0), math.log1p(r['newobj_disposable']), float(r['calls_disposable_returning']>0), math.log1p(r['calls_disposable_returning']), float(r['calls_dispose']>0),
       float(r['calls_pinvoke']>0), float(r['stfld_disposable']>0), float(r['ldfld_disposable']>0), float(r['ldsfld_disposable']>0), float(r['stsfld_disposable']>0),
       float(br.get('newobj',0)>0), float(br.get('call',0)>0)+float(br.get('callvirt',0)>0), float(br.get('ldfld',0)>0), float(br.get('ldsfld',0)>0), float(br.get('ldarg',0)>0)+float(br.get('ldarg.0',0)>0),
       float(any(k.startswith('ldloc') for k in br)), float(r['throws']>0), math.log1p(r['il_size']), math.log1p(r['arity']), float(r['has_body'])]
    x+= [float(r['name_token']==t) for t in NAMETOK]
    return x
FN=['bias','static','ret_decl','ret_iface','ret_abstract','decl_disp','decl_static','decl_final','decl_safeh','bool','dispparam','string','stream','getter','virtual','ext','async','pinvoke','newobj_d','log_newobj_d','calls_d','log_calls_d','calls_dispose','calls_pinvoke','stfld_d','ldfld_d','ldsfld_d','stsfld_d','ret<-newobj','ret<-call','ret<-ldfld','ret<-ldsfld','ret<-ldarg','ret<-ldloc','throws','log_il','log_arity','has_body']+['tok_'+t for t in NAMETOK]
def scoreA(r): return (1.0 if (r['name_token'] in TOK and r['ret_disposable'] and not r['is_getter']) else 0.0)
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
    mu=X.mean(0); sd=X.std(0)+1e-6; Xs=(X-mu)/sd; Xs[:,0]=1.0
    w=np.zeros(X.shape[1]); npos=y.sum(); nneg=len(y)-npos; wpos=nneg/max(npos,1)
    sw=np.where(y==1,wpos,1.0)
    for _ in range(iters):
        p=1/(1+np.exp(-Xs@w)); g=Xs.T@((p-y)*sw)/len(y)+l2*w/len(y); w-=lr*g
    return (w,mu,sd)
def predict(m,X):
    w,mu,sd=m; Xs=(X-mu)/sd; Xs[:,0]=1.0; return Xs@w
def rank_eval(scores_by_callable, pos, ks=(10,25), seeds=20):
    # scores_by_callable: dict callable -> score (max over overloads); ties broken randomly, averaged over seeds
    out={}
    for k in ks:
        acc=0.0; prec=0.0
        for seed in range(seeds):
            rnd=random.Random(seed); items=list(scores_by_callable.items()); rnd.shuffle(items)
            items.sort(key=lambda kv: -kv[1]); top=[c for c,_ in items[:k]]
            hit=sum(1 for c in top if c in pos); acc+=hit/max(len(pos),1); prec+=hit/k
        out[f'recall@{k}']=round(acc/seeds,3); out[f'prec@{k}']=round(prec/seeds,3)
    return out
res={}; queues={}
libs_pos=[p for p,v in libs.items() if v['pos'] and v['records']]
allX={p:np.array([feats(r) for r in v['records']]) for p,v in libs.items() if v['records']}
ally={p:np.array([1.0 if r['callable'] in v['pos'] else 0.0 for r in v['records']]) for p,v in libs.items() if v['records']}
for held in libs_pos:
    trainX=np.vstack([allX[p] for p in allX if p!=held]); trainy=np.concatenate([ally[p] for p in ally if p!=held])
    model=train_lr(trainX,trainy)
    recs=libs[held]['records']; pos=libs[held]['pos']; surface={r['callable'] for r in recs}
    sc={'A':collections.defaultdict(float),'B':collections.defaultdict(float),'C_rules':collections.defaultdict(float),'C_lr':collections.defaultdict(float)}
    pc=predict(model,allX[held])
    for i,r in enumerate(recs):
        c=r['callable']; sc['A'][c]=max(sc['A'][c],scoreA(r)); sc['B'][c]=1.0 if c in libs[held]['llm'] else 0.0
        sc['C_rules'][c]=max(sc['C_rules'].get(c,-9),scoreRules(r)); sc['C_lr'][c]=max(sc['C_lr'].get(c,-99),float(pc[i]))
    for c in surface:
        for a in sc: sc[a].setdefault(c,0.0)
    r={'surface_callables':len(surface),'positives':len(pos),'positives_on_surface':len(pos&surface)}
    for a in sc: r[a]=rank_eval(sc[a],pos&surface)
    res[held]=r
    # novelty queue: top UNLABELLED (not positive, not LLM-suggested, not E1-seen) per arm
    unl=lambda c: c not in pos and c not in libs[held]['llm'] and c not in libs[held]['e1seen'] and c not in libs[held]['negw']
    queues[held]={a:[c for c,_ in sorted(sc[a].items(),key=lambda kv:-kv[1]) if unl(c)][:5] for a in ('A','C_rules','C_lr')}
    queues[held]['B_unvalidated']=sorted(libs[held]['llm']-pos)[:5]
def agg(arm,metric): 
    v=[res[p][arm][metric] for p in res]; return round(sum(v)/len(v),3)
summary={arm:{m:agg(arm,m) for m in ('recall@10','recall@25','prec@10','prec@25')} for arm in ('A','B','C_rules','C_lr')}
# pooled: over all held-out libraries, positives found in top-10 / total positives
pool={}
for arm in ('A','B','C_rules','C_lr'):
    pool[arm]={}
    for k in (10,25):
        tot=sum(res[p]['positives_on_surface'] for p in res); found=sum(res[p][arm][f'recall@{k}']*res[p]['positives_on_surface'] for p in res)
        pool[arm][f'pooled_recall@{k}']=round(found/tot,3) if tot else None
# feature weights of a model trained on everything (for the record)
modelAll=train_lr(np.vstack([allX[p] for p in allX]),np.concatenate([ally[p] for p in ally]))
w=modelAll[0]; top=sorted(zip(FN,w),key=lambda t:-abs(t[1]))[:14]
out={'libraries_evaluated':len(res),'per_library':res,'mean_over_libraries':summary,'pooled':pool,'lr_top_weights_all_data':[(n,round(float(x),3)) for n,x in top],'novelty_queues':queues,'surface_total':sum(len(v['records']) for v in libs.values()),'positives_total':sum(len(v['pos']) for v in libs.values())}
json.dump(out,open(f'{C}/gate0-results.json','w'),indent=1)
print(json.dumps({'mean':summary,'pooled':pool,'weights':out['lr_top_weights_all_data']},indent=1))
