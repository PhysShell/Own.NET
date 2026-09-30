"""discovery S7: per library, compare the LLM arm (S3 SUGGESTED) with the proofs (S5 BODY_PROVED) and the witnesses
(S6), assemble rows-applied.json (BODY_PROVED + WITNESSED, MVID-pinned) and the per-library ledger."""
import sys, os, json, glob
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'
wit={}
for f in (f'{D}/witness-results-libs.json', f'{D}/libs/Npgsql/s6-witness-results.json', f'{D}/witness-results-tier2.json'):
    if os.path.exists(f):
        for r in json.load(open(f)): wit.setdefault(r['callable'],[]).append(r)
out={}
for acq in sorted(glob.glob(f'{D}/libs/*/acquire.json')):
    L=os.path.dirname(acq); pid=os.path.basename(L); a=json.load(open(acq)); mvid=(a.get('identity') or {}).get('mvid')
    proved=json.load(open(f'{L}/rows-bodyproved.json'))['entries'] if os.path.exists(f'{L}/rows-bodyproved.json') else []
    base=json.load(open(f'{L}/rows-bodyproved-base.json'))['entries'] if os.path.exists(f'{L}/rows-bodyproved-base.json') else None
    s3=json.load(open(f'{L}/s3-llm-candidates.json')) if os.path.exists(f'{L}/s3-llm-candidates.json') else {'suggested_rows':[],'suggested_negatives':[]}
    pk={(e['callable'],e['effect']) for e in proved}
    llm=[(r['callable'],r['effect']) for r in s3['suggested_rows']]
    admitted_proof=[c for c in llm if c in pk]
    witnessed=[]; wit_rows=[]
    for r in wit.get('',[]): pass
    for cal,rs in wit.items():
        if not cal.startswith(tuple({e['callable'].rsplit('.',2)[0] for e in proved} | {x[0].rsplit('.',2)[0] for x in llm} | {pid})): pass
    for cal,rs in wit.items():
        for r in rs:
            if r.get('verdict')=='fresh' and (cal,'return_fresh_owned') not in pk and (r.get('asm')==mvid or pid in cal or cal.startswith(pid.split('.')[0])):
                if not any(w['callable']==cal for w in wit_rows):
                    wit_rows.append({'callable':cal,'effect':'return_fresh_owned','provenance':'WITNESSED','assembly':{'name':a['package'],'mvid':mvid},'witness':r['id'],'witness_asm_mvid':r.get('asm')})
    wit_rows=[w for w in wit_rows if w['witness_asm_mvid']==mvid]
    # the pin must name the ASSEMBLY (simple name), not the package id (SSH.NET -> Renci.SshNet, SharpZipLib -> ICSharpCode.SharpZipLib);
    # constructor 'callables' from the witness list are objects, not factory rows
    asm_name=(a.get('identity') or {}).get('name') or a['package']
    wit_rows=[w for w in wit_rows if not w['callable'].endswith('..ctor')]
    for e in proved+wit_rows: e.setdefault('assembly',{})['name']=asm_name
    applied=proved+wit_rows
    json.dump({'schema':'own.net/re-oracle/v1','label':f'discovery APPLIED rows for {pid} {a["version"]} (BODY_PROVED + WITNESSED; MVID {mvid})','entries':applied}, open(f'{L}/rows-applied.json','w'), indent=1)
    wl=[(c,e) for c,e in llm]
    admitted_wit=[c for c in wl if any(w['callable']==c[0] for w in wit_rows)]
    rejected=[c for c in wl if c not in pk and not any(w['callable']==c[0] for w in wit_rows)]
    wit_all=[r for cal,rs in wit.items() for r in rs if r.get('asm')==mvid or (cal.split('.')[0] in pid)]
    out[pid]={'version':a['version'],'mvid':mvid,'body_proved_rows':len(proved),'body_proved_rows_before_H20':(len(base) if base is not None else None),'witnessed_rows_added':len(wit_rows),'applied_rows':len(applied),
              'llm_candidates':len(llm),'llm_admitted_by_proof':len(admitted_proof),'llm_admitted_by_witness':len(admitted_wit),'llm_rejected_or_undecidable':len(rejected),
              'proved_not_suggested_by_llm':len([e for e in proved if (e['callable'],e['effect']) not in set(llm)]),
              'witness_runs':[{k:r.get(k) for k in ('id','callable','verdict','expect')} for r in wit_all],
              'llm_rejected_list':[c[0] for c in rejected]}
json.dump(out, open(f'{D}/s7-ledger.json','w'), indent=1)
for pid,v in out.items(): print(pid, {k:v[k] for k in ('body_proved_rows','body_proved_rows_before_H20','witnessed_rows_added','applied_rows','llm_candidates','llm_admitted_by_proof','llm_admitted_by_witness','llm_rejected_or_undecidable','proved_not_suggested_by_llm')})
