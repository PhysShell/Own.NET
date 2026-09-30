"""Stage C/D record: the frozen candidate universe with the filter report, the arms' rankings, the witness labels, the
metrics (validated rows per 10 / 25 witness executions per arm), the receiver-ownership probe, the hostile controls,
the CodeTrek-proper gate, the two-state protocol witness, binary-only surface value, environment incidents, decisions."""
import json, collections, datetime, os, hashlib, re
OD=collections.OrderedDict; S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; P='/home/user/Own.NET-paperwork'
now=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
def J(p, d=None):
    return json.load(open(p)) if os.path.exists(p) else d
uni=J(f'{S}/lab/sc/stagec-universe.json'); ranked=J(f'{S}/lab/sc/staged-ranked.json'); met=J(f'{S}/lab/sc/staged-metrics.json')
wit=J(f'{S}/lab/sc/witness-results.json'); syn=J(f'{S}/lab/sc/witsyn-rows.json'); llm=J(f'{S}/lab/sc/llm-arm-B.json',{})
probe=J(f'{S}/lab/sc/recvprobe-results.json',[]); mut=J(f'{S}/lab/sc/mutant-results.json',[]); usage=J(f'{S}/lab/sc/usage-share.json',{'rows':[]})
rows_now={r['id']:r for r in J(f'{S}/lab/sc/witness-rows.json')}
vc=collections.Counter(r['verdict'] for r in wit); labels=met['_universe_totals']['labels']
# provenance: which pass produced each verdict (pass 1 results carry no src_sha; later passes record the sha of Program.cs)
prov=collections.Counter('pass1(parallel, no src_sha)' if 'src_sha' not in r else ('sequential' if r.get('mode')=='sequential' else 'parallel') for r in wit)
byc={r['callable']:r for r in wit}; pb={p['callable']:p for p in probe}
fresh=[r for r in wit if r['verdict']=='fresh']
static={u['callable'] for u in uni['universe'] if u['is_static']}
def trust(r):
    c=r['callable']
    if c in static: return 'admitted:static_factory(no receiver)'
    p=pb.get(c)
    if not p: return 'admitted:receiver_probe_not_run'
    o=p.get('outcome') or p.get('verdict')
    if o=='independent': return 'admitted:independent_of_receiver'
    if o=='receiver_bound': return 'REFUSED:receiver_bound(lifetime tied to the receiver)'
    return f'admitted_with_boundary:probe_{o}'
tr=collections.Counter(trust(r) for r in fresh)
ushare={r['callable']:r for r in usage['rows']}
binonly=OD([("what","every fresh row here is a binary-only-style row: RelDump relations on the deployed binary -> candidate -> H-10 witness -> trusted row pinned to the tested MVID; no source was used"),
 ("rows_validated_fresh",len(fresh)),("rows_admitted",sum(v for k,v in tr.items() if k.startswith('admitted'))),("rows_refused_receiver_bound",sum(v for k,v in tr.items() if k.startswith('REFUSED'))),
 ("usage_share_known",sum(1 for r in fresh if r['callable'] in ushare)),("mean_using_share_of_fresh_rows",round(sum(ushare[r['callable']].get('using_share') or 0 for r in fresh if r['callable'] in ushare)/max(1,sum(1 for r in fresh if r['callable'] in ushare)),3)),
 ("unique_value_measured_in","stage-e-v1.json (E2 census: units by row class witnessed_exact_binary / witnessed_identity_match versus whole-source classes)")])
