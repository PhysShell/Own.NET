"""H-24 census aggregation and the record paper-eval/h24/h24-census-v1.json: per consumer and overall, the nested-write
disposable locals (raw per project/TFM and TFM-collapsed per (consumer, file, line, local)), admissible_strict / relaxed,
with >= 1 trusted-row write, all trusted-row, new_disposable only, mixed, the refusal reasons, depths, constructs; the
primary count of the frozen gate and the decision it dictates. Reads lab/h24/census/*.h24.json (written by h24census.py)
and the H-23A counters for the denominator."""
import json, glob, os, collections, datetime, subprocess
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'; R='/home/user/Own.NET'
TR={'trusted_row','new_disposable','owning_factory','first_party_factory'}
per={}; allrecs=[]
import sys
CD=sys.argv[1] if len(sys.argv)>1 else 'census'; VER=sys.argv[2] if len(sys.argv)>2 else 'v1'
for f in sorted(glob.glob(f'{S}/lab/h24/{CD}/*.h24.json')):
    d=json.load(open(f)); recs=d['records']
    for r in recs: r['repo']=d['repo']
    allrecs+=recs
    uniq={}
    for r in recs: uniq.setdefault((r['file'],r['line'],r['local']),r)
    U=list(uniq.values())
    def cnt(pred): return {'raw_project_tfm':sum(1 for r in recs if pred(r)),'unique_locals':sum(1 for r in U if pred(r))}
    prod=lambda r:r['kind']=='production'
    per[d['repo']]={'sha':d['sha'][:10],'units':d['units'],'extractor_failures':d['extractor_failures'],'seconds':d['seconds'],
      'nested_write_disposable_locals':cnt(lambda r:True),'production':cnt(prod),
      'admissible_strict_production':cnt(lambda r:prod(r) and r['admissible_strict']),'admissible_relaxed_production':cnt(lambda r:prod(r) and r['admissible_relaxed']),
      'admissible_strict_production_with_trusted_row_write':cnt(lambda r:prod(r) and r['admissible_strict'] and r['trusted_row_writes']>0),
      'admissible_relaxed_production_with_trusted_row_write':cnt(lambda r:prod(r) and r['admissible_relaxed'] and r['trusted_row_writes']>0),
      'admissible_strict_production_all_trusted_row':cnt(lambda r:prod(r) and r['admissible_strict'] and all(w['kind']=='trusted_row' for w in r['writes'])),
      'admissible_strict_production_new_disposable_only':cnt(lambda r:prod(r) and r['admissible_strict'] and all(w['kind']=='new_disposable' for w in r['writes'])),
      'admissible_strict_test':cnt(lambda r:r['kind']=='test' and r['admissible_strict']),
      'reasons_production':dict(collections.Counter(x for r in U if prod(r) for x in r['reasons'])),
      'constructs_production':dict(collections.Counter(r['construct'] for r in U if prod(r))),
      'depth_of_admissible_relaxed':dict(collections.Counter(str(r['depth']) for r in U if r['admissible_relaxed'])),
      'write_kinds_production':dict(collections.Counter(w['kind'] for r in U if prod(r) for w in r['writes']))}
# the H-23A denominator (excluded_nested_write per consumer, lower bound)
h23=json.load(open(f'{S}/lab/sc/h23-attrib.json')); den={}
for row in h23['per_consumer']:
    c=collections.Counter()
    b=json.load(open(f'{S}/lab/sc/e2h23/'+row['repo'].replace('/','__')+'.e2.json'))
    for l in b.get('h23_census',[]):
        for kv in l.split()[1:]:
            k,v=kv.split('='); c[k]+=int(v)
    den[row['repo']]={'excluded_nested_write':c.get('excluded_nested_write',0),'excluded_loop_write':c.get('excluded_loop_write',0),'trusted_rows_in_census':row['after_units']>0}
