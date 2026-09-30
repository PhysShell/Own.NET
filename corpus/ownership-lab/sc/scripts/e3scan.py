"""Stage E3: the frozen OFF vs ON scan for ONE frozen consumer (repo, sha): re-clone at the frozen revision, restore the
production projects, rebuild the per-project/TFM reference directories and the trusted row files exactly as e2.py did
(identity_match / rederived_same_source / witnessed_exact_binary / witnessed_identity_match are trusted; unverified rows
are NOT applied), run the extractor OFF (no oracle) and ON (oracle = trusted rows) per project/TFM, run both engines,
diff findings. Output: e3/<repo>.e3.json with new / lost findings and the engine parity flag. No triage here."""
import json, os, sys, subprocess, glob, re, hashlib, time, collections
S='/tmp/claude-0/-home-user/8a9da608-aa27-5449-8306-1fae9426f9b9/scratchpad'; R='/home/user/Own.NET'; E=f'{S}/lab/sc/e3'; E2=f'{S}/lab/sc/e2'
repo=sys.argv[1]; want_sha=sys.argv[2]; tag=repo.replace('/','__'); W=f'{E}/{tag}'; os.makedirs(E,exist_ok=True)
env={**os.environ,'PATH':'/root/.dotnet:'+os.environ['PATH'],'DOTNET_NOLOGO':'1','DOTNET_CLI_TELEMETRY_OPTOUT':'1','PYTHONPATH':R,'DOTNET_SKIP_FIRST_TIME_EXPERIENCE':'1'}
for k in ('OWEN_RE_ORACLE','OWEN_RE_BODY','OWEN_RE_MINTED_RETURN','OWEN_RE_MIXED_RETURN','OWEN_LAB_THROWEXIT','OWEN_LAB_NULLINIT','OWEN_LAB_NULLGUARD','OWEN_P037X_GUARDED','OWEN_P037X_RELATIONAL','OWEN_RE_ORACLE_HITLOG'): env.pop(k,None)
EXCL=re.compile(r'(^|/)(tests?|testing|samples?|benchmarks?|examples?|docs?|demo)(/|\.|$)',re.I)
t0=time.time()
if not os.path.isdir(f'{W}/.git'):
    subprocess.run(['git','clone','-q','--depth','1',f'https://github.com/{repo}',W],env=env,capture_output=True,text=True,timeout=900)
sha=subprocess.run(['git','rev-parse','HEAD'],cwd=W,capture_output=True,text=True).stdout.strip()
if sha!=want_sha:
    subprocess.run(['git','fetch','-q','--depth','1','origin',want_sha],cwd=W,capture_output=True,text=True,timeout=900)
    subprocess.run(['git','checkout','-q',want_sha],cwd=W,capture_output=True,text=True)
    sha=subprocess.run(['git','rev-parse','HEAD'],cwd=W,capture_output=True,text=True).stdout.strip()
projs=sorted(p for p in glob.glob(f'{W}/**/*.csproj',recursive=True)); prod=[p for p in projs if not EXCL.search(os.path.relpath(p,W))]
restore={}
for sln in sorted(glob.glob(f'{W}/*.sln')+glob.glob(f'{W}/*.slnx')+glob.glob(f'{W}/src/*.sln')):
    r=subprocess.run(['dotnet','restore',sln,'-nologo','-v','q'],cwd=W,capture_output=True,text=True,env=env,timeout=1500); restore[os.path.relpath(sln,W)]={'ok':r.returncode==0}
for p in prod:
    if os.path.exists(os.path.join(os.path.dirname(p),'obj','project.assets.json')): restore.setdefault(os.path.relpath(p,W),{'ok':True,'via':'solution'}); continue
    r=subprocess.run(['dotnet','restore',p,'-nologo','-v','q'],cwd=W,capture_output=True,text=True,env=env,timeout=900); restore[os.path.relpath(p,W)]={'ok':r.returncode==0,'err':(r.stdout+r.stderr)[-300:] if r.returncode else ''}