# mutants: the 12 frozen hostile classes mapped to evidence in this track
mres={m['id']:m for m in mut}
mutants=OD([
 ("getter returning a shared singleton",{"evidence":"Stage C filter routes 73 getters to ALIAS_OR_SHARED before validation; witnesses SKTypeface.Default / SKFontManager.Default / SKData.Empty -> "+', '.join(mres[k]['verdict'] for k in ('MUT-getter-SKTypeface-Default','MUT-getter-SKFontManager-Default','MUT-SKData-Empty-getter') if k in mres),"status":"caught"}),
 ("factory returning a cached singleton",{"evidence":"12 universe candidates witnessed cached: "+', '.join(sorted(r['callable'] for r in wit if r['verdict']=='cached')),"status":"caught by the witness, never admitted"}),
 ("factory returning fresh",{"evidence":f"{len(fresh)} fresh rows; CreateRgb(sRGB parameters) -> {mres.get('MUT-CreateRgb',{}).get('verdict')} shows freshness is ARGUMENT-dependent for some factories (skia dedups sRGB); the row boundary records the tested argument vector","status":"caught; boundary recorded"}),
 ("wrapper forwarding another factory",{"evidence":"A1 variants B/C (one-hop, two-hop) and H-22 (SftpClient.Open wrapper): identity by TYPED proof slice; witness fresh","status":"covered (a1-v1, h22-v1)"}),
 ("caller body unchanged while callee semantics changes (A1)",{"evidence":"a1-v1: 5/6 variants keep the caller IL hash while the witness flips -> body hash KILLED; TYPED slice catches B/C/E/F","status":"covered"}),
 ("virtual implementation semantic change (A1 D)",{"evidence":"a2-v1: the slice contains a bodiless member -> row binary-pinned (MVID), no hash transfer","status":"covered"}),
 ("overload confusion",{"evidence":"witness rows pin the executed overload (arity + parameter types in the row source); the oracle hit log carries arity; E2 rows carry the derivation callable; no natural overload with divergent semantics was found in the universe","status":"guarded by construction; NOT stress-tested with a natural pair"}),
 ("same package version, different TFM",{"evidence":"a2-v1: 2/264 slices differ across TFM builds; E2 classes rederived_same_source vs tfm_variant_body_differs per resolved asset (stage-e-v1)","status":"measured"}),
 ("same signature and body, changed semantic dependency (A1 B/C)",{"evidence":"a1-v1 B/C","status":"covered"}),
 ("misleading Create/Open/Decode names",{"evidence":"cached witnesses with factory names: SKColorSpace.CreateSrgb, CreateSrgbLinear, SKTypeface.CreateDefault, SKTypeface.FromFamilyName (null / unknown / default family all cached), SKBlender.CreateBlendMode, SKPictureRecorder.BeginRecording","status":"caught"}),
 ("terminal-looking method that does not release",{"evidence":"no release candidates in the frozen universe (fresh candidates only); the release side was tested in resource-effects (Oracle B) and is NOT re-measured here","status":"NOT_MEASURED in this track"}),
 ("witness environment failure",{"evidence":"PostgreSQL PANICked twice (checkpointer: Permission denied after the harness re-applied mode 700 on the scratch tree; 10:31 and 11:47 UTC); every affected row reported environment-error / build-or-run-error and NO label; the database was relocated to /tmp/pgsc and the rows re-run","status":"caught; never a label"})])
# CodeTrek-proper gate
at25={k:met[k]['at_25'] for k in ('A','B','C','D','U') if k in met}; at10={k:met[k]['at_10'] for k in ('A','B','C','D','U') if k in met}
validated=labels.get('VALIDATED_FRESH',0)+labels.get('VALIDATED_SHARED_OR_CACHED',0)
gate=OD([("floors",OD([("non_provable_candidates",{"required":">=200","observed":uni['size'],"met":uni['size']>=200}),("independently_validated_labels",{"required":">=50","observed":validated,"met":validated>=50}),("useful_positive_labels",{"required":">=20","observed":labels.get('VALIDATED_FRESH',0),"met":labels.get('VALIDATED_FRESH',0)>=20})])),
 ("conditions",OD([
  ("1 relational arms beat names and LLM per validator budget",{"at_10":{k:v['validated_fresh'] for k,v in at10.items()},"at_25":{k:v['validated_fresh'] for k,v in at25.items()},"contradicted_at_25":{k:v['contradicted_cached'] for k,v in at25.items()},"verdict":"D (logistic regression) and C (rules) lead at 25 but by a margin of a few rows over names/LLM/usage; at 10 the LLM leads"}),
  ("2 novel trusted rows not derivable by E1/E2/E3",{"observed":len(fresh),"note":"novel by construction (the universe is the non-provable remainder); the H-22 class shows some 'non-provable' rows are lowering artefacts, not true non-provables"}),
  ("3 version/TFM portability recovery",{"measured_in":"stage-e-v1 (witnessed_identity_match units)"}),
  ("4 library holdout + version holdout",{"library_holdout":"arm D trained on the other libraries' CT positives","version_holdout":"ct-v1 CT-3 (SkiaSharp 3.119.4/4.148.0/4.152.0 witnesses)"}),
  ("5 demonstrated validator-budget problem",{"observed":f"the WHOLE frozen universe was witnessed: {len(wit)} executions in about {round(sum(r.get('seconds',0) for r in wit)/60)} minutes of compute; the binding cost was environment engineering (receivers, arguments, servers, protocol state), not the number of validator executions","verdict":"NOT demonstrated at this scale: ranking buys ordering, not rows"})])),
 ("decision","CodeTrek-proper (learned walks) NOT EARNED: floors met, but condition 5 fails and condition 1 is a few-row margin; the cheapest pipeline witnesses the filtered universe exhaustively and spends effort on environments")])
