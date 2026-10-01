"""H-26B census aggregation and record (paper-eval/h26/h26b-census-v1.json): every disposable-returning library call of the 8
frozen consumers (corrected environment), production and TFM-collapsed per (consumer, file, line, callable); the Q2b class
(framework assembly: the static callable is a base-typed member, ADO's DbCommand.ExecuteReaderAsync is a NON-virtual template
method over a protected virtual, so the flag is_virtual_member is not the criterion) with its receiver provenance
distribution and the FROZEN gate (primary = CONCRETE_LOCAL_CONSTRUCTION or CONCRETE_FIELD provenance, exactly as preregistered;
the wider construction-provenance set and the static-type-concrete set are reported descriptively); the step-3 value for the
owned-handle families: non-using, non-transferred (transfer = returned or stored, as preregistered; an argument pass is reported
but is not a transfer) production local sites of ExecuteReaderAsync / BeginTransactionAsync (frozen pair, concrete + base-typed),
the synchronous twins reported descriptively."""
import json, glob, os, re, collections, datetime, subprocess
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'; R='/home/user/Own.NET'
FRAMEWORK=re.compile(r'^(System(\.|$)|Microsoft\.Extensions\.|Microsoft\.AspNetCore(\.|$)|netstandard|mscorlib|Microsoft\.CSharp)')
CORPUS={'npgsql','skiasharp','stackexchange.redis','mailkit','rabbitmq.client','mqttnet','ssh.net','libgit2sharp','bouncycastle.cryptography','csvhelper','google.protobuf','k4os.compression.lz4.streams','microsoft.data.sqlite','microsoft.data.sqlite.core','mysqlconnector','nlog','nsec.cryptography','newtonsoft.json','serilog','sharpcompress','sharpziplib','sixlabors.imagesharp','zstdsharp.port','icsharpcode.sharpziplib'}
LEASE_FROZEN=re.compile(r'\.(ExecuteReaderAsync|BeginTransactionAsync)/')
LEASE_WIDE=re.compile(r'\.(ExecuteReader|ExecuteReaderAsync|ExecuteDbDataReader|ExecuteDbDataReaderAsync|BeginTransaction|BeginTransactionAsync|BeginDbTransaction|BeginDbTransactionAsync)/')
PRIMARY={'CONCRETE_LOCAL_CONSTRUCTION','CONCRETE_FIELD'}                      # frozen primary (prereg H26B.gate_frozen.primary)
CONSTRUCTION_WIDER=PRIMARY|{'CONCRETE_NEW','CONCRETE_CALL_RESULT_TYPE'}       # descriptive: construction provenance not named in the frozen primary
STATIC_CONCRETE={'CONCRETE_PARAMETER_TYPE','CONCRETE_FIELD_TYPE','CONCRETE_PROPERTY_TYPE'}   # descriptive: the declared type is concrete, no provenance needed
TRANSFER={'returned','stored'}                                                 # frozen transfer definition (argument pass reported separately)
U={}; per={}
for f in sorted(glob.glob(f'{S}/lab/h26b/census/*.h26b.json')):
    d=json.load(open(f)); recs=d['records']
    per[d['repo']]={'units':d['units'],'extractor_failures':d['extractor_failures'],'extractor_failures_after_rerun':d.get('extractor_failures_after_rerun',d['extractor_failures']),'rerun_with_fixed_build':d.get('rerun_with_fixed_build',[]),'seconds':d['seconds'],'sites_raw':len(recs)}
    for r in recs: U.setdefault((d['repo'],r['file'],r['line'],r['callable']),dict(r,repo=d['repo']))
UA=list(U.values()); prod=[r for r in UA if r['kind']=='production']
def cls(r):
    a=(r['declaring_assembly'] or '')
    if FRAMEWORK.match(a): return 'Q2b_framework'
    if a.lower() in CORPUS: return 'Q2_corpus_library'
    return 'other_library'