# trusted rows per project/TFM come from the E2 census record (frozen): rebuild them from its resolved lists
e2=json.load(open(f'{E2}/{tag}.e2.json')); assert e2['sha']==sha, ('sha drift', e2['sha'], sha)
# row texts: whole-source rows + witnessed rows (same sources as e2.py)
sys.path.insert(0,f'{S}/lab/sc'); import importlib.util
spec=importlib.util.spec_from_file_location('a2',f'{S}/lab/sc/a2lib.py'); a2=importlib.util.module_from_spec(spec); spec.loader.exec_module(a2)
D=f'{S}/lab/disc'; WHOLE={'SkiaSharp','RabbitMQ.Client','MailKit','StackExchange.Redis','Npgsql','MQTTnet','SSH.NET','LibGit2Sharp'}
libs={}
for acq in sorted(glob.glob(f'{D}/libs/*/acquire.json')):
    L=os.path.dirname(acq); pid=os.path.basename(L); a=json.load(open(acq))
    if not a.get('main_assembly'): continue
    src=f'{L}/rows-whole.json' if pid in WHOLE else f'{L}/rows-applied.json'
    if not os.path.exists(src): continue
    ents=json.load(open(src)); ents=ents['rows'] if 'rows' in ents else ents['entries']
    libs[pid.lower()]={'pid':pid,'assembly':(a.get('identity') or {}).get('name') or pid,'rows':{(e['callable'],e['effect']):e for e in ents}}
TR={'identity_match','rederived_same_source','witnessed_exact_binary','witnessed_identity_match'}
T=f'{R}/frontend/roslyn/OwnSharp.RelDump/bin/Release/net8.0/ownsharp-reldump.dll'
def mvid_of(dll):
    out=f'{E2}/dumps/'+hashlib.sha256(open(dll,'rb').read()).hexdigest()[:16]+'.json'
    if not os.path.exists(out): open(out,'w').write(subprocess.run(['dotnet',T,dll],capture_output=True,text=True,env=env).stdout)
    return json.load(open(out))['mvid']
DLL=f'{R}/frontend/roslyn/OwnSharp.Extractor/bin/Release/net8.0/ownsharp-extract.dll'; OWN=f'{R}/rust/target/release/own-cli'
FIND=re.compile(r'([^\s]+\.cs):(\d+): (\w+): \[(OWN\d+)\] (.*)')
def engines(facts, e):
    v=subprocess.run([OWN,'ownir',facts,'--format','human','--severity','warning','--verbosity','verbose'],cwd=R,capture_output=True,text=True,env={**e,'OWEN_P037X_GUARDED':'0'}).stdout
    p=subprocess.run(['python3','-m','ownlang','ownir',facts,'--format','human','--severity','warning','--verbosity','verbose'],cwd=R,capture_output=True,text=True,env=e,timeout=1500).stdout
    f=sorted(set((os.path.relpath(os.path.normpath(os.path.join(R,m.group(1))),W) if not m.group(1).startswith('/') else os.path.relpath(m.group(1),W),int(m.group(2)),m.group(4),m.group(5)) for m in FIND.finditer(v)))
    fp=sorted(set((os.path.relpath(os.path.normpath(os.path.join(R,m.group(1))),W) if not m.group(1).startswith('/') else os.path.relpath(m.group(1),W),int(m.group(2)),m.group(4),m.group(5)) for m in FIND.finditer(p)))
    return f, f==fp
