"""Stage E2 semantic opportunity census for ONE nominated repository: clone at HEAD (SHA recorded), restore every
production project (path not matching test/sample/bench/example), read project.assets.json per TFM, resolve the row
libraries' assemblies, re-pin rows against the resolved assembly, run the extractor with the oracle hit log over the
project's sources -> opportunities = unique(repo@sha, project/TFM, file, span, callable, effect, resolved MVID).
Row classes against the resolved assembly (prereg E2: 'IL-body hash for direct rows; witness or re-derivation otherwise'):
  identity_match          TYPED proof-slice identity equal and hash-portable                     -> trusted
  rederived_same_source   same package version as the whole-source derivation (same source revision), direct IL body
                          equal; the derivation is source-based so re-derivation = re-pin (TFM-conditional caveat) -> trusted
  version_drift           different package version: census only (what re-derivation would buy)   -> unverified
  tfm_variant_body_differs same version, direct body differs                                       -> unverified
  callable_absent         not present in the resolved assembly
No OFF/ON verdict comparison here. Extractor status is recorded per project/TFM (rc, stderr tail, facts size)."""
import json, os, sys, subprocess, glob, re, hashlib, time, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; D=f'{S}/lab/disc'; R='/home/user/Own.NET'; E=f'{S}/lab/sc/e2'
repo=sys.argv[1]; tag=repo.replace('/','__'); W=f'{E}/{tag}'; os.makedirs(E,exist_ok=True)
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1','PYTHONPATH':R,'DOTNET_SKIP_FIRST_TIME_EXPERIENCE':'1'}
for k in ('OWEN_RE_ORACLE','OWEN_RE_BODY','OWEN_RE_MINTED_RETURN','OWEN_RE_MIXED_RETURN','OWEN_LAB_THROWEXIT','OWEN_LAB_NULLINIT','OWEN_LAB_NULLGUARD','OWEN_P037X_GUARDED','OWEN_RE_ORACLE_HITLOG'): env.pop(k,None)
EXCL=re.compile(r'(^|/)(tests?|testing|samples?|benchmarks?|examples?|docs?|demo)(/|\.|$)',re.I)
t0=time.time()
if not os.path.isdir(f'{W}/.git'):
    subprocess.run(['git','clone','-q','--depth','1',f'https://github.com/{repo}',W],env=env,capture_output=True,text=True,timeout=900)
sha=subprocess.run(['git','rev-parse','HEAD'],cwd=W,capture_output=True,text=True).stdout.strip()
projs=sorted(p for p in glob.glob(f'{W}/**/*.csproj',recursive=True))
prod=[p for p in projs if not EXCL.search(os.path.relpath(p,W))]
# restore: solution(s) first when present, then any production project still without assets
restore={}
for sln in sorted(glob.glob(f'{W}/*.sln')+glob.glob(f'{W}/*.slnx')+glob.glob(f'{W}/src/*.sln')):
    r=subprocess.run(['dotnet','restore',sln,'-nologo','-v','q'],cwd=W,capture_output=True,text=True,env=env,timeout=1500)
    restore[os.path.relpath(sln,W)]={'ok':r.returncode==0,'err':(r.stdout+r.stderr)[-300:] if r.returncode else ''}
for p in prod:
    if os.path.exists(os.path.join(os.path.dirname(p),'obj','project.assets.json')): restore.setdefault(os.path.relpath(p,W),{'ok':True,'err':'','via':'solution'}); continue
    r=subprocess.run(['dotnet','restore',p,'-nologo','-v','q'],cwd=W,capture_output=True,text=True,env=env,timeout=900)
    restore[os.path.relpath(p,W)]={'ok':r.returncode==0,'err':(r.stdout+r.stderr)[-300:] if r.returncode else ''}
sys.path.insert(0,f'{S}/lab/sc'); import importlib.util
spec=importlib.util.spec_from_file_location('a2',f'{S}/lab/sc/a2lib.py'); a2=importlib.util.module_from_spec(spec); spec.loader.exec_module(a2)
WHOLE={'SkiaSharp','RabbitMQ.Client','MailKit','StackExchange.Redis','Npgsql','MQTTnet','SSH.NET','LibGit2Sharp'}
libs={}
for acq in sorted(glob.glob(f'{D}/libs/*/acquire.json')):
    L=os.path.dirname(acq); pid=os.path.basename(L); a=json.load(open(acq))
    if not a.get('main_assembly'): continue
    src=f'{L}/rows-whole.json' if pid in WHOLE else f'{L}/rows-applied.json'
    if not os.path.exists(src): continue
    ents=json.load(open(src)); ents=ents['rows'] if 'rows' in ents else ents['entries']
    libs[pid.lower()]={'pid':pid,'assembly':(a.get('identity') or {}).get('name') or pid,'rows':ents,'derivation_dll':a['main_assembly'],'derivation_version':a.get('version'),'derivation_mvid':(a.get('identity') or {}).get('mvid')}