def xfer(r): return any(x in TRANSFER for x in r['transferred'])
for r in UA: r['class']=cls(r); r['primary_provenance']=r['provenance'] in PRIMARY; r['transfer_frozen']=xfer(r)
q2b=[r for r in prod if r['class']=='Q2b_framework']; q2bp=[r for r in q2b if r['primary_provenance']]
q2bw=[r for r in q2b if r['provenance'] in CONSTRUCTION_WIDER]; q2bs=[r for r in q2b if r['provenance'] in STATIC_CONCRETE]
def share(a,b): return round(len(a)/len(b),3) if b else None
tot={'consumers':len(per),'units':sum(v['units'] for v in per.values()),'extractor_failures_final':sum(v['extractor_failures_after_rerun'] for v in per.values()),'sites_raw':sum(v['sites_raw'] for v in per.values()),'sites_unique':len(UA),'production_unique':len(prod),
 'classes_production':dict(collections.Counter(r['class'] for r in prod)),
 'Q2b_production':len(q2b),'Q2b_primary_concrete_provenance':len(q2bp),'Q2b_primary_share':share(q2bp,q2b),
 'Q2b_construction_provenance_wider':len(q2bw),'Q2b_construction_wider_share':share(q2bw,q2b),'Q2b_static_type_concrete':len(q2bs),'Q2b_static_type_concrete_share':share(q2bs,q2b),
 'Q2b_provenance_distribution':dict(collections.Counter(r['provenance'] for r in q2b)),'Q2b_top_callables':{k:n for k,n in collections.Counter(r['callable'] for r in q2b).most_common(15)},
 'Q2b_primary_by_callable':{k:n for k,n in collections.Counter(r['callable'] for r in q2bp).most_common(12)},'Q2b_primary_concrete_types':{k:n for k,n in collections.Counter(r['concrete_type'] for r in q2bp).most_common(10)},
 'Q2b_primary_with_row_on_override':sum(1 for r in q2bp if r['row_on_concrete_override']),'Q2b_static_concrete_with_row_on_override':sum(1 for r in q2bs if r['row_on_concrete_override']),
 'Q2b_primary_split_by_receiver_typing':{'base_typed_receiver (concrete type differs from the receiver static type: the resolution question is real)':sum(1 for r in q2bp if r['concrete_type'] and r['concrete_type']!=r['receiver_static_type']),'same_type_receiver (the static type already is the concrete class: no resolution question, the frozen primary over-counts in favour of LEVER)':sum(1 for r in q2bp if not r['concrete_type'] or r['concrete_type']==r['receiver_static_type']),'base_typed_by_callable':{k:n for k,n in collections.Counter(r['callable'] for r in q2bp if r['concrete_type'] and r['concrete_type']!=r['receiver_static_type']).most_common(10)}},
 'Q2b_by_consumer':dict(collections.Counter(r['repo'] for r in q2b)),'Q2b_primary_by_consumer':dict(collections.Counter(r['repo'] for r in q2bp)),
 'provenance_distribution_all_production':dict(collections.Counter(r['provenance'] for r in prod)),'sink_distribution_production':dict(collections.Counter(r['sink']+('/using' if r['using_declaration'] else '') for r in prod)),
 'transfer_distribution_production':dict(collections.Counter(','.join(r['transferred']) or 'none' for r in prod))}
# step 3: owned-handle families
def value(lease):
    val=[r for r in lease if not r['using_declaration'] and not r['transfer_frozen'] and r['sink'] in ('local_declaration','local_assignment')]
    return val,{'production_sites':len(lease),'by_callable':{k:n for k,n in collections.Counter(r['callable'] for r in lease).most_common(12)},'using_declaration':sum(1 for r in lease if r['using_declaration']),
     'transferred_returned_or_stored':sum(1 for r in lease if r['transfer_frozen'] and not r['using_declaration']),'sink_not_local':sum(1 for r in lease if r['sink'] not in ('local_declaration','local_assignment')),
     'VALUE_non_using_non_transferred_local_sites':len(val),'value_passed_as_argument_somewhere':sum(1 for r in val if 'passed_as_argument' in r['transferred']),
     'value_by_callable':{k:n for k,n in collections.Counter(r['callable'] for r in val).most_common(12)},'value_by_provenance':dict(collections.Counter(r['provenance'] for r in val)),'value_by_consumer':dict(collections.Counter(r['repo'] for r in val)),
     'value_by_class':dict(collections.Counter(r['class'] for r in val))}
