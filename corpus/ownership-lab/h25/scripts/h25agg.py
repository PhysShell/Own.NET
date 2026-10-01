"""H-25 census aggregation and the record paper-eval/h25/h25-census-v1.json: await-shaped writes of disposable locals over
the 8 frozen consumers (corrected environment), raw per project/TFM and TFM-collapsed per (consumer, file, line); the
frozen quantities Q1 (trusted row), Q2 (library callable, no row, disposable logical result), Q3 (first-party callable),
Q4 (await of a local / other); by callable family, return kind, form, nesting, try/finally disposal; the frozen gate."""
import json, glob, os, collections, datetime, subprocess, sys
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'; R='/home/user/Own.NET'
CD=sys.argv[1] if len(sys.argv)>1 else 'census'
LIBS={'npgsql','skiasharp','stackexchange.redis','mailkit','rabbitmq.client','mqttnet','ssh.net','libgit2sharp','bouncycastle.cryptography','csvhelper','google.protobuf','k4os.compression.lz4.streams','microsoft.data.sqlite','microsoft.data.sqlite.core','mysqlconnector','nlog','nsec.cryptography','newtonsoft.json','serilog','sharpcompress','sharpziplib','sixlabors.imagesharp','zstdsharp.port','icsharpcode.sharpziplib'}
per={}; allrecs=[]
for f in sorted(glob.glob(f'{S}/lab/h25/{CD}/*.h25.json')):
    d=json.load(open(f)); recs=d['records']
    for r in recs: r['repo']=d['repo']
    allrecs+=recs
    per[d['repo']]={'sha':d['sha'][:10],'units':d['units'],'extractor_failures':d['extractor_failures'],'seconds':d['seconds'],'await_writes_raw':len(recs),'await_writes_unique':len({(r['file'],r['line']) for r in recs}),'production_unique':len({(r['file'],r['line']) for r in recs if r['kind']=='production'})}
U={}
for r in allrecs: U.setdefault((r['repo'],r['file'],r['line']),r)
UA=list(U.values()); prod=[r for r in UA if r['kind']=='production']
def cls(r):
    if r['awaited']!='invocation' or not r['callable']: return 'Q4_await_of_local_or_other'
    if r['trusted_row']: return 'Q1_trusted_row'
    if r['first_party']: return 'Q3_first_party_callable'
    asm=(r['callable_assembly'] or '').lower()
    if r['logical_disposable'] and asm in LIBS: return 'Q2_library_callable_no_row_disposable_result'
    if r['logical_disposable']: return 'Q2b_other_library_or_framework_no_row_disposable_result'
    return 'Q5_logical_result_not_disposable_or_non_generic'
for r in UA: r['class']=cls(r)
C=collections.Counter(r['class'] for r in prod)
Q1=C.get('Q1_trusted_row',0); Q2=C.get('Q2_library_callable_no_row_disposable_result',0)
fam=collections.Counter((r['class'],r['callable']) for r in prod)
tot={'consumers':len(per),'units':sum(v['units'] for v in per.values()),'await_writes_raw':len(allrecs),'await_writes_unique':len(UA),'production_unique':len(prod),'test_unique':len(UA)-len(prod),
 'classes_production':dict(C),'Q1':Q1,'Q2':Q2,'Q3':C.get('Q3_first_party_callable',0),'Q4':C.get('Q4_await_of_local_or_other',0),
 'return_kinds_production':dict(collections.Counter(r['return_kind'] for r in prod)),'forms_production':dict(collections.Counter(r['form']+('/using' if r['declared_using'] else '') for r in prod)),
 'nesting_production':dict(collections.Counter(('try' if r['in_try'] else ('straight' if not r['nesting'] else 'nested:'+r['nesting'][0])) for r in prod)),
 'try_finally_production':{'in_try':sum(1 for r in prod if r['in_try']),'disposed_in_finally':sum(1 for r in prod if r['in_try'] and r['disposed_in_finally']),'disposed_somewhere':sum(1 for r in prod if r['in_try'] and r['disposed_somewhere']),'not_disposed_in_member':sum(1 for r in prod if r['in_try'] and not r['disposed_somewhere'])},
 'configure_await_production':sum(1 for r in prod if r['configure_await']),'sync_twin_row_true_production':sum(1 for r in prod if r['sync_twin_row']),
 'callable_families_production':{f'{c}|{k}':n for (c,k),n in fam.most_common()}}