U_all={}
for r in allrecs: U_all.setdefault((r['repo'],r['file'],r['line'],r['local']),r)
UA=list(U_all.values()); prod=lambda r:r['kind']=='production'
primary=sum(1 for r in UA if prod(r) and r['admissible_strict'] and r['trusted_row_writes']>0)
tot={'consumers_censused':len(per),'units':sum(v['units'] for v in per.values()),'nested_write_disposable_locals_raw':len(allrecs),'nested_write_disposable_locals_unique':len(UA),
 'production_unique':sum(1 for r in UA if prod(r)),'admissible_strict_production_unique':sum(1 for r in UA if prod(r) and r['admissible_strict']),'admissible_relaxed_production_unique':sum(1 for r in UA if prod(r) and r['admissible_relaxed']),
 'PRIMARY_admissible_strict_production_with_trusted_row_write_unique':primary,'admissible_relaxed_production_with_trusted_row_write_unique':sum(1 for r in UA if prod(r) and r['admissible_relaxed'] and r['trusted_row_writes']>0),
 'admissible_strict_production_new_disposable_only_unique':sum(1 for r in UA if prod(r) and r['admissible_strict'] and all(w['kind']=='new_disposable' for w in r['writes'])),
 'admissible_strict_test_unique':sum(1 for r in UA if r['kind']=='test' and r['admissible_strict']),
 'reasons_production_unique':dict(collections.Counter(x for r in UA if prod(r) for x in r['reasons'])),
 'constructs_production_unique':dict(collections.Counter(r['construct'] for r in UA if prod(r))),
 'write_kinds_production_unique':dict(collections.Counter(w['kind'] for r in UA if prod(r) for w in r['writes'])),
 'h23a_denominator_excluded_nested_write_sum_17_consumers':sum(v['excluded_nested_write'] for v in den.values()),'h23a_denominator_8_censused':sum(den[k]['excluded_nested_write'] for k in per if k in den)}
# the dominant refusal class: try/finally initialisation (`T x = null; try { x = Create(); ... } finally { x?.Dispose(); }`)
tryc=[r for r in UA if prod(r) and r['construct']=='try']
try_breakdown={'production_unique':len(tryc),'single_write':sum(1 for r in tryc if r['write_count']==1),'single_write_null_or_no_initializer':sum(1 for r in tryc if r['write_count']==1 and r['initializer']=='none_or_null'),
 'single_write_null_init_fresh_owned':sum(1 for r in tryc if r['write_count']==1 and r['initializer']=='none_or_null' and r['writes'][0]['kind'] in TR),
 'single_write_null_init_trusted_row':sum(1 for r in tryc if r['write_count']==1 and r['initializer']=='none_or_null' and r['writes'][0]['kind']=='trusted_row'),
 'write_kinds':dict(collections.Counter(w['kind'] for r in tryc for w in r['writes'])),'write_count_distribution':dict(collections.Counter(str(r['write_count']) for r in tryc))}
tot['try_class_breakdown_production_unique']=try_breakdown
# what the non-fresh ('other') writes are syntactically / semantically (callee diagnostic of the corrected build):
# an AwaitExpression hides the invocation from every acquire predicate (the oracle sees `await X()` as not an invocation)
def other_class(c):
    if c is None: return 'no_diagnostic'
    if c.startswith('unresolved'): return 'unresolved'
    if '/' in c: return 'resolved_call_without_row:'+c.rsplit('/',1)[0].rsplit('.',1)[-1]
    return 'syntax:'+c