valF,lf=value([r for r in prod if LEASE_FROZEN.search(r['callable'])]); valW,lw=value([r for r in prod if LEASE_WIDE.search(r['callable'])])
tot['lease_families_frozen_pair']=lf; tot['lease_families_wide_incl_sync']=lw
gate_h26b='LEVER (call-target-resolution experiment gets its own prereg)' if len(q2bp)>=20 and q2b and len(q2bp)/len(q2b)>=0.2 else 'KILL_H26B'
step4='ADD_EFFECT_EXPERIMENTALLY (own prereg)' if len(valF)>=20 else 'RECORD_AND_STOP (value < 20 sites)'
own=subprocess.run(['git','rev-parse','HEAD'],cwd=R,capture_output=True,text=True).stdout.strip()
site=lambda r,ks: {k:r.get(k) for k in ks}
rec={'schema':'own.net/h26b/census/v1','written_at_utc':datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),'track':'H-26B base-typed virtual resolvability census; H-27 step 3 value',
 'anchors':{'prereg':'paper-eval/h26/h26b-h27-prereg-v1.json (448d314)','seam_commit':'9358672b (89 lines, census only) + 62eac7c6 (cross-file semantic model for initializers, census only)','own_net_head':own,'own_net_main':'fb06adc2beddd750e99a52ad8c1c8b5905602539 (untouched)','fixture':'corpus/ownership-lab/h26b/fx/Prov.cs: the nine provenance classes classified as intended'},
 'environment':'corrected (invariant 0); the H-25 unit row files (erratum-3 rows); every disposable-returning call of a library / framework member; units whose first extractor run failed were re-run with the fixed build (rerun_with_fixed_build per consumer)',
 'note_on_q2b':'the Q2b class is defined by the declaring assembly (framework), not by the virtual flag: ADO.NET exposes NON-virtual template methods (DbCommand.ExecuteReaderAsync) over protected virtuals, so a concrete receiver type resolves the implementation only through that template',
 'note_on_primary':'the frozen primary counts CONCRETE_LOCAL_CONSTRUCTION and CONCRETE_FIELD only; the seam classifies finer than the prereg text (CONCRETE_NEW, CONCRETE_CALL_RESULT_TYPE, CONCRETE_*_TYPE), those classes are reported beside the primary and do not enter the gate',
 'note_on_receiver_typing':'the frozen primary counts every concrete-provenance Q2b site, including sites whose receiver static type already is the concrete class (new HttpClient().GetAsync); only the split field Q2b_primary_split_by_receiver_typing isolates the sites where a base-typed receiver is resolved by provenance; the split is descriptive and can only lower the primary, never raise it',
 'note_on_transfer':'transfer = returned or stored (frozen); passed_as_argument is recorded by the seam and reported, but a plain argument pass leaves the obligation with the caller in the engine model and is not a transfer here',
 'totals':tot,'per_consumer':per,'gate':{'primary':len(q2bp),'share':tot['Q2b_primary_share'],'rule':'primary < 20 or < 20% of the Q2b production sites = KILL; >= 20 and >= 20% = LEVER (frozen before counting)','decision':gate_h26b,
   'descriptive_wider':{'construction_provenance_wider':len(q2bw),'share':tot['Q2b_construction_wider_share'],'static_type_concrete':len(q2bs),'share_static':tot['Q2b_static_type_concrete_share'],'would_the_wider_set_change_the_decision':(len(q2bw)>=20 and bool(q2b) and len(q2bw)/len(q2b)>=0.2)!=(gate_h26b.startswith('LEVER'))}},
 'h27_step3_value':{'rule':'>= 20 non-using non-transferred local production sites of ExecuteReaderAsync / BeginTransactionAsync (concrete + base-typed) = step 4 (own prereg), else record and stop (frozen)','count':len(valF),'decision':step4,'count_wide_incl_sync':len(valW),
   'sites':[site(r,('repo','file','line','callable','provenance','concrete_type','sink','transferred','member','project','tfm','class')) for r in valF],
   'sites_wide_only':[site(r,('repo','file','line','callable','provenance','sink','transferred')) for r in valW if not LEASE_FROZEN.search(r['callable'])]},
 'q2b_primary_sites':[site(r,('repo','file','line','callable','provenance','concrete_type','row_on_concrete_override','sink','using_declaration','transferred')) for r in q2bp],
 'q2b_static_concrete_sample':[site(r,('repo','file','line','callable','provenance','receiver_static_type','row_on_concrete_override','sink','using_declaration')) for r in q2bs[:40]]}
os.makedirs(f'{P}/paper-eval/h26',exist_ok=True); json.dump(rec,open(f'{P}/paper-eval/h26/h26b-census-v1.json','w'),indent=1); json.dump(rec,open(f'{S}/lab/h26b/h26b-census-v1.json','w'),indent=1)
print(json.dumps({k:v for k,v in tot.items() if k not in ('provenance_distribution_all_production',)},indent=1)[:7000]); print('H26B GATE',gate_h26b,'| STEP4',step4,'| wider construction',len(q2bw),'static concrete',len(q2bs),'| value wide',len(valW))