# two-state protocol witness
seq=[r for r in wit if r.get('mode')=='sequential']
busy=set()
for l in open(f'{S}/lab/sc/witness-results.json.partial.jsonl'):
    try: j=json.loads(l)
    except Exception: continue
    if re.search(r'already in progress|already open', j.get('msg','') or ''): busy.add(j['callable'])
proto=OD([("demanded_by","Npgsql candidates: in pass 2 the parallel witness (three calls without disposing) failed with 'A command is already in progress' / 'A transaction is already in progress' / 'A stream is already open for this reader' on "+str(len(busy))+" callables: "+', '.join(sorted(c.split('.',1)[1] for c in busy))),
 ("prior_art",["Strom & Yemini, 'Typestate: a programming language concept for enhancing software reliability', IEEE TSE 1986","DeLine & Faehndrich, 'Typestates for objects', ECOOP 2004 (Fugue)","Bierhoff & Aldrich, 'Modular typestate checking of aliased objects', OOPSLA 2007 (Plural)","Beckman, Kim, Aldrich, 'An empirical study of object protocols in the wild', ECOOP 2011: about 7% of types define protocols, most with few states"]),
 ("witness","two-state protocol {connection idle, connection busy}: an operation-returning call in the busy state throws (pass 1/3 evidence), the same call after disposing the previous result succeeds (sequential mode, pass 4); verdicts of sequential rows: "+json.dumps(dict(collections.Counter(r['verdict'] for r in seq)))),
 ("consequence","for ADO.NET-shaped libraries the identity witness must run sequentially (dispose between calls); a 'cached' verdict in sequential mode may also mean 'pooled' (same object handed out again after return to the pool) which is caller-owned: sequential-mode cached verdicts are NOT admitted as shared without a parallel-mode confirmation"),
 ("mechanism_added","none in the engines; the harness gained a sequential mode only")])