# witness-validated rows (Stage D, verdict fresh): trusted binary-specific rows pinned to the TESTED binary (MVID);
# they transfer to another build only by TYPED-slice identity match (hash-portable), never by name
WIT={}
for f in (f'{S}/lab/sc/witness-results.json.partial.jsonl',):
    if os.path.exists(f):
        for l in open(f):
            try: j=json.loads(l)
            except Exception: continue
            WIT[j['id']]=j
wit_rows=collections.defaultdict(list)
for j in WIT.values():
    if j.get('verdict')=='fresh' and j.get('asm'):
        pid=next((u['package'] for u in json.load(open(f'{S}/lab/sc/stagec-universe.json'))['universe'] if u['callable']==j['callable']),None)
        if pid: wit_rows[pid.lower()].append({'callable':j['callable'],'effect':'return_fresh_owned','provenance':'WITNESSED','derived_from':'stage-d-witness','assembly':{'name':libs.get(pid.lower(),{}).get('assembly',pid),'mvid':j['asm']}})
T=f'{R}/frontend/roslyn/OwnSharp.RelDump/bin/Release/net8.0/ownsharp-reldump.dll'
def dump(dll):
    out=f'{E}/dumps/'+hashlib.sha256(open(dll,'rb').read()).hexdigest()[:16]+'.json'; os.makedirs(f'{E}/dumps',exist_ok=True)
    if not os.path.exists(out): open(out,'w').write(subprocess.run(['dotnet',T,dll],capture_output=True,text=True,env=env).stdout)
    return out
ids_cache={}
def row_ids(dll, callables):
    key=(dll,tuple(sorted(callables)))
    if key in ids_cache: return ids_cache[key]
    d,by=a2.load(dump(dll)); out={}
    for c in callables:
        mn=a2.meta_name(by,c)
        out[c]=(a2.ident(mn,[by],True), '|'.join(sorted((x.get('il_hash') or 'NOBODY') for x in by[mn]))) if mn else None
    ids_cache[key]=(out,d['mvid']); return ids_cache[key]