NUGET=os.path.expanduser('~/.nuget/packages'); per={}; allnew=[]; alllost=[]
for p in prod:
    rel=os.path.relpath(p,W); assets=os.path.join(os.path.dirname(p),'obj','project.assets.json')
    if not os.path.exists(assets) or rel not in e2['per_project'] or 'targets' not in e2['per_project'][rel]: continue
    a=json.load(open(assets))
    for tfm,pk in a['targets'].items():
        tfm0=tfm.split('/')[0]
        if tfm0 not in e2['per_project'][rel]['targets']: continue
        t2=e2['per_project'][rel]['targets'][tfm0]
        refdir=f'{W}/.refs/{hashlib.sha256((rel+tfm).encode()).hexdigest()[:10]}'; os.makedirs(refdir,exist_ok=True)
        rows=[]
        for k,v in pk.items():
            name,ver=k.split('/'); comp=list(v.get('compile',{}).keys())
            for c in comp:
                if c.endswith('.dll'):
                    src=f'{NUGET}/{name.lower()}/{ver}/{c}'
                    if os.path.exists(src):
                        dst=f'{refdir}/{os.path.basename(c)}'
                        if not os.path.exists(dst): os.symlink(src,dst)
            if name.lower() in libs and comp and comp[0].endswith('.dll') and os.path.exists(f'{NUGET}/{name.lower()}/{ver}/{comp[0]}'):
                mv=mvid_of(f'{NUGET}/{name.lower()}/{ver}/{comp[0]}'); lib=libs[name.lower()]
                for r in t2['resolved']:
                    if r['package']!=name or r['version']!=ver or r['status'] not in TR: continue
                    base=lib['rows'].get((r['callable'],'return_fresh_owned')) or lib['rows'].get((r['callable'],'receiver_terminal_release')) or {'callable':r['callable'],'effect':'return_fresh_owned','provenance':'WITNESSED'}
                    rows.append({**base,'assembly':{'name':lib['assembly'],'mvid':mv},'row_class':r['status']})
        keyf=f'{refdir}/rows.json'; json.dump({'schema':'own.net/re-oracle/v1','label':f'E3 {repo} {rel} {tfm0}','entries':rows},open(keyf,'w'))
        srcs=sorted(x for x in glob.glob(os.path.join(os.path.dirname(p),'**','*.cs'),recursive=True) if '/obj/' not in x and '/bin/' not in x)
        if not srcs: continue
        res={}
        for arm in ('off','on'):
            e=dict(env)
            if arm=='on': e['OWEN_RE_ORACLE']=keyf
            facts=f'{refdir}/{arm}.facts.json'; t1=time.time()
            try: pr=subprocess.run(['dotnet',DLL,'--flow-locals',*srcs,'--ref-dir',refdir,'-o',facts],cwd=R,capture_output=True,text=True,env=e,timeout=1500); rc=pr.returncode; census=re.findall(r'(re-oracle[^\n]*)',pr.stderr)
            except subprocess.TimeoutExpired: rc='timeout'; census=[]
            f,par=engines(facts,e) if os.path.exists(facts) else ([],None)
            res[arm]={'rc':rc,'seconds':round(time.time()-t1,1),'findings':f,'python_equals_rust':par,'census':census}
        new=[x for x in res['on']['findings'] if x not in res['off']['findings']]; lost=[x for x in res['off']['findings'] if x not in res['on']['findings']]
        per[f'{rel}|{tfm0}']={'rows_applied':len(rows),'row_classes':dict(collections.Counter(r['row_class'] for r in rows)),'source_files':len(srcs),'off':{k:v for k,v in res['off'].items() if k!='findings'},'on':{k:v for k,v in res['on'].items() if k!='findings'},'off_findings':len(res['off']['findings']),'on_findings':len(res['on']['findings']),'new':new,'lost':lost}
        allnew+=[(rel,tfm0,*x) for x in new]; alllost+=[(rel,tfm0,*x) for x in lost]
out={'repo':repo,'sha':sha,'seconds':round(time.time()-t0),'restore_ok':sum(1 for v in restore.values() if v['ok']),'restore_total':len(restore),'per_project_tfm':per,'new_findings':allnew,'lost_findings':alllost}
json.dump(out,open(f'{E}/{tag}.e3.json','w'),indent=1); print('E3_DONE',repo,sha[:10],'units',len(per),'new',len(allnew),'lost',len(alllost))
