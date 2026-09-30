"""H-23A reassignment ledger (prereg section 19) over the H23-ON facts of the scanned consumers (e3h23/<tag>/.refs/*/on.facts.json):
a versioned local name `x__vK` marks the K-th straight-line write of x under the narrowed seam. Per version K >= 1 whose
predecessor (x__v(K-1), or x for K = 1) was TRACKED (acquired / a fresh call result in this body):
  overwrite_after_dispose : a `release` of the predecessor precedes the first op of version K in emission order
  overwrite_live_resource : no such release (the predecessor's obligation is still open at the write)
A version that is acquired but never referenced again = the write itself is the last event of the predecessor's life.
Non-acquire writes (null / borrowed / other) leave no trace in the facts (the untracked version's references are
dropped); they are counted from the extractor census counters (write_null / write_other / write_firstparty) per
consumer. branch_overwrite / loop_overwrite = locals excluded by the narrowing (excluded_nested_write / excluded_loop_write).
alias_before_overwrite: an `alias` op whose source is a predecessor version that is later overwritten."""
import json, glob, os, re, collections, sys
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; E=f'{S}/lab/sc/e3h23'
V=re.compile(r'^(.*)__v(\d+)$')
def flat(seq, out):
    for o in seq:
        if not isinstance(o,dict): continue
        out.append(o)
        for k in ('then','else','body'):
            if isinstance(o.get(k),list): flat(o[k],out)
def names_of(o):
    ns=[]
    for k in ('var','src','result'):
        if isinstance(o.get(k),str): ns.append(o[k])
    for k in ('args','results','values'):
        if isinstance(o.get(k),list): ns+= [x for x in o[k] if isinstance(x,str)]
    return ns
ledger=collections.Counter(); sites=[]
for f in sorted(glob.glob(f'{E}/*/.refs/*/on.facts.json')):
    tag=f.split('/')[-4]; d=json.load(open(f))
    for fn in d.get('functions',[]):
        ops=[]; flat(fn.get('body',[]),ops)
        if not any('__v' in n for o in ops for n in names_of(o)): continue
        versions=collections.defaultdict(set)
        for o in ops:
            for n in names_of(o):
                m=V.match(n)
                if m: versions[m.group(1)].add(int(m.group(2)))
        for base,ks in versions.items():
            for k in sorted(ks):
                pred = base if k==1 else f'{base}__v{k-1}'
                first_k = next((i for i,o in enumerate(ops) if f'{base}__v{k}' in names_of(o)), None)
                if first_k is None: continue
                pred_tracked = any((o.get('op')=='acquire' and o.get('var')==pred) or (o.get('op')=='call' and o.get('result')==pred) for o in ops[:first_k])
                if not pred_tracked:
                    ledger['overwrite_of_untracked_or_borrowed_predecessor']+=1; continue
                released = any(o.get('op')=='release' and o.get('var')==pred for o in ops[:first_k])
                aliased = any(o.get('op') in ('alias','alias_join') and pred in names_of(o) for o in ops[:first_k])
                cat = 'overwrite_after_dispose' if released else 'overwrite_live_resource'
                ledger[cat]+=1
                if aliased: ledger['alias_before_overwrite']+=1
                sites.append({'consumer':tag,'function':fn.get('name'),'file':os.path.relpath(fn.get('file',''),f'{E}/{tag}') if fn.get('file') else None,'local':base,'version':k,'category':cat,'aliased':aliased,'write_line':next((o.get('line') for o in ops if o.get('op') in ('acquire','call') and (o.get('var')==f'{base}__v{k}' or o.get('result')==f'{base}__v{k}')),None)})
# census counters (extractor, ON runs) per consumer
cnt=collections.Counter()
for f in sorted(glob.glob(f'{S}/lab/sc/e2h23/*.e2.json')):
    b=json.load(open(f))
    for l in b.get('h23_census',[]):
        for kv in l.split()[1:]:
            k,v=kv.split('='); cnt[k]+=int(v)
out={'schema':'own.net/h23/reassignment-ledger/v1','counter_semantics':'excluded_loop_write / excluded_nested_write count LOCALS whose writes are all simple-assignment statements and at least one is loop- / block-nested; a local with a disqualifying write (compound, write inside an expression, deconstruction, ++/--, ref/out, lambda) is excluded silently in every build, so these counters are lower bounds (lab/h23/cnt/results.json); write_* counters are per WRITE on the locals the seam versions','from_facts':dict(ledger),'sites':sites,
     'from_extractor_counters_all_consumers':dict(cnt),
     'mapping':{'overwrite_with_null':cnt.get('write_null',0),'overwrite_with_borrowed_or_other':cnt.get('write_other',0)+cnt.get('write_other_nested',0),'overwrite_with_first_party_factory_result':cnt.get('write_firstparty',0)+cnt.get('write_firstparty_nested',0),'acquire_shaped_straight_line_writes':cnt.get('write_acquire',0),'acquire_shaped_nested_writes_seen_before_narrowing':cnt.get('write_acquire_nested',0),'branch_overwrite_locals_excluded':cnt.get('excluded_nested_write',0),'loop_overwrite_locals_excluded':cnt.get('excluded_loop_write',0),'candidates_minted_by_assignment':cnt.get('candidate_by_assignment',0),'declared_candidates_versioned':cnt.get('versioned_declared_candidate',0),'dropped_untracked_refs':cnt.get('dropped_untracked_ref',0)}}
json.dump(out,open(f'{S}/lab/sc/h23-reassign-ledger.json','w'),indent=1)
print(json.dumps({k:v for k,v in out.items() if k!='sites'},indent=1)); print('sites',len(sites))
for s in sites[:40]: print(' ',s)