TRUSTED={'identity_match','rederived_same_source','witnessed_exact_binary','witnessed_identity_match'}
units=collections.defaultdict(set); per_project={}; NUGET=os.path.expanduser('~/.nuget/packages'); extractor_runs=[]
for p in prod:
    rel=os.path.relpath(p,W); assets=os.path.join(os.path.dirname(p),'obj','project.assets.json')
    if not os.path.exists(assets): per_project[rel]={'status':'no_assets'}; continue
    a=json.load(open(assets)); pj={'targets':{}}
    for tfm,pk in a['targets'].items():
        tfm0=tfm.split('/')[0]; refdir=f'{W}/.refs/{hashlib.sha256((rel+tfm).encode()).hexdigest()[:10]}'; os.makedirs(refdir,exist_ok=True)
        rows=[]; resolved=[]; cls={}
        for k,v in pk.items():
            name,ver=k.split('/'); comp=list(v.get('compile',{}).keys())
            for c in comp:
                if not c.endswith('.dll'): continue
                src=f'{NUGET}/{name.lower()}/{ver}/{c}'
                if os.path.exists(src):
                    dst=f'{refdir}/{os.path.basename(c)}'
                    if not os.path.exists(dst): os.symlink(src,dst)
            if name.lower() in libs and comp:
                dll=f'{NUGET}/{name.lower()}/{ver}/{comp[0]}'
                if not os.path.exists(dll) or not dll.endswith('.dll'): continue
                lib=libs[name.lower()]; cals=[e['callable'] for e in lib['rows']]
                dev,_=row_ids(lib['derivation_dll'],cals); res,mvid=row_ids(dll,cals)
                same_version=(ver==lib['derivation_version'])
                for e in lib['rows']:
                    c=e['callable']; di=dev.get(c); ri=res.get(c)
                    if not ri: status='callable_absent'
                    elif di and di[0][0]==ri[0][0] and di[0][2]==0: status='identity_match'
                    elif same_version and di and di[1]==ri[1]: status='rederived_same_source'
                    elif same_version: status='tfm_variant_body_differs'
                    else: status='version_drift'
                    if status!='callable_absent':
                        rows.append({**e,'assembly':{'name':lib['assembly'],'mvid':mvid},'row_class':status,'trusted':status in TRUSTED,'repinned_from':e['assembly']['mvid'],'derivation_version':lib['derivation_version'],'resolved_version':ver,'resolved_asset':comp[0]})
                        cls[(c,e['effect'])]=status
                    resolved.append({'package':name,'version':ver,'asset':comp[0],'callable':c,'status':status})
                # witnessed rows: exact tested binary, or TYPED-slice identity transfer from the tested binary
                wr=wit_rows.get(name.lower(),[])
                if wr:
                    wcals=[e['callable'] for e in wr]; resw,_=row_ids(dll,wcals); tested={}
                    for e in wr:
                        c=e['callable']; ri=resw.get(c)
                        if e['assembly']['mvid']==mvid: status='witnessed_exact_binary'
                        elif ri:
                            tdll=next((x for x in glob.glob(f'{NUGET}/{name.lower()}/*/lib/*/{os.path.basename(comp[0])}') if json.loads(open(dump(x)).read())['mvid']==e['assembly']['mvid']),None)
                            if tdll:
                                tid,_=row_ids(tdll,wcals); ti=tid.get(c)
                                status='witnessed_identity_match' if (ti and ti[0][0]==ri[0][0] and ti[0][2]==0) else 'witnessed_binary_pinned_no_match'
                            else: status='witnessed_tested_binary_unavailable'
                        else: status='callable_absent'
                        if status in ('witnessed_exact_binary','witnessed_identity_match') and (c,'return_fresh_owned') not in cls:
                            rows.append({**e,'assembly':{'name':lib['assembly'],'mvid':mvid},'row_class':status,'trusted':True,'tested_mvid':e['assembly']['mvid'],'resolved_version':ver,'resolved_asset':comp[0]}); cls[(c,'return_fresh_owned')]=status
                        resolved.append({'package':name,'version':ver,'asset':comp[0],'callable':c,'status':status,'source':'witness'})
        keyf=f'{refdir}/rows.json'; json.dump({'schema':'own.net/re-oracle/v1','label':f'E2 {repo} {rel} {tfm0}','entries':rows},open(keyf,'w'))
        srcs=sorted(x for x in glob.glob(os.path.join(os.path.dirname(p),'**','*.cs'),recursive=True) if '/obj/' not in x and '/bin/' not in x)
        hit=f'{refdir}/hits.jsonl'; open(hit,'w').close(); xr=None
        if srcs and rows:
            e=dict(env); e['OWEN_RE_ORACLE']=keyf; e['OWEN_RE_ORACLE_HITLOG']=hit; t1=time.time()
            try:
                pr=subprocess.run(['dotnet',f'{R}/frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll','--flow-locals',*srcs,'--ref-dir',refdir,'-o',f'{refdir}/facts.json'],cwd=R,capture_output=True,text=True,env=e,timeout=1500)
                xr={'rc':pr.returncode,'seconds':round(time.time()-t1,1),'stderr_tail':(pr.stderr+pr.stdout)[-300:],'facts_bytes':os.path.getsize(f'{refdir}/facts.json') if os.path.exists(f'{refdir}/facts.json') else 0}
            except subprocess.TimeoutExpired:
                xr={'rc':'timeout','seconds':round(time.time()-t1,1),'stderr_tail':'','facts_bytes':0}
            extractor_runs.append({'project':rel,'tfm':tfm0,**xr})
        hits=[json.loads(l) for l in open(hit) if l.strip()]
        u=collections.defaultdict(set)
        for h in hits:
            st=cls.get((h['callable'],h['effect']),'unknown')
            u[st].add((sha,rel,tfm0,os.path.relpath(h['file'],W),h['line'],h['column'],h['end_line'],h['end_column'],h['callable'],h['effect'],h.get('assembly')))
        for st,ss in u.items(): units[st]|=ss
        pj['targets'][tfm0]={'rows_applicable_trusted':sum(1 for r in rows if r['trusted']),'rows_unverified':sum(1 for r in rows if not r['trusted']),'resolved':resolved,'source_files':len(srcs),'hits':len(hits),'extractor':xr,'units_by_class':{st:len(ss) for st,ss in u.items()}}
    per_project[rel]=pj
out={'repo':repo,'sha':sha,'seconds':round(time.time()-t0),'projects_total':len(projs),'production_projects':len(prod),'restored_ok':sum(1 for v in restore.values() if v['ok']),'restore':restore,'per_project':per_project,'extractor_runs':extractor_runs,
     'units_trusted':sorted(list(x) for st in TRUSTED for x in units.get(st,())),'units_unverified':sorted(list(x) for st in units if st not in TRUSTED for x in units[st]),
     'unit_count_trusted':sum(len(units.get(st,())) for st in TRUSTED),'unit_count_unverified':sum(len(units[st]) for st in units if st not in TRUSTED),'units_by_class':{st:len(ss) for st,ss in units.items()}}
json.dump(out,open(f'{E}/{tag}.e2.json','w'),indent=1); print('E2_DONE',repo,sha[:10],'prod',len(prod),'restored',out['restored_ok'],'trusted',out['unit_count_trusted'],'unverified',out['unit_count_unverified'],'extractor_fail',sum(1 for x in extractor_runs if x['rc']!=0))