# a `using` / `await using` declaration disposes by construction: the obligation is already discharged by the language;
# the value of a row (if any) lives in the NON-using forms, where an obligation can be missed
nonusing=[r for r in prod if not r['declared_using']]
tot['using_declaration_dominance']={'production_unique':len(prod),'declared_using':sum(1 for r in prod if r['declared_using']),'non_using':len(nonusing),'non_using_by_class':dict(collections.Counter(r['class'] for r in nonusing)),'non_using_disposed_somewhere':sum(1 for r in nonusing if r['disposed_somewhere']),'non_using_not_disposed_in_member':sum(1 for r in nonusing if not r['disposed_somewhere']),'non_using_not_disposed_by_class':dict(collections.Counter(r['class'] for r in nonusing if not r['disposed_somewhere'])),'non_using_not_disposed_top_callables':{k:n for k,n in collections.Counter(r['callable'] for r in nonusing if not r['disposed_somewhere'] and r['callable']).most_common(10)}}
tot['try_finally_production']={'in_try':sum(1 for r in prod if r['in_try']),'using_declaration_inside_try':sum(1 for r in prod if r['in_try'] and r['declared_using']),'disposed_in_finally':sum(1 for r in prod if r['in_try'] and r['disposed_in_finally']),'disposed_elsewhere':sum(1 for r in prod if r['in_try'] and not r['declared_using'] and r['disposed_somewhere'] and not r['disposed_in_finally']),'not_disposed_in_member_and_not_using':sum(1 for r in prod if r['in_try'] and not r['declared_using'] and not r['disposed_somewhere'])}
tot['value_estimate_if_rows_existed']='rows for the Q2 families would make at most the non-using sites findable (an obligation under a using declaration is discharged by the language); see using_declaration_dominance.non_using_by_class and non_using_not_disposed_by_class'
decision=('FULL_PATH' if Q1>=20 else 'TINY_PREDICATE_PROBE' if Q1>=8 else 'NOT_THE_LEVER_YET_ROW_SUPPLY_FOR_ASYNC_FACTORIES_IS' if Q2>=20 else 'KILL_AWAIT_DIRECTION_ON_THIS_POPULATION')
own=subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True).stdout.strip()
rec={'schema':'own.net/h25/census/v1','written_at_utc':datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),'track':'H-25 await-wrapped acquire recognition: the census-only gate',
 'anchors':{'prereg':'paper-eval/h25/h25-prereg-v1.json (5df220d)','own_net_head_with_census_seam':own,'own_net_main':'fb06adc2beddd750e99a52ad8c1c8b5905602539 (untouched)','builds':'ext8a / ext10a; OFF facts byte-identical to ext8m2 on both fixtures; census on == census off'},
 'environment':'corrected (harness invariant 0: SDK implicit usings per project + the ASP.NET Core ref pack of the unit TFM)','population':'the 8 frozen consumers with trusted rows, the same units / reference directories / row files as the H-23A scans',
 'fixture_classification':'corpus/ownership-lab/h25/out/await.h25.jsonl: AW1-AW6 trusted (AW3 ValueTask<T>, AW2/AW5 ConfigureAwait, AW6 try/finally with a finally dispose); HW1 await-of-local untrusted; HW2 borrowed, HW3 cached, HW5 unknown-without-row, HW6 name twin untrusted; HW4 and HW7 no record; HW8 using declaration classified only',
 'hazard_found_on_the_fixture':'HW1 (`var task = FA.FactoryAsync(); var x = await task;`) shows that TODAY\'S declaration lowering, with a trusted row on a Task<T>-returning callable, mints an `acquire` for the Task<T>-typed local itself (the fixture facts contain `acquire task`, the only emitted op of the file): a row on an async callable is therefore unsafe under the current oracle application until the declaration path refuses Task / ValueTask-typed locals (IsDisposeOptional already knows them); the existing async-named rows (Npgsql CloneWithAsync, MailKit GetStreamAsync) carry this latent false obligation; no such site occurred in the frozen population hit logs',
 'totals':tot,'per_consumer':per,'gate':{'Q1':Q1,'Q2':Q2,'Q2b_framework_or_other_assembly_no_row_disposable_result':C.get('Q2b_other_library_or_framework_no_row_disposable_result',0),'note':'Q2 counts callables of packages that have a derivation in the corpus (the prereg definition); Q2b counts framework / other assemblies (DbConnection.BeginTransactionAsync, DbCommand.ExecuteReaderAsync, HttpClient.SendAsync ...) where the receiver is base-typed and the resolved callable is a framework virtual: that is the semantic-resolution class, not a derivation gap','rule':'Q1 >= 20 FULL_PATH; 8 <= Q1 < 20 TINY_PREDICATE_PROBE; Q1 < 8 and Q2 >= 20 NOT_THE_LEVER_YET (row supply for async factories, H-26 derivation-side prereg); both small KILL (frozen before counting)','decision':decision},
 'sites_production':[{k:r.get(k) for k in ('repo','file','line','local','local_type','member','form','declared_using','awaited','configure_await','callable','callable_assembly','first_party','return_kind','logical_result','logical_disposable','trusted_row','sync_twin_row','in_try','disposed_in_finally','disposed_somewhere','class','project','tfm')} for r in prod]}
os.makedirs(f'{P}/paper-eval/h25',exist_ok=True); json.dump(rec,open(f'{P}/paper-eval/h25/h25-census-v1.json','w'),indent=1); json.dump(rec,open(f'{S}/lab/h25/h25-census-v1.json','w'),indent=1)
print(json.dumps({k:v for k,v in tot.items() if k!='callable_families_production'},indent=1)); print('FAMILIES'); [print(' ',k,n) for k,n in tot['callable_families_production'].items()]; print('DECISION',decision,'Q1',Q1,'Q2',Q2)