tot['other_write_classes_production_unique']=dict(collections.Counter(other_class(w.get('callee')) for r in UA if prod(r) for w in r['writes'] if w['kind']=='other'))
tot['await_wrapped_writes_production_unique']=sum(1 for r in UA if prod(r) for w in r['writes'] if w['kind']=='other' and w.get('callee')=='AwaitExpression')
decision=('KILL_BEFORE_IMPLEMENTATION' if primary<8 else 'CONTINUE_TO_FIXTURE_AND_LOWERING' if primary<20 else 'FULL_PATH') if VER!='v1' else 'DESCRIPTIVE_ONLY (as-is environment; the gate is evaluated on the corrected census, erratum 2)'
admissible_sites=[{k:r.get(k) for k in ('repo','file','line','local','type','member','construct','depth','writes','trusted_row_writes','refs_inside','admissible_strict','admissible_relaxed','project','tfm','kind')} for r in UA if r['admissible_relaxed']]
own=subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True).stdout.strip()
envs=sorted({json.load(open(f)).get('environment','?') for f in glob.glob(f'{S}/lab/h24/{CD}/*.h24.json')})
rec={'schema':'own.net/h24/census/'+VER,'environment':envs,'written_at_utc':datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),'track':'H-24 restricted single-obligation merge: the census-only admissibility gate (step 2 of the frozen order)',
 'anchors':{'prereg':'paper-eval/h24/h24-prereg-v1.json (e3298ed)','own_net_head_with_census_seam':own,'own_net_main':'fb06adc2beddd750e99a52ad8c1c8b5905602539 (untouched)','builds':'ext8m / ext10m from the census-seam commit; OFF facts byte-identical to the previous build on the fixture and the H-23A fixture; census on == census off byte-identical'},
 'seam':'OWEN_H24_CENSUS=<path>: H24Classify emits one JSON line per disposable local with nested simple-assignment writes; no lowering change; the oracle predicate is evaluated for the write kinds (hit-log shape merge)',
 'population':'the 8 frozen consumers with trusted rows, the SAME project/TFM units, reference directories and row files as the H-23A OFF/ON scans (751 units); the other 9 frozen consumers have no trusted rows and cannot contribute a trusted-row merge (their H-23A excluded_nested_write counters are listed for the denominator only)',
 'fixture_classification':'corpus/ownership-lab/h24/out/merge.h24.jsonl: P1 P2 P3 T4 T7 T8 T10 admissible_strict; T6 relaxed only; P4 (borrowed arm), P5 (prior live initializer), T1 (two writes on one arm), T2 (loop), T3 (try), T5 (null arm), T9 (not definitely assigned on exit), T11 (two constructs), T12 (write before the construct) refused with exactly the prereg reasons',
 'totals':tot,'per_consumer':per,'h23a_denominators':den,
 'gate':{'primary_count':primary,'rule':'< 8 KILL_BEFORE_IMPLEMENTATION; 8-19 CONTINUE_TO_FIXTURE_AND_LOWERING; >= 20 FULL_PATH (frozen in h24-prereg-v1.json before counting)','decision':decision},
 'admissible_sites':admissible_sites,
 'textual_count_rule_applied':'no textual count is reported in this record; every number above is a semantically resolved local (type implements IDisposable, writes resolved by symbol, kinds by the oracle / acquire predicates)'}
os.makedirs(f'{P}/paper-eval/h24',exist_ok=True); json.dump(rec,open(f'{P}/paper-eval/h24/h24-census-{VER}.json','w'),indent=1); json.dump(rec,open(f'{S}/lab/h24/h24-census-{VER}.json','w'),indent=1)
print(json.dumps(tot,indent=1)); print('DECISION',decision,'primary',primary)
for repo,v in per.items(): print(repo, 'locals',v['nested_write_disposable_locals'],'prod',v['production'],'strict prod',v['admissible_strict_production'],'strict prod trusted',v['admissible_strict_production_with_trusted_row_write'],'relaxed prod trusted',v['admissible_relaxed_production_with_trusted_row_write'],'new-only',v['admissible_strict_production_new_disposable_only'])
for s in admissible_sites: print('  ADMISSIBLE', s['repo'], s['file'], s['line'], s['local'], s['kind'], 'strict' if s['admissible_strict'] else 'relaxed', [w['kind'] for w in s['writes']], 'depth', s['depth'])