rec=OD([("schema","own.net/semantic-coverage/stage-cd/v2"),("written_at_utc",now),("prereg","sc-prereg-v1.json C/D + amendment 1 (arm U)"),
 ("C_universe",OD([("size",uni['size']),("removed_by_filter",uni['removed_by_filter']),("routed_classes",{k:len(v) for k,v in uni['routed_classes'].items()}),("by_package",dict(collections.Counter(u['package'] for u in uni['universe']))),("top_by_public_use",[(u['callable'],u['matches']) for u in uni['universe'][:30]])])),
 ("D_labels",OD([("validator","H-10 runtime witness on the exact deployed binaries with in-container environments (asyncssh SSH/SFTP server, portable PostgreSQL 16.2, local Redis, in-process MQTT broker, temp git repositories); MailKit and RabbitMQ.Client have no environment here (UNWITNESSABLE_ENV)"),
   ("witness_rows_executed",len(wit)),("verdicts",dict(vc)),("label_classes",labels),("verdict_provenance",dict(prov)),("routed_before_execution",dict(collections.Counter(v.split(':')[0] for v in syn['routed'].values()))),
   ("harness_passes",["pass 1: parallel mode (three calls, no disposal between); PostgreSQL was down (PANIC 10:31) -> all Npgsql rows errored","pass 2: null-result verdict (Make() returned null: 14 rows, e.g. GL contexts, unsuitable inputs); out/ref discards read back from CS1620; expandable MemoryStream helper; command-builder placeholder replaced by a real CREATE TABLE","pass 3: sequential mode for Npgsql receiver types (documented one-operation-per-connection protocol); COPY command texts; array sizes read back from ArgumentException texts; libgit2 remote names; PostgreSQL PANIC again (11:47) -> Npgsql rows errored","pass 4: PostgreSQL relocated to /tmp/pgsc; Npgsql rows re-run; receiver-ownership probe re-run"]),
   ("resume_rule","a row is re-executed only while its verdict is build-or-run-error / environment-error; fresh, cached, null-result and inconclusive verdicts are never re-run (no label shopping); each result records the sha of its Program.cs from pass 2 on")])),
 ("D_receiver_ownership_probe",OD([("what","for fresh rows with a receiver: create the result, dispose the RECEIVER, then read Handle / IsDisposed / IsClosed on the result; 'independent' = the result outlives its receiver (caller-owned lifetime); 'receiver_bound' = invalidated by the receiver's disposal (NOT admitted as return_fresh_owned); 'unprobed' = no such property (admitted with the boundary recorded)"),("results",dict(collections.Counter((p.get('outcome') or p.get('verdict')) for p in probe))),("trust_of_fresh_rows",dict(tr))])),
 ("D_arms",OD([("A","names/signature (frozen token list)"),("B","LLM candidates from the API listing, frozen prompt (procedural blinding only)"),("C","relational rules (CT gate0 scoreRules, frozen)"),("D","logistic regression over RelDump relations, trained on the CT positives of the OTHER libraries (library holdout)"),("U","usage share (amendment 1)")])),
 ("D_metrics",{k:v for k,v in met.items()}),
 ("D_rankings_top15",{k:[(c,round(s,3)) for c,s,_ in v[:15]] for k,v in ranked.items()}),
 ("B_candidates",llm.get('candidates',[])),
 ("codetrek_proper_gate",gate),("two_state_protocol_witness",proto),("binary_only_surfaces",binonly),("hostile_controls",mutants),
 ("mutant_witness_rows",[OD([(k,m.get(k)) for k in ('id','callable','expect','verdict','mutant')]) for m in mut]),
 ("stage_b_addendum",OD([("what","secondary coverage counting the production ADO.NET convention (CreateCommand / BeginTransaction / ExecuteReader, tracked without rows) as covered surface"),("computed_over","surface-census.json line matches (cap 1000 per callable)"),("primary_weighted_coverage",0.101),("with_convention",0.154),("note","the Stage B record's pooled 0.13 uses the 507-callable surface; this addendum uses all 597 census rows; both denominators are frozen census outputs")])),
 ("environment_incidents",["PostgreSQL 16.2 (pgserver) PANIC at 10:31:07 and 11:47:56 UTC: checkpointer could not open global/pg_control (Permission denied) because the harness re-applies mode 700 to the scratch tree; relocated to /tmp/pgsc at 11:54","pgserver handle-count cleanup can stop the server when an ad-hoc get_server() process exits: the persistent pg.py now uses cleanup_mode=None"]),
 ("decisions",OD([("H-21 arms A/B/C/D/U","KEEP_AS_CANDIDATE_GENERATOR (ordering only): exhaustive witnessing of the filtered universe is cheaper than any ranking; the arms differ by a few rows at 25"),("learned walks (CodeTrek-proper)","NOT EARNED: no validator-budget problem at 205 candidates"),("H-10 witness harness","KEEP_AS_VALIDATOR with the sequential mode and the receiver-ownership probe; boundary = tested binary, argument vector, environment"),("binary-only surfaces","KEEP_AS_VALIDATOR path (RelDump -> witness) pending the E2 unique-value measurement")])),
 ("witness_results",[OD([(k,r.get(k)) for k in ('id','callable','verdict','mode','distinct','asm','src_sha','err')]) for r in wit]),
 ("receiver_probe_results",[OD([(k,p.get(k)) for k in ('id','callable','outcome','probe','err')]) for p in probe])])
json.dump(rec,open(f'{P}/paper-eval/semantic-coverage/stage-cd-v1.json','w'),indent=1); print('stage-cd record written', len(json.dumps(rec)))
